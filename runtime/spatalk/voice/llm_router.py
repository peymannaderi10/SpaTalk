"""Per-turn failover between two LLM vendors, inside the running voice pipeline.

Founder decision 2026-09-03 ~21:20. On text there is one `await` to wrap; on the phone the
model is a Pipecat service in a pipeline, and a failed turn is an `ErrorFrame` travelling
upstream while the caller listens to silence. So the router holds both services as its own
children and does for a call what :class:`~spatalk.brain.driver.FailoverLLMClient` does for
a text conversation: it sends the turn's `LLMContextFrame` to the vendor the breaker says is
worth trying, and when that vendor answers with an error it sends the *same* context to the
other vendor at once. The caller waits one extra model call, about a second, and hears an
answer rather than an apology.

**How the two services are linked.** The router is a `ParallelPipeline` with one branch per
service, each branch gated by a `FunctionFilter` that passes frames only while its service
is the active one. That is Pipecat 1.8's own idiom for holding interchangeable services:
`pipecat.pipeline.service_switcher.ServiceSwitcher` builds exactly this layout
(`Filter -> service -> Filter`), and `ParallelPipeline` is what gives each branch its
source, its sink, its lifecycle frames and its metrics. Every frame that is not an
`LLMContextFrame` therefore travels the active service's chain unchanged, so `LLMTextFrame`,
`LLMFullResponseStartFrame`/`EndFrame`, the function-call frames and the usage metrics
behave exactly as they did when the service sat in the pipeline on its own.

Pipecat's own `ServiceSwitcherStrategyFailover` is not what this needs, for two reasons
worth writing down: it switches only once a service reports itself unable to work at all
(`is_usable=False`, which a 503 does not do), and it never re-sends the turn that failed, so
the caller would still lose that turn. The cooling-off decision also belongs to the shared
:class:`~spatalk.brain.breaker.VendorBreaker`, which the text channels read too.

The router names no vendor. `vendors` is whatever `LLM_MODEL` and `LLM_MODEL_FALLBACK` named
(CLAUDE.md non-negotiable 4), and it is used only as a key on the breaker.
"""

from __future__ import annotations

from loguru import logger
from pipecat.frames.frames import ErrorFrame, Frame, LLMContextFrame, LLMTextFrame
from pipecat.pipeline.parallel_pipeline import ParallelPipeline
from pipecat.processors.filters.function_filter import FunctionFilter
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from spatalk.brain.breaker import VendorBreaker


class LLMRouter(ParallelPipeline):
    """Two LLM services, one active at a time, and one retry at the other on a failed turn."""

    def __init__(
        self,
        primary: FrameProcessor,
        secondary: FrameProcessor,
        breaker: VendorBreaker,
        vendors: tuple[str, str],
    ):
        self._services: list[FrameProcessor] = [primary, secondary]
        self.vendors: tuple[str, str] = (vendors[0], vendors[1])
        self._breaker = breaker
        # Which service the next frame goes to. Re-decided from the breaker at the start of
        # every turn, and switched inside a turn when the active one fails it.
        self._active: FrameProcessor = primary
        # The turn in flight, kept so the other vendor can be given the same one, and the
        # services that have already failed it, so a turn is never sent round in a circle.
        self._turn: LLMContextFrame | None = None
        self._failed_this_turn: set[int] = set()
        super().__init__(*[self._branch(service) for service in self._services])

    # ----- the two branches -----------------------------------------------------------

    def _branch(self, service: FrameProcessor) -> list[FrameProcessor]:
        """`Filter -> service -> Filter`, the layout Pipecat's own ServiceSwitcher uses.

        The downstream filter keeps a turn away from the service that is not active; the
        upstream one does the same for anything travelling back. `filter_system_frames` is
        on so an interruption cannot reach a service that is not in the conversation;
        `StartFrame`, `EndFrame` and `CancelFrame` always pass, whatever the filter says, so
        both services are still started and stopped with the pipeline.
        """

        async def is_active(_: Frame) -> bool:
            return service is self._active

        return [
            FunctionFilter(
                filter=is_active,
                direction=FrameDirection.DOWNSTREAM,
                filter_system_frames=True,
                enable_direct_mode=True,
            ),
            service,
            FunctionFilter(
                filter=is_active,
                direction=FrameDirection.UPSTREAM,
                filter_system_frames=True,
                enable_direct_mode=True,
            ),
        ]

    # ----- the services -----------------------------------------------------------------

    @property
    def services(self) -> list[FrameProcessor]:
        """Both LLM services, primary first."""
        return list(self._services)

    @property
    def active_service(self) -> FrameProcessor:
        """The service the next turn will be sent to."""
        return self._active

    @property
    def active_vendor(self) -> str:
        """The vendor name of the service the next turn will be sent to."""
        return self.vendors[self._services.index(self._active)]

    def register_function(self, function_name, handler, **kwargs):
        """Register a tool handler on **both** services.

        A turn the secondary answers has to be able to file the item the caller rang about.
        A tool the model can see but whose handler was never registered is the worst of both
        worlds: the model calls it and nothing happens.
        """
        for service in self._services:
            service.register_function(function_name, handler, **kwargs)

    # ----- routing ----------------------------------------------------------------------

    def _vendor_of(self, service: FrameProcessor) -> str:
        return self.vendors[self._services.index(service)]

    def _service_for(self, vendor: str) -> FrameProcessor:
        """The service that answers for `vendor`; the primary when both names are equal."""
        index = 1 if (vendor == self.vendors[1] and self.vendors[0] != self.vendors[1]) else 0
        return self._services[index]

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        """Start each turn at whichever vendor the breaker says is worth trying."""
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.DOWNSTREAM:
            self._turn = frame
            self._failed_this_turn = set()
            self._activate(self._service_for(self._breaker.active(*self.vendors)))
        await super().process_frame(frame, direction)

    async def push_frame(self, frame: Frame, direction: FrameDirection = FrameDirection.DOWNSTREAM):
        """Everything leaving the router: the answers go on, a failed turn is retried once."""
        if isinstance(frame, ErrorFrame) and frame.processor in self._services:
            if await self._failover(frame):
                # The other vendor has the turn. Downstream never hears about this one, so
                # the caller is not told about a failure that cost them a second.
                return
        elif isinstance(frame, LLMTextFrame) and direction == FrameDirection.DOWNSTREAM:
            # Words came back, so whichever vendor is answering is answering.
            self._breaker.record_success(self.active_vendor)
        await super().push_frame(frame, direction)

    async def _failover(self, frame: ErrorFrame) -> bool:
        """Record the failure and hand the same turn to the other vendor. True if it was."""
        failed = frame.processor
        vendor = self._vendor_of(failed)
        self._breaker.record_failure(vendor)
        self._failed_this_turn.add(self._services.index(failed))
        other = self._services[1 - self._services.index(failed)]
        if self._turn is None or self._services.index(other) in self._failed_this_turn:
            # Either there is no turn to re-send, or both vendors have now failed this one.
            # The error travels on and `on_pipeline_error` says something to the caller.
            logger.error("both llm vendors failed this turn: {}", str(frame.error)[:200])
            return False
        logger.warning(
            "llm vendor {} failed this turn ({}); sending it to {}",
            vendor,
            str(frame.error)[:160],
            self._vendor_of(other),
        )
        self._activate(other)
        # Through the branch rather than straight at the service, so the retry takes exactly
        # the path a fresh turn takes: same filter, same queue, same ordering.
        await self._pipelines[self._services.index(other)].queue_frame(
            self._turn, FrameDirection.DOWNSTREAM
        )
        return True

    def _activate(self, service: FrameProcessor) -> None:
        if service is not self._active:
            logger.info(
                "llm turns now going to {}", self.vendors[self._services.index(service)]
            )
        self._active = service
