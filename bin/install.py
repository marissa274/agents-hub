#!/usr/bin/env python3
"""Installe ou désinstalle Agents Hub dans la configuration de Claude Code.

  install.py install [--force]     copie les agents et le skill, ajoute les hooks
  install.py uninstall             retire ce que install a ajouté (et seulement cela)

Dossier de configuration : $CLAUDE_CONFIG_DIR ou ~/.claude. Rien n'est modifié dans les logs ni dans le dépôt.
"""
import argparse, hashlib, json, os, shlex, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA, CLAUDE

MARK = "__AGENTS_HUB__"
MANIFEST = os.path.join(DATA, "install-manifest.json")
SETTINGS = os.path.join(CLAUDE, "settings.json")
TIMEOUT = 5


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def sha_file(path):
    with open(path, "rb") as f: return sha(f.read())


def commands():
    """[(événement, matcher ou None, commande)] des hooks du Hub."""
    log = f"python3 {shlex.quote(os.path.join(ROOT, 'bin', 'log_event.py'))}"
    win = f"python3 {shlex.quote(os.path.join(ROOT, 'bin', 'open_window.py'))} --hook >/dev/null 2>&1"
    return [("PreToolUse", "*", log), ("PreToolUse", "Agent|Task", win),
            ("SubagentStart", "*", log), ("SubagentStop", "*", log),
            ("UserPromptSubmit", None, log), ("Stop", None, log), ("Notification", None, log)]


def load_settings():
    """dict des réglages ; {} si absent ; None si le JSON est invalide (on n'écrit alors rien)."""
    try:
        with open(SETTINGS, encoding="utf-8") as f: d = json.load(f)
    except FileNotFoundError:
        return {}
    except (ValueError, OSError):
        return None
    return d if isinstance(d, dict) else None


def hooks_shape_ok(settings):
    """True si settings["hooks"] est absent ou un dict dont chaque valeur est une liste."""
    h = settings.get("hooks", {})
    return isinstance(h, dict) and all(isinstance(v, list) for v in h.values())


def load_manifest():
    try:
        with open(MANIFEST, encoding="utf-8") as f: d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def write_atomic(path, text):
    path = os.path.realpath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f: f.write(text)
    try: shutil.copymode(path, tmp)
    except OSError: pass
    os.replace(tmp, path)


def write_settings(s):
    write_atomic(SETTINGS, json.dumps(s, indent=2, ensure_ascii=False) + "\n")


def backup_settings():
    if not os.path.exists(SETTINGS): return
    d = os.path.join(ROOT, "backups")
    os.makedirs(d, mode=0o700, exist_ok=True)
    base = os.path.join(d, "settings.json." + time.strftime("%Y%m%d-%H%M%S"))
    dest, n = base, 1
    while os.path.exists(dest): dest = f"{base}.{n}"; n += 1
    shutil.copy2(SETTINGS, dest)
    print(f"Sauvegarde de settings.json : {dest}")


def all_commands(settings):
    out = []
    for groups in (settings.get("hooks") or {}).values():
        for g in groups if isinstance(groups, list) else []:
            for h in (g.get("hooks") or []) if isinstance(g, dict) else []:
                if isinstance(h, dict) and isinstance(h.get("command"), str): out.append(h["command"])
    return out


def remove_commands(settings, cmds):
    """Retire exactement ces commandes ; supprime groupe/clé seulement s'ils deviennent vides. -> nombre retiré."""
    cmds, removed = set(cmds), 0
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict): return 0
    for ev in list(hooks):
        groups = hooks[ev]
        if not isinstance(groups, list): continue
        kept = []
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                before = len(g["hooks"])
                g["hooks"] = [h for h in g["hooks"] if not (isinstance(h, dict) and h.get("command") in cmds)]
                removed += before - len(g["hooks"])
                if before and not g["hooks"]: continue
            kept.append(g)
        if kept: hooks[ev] = kept
        elif groups: del hooks[ev]
    if not hooks and removed: del settings["hooks"]
    return removed


def add_hooks(settings):
    added = []
    hooks = settings.setdefault("hooks", {})
    for ev, matcher, cmd in commands():
        groups = hooks.setdefault(ev, [])
        if cmd in all_commands({"hooks": {ev: groups}}): continue
        g = {"hooks": [{"type": "command", "command": cmd, "timeout": TIMEOUT}]}
        if matcher is not None: g = {"matcher": matcher, **g}
        groups.append(g); added.append(cmd)
    return added


def sources():
    """[(source, destination, est_un_agent)] avec le marqueur remplacé par le chemin du dépôt."""
    out = []
    adir = os.path.join(ROOT, "agents")
    for n in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        if n.endswith(".md"): out.append((os.path.join(adir, n), os.path.join(CLAUDE, "agents", n), True))
    skill = os.path.join(ROOT, "skills", "hub", "SKILL.md")
    if os.path.exists(skill): out.append((skill, os.path.join(CLAUDE, "skills", "hub", "SKILL.md"), False))
    return out


def install(force):
    bad = [c for c in '"$`\\\n\r' if c in ROOT]
    if bad:
        print(f"Abandon : le chemin du dépôt ({ROOT!r}) contient un caractère interdit (guillemet \", $, `, \\ ou saut de ligne). "
              "Déplacez le dépôt dans un chemin sans ces caractères (les espaces sont acceptés).", file=sys.stderr)
        return 1
    settings = load_settings()
    if settings is None:
        print(f"Abandon : {SETTINGS} n'est pas un JSON valide. Corrigez-le puis relancez (rien n'a été modifié).", file=sys.stderr)
        return 1
    if not hooks_shape_ok(settings):
        print(f"Abandon : la clé \"hooks\" de {SETTINGS} n'a pas la forme attendue (un objet dont chaque événement est une liste). "
              "Corrigez-la puis relancez (rien n'a été modifié).", file=sys.stderr)
        return 1
    man = load_manifest()
    old_cmds = [c for c in man.get("commands", []) if isinstance(c, str)]
    ours = {c for _, _, c in commands()} | set(old_cmds)
    foreign = sorted({c for c in all_commands(settings) if ("log_event.py" in c or "bin/hub" in c) and c not in ours})
    if foreign and not force:
        print("Abandon : settings.json contient déjà des hooks Agents Hub d'une autre installation :", file=sys.stderr)
        for c in foreign: print(f"  {c}", file=sys.stderr)
        print("Désinstallez l'autre version, ou relancez avec --force pour ajouter celle-ci en plus.", file=sys.stderr)
        return 1

    # fichiers
    files = {p: h for p, h in (man.get("files") or {}).items() if os.path.exists(p)}
    for src, dst, is_agent in sources():
        with open(src, encoding="utf-8") as f: text = f.read().replace(MARK, ROOT)
        h = sha(text)
        if not os.path.exists(dst):
            write_atomic(dst, text); files[dst] = h
            print(f"Installé : {dst}")
        elif sha_file(dst) == h:
            files[dst] = h  # identique à notre version : on l'enregistre (même sans manifeste préalable)
            print(f"À jour : {dst}")
        elif files.get(dst) == sha_file(dst):  # c'est notre copie, jamais modifiée : on la met à jour
            write_atomic(dst, text); files[dst] = h
            print(f"Mis à jour : {dst}")
        elif is_agent:
            print(f"Agent existant conservé : {dst}")
        else:
            print(f"Attention : {dst} a été modifié, il est conservé tel quel (supprimez-le pour réinstaller la version du dépôt).")

    # hooks
    if man.get("root") and man.get("root") != ROOT and old_cmds:
        n = remove_commands(settings, old_cmds)
        print(f"Anciens hooks retirés ({man['root']}) : {n}")
    added = add_hooks(settings)
    changed = bool(added) or bool(man.get("root") and man.get("root") != ROOT and old_cmds)
    if changed:
        backup_settings()
        write_settings(settings)
        print(f"Hooks ajoutés dans {SETTINGS} : {len(added)}")
    else:
        print("Hooks déjà en place.")
    cmds = sorted({c for _, _, c in commands()})
    write_atomic(MANIFEST, json.dumps({"root": ROOT, "files": files, "commands": cmds}, indent=2, ensure_ascii=False) + "\n")
    print("Terminé. Redémarrez Claude Code pour charger les hooks, puis lancez bin/hub.")
    return 0


def uninstall():
    man = load_manifest()
    if not man:
        print("Rien à désinstaller (aucun manifeste d'installation).")
        return 0
    settings = load_settings()
    if settings is None:
        print(f"Abandon : {SETTINGS} n'est pas un JSON valide (rien n'a été modifié).", file=sys.stderr)
        return 1
    cmds = [c for c in man.get("commands", []) if isinstance(c, str)]
    before = json.dumps(settings, sort_keys=True)
    n = remove_commands(settings, cmds)
    if json.dumps(settings, sort_keys=True) != before:
        backup_settings()
        write_settings(settings)
    print(f"Hooks retirés : {n}")
    for path, h in (man.get("files") or {}).items():
        if not os.path.exists(path): continue
        if sha_file(path) == h:
            os.remove(path); print(f"Supprimé : {path}")
            parent = os.path.dirname(path)
            if os.path.basename(parent) == "hub":  # dossier du skill, s'il est vide
                try: os.rmdir(parent)
                except OSError: pass
        else:
            print(f"Modifié, conservé : {path}")
    try: os.remove(MANIFEST)
    except OSError: pass
    print("Désinstallé. Les logs et le dépôt n'ont pas été touchés.")
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("action", choices=["install", "uninstall"])
    p.add_argument("--force", action="store_true", help="installer même si d'autres hooks Agents Hub existent")
    o = p.parse_args()
    return install(o.force) if o.action == "install" else uninstall()


if __name__ == "__main__":
    sys.exit(main())
