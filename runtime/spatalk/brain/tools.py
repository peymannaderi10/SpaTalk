from __future__ import annotations

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema

from spatalk.tenants.schema import TenantConfig

# The closed tools of the slot engine (slot engine design, §6.2). One slot tool per step,
# offered only at that step by `spatalk.brain.flow.step_tools`; `file_request` and
# `send_link` take no arguments, so nothing on an item can come from a model argument.
TOOL_NAMES = (
    "start_request",
    "answer",
    "choose_practitioner",
    "choose_service",
    "give_name",
    "give_phone",
    "choose_window",
    "change_answer",
    "file_request",
    "send_link",
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
        "date": {
            "type": "string",
            "description": (
                "An ISO date YYYY-MM-DD, a weekday name such as 'Thursday', or 'any'. "
                "Nothing else: anything the caller said in their own words is not a date "
                "and is discarded."
            ),
        },
        "part_of_day": {"type": "string", "enum": ["morning", "afternoon", "evening", "any"]},
    },
}

ONLY_WHAT_THEY_SAID = " Only what the caller said in answer to the question just asked; never a guess."

SLOT_NAMES = ["returning_client", "practitioner", "service", "name", "phone", "window"]

REQUEST_KINDS = ["new_booking", "callback", "reschedule", "cancel", "question"]


def slot_tool(name: str, cfg: TenantConfig) -> FunctionSchema:
    """One of the slot engine's tools by name. The three transient strings (`said`,
    `first_name`, `digits`) are resolved in code before anything is stored."""
    if name == "start_request":
        return FunctionSchema(
            name="start_request",
            description=(
                "The caller wants something the team has to do: book, be called back, "
                "reschedule or cancel, or a question the facts do not answer. Call this the "
                "moment they say so; the system asks the questions from here."
            ),
            properties={"kind": {"type": "string", "enum": REQUEST_KINDS}},
            required=["kind"],
        )
    if name == "answer":
        return FunctionSchema(
            name="answer",
            description="The caller's yes or no to the question just asked." + ONLY_WHAT_THEY_SAID,
            properties={"value": {"type": "string", "enum": ["yes", "no", "unsure"]}},
            required=["value"],
        )
    if name == "choose_practitioner":
        return FunctionSchema(
            name="choose_practitioner",
            description=(
                "Who the caller said they would like to see, in their words, or 'anyone'."
                + ONLY_WHAT_THEY_SAID
            ),
            properties={"said": {"type": "string"}},
            required=["said"],
        )
    if name == "choose_service":
        return FunctionSchema(
            name="choose_service",
            description="The treatment the caller named, in their words." + ONLY_WHAT_THEY_SAID,
            properties={"said": {"type": "string"}},
            required=["said"],
        )
    if name == "give_name":
        return FunctionSchema(
            name="give_name",
            description="The caller's first name, as they gave it." + ONLY_WHAT_THEY_SAID,
            properties={"first_name": {"type": "string"}},
            required=["first_name"],
        )
    if name == "give_phone":
        return FunctionSchema(
            name="give_phone",
            description="The phone number the caller gave, as digits." + ONLY_WHAT_THEY_SAID,
            properties={"digits": {"type": "string"}},
            required=["digits"],
        )
    if name == "choose_window":
        return FunctionSchema(
            name="choose_window",
            description="When the caller would like to come in." + ONLY_WHAT_THEY_SAID,
            properties=dict(WINDOW["properties"]),
            required=[],
        )
    if name == "change_answer":
        return FunctionSchema(
            name="change_answer",
            description=(
                "The caller changed their mind about an earlier answer. "
                "The system asks that question again."
            ),
            properties={"slot": {"type": "string", "enum": SLOT_NAMES}},
            required=["slot"],
        )
    if name == "file_request":
        return FunctionSchema(
            name="file_request",
            description=(
                "Send the request to the team. Say nothing about it yourself; "
                "the system speaks the result."
            ),
            properties={},
            required=[],
        )
    if name == "send_link":
        return FunctionSchema(
            name="send_link",
            description=(
                "Text the caller the booking link now. Say nothing about it yourself; "
                "the system speaks the result."
            ),
            properties={},
            required=[],
        )
    raise ValueError(name)


def always_tools(cfg: TenantConfig, transfer_enabled: bool = False) -> list[FunctionSchema]:
    """The tools offered at every step: escalate, end, and the transfer when it is staffed."""
    tools = [
        FunctionSchema(
            name="escalate",
            description=(
                "Hand the conversation to a person. Use for clinical or medical questions, "
                "anything about a reaction or symptom, complaints, payment or legal questions, "
                "an explicit request for a human, or whenever you are unsure. The reason "
                "'emergency' is for a life-threatening situation only (trouble breathing, a "
                "severe allergic reaction, chest pain, fainting): the caller is then told to "
                "call 911."
            ),
            properties={
                "reason": {
                    "type": "string",
                    "enum": [
                        "emergency", "human_request", "clinical", "complaint", "payment",
                        "legal", "unsure",
                    ],
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


def build_tools(cfg: TenantConfig, transfer_enabled: bool = False) -> list[FunctionSchema]:
    """The Q&A tool set. The per-step sets are `spatalk.brain.flow.step_tools`."""
    return [slot_tool("start_request", cfg)] + always_tools(cfg, transfer_enabled)


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
