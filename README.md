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
- Trois thèmes : Rose, Clair, Sombre.
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

L'installation ne remplace jamais un agent que tu as déjà.

## Installation

Prérequis : macOS ou Linux, Python 3.8+, Claude Code. Chrome/Chromium est facultatif (sinon le navigateur par défaut est utilisé).

```sh
git clone https://github.com/marissa274/agents-hub
cd agents-hub
./install.sh
```

L'installation ne touche à rien d'existant : elle copie les agents et le skill `hub` dans `~/.claude` et ajoute ses hooks à `settings.json`, qu'elle sauvegarde d'abord (dans `backups/`). Redémarre ensuite Claude Code pour charger les hooks et les nouveaux agents.

## Utilisation

Dans Claude Code, dis « ouvre mon hub » ou tape `/hub`. Tu peux aussi lancer `bin/hub` dans un terminal.

La fenêtre s'ouvre aussi toute seule quand Claude Code lance un sous-agent.

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
