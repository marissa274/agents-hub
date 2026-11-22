#!/usr/bin/env python3
"""Scoreboard du reviewer.
  score.py add --cycle 1 --severity majeur --file app/x.php --line 12 --title ".." --scenario ".."
  score.py reject C1-B2 [--reason ..]   (faux positif, -3)
  score.py confirm C1-B2 | fixed C1-B2
  score.py total | list | reset
"""
import argparse, json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import SC as F, codex_root, task_key, env_task
# chaque bug appartient au projet (racine git) d'où la commande est lancée : les projets ne se mélangent pas
try: PROJ = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True).stdout.strip() or os.getcwd()
except Exception: PROJ = os.getcwd()
# chaque bug appartient aussi à la tâche (session Claude Code ou Codex) qui l'a noté : la fenêtre d'une tâche ne montre que ses bugs
SID, SRC, THREAD = env_task()  # outil le plus proche (Claude ou Codex), même règle que bin/hub
def ours(b): return b.get("session") == SID if SID else b.get("project") == PROJ
PTS = {"critique": 10, "majeur": 5, "mineur": 2, "style": 1}
def load():
    try: return json.load(open(F))
    except Exception: return {"bugs": []}
def save(s):
    tmp = f"{F}.{os.getpid()}.tmp"
    with open(tmp, "w") as f: json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, F)
def total(s): return sum((-3 if b["status"] == "rejeté" else b["points"]) for b in s["bugs"] if ours(b))
p = argparse.ArgumentParser(); sp = p.add_subparsers(dest="cmd", required=True)
a = sp.add_parser("add")
a.add_argument("--cycle", type=int, choices=[1, 2, 3], required=True)
for k in ("severity", "file", "line", "title", "scenario"): a.add_argument("--" + k, default="")
for c in ("reject", "confirm", "fixed"):
    x = sp.add_parser(c); x.add_argument("id"); x.add_argument("--reason", default="")
for c in ("total", "list", "reset"): sp.add_parser(c)
o = p.parse_args(); s = load()
mine = [b for b in s["bugs"] if ours(b)]
if o.cmd == "add":
    sev = o.severity.lower()
    if sev not in PTS: sys.exit(f"Sévérité invalide : {o.severity!r} (attendu : {', '.join(PTS)}).")
    n = 1 + sum(1 for b in mine if str(b["cycle"]) == str(o.cycle))
    b = dict(id=f"C{o.cycle}-B{n}", cycle=o.cycle, severity=sev, points=PTS.get(sev, 1),
             file=o.file, line=o.line, title=o.title, scenario=o.scenario, status="signalé", ts=time.time(), project=PROJ, session=SID, **({"thread": THREAD} if THREAD else {}))
    s["bugs"].append(b); save(s); print(f'{b["id"]} enregistré (+{b["points"]} pts). Total: {total(s)}')
elif o.cmd in ("reject", "confirm", "fixed"):
    st = {"reject": "rejeté", "confirm": "confirmé", "fixed": "corrigé"}[o.cmd]
    for b in mine:
        if b["id"] == o.id: b["status"] = st; b["reason"] = o.reason
    save(s); print(f"{o.id} -> {st}. Total: {total(s)}")
elif o.cmd == "total": print(f"Total reviewer: {total(s)} pts")
elif o.cmd == "list":
    for b in mine: print(b["id"], b["severity"], b["status"], f'{b["file"]}:{b["line"]}', b["title"])
elif o.cmd == "reset":
    s["bugs"] = [b for b in s["bugs"] if not ours(b)]  # seulement cette tâche (ou ce projet hors tâche)
    save(s); print(f"Scoreboard {'de cette tâche' if SID else 'de ' + os.path.basename(PROJ) + ' (hors tâche)'} remis à zéro")
