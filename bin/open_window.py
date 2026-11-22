#!/usr/bin/env python3
"""Ouvre une fenêtre du Hub par tâche, jamais deux pour la même.

  open_window.py                     sans argument (/hub) : la tâche en cours = « session <id> » d'après
                                     CLAUDE_CODE_SESSION_ID, sinon CODEX_THREAD_ID (tâche racine), sinon auto
  open_window.py [auto|--auto]       ouvre la fenêtre seulement si aucune fenêtre non épinglée n'est ouverte
                                     (elle suit la tâche active ; les fenêtres épinglées ne comptent pas)
  open_window.py session <id>        ouvre une fenêtre épinglée sur la tâche <id>, sauf si une fenêtre l'affiche déjà
  open_window.py --hook              ancien hook Claude Code (anciennes installations) : ne fait plus rien

Aucun hook n'ouvre de fenêtre : elle s'ouvre seulement via /hub (ou le skill hub).

Le serveur est démarré au besoin ; il compte les fenêtres ouvertes, les non épinglées et les tâches affichées
(GET /api/windows). Ce processus détaché peut attendre quelques secondes (garde globale, fenêtre en cours
d'ouverture) puis revérifier, plutôt que d'abandonner.
"""
import json, os, platform, shutil, socket, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import fcntl
except ImportError:
    sys.exit("Agents Hub : Windows non supporté (fcntl indisponible).")
from common import ROOT, LOCK, LAST, ERR, PORT, URL, codex_root, task_key

GRACE = 20       # secondes : une fenêtre qui vient d'être ouverte met un moment à se signaler (par tâche)
GLOBAL_GUARD = 3 # secondes : garde courte entre deux ouvertures, toutes tâches confondues
SETTLE = 5       # secondes : après un démarrage du serveur, les fenêtres existantes se reconnectent
POLL = 0.5       # secondes : cadence de relecture de /api/windows en attendant qu'une fenêtre se déclare
CHROMES = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "brave-browser", "microsoft-edge"]


def should_open(n, up, last_open, now, sid="", views=None, last_any=0):
    """Faut-il ouvrir une fenêtre ?

    n = fenêtres non épinglées (mode auto) ou connectées (mode session), serveur démarré depuis up s,
    last_open = dernière ouverture pour cette clé (la tâche sid, ou la clé auto), last_any = dernière ouverture.
    Mode session (sid) : non si une fenêtre affiche déjà cette tâche (views = {sid: nb}).
    Mode auto (sid vide) : non si une fenêtre non épinglée est ouverte, quelle que soit la tâche.
    """
    if sid:
        if (views or {}).get(sid, 0) > 0: return False  # cette tâche a déjà sa fenêtre
    elif n > 0: return False                            # une fenêtre est déjà ouverte
    if up < SETTLE: return False                        # trop tôt pour savoir : les fenêtres se reconnectent
    if now - last_open < GRACE: return False           # une ouverture est déjà en cours pour cette clé
    if now - last_any < GLOBAL_GUARD: return False     # rafale d'ouvertures
    return True


def wait_needed(n, now, sid, views, last):
    """Secondes à attendre avant de décider (0 = décider maintenant).

    - garde globale : une ouverture toutes tâches confondues date de moins de GLOBAL_GUARD s ;
    - mode session : une fenêtre auto vient d'être ouverte (moins de GRACE s) et ne s'est pas encore déclarée
      (n n'a pas augmenté) : elle affichera peut-être cette tâche, on attend de voir ses vues réelles."""
    if sid and (views or {}).get(sid, 0) > 0: return 0
    def ts(k):
        v = last.get(k, 0)
        return v if isinstance(v, (int, float)) else 0
    d = max(0, GLOBAL_GUARD - (now - ts("_any")))
    auto_age = now - ts("*")
    if sid and auto_age < GRACE and n <= ts("_n"):
        d = max(d, min(POLL, GRACE - auto_age))
    return d


def clean_sid(v):
    """8 premiers caractères alphanumériques d'un identifiant de session (comme log_event)."""
    return "".join(c for c in str(v or "") if c.isascii() and c.isalnum())[:8]


def port_open(timeout=0.3):
    try:
        socket.create_connection(("127.0.0.1", PORT), timeout).close()
        return True
    except OSError:
        return False


def start_server():
    with open(ERR, "ab") as err:
        subprocess.Popen([sys.executable, os.path.join(ROOT, "bin", "server.py")], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=err, start_new_session=True)
    end = time.time() + 2
    while time.time() < end:
        if port_open(): return True
        time.sleep(0.1)
    return port_open()


def windows():
    """(n, up, views, unpinned) d'après le serveur, ou None s'il ne répond pas."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/windows", timeout=1) as r:
            d = json.load(r)
        views = d.get("views") if isinstance(d.get("views"), dict) else {}
        n = int(d.get("n", 0))
        return n, float(d.get("up", 0)), views, int(d.get("unpinned", n))
    except Exception:
        return None


def launch(url):
    """Ouvre url dans une fenêtre d'application Chrome si possible, sinon le navigateur par défaut."""
    quiet = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    system = platform.system()
    if system == "Darwin":
        if subprocess.run(["open", "-Ra", "Google Chrome"], **quiet).returncode == 0:
            subprocess.run(["open", "-na", "Google Chrome", "--args", f"--app={url}", "--window-size=1440,920"], **quiet)
            return "chrome"
    elif system == "Linux":
        if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            print(f"Agents Hub : pas d'affichage graphique, ouvre {url} dans un navigateur.", file=sys.stderr)
            return "none"
        for name in CHROMES:
            exe = shutil.which(name)
            if exe:
                subprocess.Popen([exe, f"--app={url}", "--window-size=1440,920"], start_new_session=True, **quiet)
                return name
    import webbrowser
    webbrowser.open(url)
    return "webbrowser"


def load_last():
    try:
        with open(LAST) as f: last = json.load(f)
        return last if isinstance(last, dict) else {}
    except Exception:
        return {}


def current_task():
    """Tâche en cours d'après l'environnement : session Claude Code, sinon tâche racine du fil Codex, sinon "" (auto)."""
    sid = task_key(os.environ.get("CLAUDE_CODE_SESSION_ID"))
    if not sid and os.environ.get("CODEX_THREAD_ID"):
        sid = task_key(codex_root(os.environ["CODEX_THREAD_ID"]), "codex")
    return sid


def main(argv):
    if "--hook" in argv: return 0  # compat : les anciens hooks n'ouvrent plus rien
    if argv and argv[0] in ("auto", "--auto"): sid = ""
    elif len(argv) > 1 and argv[0] == "session": sid = clean_sid(argv[1])
    else: sid = current_task()
    key = sid or "*"
    with open(LOCK, "w") as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)  # les appels simultanés passent l'un après l'autre
        if not port_open() and not start_server():
            print(f"Agents Hub : le serveur ne démarre pas (voir {ERR}).", file=sys.stderr)
            return 1
        w = windows()
        if w is None:
            print("Agents Hub : le serveur ne répond pas.", file=sys.stderr)
            return 1
        n, up, views, unpinned = w
        shown = views.get(sid, 0) if sid else unpinned
        if shown == 0 and up < SETTLE:
            time.sleep(SETTLE - up)  # laisse aux fenêtres déjà ouvertes le temps de se reconnecter
            w = windows()
            if w is None: return 1
            n, up, views, unpinned = w
            up = max(up, SETTLE)  # le délai est écoulé, quoi qu'en dise l'horloge du serveur
        while True:
            now = time.time()
            last = load_last()
            d = wait_needed(n, now, sid, views, last)
            if d <= 0: break
            time.sleep(d)  # garde globale ou fenêtre en cours d'ouverture : on attend puis on revérifie
            w = windows()
            if w is None: return 1
            n, _, views, unpinned = w
        def ts(k):
            v = last.get(k, 0)
            return v if isinstance(v, (int, float)) else 0
        if not should_open(n if sid else unpinned, up, ts(key), now, sid, views, ts("_any")):
            if (views.get(sid, 0) if sid else unpinned) > 0: print("Agents Hub est déjà ouvert pour cette tâche.")
            else: print("Agents Hub est en train de s'ouvrir… si rien n'apparaît, réessaie dans quelques secondes.")
            return 0
        last = {k: v for k, v in last.items() if isinstance(v, (int, float)) and (k == "_n" or now - v < 600)}
        last[key] = last["_any"] = now
        last["_n"] = n  # fenêtres connectées avant cette ouverture : sert à repérer quand la nouvelle se déclare
        tmp = f"{LAST}.{os.getpid()}.tmp"
        with open(tmp, "w") as f: json.dump(last, f)
        os.replace(tmp, LAST)
        launch(f"{URL}#s-{sid}" if sid else URL)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
