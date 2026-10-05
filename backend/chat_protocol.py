"""Application WebSocket messages, independent of Codex JSON-RPC."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class SubmitPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["submit_prompt"]
    text: StrictStr = Field(min_length=1)
    request_id: StrictStr | None = Field(default=None, min_length=1, max_length=128)
    model_id: StrictStr | None = None
    reasoning_effort: StrictStr | None = None
    collaboration_mode: StrictStr | None = None


class ListCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list_capabilities"]


class ReadUsage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["read_usage"]


class StopTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["stop_turn"]


class SteerTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["steer_turn"]
    text: StrictStr = Field(min_length=1)


class NewConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["new_conversation"]


class ListProjects(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["list_projects"]


class SelectProject(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["select_project"]
    id: StrictStr = Field(min_length=1)


class ListConversations(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["list_conversations"]


class SelectConversation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["select_conversation"]
    id: StrictStr = Field(min_length=1)


class AnswerApproval(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["answer_approval"]
    id: StrictStr = Field(min_length=1)
    decision: Literal["accept", "decline"]


class AnswerUserInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["answer_user_input"]
    id: StrictStr = Field(min_length=1)
    answers: dict[str, list[StrictStr]]


class Ready(BaseModel):
    type: Literal["ready"] = "ready"


class TurnStarted(BaseModel):
    type: Literal["turn_started"] = "turn_started"


class Capabilities(BaseModel):
    type: Literal["capabilities"] = "capabilities"
    models: list[dict[str, object]]
    collaboration_modes: list[dict[str, object]]
    user_input: Literal["supported", "unsupported"] = "unsupported"


class Usage(BaseModel):
    type: Literal["usage"] = "usage"
    status: Literal["available", "unsupported", "error"]
    rate_limits: dict[str, object] | None = None
    rate_limits_by_id: dict[str, dict[str, object]] = Field(default_factory=dict)
    ordinary_usage_allowed: bool | None = None


class UsageUpdate(BaseModel):
    type: Literal["usage_update"] = "usage_update"
    rate_limits: dict[str, object]


class PendingRequest(BaseModel):
    type: Literal["pending_request"] = "pending_request"
    id: str
    kind: Literal["command", "file_change", "user_input"]
    details: dict[str, object]


class RequestOutcome(BaseModel):
    type: Literal["request_outcome"] = "request_outcome"
    id: str
    status: Literal["completed", "expired", "cancelled"]


class SteerAccepted(BaseModel):
    type: Literal["steer_accepted"] = "steer_accepted"
    text: str


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
    id: str | None = None
    code: Literal[
        "invalid_message",
        "turn_in_progress",
        "codex_failure",
        "codex_unavailable",
        "conversation_not_found",
        "thread_unavailable",
        "model_unavailable",
        "reasoning_unavailable",
        "collaboration_unavailable",
        "no_active_turn",
        "steer_failed",
        "stop_failed",
        "request_unavailable",
        "project_not_found",
        "project_unavailable",
        "duplicate_submission",
    ]


class ConversationList(BaseModel):
    type: Literal["conversation_list"] = "conversation_list"
    conversations: list[dict[str, str]]


class ProjectList(BaseModel):
    type: Literal["project_list"] = "project_list"
    projects: list[dict[str, str]]
    selected_id: str


class ProjectSelected(BaseModel):
    type: Literal["project_selected"] = "project_selected"
    id: str


class ConversationSelected(BaseModel):
    type: Literal["conversation_selected"] = "conversation_selected"
    conversation: dict[str, str]
    messages: list[dict[str, str]]


ClientMessage = (
    SubmitPrompt
    | NewConversation
    | ListProjects
    | SelectProject
    | ListConversations
    | SelectConversation
    | ListCapabilities
    | ReadUsage
    | StopTurn
    | SteerTurn
    | AnswerApproval
    | AnswerUserInput
)
ServerEvent = (
    Ready
    | TurnStarted
    | Capabilities
    | Usage
    | UsageUpdate
    | SteerAccepted
    | AssistantDelta
    | AgentStatus
    | TurnFinished
    | ChatError
    | ConversationList
    | ProjectList
    | ProjectSelected
    | ConversationSelected
    | PendingRequest
    | RequestOutcome
)
