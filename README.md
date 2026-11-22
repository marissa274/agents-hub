# Agents Hub

*A live dashboard that shows what your Claude Code and Codex agents are doing. Local-only, no dependencies, MIT.*

Un tableau de bord qui montre en direct ce que font tes agents Claude Code et Codex.

## Pourquoi

Je n'arrivais pas à voir mes agents travailler, alors j'ai créé Agents Hub : un tableau de bord qui montre en direct ce que font mes agents Claude Code et Codex. C'est mon premier projet open source : je le partage pour que tout le monde puisse l'utiliser, l'adapter à ses besoins et régler les problèmes qu'il rencontre.

![Agents Hub](docs/screenshot.png)

## Ce qu'il fait

- Affiche tes agents en direct : qui travaille, avec quel outil, sur quoi.
- Fonctionne avec Claude Code et Codex.
- Une fenêtre par tâche (Claude Code ou Codex), jamais deux pour la même tâche ; `bin/hub` sans argument ouvre une fenêtre qui suit la tâche en cours.
- Le titre de la tâche (« Projet · Titre ») s'affiche en haut de la page, repris de Claude Code ou, à défaut, du premier prompt.
- Trois thèmes : Sombre (par défaut), Rose (rose sur fond noir) et Clair.
- Un scoreboard pour le reviewer : bugs trouvés, confirmés ou rejetés, sur 3 cycles de revue.

## L'équipe de départ

Agents Hub est d'abord un hub qui montre **tous** tes agents : ceux du projet (`.claude/agents/`, avec un badge indiquant le nom du projet) et ceux de ton ordinateur (`~/.claude/agents/`).

Il est aussi livré avec 6 agents de base, optionnels, qui servent quand tu n'as pas tes propres agents :

- `product-manager` : transforme un besoin en user stories.
- `architecte` : prépare le plan technique avant le code.
- `ux-designer` : parcours, maquettes et accessibilité.
- `developpeur` : écrit le code et les correctifs, avec tests.
- `redacteur-doc` : documentation et notes de version.
- `reviewer` : chasse les bugs et marque des points.

Ils sont installés pour Claude Code (`~/.claude/agents/*.md`) et pour Codex (`~/.codex/agents/*.toml`). L'installation ne remplace jamais un agent que tu as déjà.

## Ajouter tes propres agents

Un agent, c'est un simple fichier texte. Agents Hub l'affiche automatiquement :

- **Pour un seul projet** : crée `.claude/agents/mon-agent.md` à la racine du projet (Codex : `.codex/agents/mon-agent.toml`).
- **Pour tous tes projets** : crée `~/.claude/agents/mon-agent.md` (Codex : `~/.codex/agents/mon-agent.toml`).

Exemple minimal pour Claude Code :

```markdown
---
name: testeur
description: Écrit et lance les tests du projet.
---
Tu écris des tests clairs pour chaque fonctionnalité, puis tu les lances.
```

Redémarre Claude Code pour qu'il voie le nouvel agent. Dans le hub, les agents d'un projet portent le nom du projet en badge.

## Installation

Prérequis : macOS ou Linux, Python 3.8+, Claude Code et/ou Codex. Chrome/Chromium est facultatif (sinon le navigateur par défaut est utilisé).

```sh
git clone https://github.com/marissa274/agents-hub
cd agents-hub
./install.sh
```

L'installation ne touche à rien d'existant : elle copie les agents et le skill `hub` dans `~/.claude` et ajoute ses hooks à `settings.json`, qu'elle sauvegarde d'abord (dans `backups/`). Redémarre ensuite Claude Code pour charger les hooks et les nouveaux agents.

**Codex** est configuré automatiquement s'il est détecté (dossier `~/.codex` ou commande `codex`) : l'installation ajoute `~/.codex/hooks.json` (ou le complète, en le sauvegardant d'abord), les agents `~/.codex/agents/*.toml` et le skill `~/.codex/skills/hub`.

- **Dans Codex, tape `/hooks` et approuve les hooks d'Agents Hub.** Codex n'exécute un hook qu'après ton accord ; l'approbation est à refaire si tu déplaces le dépôt ou si la commande change.
- `./install.sh --no-codex` ignore Codex ; la variable `CODEX_HOME` change le dossier de Codex (`CLAUDE_CONFIG_DIR` fait de même pour Claude Code).
- Si tu as déjà un skill `~/.codex/skills/hub` à toi, il est conservé : renomme-le (ou supprime-le), puis relance l'installation pour installer celui d'Agents Hub.
- Le sandbox de Codex peut empêcher `score.py` et `bin/hub` d'écrire hors du projet : autorise ces commandes quand Codex le demande (ou ajoute les `logs/` d'Agents Hub dans `~/.codex/config.toml`) :

  ```toml
  [sandbox_workspace_write]
  writable_roots = ["<chemin du dépôt>/logs"]
  ```
- Après une mise à jour d'Agents Hub, redémarre le serveur (ferme les fenêtres puis relance `bin/hub`).

### Claude Code et Codex : ce qui est pareil

| | Claude Code | Codex |
|---|---|---|
| Fenêtre automatique | au lancement d'un sous-agent | au lancement d'un sous-agent (`spawn_agent`) |
| Titre de la tâche | titre de Claude Code | nom du fil Codex (`session_index.jsonl`), sinon premier prompt |
| Bugs du reviewer par tâche | oui | oui (`CODEX_THREAD_ID`) |
| Agents de base | `~/.claude/agents/*.md` | `~/.codex/agents/*.toml` |
| Skill `hub` | `~/.claude/skills/hub` | `~/.codex/skills/hub` |
| Alertes (question, permission, fin) | oui | oui (hook `PermissionRequest` inclus) |

Sans hooks approuvés, Codex reste suivi en lecture des sessions (`~/.codex/sessions`), avec un peu moins de détails.

## Utilisation

Dans Claude Code, dis « ouvre mon hub » ou tape `/hub`. Tu peux aussi lancer `bin/hub` dans un terminal.

Dans Codex, demande « ouvre mon hub » (le skill `hub` s'en charge) ou lance `bin/hub`. Si les hooks ne semblent pas actifs, tape `/hooks` et approuve ceux d'Agents Hub.

La fenêtre s'ouvre aussi toute seule quand Claude Code lance un sous-agent, et dans Codex au premier `spawn_agent` d'une tâche.

## Ajouter un autre outil (Cursor, Gemini…)

Copie `bin/adapters/codex.py`, adapte le nom, le dossier des sessions et la lecture des lignes, puis ajoute le module à `bin/adapters/__init__.py` (et une entrée dans `ui/index.html`). Les contributions sont bienvenues.

## Vie privée

Tout reste sur ta machine : le serveur n'écoute que sur `127.0.0.1`. Le dossier `logs/` contient tes prompts : il est ignoré par git et ne doit jamais être publié.

## Désinstaller

```sh
./uninstall.sh
```

Retire les hooks, les agents et le skill installés (un fichier que tu as modifié est conservé). Les logs et le dépôt ne sont pas touchés.

## Limites

- Windows n'est pas encore supporté.
- Si tu déplaces le dossier, relance `./install.sh`.

## Licence

MIT, voir [LICENSE](LICENSE).

Créé par [Marissabelle Bindeki](https://www.linkedin.com/in/marissa-belle-bindeki-b32090333/)
