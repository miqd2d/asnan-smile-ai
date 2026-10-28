"""
Test harness: the REAL agent package (src/agent) behind the standard chat routes, with a scripted
stand-in for the language model (no Ollama needed) and a COPY of the database.

    python tests/support/fake_backend.py 8765

Used by tests/voiceSession.integration.test.tsx. Not needed to run the app.
"""
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
tmp = Path(tempfile.mkdtemp()) / "frontend_test.db"
shutil.copy(ROOT / "db" / "clinic.db", tmp)
os.environ["DENTAL_DB"] = str(tmp)
os.environ["DEMO_NOW"] = "2026-10-26T08:00"

con = sqlite3.connect(tmp)
con.execute("UPDATE visit_types SET patient_bookable = 0")
con.execute("UPDATE visit_types SET patient_bookable = 1 WHERE active = 1 AND rov_id IN (39,5,50,1055,1059,48,1074,2,20,1147,49,1099,1242,51,1108)")
con.commit()
PID, PHONE = con.execute("SELECT patient_id, phone FROM patients LIMIT 1").fetchone()
con.close()

import uvicorn                                       # noqa: E402
from fastapi import FastAPI                          # noqa: E402
from fastapi.responses import JSONResponse           # noqa: E402
from agent import llm, loop as agent                 # noqa: E402
from agent.chat_schemas import CallLogOut, ChatIn, ChatOut, ChatStartOut   # noqa: E402
from rules import RuleError                          # noqa: E402


def fake_model(messages, tools):
    if messages[0]["content"].startswith("You write short internal call summaries"):
        return {"content": "The caller asked for help with an appointment.", "tool_calls": []}
    last = next(m for m in reversed(messages) if m["role"] == "user")["content"].lower()
    call = lambda n, **a: {"content": "", "tool_calls": [{"name": n, "arguments": a}]}   # noqa: E731
    if "cleaning" in last:
        return call("check_availability", visit_type_id=48, doctor_name="Burezq", date="wednesday")
    if "the first" in last:
        return call("book_appointment", option=1)
    if "goodbye" in last:
        return call("end_call")
    return {"content": "Hello! How can I help you today?", "tool_calls": []}


llm.set_backend(fake_model)
app = FastAPI()


@app.exception_handler(RuleError)
async def rule_error(request, exc: RuleError):
    return JSONResponse(status_code=exc.http_status, content=exc.to_dict())


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/_test/patient")
def patient():
    return {"patient_id": PID, "phone": PHONE[-8:]}


@app.post("/chat/start", response_model=ChatStartOut)
def chat_start():
    return agent.start_session()


@app.post("/chat", response_model=ChatOut)
def chat(body: ChatIn):
    return agent.handle_message(body.session_id, body.message)


@app.post("/chat/{session_id}/end", response_model=CallLogOut)
def chat_end(session_id: str):
    return agent.end_session(session_id)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765, log_level="warning")
