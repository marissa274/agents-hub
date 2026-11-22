"""Adaptateur Codex : lit les sessions Codex (~/.codex/sessions) et les ajoute au flux du Hub.

Pour ajouter un autre outil (Cursor, Gemini...), copiez ce fichier, changez NAME,
ROOT_DIR et la conversion des lignes, puis ajoutez le module à ADAPTERS dans
adapters/__init__.py. Côté interface, il suffit d'une entrée LABEL/INIT dans ui/index.html.

Interface d'un adaptateur :
  NAME                 identifiant court de l'outil (valeur du champ "source")
  ROOT_DIR             dossier (realpath) sous lequel vivent ses transcriptions ;
                       le serveur ne lit jamais un fichier situé hors de ce dossier
  start(emit)          démarre la surveillance (thread démon) ; appelle emit(liste_d_evenements)
  find_session(sid)    -> chemin de la transcription principale d'une session ("" si inconnue)
  transcript(path, short) -> liste d'items {"k": "mission|text|tool|result", "t": "...", ...}

Format d'un événement (un objet JSON par ligne dans events.jsonl) :
  ts          float, secondes Unix
  event       UserPromptSubmit | PreToolUse | SubagentStart | SubagentStop | Stop | Notification
  session     identifiant court de la session (8 caractères)
  agent_id    identifiant du sous-agent ("" pour l'orchestrateur)
  agent       nom de l'agent ("" ou NAME pour l'orchestrateur)
  tool        nom de l'outil appelé (PreToolUse)
  detail      texte court affiché dans le flux
  cwd         dossier de travail
  transcript  chemin de la transcription
  source      NAME
"""
import glob, json, os, time, threading
from common import short

NAME = "codex"
ROOT_DIR = os.path.realpath(os.path.expanduser("~/.codex/sessions"))
SESS = ROOT_DIR

def tool_detail(p):
    raw = p.get("arguments") or p.get("input") or ""
    try: a = json.loads(raw) if isinstance(raw, str) else raw
    except Exception: a = raw
    if isinstance(a, dict):
        for k in ("agent_type", "role", "message", "description", "cmd", "command", "path", "query", "items"):
            if a.get(k): return short(a[k])
    return short(a)

class File:
    def __init__(self, path, off=0):
        self.path, self.buf = path, b""
        self.off = off
        self.agent, self.thread, self.cwd, self.session = "codex", "", "", ""
        self.ready = False
        self._load_meta()

    def _load_meta(self):
        meta = self._meta()
        if meta:
            self.ready = True
            self.thread, self.cwd = meta.get("id", ""), meta.get("cwd", "")
            self.session = (meta.get("parent_thread_id") or self.thread)[:8]  # sous-agents rangés avec leur session parente
            src = meta.get("source")
            spawn = src.get("subagent", {}).get("thread_spawn") if isinstance(src, dict) else None
            if isinstance(src, dict) and "subagent" in src and not spawn:
                self.agent = None  # sous-agent interne de Codex (guardian) : ignoré
            elif spawn:
                name = spawn.get("agent_role") or os.path.basename(spawn.get("agent_path") or "") or spawn.get("agent_nickname") or "agent"
                self.agent = f"codex · {name}"
                self.nick = spawn.get("agent_nickname") or ""

    def _meta(self):
        try:
            with open(self.path) as f: d = json.loads(f.readline())
            return d.get("payload") if d.get("type") == "session_meta" else None
        except Exception: return None

    def read(self):
        if not self.ready:
            self._load_meta()  # rollout vide/incomplet à la création : on relit tant que session_meta manque
            if not self.ready: return []  # off inchangé : aucun événement perdu
        if self.agent is None: return []
        size = os.path.getsize(self.path)
        if size <= self.off: return []
        with open(self.path, "rb") as f:
            f.seek(self.off); data = f.read()
        self.off += len(data)
        lines = (self.buf + data).split(b"\n")
        self.buf = lines.pop()
        out = []
        for l in lines:
            try: d = json.loads(l.decode(errors="replace"))
            except Exception: continue
            ev = self.convert(d)
            if ev: out.append(ev)
        return out

    def convert(self, d):
        t, p = d.get("type"), d.get("payload") or {}
        sub = self.agent != "codex"
        base = {"ts": time.time(), "session": self.session, "agent_id": self.thread if sub else "",
                "agent": self.agent, "tool": "", "detail": "", "cwd": self.cwd, "transcript": self.path, "source": NAME}
        if t == "session_meta" and sub:
            return {**base, "event": "SubagentStart", "detail": getattr(self, "nick", "")}
        if t == "response_item" and p.get("type") in ("function_call", "custom_tool_call"):
            return {**base, "event": "PreToolUse", "tool": p.get("name") or "outil", "detail": tool_detail(p)}
        if t == "response_item" and p.get("type") == "message" and p.get("role") == "user" and not sub:
            txt = " ".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict))
            if txt.strip() and not txt.lstrip().startswith("<"):
                return {**base, "event": "UserPromptSubmit", "detail": short(txt)}
        if t == "event_msg" and p.get("type") == "task_complete":
            return {**base, "event": "SubagentStop" if sub else "Stop", "detail": short(p.get("last_agent_message") or "", 400)}
        return None

def all_files():
    # toutes les sessions, quel que soit leur dossier de date : une session reprise
    # (ex. orchestrateur créé le 10 et repris aujourd'hui) continue d'écrire dans son ancien dossier
    return glob.glob(f"{SESS}/*/*/*/*.jsonl")

def size(p):
    try: return os.path.getsize(p)
    except OSError: return 0

def loop(emit):
    # état au démarrage : pour les fichiers déjà là, on suit seulement la suite
    known = {p: size(p) for p in all_files()}
    files = {}
    while True:
        try:
            new_events = []
            for path in all_files():
                if path in files: continue
                if path not in known:
                    files[path] = File(path, 0)  # nouvelle session : tout
                elif size(path) != known[path]:
                    files[path] = File(path, known[path])  # session reprise : la suite
            for f in files.values():
                new_events += f.read()
            if new_events: emit(new_events)
        except Exception:
            pass
        time.sleep(1)

def start(emit):
    threading.Thread(target=loop, args=(emit,), daemon=True).start()

def find_session(sid):
    """Fichier de l'orchestrateur Codex d'une session (celui sans parent_thread_id)."""
    best = ""
    if not sid or not sid.isalnum(): return best
    for f in glob.glob(f"{SESS}/*/*/*/*-{sid}*.jsonl"):
        try:
            with open(f) as fh: meta = json.loads(fh.readline()).get("payload") or {}
        except Exception: continue
        if meta.get("parent_thread_id") or not str(meta.get("id", "")).startswith(sid): continue
        if not best or os.path.getmtime(f) > os.path.getmtime(best): best = f
    return best

def transcript(path, short_fn=short):
    """Transcription lisible d'une session Codex."""
    items = []
    sz = os.path.getsize(path)
    with open(path, "rb") as f:
        if sz > 3_000_000: f.seek(sz - 3_000_000); f.readline()  # longues sessions : la fin suffit
        lines = f.read().decode(errors="ignore").splitlines()
    for l in lines:
        try: d = json.loads(l)
        except Exception: continue
        if d.get("type") != "response_item": continue
        p = d["payload"]; ty = p.get("type")
        if ty == "message" and p.get("role") in ("user", "assistant"):
            txt = " ".join(c.get("text", "") for c in p.get("content") or [] if isinstance(c, dict)).strip()
            if txt and not txt.startswith("<"):
                items.append({"k": "text" if p["role"] == "assistant" else "mission", "t": short_fn(txt, 4000)})
        elif ty in ("function_call", "custom_tool_call"):
            items.append({"k": "tool", "name": p.get("name"), "t": short_fn(p.get("arguments") or p.get("input") or "", 500)})
        elif ty in ("function_call_output", "custom_tool_call_output"):
            o = p.get("output")
            if isinstance(o, list): o = " ".join(x.get("text", "") for x in o if isinstance(x, dict))
            items.append({"k": "result", "t": short_fn(o or "", 700)})
    return items[-400:]
