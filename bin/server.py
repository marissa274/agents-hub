#!/usr/bin/env python3
"""Serveur du tableau de bord : http://127.0.0.1:7777 (port : AGENTS_HUB_PORT). Écoute en local seulement."""
try:
    import tomllib  # Python 3.11+
except ImportError:
    tomllib = None
import glob, http.server, json, os, sys, threading, time, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, EV, SC, CLAUDE, CODEX, PORT, short
from adapters import ADAPTERS

PROJ = os.path.realpath(os.path.join(CLAUDE, "projects"))
UI = os.path.join(ROOT, "ui", "index.html")
HOSTS = {f"127.0.0.1:{PORT}", f"localhost:{PORT}"}  # contre le DNS rebinding
START = time.time()
WINDOWS = {}; WLOCK = threading.Lock()  # une entrée par connexion /api/alive (= une fenêtre) -> (tâche affichée, épinglée)

def tool_summary(name, i):
    if not isinstance(i, dict): return short(i, 300)
    for k in ("description", "command", "file_path", "pattern", "skill", "prompt", "url", "query"):
        if i.get(k):
            extra = f' — {short(i["command"], 300)}' if k == "description" and i.get("command") else ""
            return short(i[k], 400) + extra
    return short(i, 300)

def transcript(path):
    items = []
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size > 3_000_000: f.seek(size - 3_000_000); f.readline()
        lines = f.read().decode(errors="ignore").splitlines()
    for l in lines:
        try: d = json.loads(l)
        except Exception: continue
        m = d.get("message") or {}; role = m.get("role") or d.get("type"); c = m.get("content")
        ts = d.get("timestamp", "")
        if isinstance(c, str):
            if role in ("user", "assistant") and c.strip() and not c.lstrip().startswith("<system-reminder>"):
                items.append({"k": "mission" if role == "user" else "text", "t": short(c, 4000), "ts": ts})
            continue
        for b in c or []:
            ty = b.get("type")
            if ty == "text" and b.get("text", "").strip() and not b["text"].lstrip().startswith("<system-reminder>"):
                items.append({"k": "text" if role == "assistant" else "mission", "t": short(b["text"], 4000), "ts": ts})
            elif ty == "tool_use":
                items.append({"k": "tool", "name": b.get("name"), "t": tool_summary(b.get("name"), b.get("input")), "ts": ts})
            elif ty == "tool_result":
                r = b.get("content")
                if isinstance(r, list): r = " ".join(x.get("text", "") for x in r if isinstance(x, dict))
                items.append({"k": "result", "err": bool(b.get("is_error")), "t": short(r or "", 700), "ts": ts})
    return items[-400:]

def read_desc(path):
    name, desc = os.path.splitext(os.path.basename(path))[0], ""
    for l in open(path, errors="ignore"):
        if l.startswith("name:") or l.startswith("name ="): name = l.split(":" if ":" in l[:6] else "=", 1)[1].strip().strip('"')
        if l.startswith("description:") or l.startswith("description ="):
            desc = l.split(":" if l.startswith("description:") else "=", 1)[1].strip().strip('"')
    return name, desc

def read_toml_agent(path):
    """(name, description) d'un agent Codex .toml : tomllib si disponible, sinon analyse ligne à ligne."""
    if tomllib:
        try:
            with open(path, "rb") as f: d = tomllib.load(f)
            n, desc = d.get("name"), d.get("description")
            base = os.path.splitext(os.path.basename(path))[0]
            return (n if isinstance(n, str) and n else base), (desc if isinstance(desc, str) else "")
        except Exception: pass
    return read_desc(path)

def under(path, root):
    """path (déjà passé par realpath) est-il dans root ?"""
    try: return os.path.commonpath([path, root]) == root and path != root
    except ValueError: return False

CWDS = set(); HOOKED = set(); TRANSCRIPTS = {}; cwd_off = 0; CWD_LOCK = threading.Lock()
def main_transcript(path):
    """Transcription principale d'une session ; celle d'un sous-agent (.../<session>/subagents/agent-x.jsonl) y est ramenée."""
    if os.sep + "subagents" + os.sep in path:
        return os.path.dirname(os.path.dirname(path)) + ".jsonl"
    return path

def known_cwds():
    """Dossiers de travail vus dans le flux, mis à jour par lecture incrémentale de EV."""
    global cwd_off
    with CWD_LOCK:
        try:
            size = os.path.getsize(EV)
            if size < cwd_off: cwd_off = 0; CWDS.clear(); TRANSCRIPTS.clear()  # (HOOKED est conservé) journal tourné ou vidé
            if size > cwd_off:
                with open(EV, "rb") as f:
                    f.seek(cwd_off); data = f.read()
                end = data.rfind(b"\n") + 1  # ligne incomplète : au prochain tour
                cwd_off += end
                for l in data[:end].decode(errors="ignore").splitlines():
                    try: e = json.loads(l); c = e.get("cwd") or ""
                    except Exception: continue
                    if not isinstance(e, dict): continue
                    if isinstance(c, str) and c.startswith("/"): CWDS.add(c)
                    if e.get("via") == "hook" and isinstance(e.get("source"), str) and isinstance(e.get("session"), str) and e["session"]:
                        HOOKED.add((e["source"], e["session"]))  # session « sous hooks » : définitif
                    t, sid = e.get("transcript"), e.get("session")
                    if isinstance(t, str) and t.endswith(".jsonl") and isinstance(sid, str) and sid and e.get("source") != "codex":
                        TRANSCRIPTS[sid] = main_transcript(t)
        except OSError: pass
        return set(CWDS)

def list_agents():
    """Agents globaux (Claude + Codex) et agents des projets vus dans le flux."""
    out, seen = [], set()
    def add(pattern, scope, prefix=""):
        for f in sorted(glob.glob(pattern)):
            n, d = (read_toml_agent if f.endswith(".toml") else read_desc)(f); key = prefix + n
            if key not in seen: seen.add(key); out.append({"name": key, "description": d, "scope": scope})
    add(os.path.join(CLAUDE, "agents", "*.md"), "global")
    add(os.path.join(glob.escape(CODEX), "agents", "*.toml"), "global", "codex · ")
    cwds = known_cwds(); cwds.add(os.getcwd())
    for c in cwds:
        root = c
        while root != "/" and not os.path.isdir(f"{root}/.git"): root = os.path.dirname(root)
        root = root if root != "/" else c
        add(f"{root}/.claude/agents/*.md", os.path.basename(root))
        add(f"{root}/.codex/agents/*.toml", os.path.basename(root), "codex · ")
    return out

TITLES = {}; TLOCK = threading.Lock()  # chemin -> {"sig", "off", "custom", "ai"}
TITLE_SCAN = 8_000_000  # octets relus au maximum lors d'un scan complet

def scan_titles(path):
    """(custom, ai) derniers titres écrits dans la transcription Claude Code ; ("", "") si absents.
    Cache par (mtime, taille) ; ne relit que la fin ajoutée quand le fichier n'a fait que grandir."""
    st = os.stat(path); sig = (st.st_mtime_ns, st.st_size)
    with TLOCK:
        c = TITLES.get(path)
        if c and c["sig"] == sig: return c["custom"], c["ai"]
        incr = bool(c) and st.st_size >= c["off"]
        if incr: start, custom, ai = c["off"], c["custom"], c["ai"]
        else: start, custom, ai = max(0, st.st_size - TITLE_SCAN), "", ""
        with open(path, "rb") as f:
            f.seek(start); data = f.read(st.st_size - start)
        end = data.rfind(b"\n") + 1  # ligne incomplète : au prochain tour
        lines = data[:end].split(b"\n")
        if start and not incr: lines = lines[1:]  # début de scan : première ligne probablement coupée
        for l in lines:
            if b'"custom-title"' not in l and b'"ai-title"' not in l: continue
            try: d = json.loads(l)
            except Exception: continue
            if not isinstance(d, dict): continue
            if d.get("type") == "custom-title" and isinstance(d.get("customTitle"), str): custom = d["customTitle"].strip()
            elif d.get("type") == "ai-title" and isinstance(d.get("aiTitle"), str): ai = d["aiTitle"].strip()
        TITLES[path] = {"sig": sig, "off": start + end, "custom": custom, "ai": ai}
        if len(TITLES) > 500: TITLES.pop(next(iter(TITLES)))
        return custom, ai

def session_title(sid):
    """Titre de la tâche : dernier custom-title, sinon dernier ai-title, sinon "". Jamais d'exception."""
    try:
        known_cwds()
        path = TRANSCRIPTS.get(sid) or ""
        if not path or not os.path.isfile(os.path.realpath(path)):
            hits = glob.glob(f"{glob.escape(PROJ)}/*/{glob.escape(sid)}*.jsonl") if sid.isalnum() else []
            path = hits[0] if hits else ""
        if not path: return ""
        path = os.path.realpath(path)
        if not path.endswith(".jsonl") or not under(path, PROJ) or not os.path.isfile(path): return ""
        custom, ai = scan_titles(path)
        return short(custom or ai, 200) if (custom or ai) else ""
    except Exception: return ""

def any_title(sid):
    t = session_title(sid)
    if t: return t
    for a in ADAPTERS:
        fn = getattr(a, "title", None)
        if fn:
            try: t = fn(sid)
            except Exception: t = ""
            if t: return short(t, 200)
    return ""

def n_windows():
    with WLOCK: return len(WINDOWS)

def n_unpinned():
    with WLOCK: return sum(1 for _, p in WINDOWS.values() if not p)

def views():
    """{session: nombre de fenêtres qui l'affichent}"""
    out = {}
    with WLOCK:
        for v, _ in WINDOWS.values():
            if v: out[v] = out.get(v, 0) + 1
    return out

def pinned():
    with WLOCK: return sorted({v for v, p in WINDOWS.values() if v and p})

EVLOCK = threading.Lock()

def emit(events):
    """Appelé par les adaptateurs : écrit dans le flux (jamais d'ouverture de fenêtre : seul /hub en ouvre une)."""
    if not events: return
    known_cwds()  # met HOOKED à jour : une session dont les hooks écrivent déjà n'a pas besoin de l'adaptateur
    events = [e for e in events if not (isinstance(e, dict) and e.get("via") != "hook" and (e.get("source"), e.get("session")) in HOOKED)]
    if not events: return
    blob = "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events).encode()
    with EVLOCK, open(EV, "ab") as f:
        f.write(blob)  # un seul write par lot

def resolve_transcript(q):
    """-> (items) pour une requête /api/transcript ; [] si rien de valide."""
    path, adapter = "", None
    aid = q.get("agent_id", [""])[0]
    source = q.get("source", [""])[0]; sid = q.get("session", [""])[0]
    if not source and q.get("codex_session"): source, sid = "codex", q["codex_session"][0]  # ancien nom
    if aid and aid.isalnum():
        hits = glob.glob(f"{PROJ}/*/*/subagents/agent-{aid}.jsonl")
        path = hits[0] if hits else ""
    elif source and q.get("thread"):
        adapter = next((a for a in ADAPTERS if a.NAME == source), None)
        find = getattr(adapter, "find_thread", None)
        path = find(q["thread"][0]) if find else ""
    elif q.get("path"):
        path = q["path"][0]
    elif source and sid.isalnum():
        adapter = next((a for a in ADAPTERS if a.NAME == source), None)
        path = adapter.find_session(sid) if adapter else ""
    if not path: return []
    path = os.path.realpath(path)
    if not path.endswith(".jsonl") or not os.path.isfile(path): return []
    try:
        if under(path, PROJ): return transcript(path)
        for a in ADAPTERS:
            if under(path, a.ROOT_DIR): return a.transcript(path, short)
    except OSError: pass
    return []

class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def send(self, body, ctype="application/json", code=200):
        b = body.encode() if isinstance(body, str) else body
        try:
            self.send_response(code); self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)
        except OSError: pass  # le client a coupé
    def do_GET(self):
        if self.headers.get("Host", "") not in HOSTS: return self.send("Forbidden", "text/plain; charset=utf-8", 403)
        u = urllib.parse.urlparse(self.path); q = urllib.parse.parse_qs(u.query)
        if u.path == "/api/windows":
            return self.send(json.dumps({"n": n_windows(), "up": round(time.time() - START, 1), "views": views(), "unpinned": n_unpinned()}))
        if u.path == "/api/alive":
            try:
                self.send_response(200); self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-store"); self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers(); self.wfile.flush()
            except OSError: return
            key = object()
            view = q.get("view", [""])[0]
            with WLOCK: WINDOWS[key] = (view if view.isalnum() and len(view) <= 16 else "", q.get("pin", ["0"])[0] == "1")
            try:
                while True:
                    self.wfile.write(b": ping\n\n"); self.wfile.flush()
                    time.sleep(3)
            except Exception: pass
            finally:
                with WLOCK: WINDOWS.pop(key, None)
            return
        if u.path == "/api/events":
            try: off = max(0, int(q.get("since", ["0"])[0]))
            except ValueError: off = 0
            try:
                size = os.path.getsize(EV)
                if off > size: off = 0
                first = off == 0 and size > 3_000_000
                if first: off = size - 3_000_000  # premier chargement : seulement l'activité récente
                with open(EV, "rb") as f:
                    f.seek(off); data = f.read()
                if first:
                    cut = data.find(b"\n") + 1; off += cut; data = data[cut:]
            except FileNotFoundError: data = b""
            data = data[:data.rfind(b"\n") + 1]  # jamais au-delà d'une ligne incomplète
            evs = []
            for l in data.decode(errors="ignore").splitlines():
                try: evs.append(json.loads(l))
                except Exception: pass
            return self.send(json.dumps({"next": off + len(data), "events": evs, "pinned": pinned()}))
        if u.path == "/api/transcript":
            return self.send(json.dumps({"items": resolve_transcript(q)}))
        if u.path == "/api/titles":
            sids = [x for x in q.get("s", [""])[0].split(",") if x.isalnum()][:60]
            return self.send(json.dumps({x: t for x in sids if (t := any_title(x))}))
        if u.path == "/api/scores":
            try:
                with open(SC) as f: return self.send(f.read())
            except FileNotFoundError: return self.send('{"bugs":[]}')
        if u.path == "/api/agents":
            return self.send(json.dumps(list_agents()))
        if u.path in ("/", "/index.html"):
            with open(UI, "rb") as f: return self.send(f.read(), "text/html; charset=utf-8")
        return self.send("Not found", "text/plain; charset=utf-8", 404)

class S(http.server.ThreadingHTTPServer):
    daemon_threads = True; allow_reuse_address = True
    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)): return
        super().handle_error(request, client_address)

if __name__ == "__main__":
    for a in ADAPTERS: a.start(emit)
    S(("127.0.0.1", PORT), H).serve_forever()
