"""
llm.py - The ONLY file that talks to the model.

chat(messages, tools) returns a plain dict:
    {"content": "text", "tool_calls": [{"name": "...", "arguments": {...}}]}
so the rest of the project never depends on Ollama's classes. To use a cloud model
or another runtime, write another backend here and nothing else changes.
"""
import json
import re

from . import ai_config

_backend = None   # tests plug a fake model in here


def set_backend(fn) -> None:
    global _backend
    _backend = fn


def _ollama(messages: list, tools: list) -> dict:
    from ollama import chat as ollama_chat
    resp = ollama_chat(
        model=ai_config.LLM_MODEL,
        messages=messages,
        tools=tools or None,
        options={"temperature": ai_config.LLM_TEMPERATURE, "num_ctx": ai_config.LLM_NUM_CTX},
        keep_alive=ai_config.LLM_KEEP_ALIVE,
    )
    msg = resp.message
    calls = [{"name": c.function.name, "arguments": dict(c.function.arguments or {})}
             for c in (msg.tool_calls or [])]
    return {"content": msg.content or "", "tool_calls": calls}


def parse_text_tool_calls(content: str, names: set[str]) -> list[dict]:
    """
    Small models sometimes WRITE the tool call as text instead of making a real one:
        {"name": "get_slots", "arguments": {...}}   or   <tool_call>{...}</tool_call>
    Recover those so the conversation does not break.
    """
    text = (content or "").strip()
    text = re.sub(r"</?tool_call>", "", text)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    if not text.startswith(("{", "[")):
        return []
    try:
        data = json.loads(text)
    except ValueError:
        return []
    out = []
    for item in (data if isinstance(data, list) else [data]):
        if isinstance(item, dict) and item.get("name") in names:
            args = item.get("arguments", item.get("parameters", {}))
            if isinstance(args, dict):
                out.append({"name": item["name"], "arguments": args})
    return out


def chat(messages: list, tools: list) -> dict:
    out = (_backend or _ollama)(messages, tools)
    if not out.get("tool_calls"):
        names = {t["function"]["name"] for t in tools}
        recovered = parse_text_tool_calls(out.get("content", ""), names)
        if recovered:
            return {"content": "", "tool_calls": recovered}
    return {"content": out.get("content", ""), "tool_calls": out.get("tool_calls", [])}
