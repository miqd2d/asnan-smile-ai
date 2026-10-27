"""session.py - Per-call memory kept on the server (the model itself remembers nothing)."""
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import config


@dataclass
class Session:
    id: str
    started: datetime
    last_active: datetime
    messages: list = field(default_factory=list)       # what the model sees (no system prompt)
    transcript: list = field(default_factory=list)     # (role, text) pairs, for the summary only
    token: str | None = None                           # verification token: NEVER shown to the model
    patient_id: int | None = None
    first_name: str | None = None
    options: list = field(default_factory=list)       # numbered times last offered: caller says "the second one"
    appts: list = field(default_factory=list)         # numbered appointments last listed
    ctx: dict = field(default_factory=dict)           # what the caller already chose (visit type, doctor, specialty, day)
    pending: dict | None = None                       # an action waiting for the caller's yes/no (run by CODE)
    awaiting_identity: bool = False                   # code is collecting file number + phone/name
    resume: dict | None = None                        # the tool call to re-run once identity is verified
    id_fields: dict = field(default_factory=dict)
    id_asks: int = 0
    id_scan_from: int = 0                             # details said before an expiry are not reused
    lang: str = "en"
    verify_failures: int = 0
    transferred: bool = False
    transfer_reason: str | None = None
    end_requested: bool = False
    ended: bool = False
    llm_failures: int = 0
    events: list = field(default_factory=list)         # what actually happened (drives the outcome)
    turn_actions: list = field(default_factory=list)   # successful writes in the CURRENT turn (drives the receipt)
    call_log: dict | None = None
    lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def verified(self) -> bool:
        return self.token is not None


_sessions: dict[str, Session] = {}


def create() -> Session:
    now = config.get_now()
    s = Session(id=uuid.uuid4().hex[:16], started=now, last_active=now)
    _sessions[s.id] = s
    return s


def get(session_id: str) -> Session | None:
    return _sessions.get(session_id)


def remove(session_id: str) -> None:
    _sessions.pop(session_id, None)


def all_sessions() -> list[Session]:
    return list(_sessions.values())
