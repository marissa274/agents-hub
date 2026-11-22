#!/usr/bin/env python3
"""Installe ou désinstalle Agents Hub dans la configuration de Claude Code et de Codex.

  install.py install [--force] [--no-codex]   copie les agents et le skill, ajoute les hooks
  install.py uninstall                        retire ce que install a ajouté (et seulement cela)

Dossiers de configuration : $CLAUDE_CONFIG_DIR ou ~/.claude ; $CODEX_HOME ou ~/.codex (Codex n'est configuré que
s'il est détecté : dossier présent ou binaire `codex` dans le PATH). Rien n'est modifié dans les logs ni dans le dépôt.
"""
import argparse, hashlib, json, os, shlex, shutil, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ROOT, DATA, CLAUDE, CODEX

MARK = "__AGENTS_HUB__"
MANIFEST = os.path.join(DATA, "install-manifest.json")
SETTINGS = os.path.join(CLAUDE, "settings.json")
CODEX_HOOKS = os.path.join(CODEX, "hooks.json")
TIMEOUT = 5


def sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode()).hexdigest()


def sha_file(path):
    with open(path, "rb") as f: return sha(f.read())


def codex_commands():
    """[(événement, matcher ou None, commande)] des hooks Codex : une seule commande, source codex."""
    log = f"python3 {shlex.quote(os.path.join(ROOT, 'bin', 'log_event.py'))} --source codex"
    return [("PreToolUse", "*", log), ("SubagentStart", "*", log), ("SubagentStop", "*", log),
            ("UserPromptSubmit", None, log), ("Stop", None, log), ("PermissionRequest", "*", log)]


def commands():
    """[(événement, matcher ou None, commande)] des hooks du Hub."""
    log = f"python3 {shlex.quote(os.path.join(ROOT, 'bin', 'log_event.py'))}"
    win = f"python3 {shlex.quote(os.path.join(ROOT, 'bin', 'open_window.py'))} --hook >/dev/null 2>&1"
    return [("PreToolUse", "*", log), ("PreToolUse", "Agent|Task", win),
            ("SubagentStart", "*", log), ("SubagentStop", "*", log),
            ("UserPromptSubmit", None, log), ("Stop", None, log), ("Notification", None, log)]


def load_json(path):
    """dict ; {} si le fichier est absent ; None s'il est invalide (on n'écrit alors rien)."""
    try:
        with open(path, encoding="utf-8") as f: d = json.load(f)
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


def write_json(path, d):
    write_atomic(path, json.dumps(d, indent=2, ensure_ascii=False) + "\n")


def backup(path, label):
    if not os.path.exists(path): return
    d = os.path.join(ROOT, "backups")
    os.makedirs(d, mode=0o700, exist_ok=True)
    base = os.path.join(d, f"{label}." + time.strftime("%Y%m%d-%H%M%S"))
    dest, n = base, 1
    while os.path.exists(dest): dest = f"{base}.{n}"; n += 1
    shutil.copy2(path, dest)
    print(f"Sauvegarde de {label} : {dest}")


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


def add_hooks(settings, cmds):
    added = []
    hooks = settings.setdefault("hooks", {})
    for ev, matcher, cmd in cmds:
        groups = hooks.setdefault(ev, [])
        if cmd in all_commands({"hooks": {ev: groups}}): continue
        g = {"hooks": [{"type": "command", "command": cmd, "timeout": TIMEOUT}]}
        if matcher is not None: g = {"matcher": matcher, **g}
        groups.append(g); added.append(cmd)
    return added


def toml_str(v):
    """Chaîne TOML « basique » sur une ligne (le JSON en est un sous-ensemble ; DEL doit être échappé)."""
    return json.dumps(v, ensure_ascii=False).replace("\x7f", "\\u007f")


def toml_multiline(v):
    """Contenu d'une chaîne TOML multiligne basique : \\, guillemets et caractères de contrôle échappés."""
    out = []
    for c in v:
        if c == "\\": out.append("\\\\")
        elif c == '"': out.append('\\"')
        elif c == "\r": out.append("\\r")
        elif c in "\t\n": out.append(c)
        elif ord(c) < 0x20 or ord(c) == 0x7F: out.append("\\u%04X" % ord(c))
        else: out.append(c)
    return "".join(out)


def split_agent(text, stem):
    """(name, description, corps) d'un agent .md à frontmatter ; sans frontmatter : tout le texte est le corps."""
    name, desc, body = stem, "", text
    if text.startswith("---\n"):
        end = text.find("\n---\n", 3)
        if end != -1:
            for l in text[4:end].split("\n"):
                if l.startswith("name:"): name = l[5:].strip() or stem
                elif l.startswith("description:"): desc = l[12:].strip()
            body = text[end + 5:]
    return name, desc, body


def to_codex_agent(text, stem):
    """Agent Codex .toml : name, description, developer_instructions (rien d'autre)."""
    name, desc, body = split_agent(text, stem)
    return (f"name = {toml_str(name)}\ndescription = {toml_str(desc)}\n"
            f'developer_instructions = """\n{toml_multiline(body)}"""\n')


def sources(with_codex):
    """[(texte, destination, est_un_agent, outil)] avec le marqueur remplacé par le chemin du dépôt."""
    out = []
    adir = os.path.join(ROOT, "agents")
    for n in sorted(os.listdir(adir)) if os.path.isdir(adir) else []:
        if not n.endswith(".md"): continue
        with open(os.path.join(adir, n), encoding="utf-8") as f: text = f.read().replace(MARK, ROOT)
        out.append((text, os.path.join(CLAUDE, "agents", n), True, "claude"))
        if with_codex:
            with open(os.path.join(adir, n), encoding="utf-8", newline="") as f: raw = f.read().replace(MARK, ROOT)  # \r conservés
            out.append((to_codex_agent(raw, n[:-3]), os.path.join(CODEX, "agents", n[:-3] + ".toml"), True, "codex"))
    skill = os.path.join(ROOT, "skills", "hub", "SKILL.md")
    if os.path.exists(skill):
        with open(skill, encoding="utf-8") as f: text = f.read().replace(MARK, ROOT)
        out.append((text, os.path.join(CLAUDE, "skills", "hub", "SKILL.md"), False, "claude"))
        if with_codex: out.append((text, os.path.join(CODEX, "skills", "hub", "SKILL.md"), False, "codex"))
    return out


def codex_detected():
    return os.path.isdir(CODEX) or bool(shutil.which("codex"))


def foreign_cmds(settings, ours):
    return sorted({c for c in all_commands(settings) if ("log_event.py" in c or "bin/hub" in c) and c not in ours})


def install(force, no_codex=False):
    bad = [c for c in '"$`\\\n\r' if c in ROOT]
    if bad:
        print(f"Abandon : le chemin du dépôt ({ROOT!r}) contient un caractère interdit (guillemet \", $, `, \\ ou saut de ligne). "
              "Déplacez le dépôt dans un chemin sans ces caractères (les espaces sont acceptés).", file=sys.stderr)
        return 1
    with_codex = not no_codex and codex_detected()
    hint = " Corrigez-le puis relancez" + (", ou relancez avec --no-codex pour ignorer Codex" if with_codex else "") + " (rien n'a été modifié)."
    # 1. toutes les vérifications, pour Claude ET Codex, avant la moindre écriture
    settings = load_json(SETTINGS)
    if settings is None:
        print(f"Abandon : {SETTINGS} n'est pas un JSON valide. Corrigez-le puis relancez (rien n'a été modifié).", file=sys.stderr)
        return 1
    if not hooks_shape_ok(settings):
        print(f"Abandon : la clé \"hooks\" de {SETTINGS} n'a pas la forme attendue (un objet dont chaque événement est une liste). "
              "Corrigez-la puis relancez (rien n'a été modifié).", file=sys.stderr)
        return 1
    chooks, codex_existed = {}, False
    if with_codex:
        chooks = load_json(CODEX_HOOKS)
        if chooks is None:
            print(f"Abandon : {CODEX_HOOKS} n'est pas un JSON valide.{hint}", file=sys.stderr)
            return 1
        if not hooks_shape_ok(chooks):
            print(f"Abandon : la clé \"hooks\" de {CODEX_HOOKS} n'a pas la forme attendue (un objet dont chaque événement est une liste).{hint}",
                  file=sys.stderr)
            return 1
        codex_existed = os.path.exists(CODEX_HOOKS)
    man = load_manifest()
    old_cmds = [c for c in man.get("commands", []) if isinstance(c, str)]
    old_ccmds = [c for c in man.get("codex_commands", []) if isinstance(c, str)]
    ccmds = codex_commands()
    ours = {c for _, _, c in commands()} | {c for _, _, c in ccmds} | set(old_cmds) | set(old_ccmds)
    found = [(SETTINGS, c) for c in foreign_cmds(settings, ours)] + [(CODEX_HOOKS, c) for c in foreign_cmds(chooks, ours)]
    if found and not force:
        print("Abandon : des hooks Agents Hub d'une autre installation existent déjà :", file=sys.stderr)
        for path, c in found: print(f"  {path} : {c}", file=sys.stderr)
        print("Désinstallez l'autre version, ou relancez avec --force pour ajouter celle-ci en plus.", file=sys.stderr)
        return 1

    # 2. fichiers (agents, skill)
    files = {p: h for p, h in (man.get("files") or {}).items() if os.path.exists(p)}
    for text, dst, is_agent, tool in sources(with_codex):
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
        elif tool == "codex":
            print(f"Skill existant conservé : {dst} (renomme-le pour installer celui d'Agents Hub).")
        else:
            print(f"Attention : {dst} a été modifié, il est conservé tel quel (supprimez-le pour réinstaller la version du dépôt).")

    # 3. hooks Claude
    moved = bool(man.get("root") and man.get("root") != ROOT)
    if moved and old_cmds:
        n = remove_commands(settings, old_cmds)
        print(f"Anciens hooks retirés ({man['root']}) : {n}")
    added = add_hooks(settings, commands())
    if added or (moved and old_cmds):
        backup(SETTINGS, "settings.json")
        write_json(SETTINGS, settings)
        print(f"Hooks ajoutés dans {SETTINGS} : {len(added)}")
    else:
        print("Hooks déjà en place.")

    # 4. hooks Codex
    created = bool(man.get("codex_hooks_created"))
    if with_codex:
        if not codex_existed and not os.path.isdir(CODEX): os.makedirs(CODEX, mode=0o700, exist_ok=True)
        if moved and old_ccmds:
            n = remove_commands(chooks, old_ccmds)
            print(f"Anciens hooks Codex retirés ({man['root']}) : {n}")
        cadded = add_hooks(chooks, ccmds)
        if cadded or (moved and old_ccmds):
            if codex_existed: backup(CODEX_HOOKS, "codex-hooks.json")
            else: created = True
            write_json(CODEX_HOOKS, chooks)
            print(f"Hooks Codex ajoutés dans {CODEX_HOOKS} : {len(cadded)}")
        else:
            print("Hooks Codex déjà en place.")
    elif not no_codex:
        print("Codex non détecté : hooks, agents et skill Codex ignorés (relancez l'installation une fois Codex installé).")
    else:
        print("Codex ignoré (--no-codex).")

    new = {"root": ROOT, "files": files, "commands": sorted({c for _, _, c in commands()})}
    if with_codex:
        new.update(codex_home=CODEX, codex_commands=sorted({c for _, _, c in ccmds}), codex_hooks_created=created)
    else:  # Codex non touché cette fois : on conserve ce que l'installation précédente avait enregistré
        for k in ("codex_home", "codex_commands", "codex_hooks_created"):
            if k in man: new[k] = man[k]
    write_atomic(MANIFEST, json.dumps(new, indent=2, ensure_ascii=False) + "\n")
    print("Terminé. Redémarrez Claude Code pour charger les hooks, puis lancez bin/hub.")
    if with_codex:
        print("Dans Codex : tape /hooks et approuve les hooks d'Agents Hub (à refaire si le dépôt est déplacé).")
    return 0


def uninstall():
    man = load_manifest()
    if not man:
        print("Rien à désinstaller (aucun manifeste d'installation).")
        return 0
    settings = load_json(SETTINGS)
    if settings is None:
        print(f"Abandon : {SETTINGS} n'est pas un JSON valide (rien n'a été modifié).", file=sys.stderr)
        return 1
    chome = man.get("codex_home") if isinstance(man.get("codex_home"), str) and man.get("codex_home") else ""
    chooks_path = os.path.join(chome, "hooks.json") if chome else ""
    chooks = load_json(chooks_path) if chome else {}
    if chooks is None:
        print(f"Abandon : {chooks_path} n'est pas un JSON valide (rien n'a été modifié).", file=sys.stderr)
        return 1
    cmds = [c for c in man.get("commands", []) if isinstance(c, str)]
    before = json.dumps(settings, sort_keys=True)
    n = remove_commands(settings, cmds)
    if json.dumps(settings, sort_keys=True) != before:
        backup(SETTINGS, "settings.json")
        write_json(SETTINGS, settings)
    print(f"Hooks retirés : {n}")
    if chome:
        ccmds = [c for c in man.get("codex_commands", []) if isinstance(c, str)]
        before = json.dumps(chooks, sort_keys=True)
        n = remove_commands(chooks, ccmds)
        if json.dumps(chooks, sort_keys=True) != before:
            if man.get("codex_hooks_created") and not chooks:
                os.remove(chooks_path); print(f"Supprimé : {chooks_path}")
            else:
                backup(chooks_path, "codex-hooks.json")
                write_json(chooks_path, chooks)
        print(f"Hooks Codex retirés : {n}")
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
    p.add_argument("--no-codex", action="store_true", help="ne pas configurer Codex")
    o = p.parse_args()
    return install(o.force, o.no_codex) if o.action == "install" else uninstall()


if __name__ == "__main__":
    sys.exit(main())
