---
name: hub
description: Fait travailler une équipe d'agents (ceux du projet, ceux de la personne, ou les agents de base) et pilote les cycles du reviewer. À utiliser quand on tape /hub (ou $hub dans Codex), qu'on dit « utilise mes agents / mes sous-agents / les agents de mon projet / mon équipe », ou qu'on demande les cycles du reviewer. La fenêtre du tableau de bord ne s'ouvre que sur /hub ou sur demande explicite.
---
1. Fenêtre : n'exécute `sh "__AGENTS_HUB__/bin/hub"` QUE si la personne a tapé `/hub` (ou `$hub` dans Codex) ou demande explicitement d'ouvrir le hub. Sinon (par exemple « utilise mes agents » ou un cycle de reviewer), n'ouvre aucune fenêtre et fais seulement le travail d'équipe : l'activité est enregistrée de toute façon et sera là si elle ouvre le hub plus tard. La fenêtre n'est jamais ouverte en double.

2. Sans tâche : si la fenêtre a été demandée, ouvre-la et dis que c'est fait ; sinon, demande ce qu'elle veut faire.

3. Avec une tâche, tu es l'orchestrateur. Choisis l'équipe selon ce que la personne demande :
   - Fais l'inventaire avant de déléguer (à la racine du dépôt : `git rev-parse --show-toplevel`) :
     - dans Claude Code : agents du projet `.claude/agents/*.md`, agents personnels `~/.claude/agents/*.md` ; lis le `name` et la `description` de chacun (frontmatter) ;
     - dans Codex : agents du projet `.codex/agents/*.toml`, agents personnels `agents/*.toml` dans le dossier de configuration de Codex (`$CODEX_HOME`, sinon `~/.codex`) ; lis les clés `name` et `description` de chacun.
   - « les agents de mon projet » → n'utilise QUE les agents du projet. S'il n'y en a pas, dis-le et propose les autres.
   - « mes agents / mes sous-agents » → agents du projet puis agents personnels, tous confondus.
   - Rien de précisé → agents du projet et personnels d'abord. Les 6 agents de base (product-manager, architecte, ux-designer, developpeur, redacteur-doc, reviewer) servent quand aucun agent de la personne ne convient à la sous-tâche.
   - Un agent qu'elle nomme explicitement passe toujours en premier.
   - Délègue avec l'outil Agent de Claude Code (`subagent_type` = le `name` de l'agent), ou avec `spawn_agent` dans Codex (`agent_type` = le `name` de l'agent). Si un nom n'est pas proposé par l'outil, c'est que l'application n'a pas encore été redémarrée depuis sa création : dis-le et prends l'agent le plus proche.
   - Annonce l'équipe choisie en une ligne (qui fait quoi) avant de lancer.
   - Dans Codex, si le sandbox bloque `score.py` ou `bin/hub` (écriture hors du projet), demande l'élévation des droits pour cette commande.
   - Tout s'affiche en direct dans la fenêtre (les agents du projet ont un badge avec le nom du projet).

4. Revue de code = 3 cycles de reviewer (le reviewer du projet s'il y en a un, sinon `reviewer`) :
   - Avant le cycle 1 : `python3 "__AGENTS_HUB__/bin/score.py" reset`.
   - Cycle 1 logique et sécurité ; cycle 2 vérification des correctifs et cas limites ; cycle 3 conventions, lisibilité, accessibilité.
   - Si le reviewer utilisé ne note pas lui-même ses bugs, enregistre chaque bug de son rapport :
     `python3 "__AGENTS_HUB__/bin/score.py" add --cycle N --severity critique|majeur|mineur|style --file F --line L --title ".." --scenario ".."`
   - Après chaque cycle : vérifie chaque bug, puis `score.py confirm <id>` ou `score.py reject <id> --reason ".."` ; fais corriger les bugs confirmés (développeur du projet ou `developpeur`), puis `score.py fixed <id>` ; lance le cycle suivant.
