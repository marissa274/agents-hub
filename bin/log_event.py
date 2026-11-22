#!/usr/bin/env python3
"""Hook Claude Code ou Codex : ajoute chaque événement dans events.jsonl (dossier de données du Hub).

Avec `--source codex`, l'entrée est celle d'un hook Codex (même schéma que Claude Code) ; le hook sort toujours
avec le code 0 et n'écrit jamais sur la sortie standard (Codex lirait ce texte comme une réponse du hook).
"""
import json, re, subprocess, sys, time, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import EV as LOG, short
MAX_LOG = 50 * 1024 * 1024  # au-delà, le journal passe dans events.1.jsonl
CODEX_MODE = "--source" in sys.argv and sys.argv[sys.argv.index("--source") + 1:][:1] == ["codex"]
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

PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.M)


def codex_event(d):
    """Événement du Hub pour un hook Codex, ou None s'il faut l'ignorer."""
    event = d.get("hook_event_name")
    sid = d.get("session_id")
    if not isinstance(event, str) or not isinstance(sid, str) or not sid: return None
    aid = d.get("agent_id") if isinstance(d.get("agent_id"), str) else ""
    atype = d.get("agent_type") if isinstance(d.get("agent_type"), str) else ""
    sub = bool(aid)
    if event == "UserPromptSubmit" and sub: return None
    ti = d.get("tool_input")
    ti_d = ti if isinstance(ti, dict) else {}
    tool = d.get("tool_name") if isinstance(d.get("tool_name"), str) else ""
    detail, kind = "", ""

    def tool_detail():
        if tool == "Bash": return ti_d.get("command") or ""
        if tool == "apply_patch":
            text = ti if isinstance(ti, str) else next((ti_d[k] for k in ("command", "input", "patch") if isinstance(ti_d.get(k), str)), "")
            return ", ".join(PATCH_FILE.findall(text))
        if tool == "spawn_agent":
            # Dans les vrais rollouts, la plupart des spawn_agent n'ont que {message, task_name} ; Codex nomme alors
            # le sous-agent d'après task_name (thread_spawn.agent_path = /root/<task_name>). Même nom que sa carte.
            who = ti_d.get("agent_type") or ti_d.get("role") or ti_d.get("task_name") or ""
            what = ti_d.get("message") or ti_d.get("items") or ""
            what = what if isinstance(what, str) else short(what)
            # sans nom : pas de « : … » (l'interface en ferait une carte fantôme), le texte reste dans le flux
            return f"{who}: {what}" if isinstance(who, str) and who else what
        if tool == "update_plan":
            plan = ti_d.get("plan")
            return ti_d.get("explanation") or (f"{len(plan)} étapes" if isinstance(plan, list) else "")
        return short(ti) if ti else ""

    if event == "PreToolUse": detail = tool_detail()
    elif event == "PermissionRequest":
        event, kind = "Notification", "permission_prompt"
        detail = tool_detail() or tool
    elif event == "UserPromptSubmit": detail = d.get("prompt") or ""
    elif event in ("Stop", "SubagentStop"): detail = d.get("last_assistant_message") or ""
    if not isinstance(detail, str): detail = short(detail)
    path = d.get("agent_transcript_path") if isinstance(d.get("agent_transcript_path"), str) else ""
    if not path and not sub:
        tp = d.get("transcript_path"); path = tp if isinstance(tp, str) else ""
    return {
        "ts": time.time(), "event": event, "session": sid[:8], "agent_id": aid,
        "agent": f"codex · {atype or 'agent'}" if sub else "codex",
        "tool": tool, "detail": short(detail, 600 if event in ("Stop", "SubagentStop", "Notification") else 220),
        "kind": kind, "cwd": d.get("cwd") if isinstance(d.get("cwd"), str) else "", "transcript": path,
        "source": "codex", "via": "hook",
    }


def append(ev):
    try:
        if os.path.getsize(LOG) > MAX_LOG: os.replace(LOG, LOG.replace(".jsonl", ".1.jsonl"))
    except OSError:
        pass
    with open(LOG, "a") as f:
        f.write(json.dumps(ev, ensure_ascii=False) + "\n")


if CODEX_MODE:
    try:
        ev = codex_event(d) if isinstance(d, dict) else None
        if ev:
            append(ev)
            if ev["tool"] == "spawn_agent" and ev["event"] == "PreToolUse" and not os.environ.get("AGENTS_HUB_NO_WINDOW") and ev["session"].isalnum():
                subprocess.Popen([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "open_window.py"), "session", ev["session"]],
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except BaseException:
        pass
    sys.exit(0)

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
append(ev)
