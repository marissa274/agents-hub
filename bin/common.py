"""Chemins, port et utilitaires communs à tous les scripts d'Agents Hub."""
import glob, json, os, re

os.umask(0o077)  # les journaux contiennent des prompts : lisibles par l'utilisateur seulement

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DATA = os.environ.get("AGENTS_HUB_DATA") or os.path.join(ROOT, "logs")
os.makedirs(DATA, mode=0o700, exist_ok=True)

CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")



def _codex_home():
    """$CODEX_HOME, sinon le dossier mémorisé à l'installation, sinon ~/.codex (lecture tolérante)."""
    env = os.environ.get("CODEX_HOME")
    if env: return env
    try:
        with open(os.path.join(DATA, "install-manifest.json"), encoding="utf-8") as f: d = json.load(f)
        h = d.get("codex_home") if isinstance(d, dict) else None
        if isinstance(h, str) and h.startswith("/"): return h
    except Exception:
        pass
    return os.path.expanduser("~/.codex")


CODEX = _codex_home()

EV = os.path.join(DATA, "events.jsonl")
SC = os.path.join(DATA, "scores.json")
LOCK = os.path.join(DATA, ".open.lock")
LAST = os.path.join(DATA, ".lastopen.json")
ERR = os.path.join(DATA, "server.err")

try:
    PORT = int(os.environ.get("AGENTS_HUB_PORT") or 7777)
except ValueError:
    PORT = 7777
URL = f"http://127.0.0.1:{PORT}/"


def codex_root(tid):
    """Tâche racine d'un fil Codex : session_id du rollout, sinon parent_thread_id, sinon le fil lui-même."""
    try:
        if re.match(r"^[0-9a-fA-F-]{8,64}$", tid):
            hits = glob.glob(os.path.join(glob.escape(CODEX), "sessions", "*", "*", "*", f"*-{tid}.jsonl"))
            if hits:
                with open(max(hits, key=os.path.getmtime)) as f: meta = json.loads(f.readline()).get("payload") or {}
                return str(meta.get("session_id") or meta.get("parent_thread_id") or tid)
    except Exception: pass
    return tid


def task_key(uuid, source="claude"):
    """Clé courte de tâche (8 caractères alphanumériques ASCII), commune au hook, à l'adaptateur, au score et à la fenêtre.

    Claude Code : les 8 premiers. Codex : les 8 derniers, car ses ids de fil sont des UUIDv7 dont le début est un
    horodatage (identique pour deux tâches lancées à ~65 s d'écart) ; la fin est la partie aléatoire."""
    s = "".join(c for c in str(uuid or "") if c.isascii() and c.isalnum())
    return s[-8:] if source == "codex" else s[:8]


def short(v, n=220):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"
