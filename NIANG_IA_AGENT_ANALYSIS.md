# Diagnostic technique — NIANG IA et extraits VS Code/Copilot

Date : 2026-11-03

## 1. Portee et resultat

L'application existante est une application de bureau Windows en Python, avec interface Tkinter, conversation vocale/texte basee sur Gemini Live et un catalogue important d'actions locales. Le depot contient 118 fichiers Python repartis notamment entre `actions/`, `agent/`, `vision/`, `memory/`, `remote/` et `tests/`. `NIANG_IA_A_TESTER/` est une seconde copie de distribution; elle ne doit pas etre modifiee en parallele sans verifier sa relation avec la racine.

L'archive fournit du code TypeScript/TSX de VS Code et Copilot. Elle ne constitue pas un composant directement importable dans NIANG IA : les concepts d'orchestration, de prompt, d'isolation de session et d'execution Playwright sont reutilisables, mais leur integration doit rester en Python et conserver Gemini et l'interface actuels.

## 2. Architecture et fonctions deja presentes

- `main.py` : application, Gemini Live, definitions des outils de conversation, dispatch des appels et lancement des missions.
- `ui.py` : interface existante, conversation et controles de mission. Aucun changement de design n'est necessaire pour le plan propose.
- `agent/planner.py` et `agent/executor.py` : planification Gemini, execution sequentielle, nouvelles tentatives, reprise de plan et limites configurables.
- `agent/task_queue.py`, `agent/mission_store.py` et `agent/settings.py` : file de missions, historique, annulation et limites/delais; la persistance locale utilise DPAPI sous Windows.
- `agent/workspace_tools.py` : operations de fichiers bornees a `NIANG_IA_WORKSPACE_ROOT`, protections de chemins/fichiers sensibles et controles de projet predefinis. Ce n'est pas un terminal de projet general.
- `actions/browser_control.py`, `actions/browser_security.py`, `actions/browser_network_proxy.py` et `actions/playwright_mcp.py` : navigateur Playwright, politique d'URL/reseau, sessions, controles accessibles, captures et annulation.
- `actions/computer_control.py`, `actions/desktop.py`, `actions/screen_processor.py` et `vision/` : controle de fenetres/UI Automation, saisie/clavier/souris et analyse visuelle.
- `safety.py`, `agent/secrets.py` et les tests associes : classification des risques, confirmations, protection de donnees sensibles et journalisation.

### Ecarts architecturaux a traiter

1. La conversation Gemini Live de `main.py` et les missions autonomes de `agent/` sont deux voies distinctes. Elles ne doivent pas devenir deux agents concurrents.
2. Les definitions de schemas/handlers de `main.py`, la liste `ALLOWED_TOOLS` et les instructions de `agent/planner.py`, et le dispatch conditionnel de `agent/executor.py` dupliquent l'inventaire des outils. Le registre unifie demande doit devenir la source commune de metadonnees, schema, execution et autorisation.
3. La plupart des resultats d'action de l'executant sont des chaines de texte, ce qui rend moins fiable la distinction entre succes, erreur, blocage et resultat inconnu.
4. Le rapport final de l'executant peut produire un texte de succes de repli quand la synthese Gemini echoue; il faut garantir qu'un compte rendu ne presente comme verifie que ce qui l'a effectivement ete.
5. Les primitives sont deja segmentees : Playwright pour son navigateur controle, et UI Automation/vision pour l'ordinateur. Une integration devra conserver cette distinction et signaler les limites d'observation/controle de chaque canal.

## 3. Enseignements de l'archive et licences

- `toolCallingLoop.ts` illustre une boucle multi-tours qui conserve l'historique, observe les appels/resultats, gere l'annulation, les limites, les erreurs transitoires et des conditions d'arret/verifications.
- `agentPrompt.tsx` et `defaultAgentInstructions.tsx` montrent une construction de contexte en couches, les outils disponibles, les instructions de securite et la gestion du contexte de conversation. Le modele utile est l'organisation, pas la copie de prompts Copilot.
- `allTools.ts` est un point d'entree d'enregistrement/import d'outils; les schemas et implementations restent dans des modules specialises.
- Le service Browser View/Playwright de l'archive isole les sessions et pages, retourne des resultats avec erreurs, delimite les appels longs, gere dialogues/selection de fichiers et libere les sessions.
- Le fichier `vscode-main/LICENSE.txt` de l'archive est MIT et les fichiers examines portent l'en-tete MIT. Si du code est copie, conserver les avis de copyright et licence; le plan privilegie l'adaptation des principes sans reprise textuelle. La licence de tout paquet npm installe ou redistribue devra etre verifiee independamment.

## 4. Compatibilite et dependances

- Le langage cible reste Python; le code TypeScript/TSX de l'archive ne peut pas etre repris directement dans l'application.
- `requirements.txt` inclut deja Gemini, Playwright Python, MCP, PyAutoGUI, pywinauto, mss, psutil, OpenCV et les bibliotheques de vision necessaires aux fonctions observees.
- `actions/playwright_mcp.py` lance `@playwright/mcp@0.0.84` via `npx` et exige Node.js 18+ ainsi que npm/npx disponibles sur PATH; ce prerequis systeme doit etre explicite dans l'installation et le diagnostic de disponibilite.
- `agent/mission_store.py` depend de `win32crypt` pour DPAPI. `pywin32` n'apparait pas dans le `requirements.txt` examine; il faut verifier que l'installateur l'inclut ou declarer proprement cette dependance avant de compter sur la persistance chiffree dans une installation neuve.
- Les tests existants couvrent deja les missions, l'annulation, les approbations, les secrets, la navigation Playwright et les outils de workspace. Le rapport `NIANG_IA_AUDIT_COMPLET.md` indique des tests anterieurs reussis; ces chiffres n'ont pas ete relances pendant cette analyse.

## 5. Plan d'integration propose

1. **Phases 1–3 — analyse/conception (faites)** : conserver Gemini Live et l'interface; definir une source de verite commune et des resultats structures; reutiliser les services existants plutot que les dupliquer.
2. **Phase 4 — moteur et registre** : faire converger les deux dispatchers vers des definitions d'outils uniques (identifiant, description, schema, executant, risque/autorisation, resultat); conserver limites, delais, annulation, historique et reprise existants; ajouter une verification explicite et des statuts sans faux succes.
3. **Phase 5 — navigateur** : reutiliser Playwright et sa politique d'URL, garder les sessions isolees, preferer snapshots accessibles et references recentes; confirmer avant soumission, telechargement ou dialogue engageant.
4. **Phase 6 — fichiers/commandes** : conserver le confinement workspace et les controles predefinis; n'ajouter des commandes de terminal qu'avec racine autorisee, politique explicite, limites de temps et confirmations adaptees.
5. **Phase 7 — controle visuel** : reutiliser UI Automation/vision; privilegier les controles accessibles, distinguer la fenetre navigateur pilotee des autres fenetres, et rapporter une action comme executee uniquement apres observation d'un resultat.
6. **Phase 8 — securite** : centraliser les permissions dans le registre, appliquer les confirmations avant actions destructrices/externes, proteger secrets et donnees non fiables, permettre l'arret et journaliser les resultats sans secrets.
7. **Phases 9–10 — validation** : tests unitaires des schemas et statuts, tests avec navigateur local et workspace temporaire, tests d'annulation/delais/permissions, puis suite cible de non-regression. Aucun achat, envoi reel, reparation Windows ou action externe ne sera utilise comme test.

Les modifications seront additives et ciblees; les fonctionnalites, parametres, langues et presentation existants seront preserves.

## 6. Etat initial du worktree (avant autorisation)

Au moment du diagnostic initial, le worktree contenait deja de nombreux changements modifies ou non suivis, dans les fichiers qui couvrent directement les phases 4–8 (`main.py`, `agent/`, `actions/`, `safety.py`, `ui.py`, tests et rapports). Leur provenance ne pouvait pas etre determinee a partir du depot. Ils ont ete conserves; l'utilisateur a ensuite autorise la poursuite sur cette base.

## 7. Phase 2 — implementation et validation

### Realisations

- `agent/terminal_agent.py` ajoute l'execution PowerShell/Bash (si le shell est installe), les sorties stdout/stderr bornees et expurgees, les commandes synchrones avec delai, ainsi que les processus supervises (identifiant, statut, journaux, arret et annulation). Les commandes d'execution requierent une confirmation par la politique de securite et le repertoire courant est limite a `NIANG_IA_WORKSPACE_ROOT`.
- `agent/project_execution.py` inspecte les manifestes sans executer le code, identifie les scripts/gestionnaires/dependances et distingue une application Tkinter d'un serveur Web. Il evite le double lancement, refuse les ports attendus deja occupes par un processus non identifie, verifie la sante HTTP et limite l'exception reseau du navigateur a un apercu loopback associe a un processus NIANG actif.
- `main.py`, `agent/tool_registry.py`, `agent/planner.py`, `agent/executor.py` et `safety.py` relient ces commandes au registre existant, aux approbations, aux annulations et aux resultats structures; aucune seconde boucle IA n'est creee.
- L'agent Playwright existant est reutilise pour la navigation, les controles accessibles, les formulaires, les attentes, les dialogues, les captures et la verification des actions. Les tests navigateur couvrent egalement les redirections/reseaux locaux et les protections de soumission.
- Le controle bureau existant conserve UI Automation, souris/clavier et arret d'urgence. L'analyse et le clic visuels generiques a partir d'une capture envoyee au modele restent desactives; aucune capture privee n'est transmise implicitement.
- `tests/test_terminal_agent.py` et `tests/test_project_execution.py` couvrent les nouvelles fonctions, dont l'arret, l'annulation, les erreurs de commandes, la detection BOM UTF-8, les conflits de ports et un serveur Node local reel.

### Verification et limites constatees

- Detection reelle du depot : Python/Tkinter, application de bureau, entree `main.py`; `PyMuPDF` est absent de l'environnement Python courant. Le detecteur ne lance pas l'application et ne telecharge rien.
- Le test d'integration a lance un serveur Node local temporaire, verifie sa reponse HTTP, confirme qu'un second appel ne demarre pas un doublon, puis l'a arrete.
- Apres autorisation explicite, `project_execution` a lance le processus NIANG IA. Il etait encore actif au controle, mais UI Automation n'a trouve aucun titre de fenetre accessible; stdout/stderr etaient vides. Le processus a ete arrete par le gestionnaire, qui a rapporte le code de sortie `1`. L'ouverture visuelle de l'interface et une session Gemini fonctionnelle ne sont donc pas confirmees.
- Le test Playwright reel sur page locale en memoire reussit; il verifie navigation/interaction de page, mais ne constitue pas un parcours du bureau NIANG IA. Aucun URL navigateur n'a ete invente pour l'application Tkinter.
- Suite complete : **456 tests reussis, 7 ignores, 91 sous-tests reussis**. `compileall` et `git diff --check` reussissent.
- PowerShell a ete teste dans cet environnement; Bash n'y est pas installe et ne peut donc pas y etre execute. L'execution PowerShell utilise les permissions du compte Windows : la racine de travail et les approbations ne constituent pas une sandbox OS.
- Le scenario de bout en bout reste partiellement valide : l'inspection, le serveur Node local et le test Playwright local sont executes, mais l'interface NIANG IA n'a pas ete confirmee par UI Automation. L'application est un bureau, pas un site Web; le test Node ne remplace pas un parcours de l'application elle-meme.

## 8. Phase 3 — diagnostic Tkinter et controle du bureau

### Diagnostic et corrections

- Le processus retourne par le lanceur Python du venv n'est pas toujours celui qui cree le HWND Tkinter : un `python.exe` enfant peut posseder la fenetre. L'ancien balayage Win32 inspectait les metadonnees de fenetres sans rapport avant le filtrage PID et pouvait depasser le delai de verification. `list_windows` filtre maintenant le PID avant les requetes couteuses, met en cache les metadonnees par processus et suit les descendants.
- `ProjectExecutionManager` privilegie une fenetre principale visible plutot qu'un dialogue Tk `Toplevel` enumere en premier. La recherche d'un HWND connu lit directement cette fenetre au lieu de rescanner tout le bureau.
- Les dimensions Win32 et MSS etaient incoherentes sous mise a l'echelle Windows (coordonnees logiques contre pixels physiques). L'enumeration utilise maintenant un contexte DPI temporaire, propre au thread, et le restaure ensuite. L'application et son interface ne changent pas globalement de DPI.
- L'observation/capture d'une fenetre visible l'active et verifie qu'elle est au premier plan; les actions souris/clavier echouent explicitement si le focus n'est pas confirme. Les captures restent locales, bornees a la fenetre choisie et ne sont jamais envoyees a Gemini.
- Pour Tkinter, l'UI Automation/Win32 reste prioritaire pour les controles accessibles; le repli visuel utilise OCR Tesseract local, coordonnees valides dans la fenetre et `SendInput` Unicode pour le texte. La verification OCR attend brievement les mises a jour visibles et normalise les espaces sans transformer un resultat absent en succes.
- La fermeture d'une fenetre peut faire sortir le lanceur Python pendant que le superviseur enumere ses descendants. `TerminalAgent` traite maintenant le cas de course `psutil.NoSuchProcess`; un test simule la sortie entre le controle et l'enumeration.

### Fichiers de la phase 3

- Modifies : `agent/windows_desktop.py`, `agent/project_execution.py`, `agent/terminal_agent.py`, `main.py`, `tests/test_windows_desktop.py`, `tests/test_terminal_agent.py`.
- Ajoutes : `tests/fixtures/desktop_app.py` et `tests/test_windows_desktop.py` (ce dernier etait deja present dans le worktree au debut de la reprise).
- `main.py` precise que le moniteur local echantillonne les changements a un intervalle cible de 30 ms, que les descriptions/recherches visuelles de l'outil bureau sont desactivees, et que `screen_process angle='local_vision'` garde l'analyse visuelle locale.

### Verification executee

- Les six modes Tkinter de fixture ont ete lances reellement : bouton (clic + compteur), formulaire (saisie Unicode + valeur sauvegardee), plusieurs fenetres (proprietaire + fermetures), dialogue (identification + fermeture independante), fenetre reduite (detection + restauration) et erreur intentionnelle (traceback stderr, stdout et code de sortie non nul). Chaque processus de fixture a ete ferme ou s'est termine; aucune fenetre de fixture ne restait apres les tests.
- Le lancement reel de NIANG IA via `ProjectExecutionManager` a retourne `started`, `verified=true`, titre `NIANG IA`, et une fenetre appartenant au processus Python enfant. La fermeture Win32 de la fenetre a ete confirmee. Le statut immediat du superviseur etait encore `running` pendant la sortie; une verification suivante n'a trouve aucun des PID de cet essai. Aucun contenu de fenetre n'a ete lu ni transmis.
- Validation finale : `python -m unittest discover -s tests` — **406 tests reussis, 7 ignores**; tests bureau/terminal cibles — **15 reussis**; `compileall` et `git diff --check` reussissent.

### Limites restantes

- Le role `main`/`secondary` repose sur la relation native `GW_OWNER`; un `Toplevel` Tk sans fenetre proprietaire peut etre indistinguable d'une fenetre principale avec les seules API Win32. La fixture de dialogue definit explicitement son proprietaire pour tester ce cas.
- Le controle exige une session Windows interactive et un HWND visible. Une politique de premier plan Windows qui refuse le focus est signalee; l'agent ne clique pas en aveugle.
- L'OCR est local et depend de Tesseract; il est moins fiable que UI Automation et reste sensible a la langue, au contraste et au scaling. `winapp ui` n'est pas installe.
- Windows Sandbox n'a pas ete active/verifie. L'execution demeure dans la session et avec les droits du compte courant; la racine de workspace n'est pas une isolation OS. Les actions systeme/destructrices et externes restent protegees par les autorisations existantes.
- Le test reel de NIANG IA confirme le demarrage et la fenetre, mais n'a pas valide une session Gemini Live ni un parcours de conversation. Les tests de saisie et de verification fonctionnelle utilisent les applications Tkinter de fixture; aucun contenu personnel n'a ete analyse.
