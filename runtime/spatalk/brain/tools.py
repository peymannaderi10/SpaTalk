from __future__ import annotations

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from spatalk.tenants.schema import TenantConfig

TOOL_NAMES = (
    "send_booking_link",
    "capture_request",
    "request_appointment_change",
    "escalate",
    "end_conversation",
)

# --- live transfer (operations plan, Task E10) -------------------------------------------
# Not in TOOL_NAMES: this one is not a property of the tenant, it is a property of the
# moment. It exists in the model's tool list only on a call where the tenant has a staffed
# back-line and the clinic is open right now, so the model can never offer a transfer that
# would ring an empty room. `spatalk.voice.transfer.transfer_available` is the decision.
TRANSFER_TOOL = "transfer_to_human"

WINDOW = {
    "type": "object",
    "description": "When the caller would like to come in.",
    "properties": {
        "date": {"type": "string", "description": "ISO date YYYY-MM-DD, or 'any'"},
        "part_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening", "any"]},
    },
}


def _contact() -> dict:
    # name/phone/email are the only free strings the model may fill; they are contact details,
    # not notes. There is no notes parameter anywhere in this file, by design (spec §5).
    return {
        "type": "object",
        "description": (
            "Contact details the caller gave. Leave phone empty on voice; the caller id is used."
        ),
        "properties": {
            "name": {"type": "string"},
            "phone": {"type": "string"},
            "email": {"type": "string"},
        },
    }


def build_tools(cfg: TenantConfig, transfer_enabled: bool = False) -> list[FunctionSchema]:
    """The tools the model may call on this turn.

    `transfer_enabled` is decided per call from the calendar state (E10), which is why the
    tool list is built here rather than cached on the tenant.
    """
    service_ids = [s.id for s in cfg.services]
    tools = [
        FunctionSchema(
            name="send_booking_link",
            description=(
                "Text the caller the online booking link for one service. "
                "Use when they want to book and are happy to self-serve."
            ),
            properties={
                "service_id": {"type": "string", "enum": service_ids},
                "contact": _contact(),
            },
            required=["service_id"],
        ),
        FunctionSchema(
            name="capture_request",
            description=(
                "File a request for the team to complete. Use for callbacks, help booking, "
                "questions the knowledge base does not answer, and training-course enquiries."
            ),
            properties={
                "kind": {
                    "type": "string",
                    "enum": ["new_booking", "callback", "question", "training_enquiry"],
                },
                "service_id": {"type": "string", "enum": service_ids},
                "contact": _contact(),
                "preferred_window": WINDOW,
            },
            required=["kind"],
        ),
        FunctionSchema(
            name="request_appointment_change",
            description=(
                "File a reschedule or cancellation request for an existing appointment. "
                "The team completes it and confirms with the caller; you never confirm it yourself."
            ),
            properties={
                "kind": {"type": "string", "enum": ["reschedule", "cancel"]},
                "contact": _contact(),
                "preferred_window": WINDOW,
            },
            required=["kind", "contact"],
        ),
        FunctionSchema(
            name="escalate",
            description=(
                "Hand the conversation to a person. Use for clinical or medical questions, "
                "anything about a reaction or symptom, complaints, payment or legal questions, "
                "an explicit request for a human, or whenever you are unsure."
            ),
            properties={
                "reason": {
                    "type": "string",
                    "enum": ["human_request", "clinical", "complaint", "payment", "legal", "unsure"],
                }
            },
            required=["reason"],
        ),
        FunctionSchema(
            name="end_conversation",
            description=(
                "End the call once the caller has nothing else. "
                "Say nothing yourself; the system says goodbye."
            ),
            properties={},
            required=[],
        ),
    ]
    if transfer_enabled:
        tools.append(
            FunctionSchema(
                name=TRANSFER_TOOL,
                description=(
                    "Put the caller through to a person at the clinic now. "
                    "Use only when they ask to speak to someone and the matter needs a "
                    "person. Say nothing about the result; the system speaks it."
                ),
                properties={},
                required=[],
            )
        )
    return tools


def tools_schema(cfg: TenantConfig, transfer_enabled: bool = False) -> ToolsSchema:
    return ToolsSchema(standard_tools=build_tools(cfg, transfer_enabled=transfer_enabled))


def to_genai_declarations(tools: list[FunctionSchema]) -> list[dict]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "parameters": {"type": "object", "properties": t.properties, "required": t.required},
        }
        for t in tools
    ]
