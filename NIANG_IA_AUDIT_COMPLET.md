# NIANG_IA_AUDIT_COMPLET

Date: 2026-11-03

## A. Architecture analysee

NIANG IA est une application Windows Tkinter/Python 3.12 avec:

- `main.py`: point d'entree, audio, Gemini Live, dispatch d'outils et interface.
- `ui.py`: fenetre, historique, mission panel, saisie et themes.
- `safety.py`: risques, confirmations, sanitisation et jetons sensibles.
- `api_keys.py`: chargement et rotation des clefs Gemini.
- `agent/`: planificateur, executeur, file de missions et persistence.
- `actions/`: navigation Playwright, proxy navigateur, diagnostics et actions Windows.
- Suite `unittest` et `pytest`.

L'environnement actif utilise `.venv` et Python 3.12.10 64 bits. `pip check` ne signale aucune dependance cassée.

## B. Fonctionnalites verifiees

| Fonctionnalite | Statut | Preuve |
|---|---|---|
| Demarrage Python | PASS | Application lancee avec `.venv`, fenetre detectee |
| Compilation projet | PASS | `compileall` et py_compile sans erreur Python |
| Tests unitaires | PASS | pytest 380 passes, unittest 353 passes |
| Fenetre Tkinter | PASS | Fenetre `NIANG IA` detectee et processus repondant |
| Agent autonome isole | PASS/PARTIAL | Missions, limites, annulation, reprise et retries testes par mocks |
| Gemini Live | BLOCKED | Aucune cle de test valide autorisee pour un appel reel |
| Playwright Chromium | PASS | Navigation locale HTTP 200 |
| Playwright WebKit | PASS | Navigation locale HTTP 200 |
| Google Chrome systeme | PASS | Navigation locale HTTP 200 |
| Microsoft Edge systeme | PASS | Navigation locale HTTP 200 |
| Playwright Firefox | FAIL | Installe mais impossible de terminer le lancement a 30 secondes |
| Proxy SSRF navigateur | PASS | Tests internes de resolution locale et route bloquee |
| Diagnostics Windows | PASS | Detection environnementale sans modification du systeme |
| Confirmation sensible | PASS apres correction | Arguments exacts et TTL verifies |
| Audio | PARTIAL | Périphérique Realtek detecte et test de sortie valide precedemment |

## C. Fonctionnalites operationnelles

- Demarrage et affichage de l'application.
- Moteur Python 3.12 et dependances.
- Execution des suites de tests.
- Agent avec limites et annulation dans un environnement isole.
- Navigation locale Chromium/WebKit/Chrome/Edge.
- Proxy de politique et restrictions de navigateur.
- Diagnostics Windows en lecture seule.
- Persistence de missions.

## D. Fonctionnalites partiellement operationnelles

- Audio: pilote Realtek valide, mais dependance aux appareils Windows disponibles.
- UI: interface visible, mais plusieurs instances ou fenetres portant un titre similaire ont ete observees.
- Gemini: chargement des clefs et rotation testes, appel Live reel non teste sans cle de test.
- Agent: comportement teste principalement par mocks; aucune mission PC réelle non destructive pendant cette passe finale.

## E. Fonctionnalites non operationnelles

- Appel Gemini reel: non verifie et donc BLOCKED, sans cle de test valide.
- Firefox Playwright: lancement confirme instable/echoue dans cette machine.
- Vue et clic visuels d'ecran: effectivement desactives par la logique de l'application.

## F. Bugs detectes

### Bug corrige: confirmation sensitive contestable

- Fichier: `safety.py`
- Fonction: `_fingerprint`, `issue_confirmation_token`, `redeem_confirmation_token`
- Reproduction: un token emis pour un jeu d'arguments pouvait etre accepte par des arguments differents lorsque le fingerprint utilisait des champs expurges/sanitises.
- Effet: actions sensibles potentiellement rejouees avec un argument different.
- Correction: fingerprint exact en JSON canonique, hors champs `confirm`/`confirm_token`.
- TTL: expiration de 600 secondes imposee avec `time.monotonic()`.
- Sauvegarde: `safety.py.audit_backup_20261103_005844.py`.

Autres observations:

- Firefox Playwright ne termine pas son lancement.
- Plusieurs fenetres Tk portant des titres similaires ont ete detectees.
- Les fenetres `screen_find`/`screen_click` sont visuellement desactivees.

## G. Vulnerabilites detectees

Vulnerabilite du jeton de confirmation: corrigée.

Points de risque restants:

- Exposition potentielle d'une cle dans une configuration locale si mal configuree ou sauvegarde.
- Fichiers locaux de configuration API sans protection visible uniforme.
- Génération de code autonome presente dans l'executant, meme si elle n'est pas un chemin actif confirmé dans le plan.
- Journalisation a verifier pour l'absence de valeurs privees sur toutes les branches.

## H. Problemes de performance

- Le processus NIANG IA mesure environ 4.33 Mo WorkingSet lors du controle live, avec CPU quasi nul.
- Aucun test de fuite mémoire prolongée confirmé.
- Temps de startup UI complet et délai Gemini réel non mesurés sans cle/live.
- Le Firefox Playwright atteint un timeout de lancement.

## I. Corrections effectuees

- Sauvegarde de `safety.py`.
- Ajout du binding exact du jeton aux arguments.
- Ajout de l'expiration des jetons.
- Conservation du caractère single-use.
- Ajout d'un test de regression pour arguments differents.

## J. Tests executes

- Version Python, architecture 64 bits et pip check.
- Compilation complète hors environnements, caches, Node et dist.
- pytest complet.
- unittest complet.
- 107 tests cibles precedemment executes, dont agent, Windows, navigateur, fichiers et securite.
- Playwright Chromium, WebKit, Chrome et Edge.
- Playwright Firefox avec timeout.
- Reproduction directe du mismatch de confirmation.
- Verification du TTL simule.
- Demarrage UI real et detection des fenêtres.

## K. Tests reussis

- pytest: 380 passes, 7 ignores, 65 sous-tests passes.
- unittest: 353 passes, 7 ignores.
- 38 tests safety dans la suite cible.
- Chromium PASS.
- WebKit PASS.
- Chrome PASS.
- Edge PASS.
- Mismatch argument bloque apres correction.
- Jeton expire bloque apres correction.
- Application visible et processus repondant.

## L. Tests echoues

- Firefox Playwright: lancement timeout.
- Aucun appel Gemini Live reussi ou échoué: non execute.

## M. Tests non executes et raisons

- Actions PC réelles: exclues par la mission de sécurité.
- Reparations Windows réelles: exclues explicitement.
- Clé API réelle: aucune cle de test autorisee.
- Firefox navigation fonctionnelle: impossible faute de lancement stable.
- Leaks mémoire prolonges: instrumentations répétées nécessaires.
- Sites tiers: non autorisés sans consentement.

## N. Risques restants

- Firefox Playwright instable.
- Plusieurs fenetres UI peuvent creer une ambiguite de controle.
- Configuration Gemini locale doit rester protegee.
- Confirmation sensitive doit continuer a etre testee sur tous les outils HIGH.
- Le comportement sans cle Gemini doit rester un bloqueage explicite, pas une simulation.
- Certains ecrans de l'application peuvent ne pas indiquer une action non prise en charge.

## O. Recommandations prioritaires

1. Executer les tests Firefox en mode normal et reinstaller le navigateur Playwright si nécessaire.
2. Ajouter une verification visuelle UI qui refuse les fenetres dupliquees.
3. Ajouter des tests de TTL en mode horloge controlee dans la suite permanente.
4. Tester Gemini seulement avec une cle de test et enregistrer les résultats sans secret ni contenu privé.
5. Maintenir les tests de fingerprint sur tous les outils HIGH-risk.
6. Verifier periodiquement les permissions des fichiers de cle et des exports.
7. Effectuer un test mémoire prolonge sans missions tierces ni donnees privées.

## P. Evaluation finale de preparation a la production

| Domaine | Note /100 | Justification |
|---|---:|---|
| Architecture | 82 | Structure modulaire, tests importants, architecture coherent |
| Intelligence artificielle | 35 | Rotation de clefs presente, aucun appel Live réel testé |
| Agent autonome | 72 | Limites, annulation, replans et retries verifies par tests isolés |
| Navigation Web | 78 | Chromium/WebKit/Chrome/Edge PASS; Firefox bloque |
| Securite | 68 | Défaut token corrigé; clefs et protections locales restent a verifier |
| Windows | 72 | Diagnostics reels pass; modifications réelles correctement exclues |
| Interface | 74 | Fenêtre detectée et répondante; ambiguite multi-fenêtres |
| Performance | 60 | Peu de mesures vérifiables; pas de test mémoire long |
| Fiabilité | 73 | Tests complets, erreur de Firefox identifiee |
| Qualité des tests | 95 | 380 tests pytest et 353 unittest; reproduction isolee utile |

Note globale prudente: **70/100**.

Verdict: NIANG IA est utilisable en mode local controle pour les fonctionnalités vérifiées, mais n'est pas déclarée prête pour un déploiement autonome en production sans validation Gemini Live avec cle de test, stabilisation Firefox et validation prolongée mémoire/UI.

## Addendum des corrections du 2026-11-03

- Sauvegarde supplémentaire de `main.py` avant l'ajout du mutex: `main.py.audit_backup_20261103_010410.py`.
- Sauvegarde supplémentaire de `tests/test_safety.py`: `tests/test_safety.py.audit_backup_20261103_010410.py`.
- Ajout d'un mutex Windows nommé empêchant une seconde instance NIANG IA locale de créer une fenêtre dupliquée.
- Vérification du mutex: premier acquisition acceptée, seconde acquisition rejetée dans le même processus.
- Ajout permanent du test unittest de TTL des jetons de confirmation.
- Réinstallation Playwright Firefox effectuée.
- Firefox reste FAIL: le processus se lance puis se termine avec `exitCode=255`; cette machine bloque donc le lancement, pas seulement la navigation.
- Régressions après corrections: pytest 419 passes, 7 ignores, 86 sous-tests passes; unittest 354 passes, 7 ignores.
