"""chat_schemas.py - Request/response shapes for the chat and call-log endpoints."""
from pydantic import BaseModel, Field


class ChatStartOut(BaseModel):
    session_id: str
    reply: str


class ChatIn(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=1000)


class ChatOut(BaseModel):
    session_id: str
    reply: str
    transferred: bool
    ended: bool


class CallLogOut(BaseModel):
    call_id: int
    session_id: str
    started_at: str
    ended_at: str
    duration_sec: int
    language: str
    patient_id: int | None
    outcome: str
    summary: str
    follow_up: str
    appointment_refs: str
    transferred: int
    end_reason: str


class HandoffOut(BaseModel):
    handoff_id: int
    session_id: str
    created_at: str
    reason: str
    patient_id: int | None
    status: str
