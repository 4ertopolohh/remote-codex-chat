"""Application WebSocket messages, independent of Codex JSON-RPC."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class SubmitPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["submit_prompt"]
    text: StrictStr = Field(min_length=1, max_length=10000)


class Ready(BaseModel):
    type: Literal["ready"] = "ready"


class TurnStarted(BaseModel):
    type: Literal["turn_started"] = "turn_started"


class AssistantDelta(BaseModel):
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str


class AgentStatus(BaseModel):
    type: Literal["agent_status"] = "agent_status"
    status: str


class TurnFinished(BaseModel):
    type: Literal["turn_completed"] = "turn_completed"
    status: Literal["completed", "failed", "interrupted"]


class ChatError(BaseModel):
    type: Literal["error"] = "error"
    code: Literal[
        "invalid_message", "turn_in_progress", "codex_failure", "codex_unavailable"
    ]


ServerEvent = Ready | TurnStarted | AssistantDelta | AgentStatus | TurnFinished | ChatError
