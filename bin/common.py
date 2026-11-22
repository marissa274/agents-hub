"""Chemins, port et utilitaires communs à tous les scripts d'Agents Hub."""
import json, os

os.umask(0o077)  # les journaux contiennent des prompts : lisibles par l'utilisateur seulement

ROOT = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
DATA = os.environ.get("AGENTS_HUB_DATA") or os.path.join(ROOT, "logs")
os.makedirs(DATA, mode=0o700, exist_ok=True)

CLAUDE = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")

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


def short(v, n=220):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + " …"
