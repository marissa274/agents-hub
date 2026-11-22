#!/usr/bin/env python3
"""Hook Claude Code : ajoute chaque événement dans events.jsonl (dossier de données du Hub)."""
import json, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EV as LOG, short
MAX_LOG = 50 * 1024 * 1024  # au-delà, le journal passe dans events.1.jsonl
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)

def last_assistant_text(path):
    """Dernier message écrit par Claude dans la transcription (pour le hook Stop)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            f.seek(max(0, size - 400_000)); lines = f.read().decode(errors="ignore").splitlines()
        for l in reversed(lines):
            try: m = json.loads(l).get("message") or {}
            except Exception: continue
            if m.get("role") != "assistant": continue
            c = m.get("content")
            txt = c if isinstance(c, str) else " ".join(b.get("text", "") for b in c or [] if b.get("type") == "text")
            if txt.strip(): return txt.strip()
    except Exception:
        pass
    return ""

event = d.get("hook_event_name")
# Agents internes de Claude Code (sans nom, sans conversation lisible) : ignorés
if event in ("SubagentStart", "SubagentStop") and not d.get("agent_type"):
    sys.exit(0)
ti = d.get("tool_input") or {}
tool = d.get("tool_name", "")
detail = ""
if tool == "Skill": detail = ti.get("skill", "")
elif tool == "Bash": detail = ti.get("description") or ti.get("command", "")
elif tool in ("Read", "Edit", "Write"): detail = ti.get("file_path", "")
elif tool in ("Grep", "Glob"): detail = ti.get("pattern", "")
elif tool in ("Agent", "Task"): detail = f'{ti.get("subagent_type","")}: {ti.get("description","")}'
elif tool == "AskUserQuestion": detail = " / ".join(q.get("question", "") for q in ti.get("questions") or [])
elif ti: detail = short(ti)

if event == "UserPromptSubmit": detail = d.get("prompt", "")
elif event == "SubagentStop": detail = d.get("last_assistant_message") or ""
elif event == "Stop": detail = d.get("last_assistant_message") or last_assistant_text(d.get("transcript_path") or "")
elif event == "Notification": detail = d.get("message") or ""

ev = {
    "ts": time.time(),
    "event": event,
    "session": (d.get("session_id") or "")[:8],
    "agent_id": d.get("agent_id") or "",
    "agent": d.get("agent_type") or "",
    "tool": tool,
    "detail": short(detail, 600 if event in ("Stop", "SubagentStop", "Notification") or tool == "AskUserQuestion" else 220),
    "kind": d.get("notification_type") or "",
    "cwd": d.get("cwd") or "",
    "transcript": d.get("agent_transcript_path") or d.get("transcript_path") or "",
}
try:
    if os.path.getsize(LOG) > MAX_LOG: os.replace(LOG, LOG.replace(".jsonl", ".1.jsonl"))
except OSError:
    pass
with open(LOG, "a") as f:
    f.write(json.dumps(ev, ensure_ascii=False) + "\n")
