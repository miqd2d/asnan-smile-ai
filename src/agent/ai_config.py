"""ai_config.py - settings for the AI layer (kept apart from the PMS settings in config.py)."""
import os

CLINIC_NAME = os.environ.get("CLINIC_NAME", "Asnan Tower")
EMERGENCY_NUMBER = "112"                    # Kuwait emergency number

# ---- Model -----------------------------------------------------------------
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen3:4b")
LLM_TEMPERATURE = 0.1                       # low = more reliable tool calls
LLM_NUM_CTX = 6144                          # context window (tokens); fits a 4 GB GPU with a 3B model
LLM_KEEP_ALIVE = "30m"                      # keep the model loaded between turns

# ---- Conversation ------------------------------------------------------------
MAX_TOOL_ROUNDS = 6                         # model<->tool round trips per caller message
MAX_HISTORY_MESSAGES = 24                   # older messages are dropped from the prompt
MAX_MESSAGE_CHARS = 1000
SESSION_TTL_MIN = 30                        # idle calls are closed after this
MAX_SLOTS_SHOWN = 6                         # slots the model sees per lookup

# ---- Privacy ---------------------------------------------------------------------
CALL_LOG_RETENTION_DAYS = 90                # purge_old() deletes summaries older than this
