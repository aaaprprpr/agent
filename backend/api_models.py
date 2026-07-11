from typing import Literal

from pydantic import BaseModel, Field


class UploadedFileRef(BaseModel):
    name: str
    path: str
    size: int


class UploadFilePayload(BaseModel):
    name: str = Field(..., min_length=1)
    content_base64: str = Field(..., min_length=1)
    size: int | None = None
    mime_type: str | None = None


class UploadRequest(BaseModel):
    conversation_id: str | None = None
    files: list[UploadFilePayload] = Field(default_factory=list)


class UploadResponse(BaseModel):
    files: list[UploadedFileRef]


class RunRequest(BaseModel):
    user_input: str = Field(..., min_length=1)
    conversation_id: str | None = None
    uploaded_files: list[UploadedFileRef] = Field(default_factory=list)
    uploaded_file_payloads: list[UploadFilePayload] = Field(default_factory=list)
    selected_memory_ids: list[str] = Field(default_factory=list)
    use_global_memory: bool = False
    toolset: str = "basic_tools"
    save_memory: Literal["none", "conversation", "global"] = "conversation"
    llm_mode: Literal["mock", "prompt_json"] | None = None


class RunResponse(BaseModel):
    conversation_id: str
    user_message_id: str | None = None
    assistant_message_id: str | None = None
    status: str
    final_answer: str
    elapsed_ms: float
    output_dir: str
    trace: dict


class ConversationSummary(BaseModel):
    id: str
    title: str
    is_trivial: bool = False
    created_at: str
    updated_at: str
    last_message_at: str | None = None


class ConversationMessage(BaseModel):
    id: str
    role: str
    content: str
    message_order: int
    created_at: str
    status: Literal["pending", "error"] | None = None
    tool_steps: list[dict] = Field(default_factory=list)
    attachments: list[UploadedFileRef] = Field(default_factory=list)


class ConversationDetail(BaseModel):
    conversation_id: str
    messages: list[ConversationMessage]


class DeleteConversationResponse(BaseModel):
    conversation_id: str
    deleted: bool
    upload_dir_deleted: bool
    output_dir_deleted: bool
