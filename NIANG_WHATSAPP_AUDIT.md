# NIANG WHATSAPP AUDIT REPORT

## Project Overview
**NIANG IA** is a Windows-based AI voice assistant (project owner: Musayev Doniyor) that can hear, see, and interact with the computer. The project already has pywinauto, Windows UI Automation, and various action modules for controlling the desktop, managing files, and integrating with external services (Telegram, Gmail, etc.).

This audit examines the feasibility of adding WhatsApp Desktop message surveillance capabilities.

---

## Phase 1 — Architecture Audit

### 1.1 Existing System Architecture

| Component | Status | Notes |
|-----------|--------|-------|
| **Voice Engine** | ✅ Operational | `voice_activation.py` — wake word detection ("Hey Niang", "Niang IA") using openWakeWord + Vosk (French model). Background mic loop with refractory cooldown. |
| **Text-to-Speech** | ✅ Operational | Gemini API with 30+ voices configured. `voice_activation.py` reports available voices. |
| **Speech-to-Text** | ✅ Operational | Vosk offline STT (`vosk-model-small-fr-0.22` for French). Also supports google-genai. |
| **Memory System** | ✅ Operational | `memory_manager.py` — long-term memory (`long_term.json`), conversation archive (`conversations.sqlite3`), category-based storage, backup/cleanup logic. |
| **Notifications** | ✅ Operational | `actions/notifications.py` — Windows toast notifications via `winotify`. |
| **pywinauto / UI Automation** | ✅ Installed and In Use | `pywinauto` imported in `actions/computer_control.py` (line 251) and `agent/windows_desktop.py`. Used for window discovery, control interaction. |
| **Existing WhatsApp Integration** | ⚠️ Limited | `actions/whatsapp_call.py` — handles *voice calls* only (manual, privacy-isolated, requires virtual audio cables). Does **not** monitor messages. |
| **API Configuration** | ⚠️ Required | Gemini API key in `config/api_keys.json`. No WhatsApp API integration (by design — privacy-first). |
| **Testing Framework** | ✅ Comprehensive | `tests/` directory with 100+ tests. `test_whatsapp_call.py` as reference pattern. |

### 1.2 System Dependencies (from requirements.txt)

```text
pywinauto              # Windows UI Automation
psutil                 # Process identification
pyautogui              # Coordinate input (fallback)
pygetwindow            # Window management
mss                    # Screen capture
winotify               # Toast notifications
pystray                # System tray
keyboard               # Hotkey handling
vosk                   # Offline STT
sounddevice            # Audio I/O
google-genai           # Gemini API
```

### 1.3 Key Files Examined

| File | Purpose |
|------|---------|
| `main.py` | Entry point, tool registry, action dispatching. Loads Gemini, UI, memory, and all action modules. |
| `ui.py` | Tkinter-based UI with custom themes (cyber/ocean/aurora/sunset). Contains status panels, agent report panel, diagnostics. |
| `voice_activation.py` | Wake word engine, background mic loop, refractory period, settings persistence. |
| `memory_manager.py` | Persistent memory, conversation archive, semantic search. |
| `actions/whatsapp_call.py` | WhatsApp *call* infrastructure (manual, privacy-isolated, virtual audio cables). |
| `actions/computer_control.py` | pywinauto-based desktop control, UI Automation. |
| `agent/windows_desktop.py` | Windows Desktop Agent — window discovery, control enumeration, guarded input. |
| `actions/notifications.py` | Windows toast notifications. |
| `safety.py` | Risk classification (LOW/MEDIUM/HIGH), confirmation gate for all actions. |

### 1.4 Strengths & Limitations

**Strengths:**
- pywinauto already installed and used for Windows UI Automation
- Existing voice engine (wake word + TTS/STT) can be extended
- Memory system can track "already read" state per message
- Notification system available for alerts
- Safety/confirmation gate already in place
- Tests exist for whatsapp_call as a pattern reference

**Limitations:**
- WhatsApp Desktop is a UWP/Electron app — UI Automation compatibility varies
- No native WhatsApp Desktop API (must use UI Automation)
- Message text exposure depends on Windows UI Automation tree accessibility
- Must avoid permanent message storage (privacy requirement)
- Must not bypass WhatsApp encryption or extract cookies/tokens
- Coordination with existing voice engine must not block NIANG IA operations

### 1.5 Audit Conclusion — Phase 1

The project has a solid foundation for WhatsApp Desktop message surveillance. The key enablers are:

1. **pywinauto** already installed and functional for Windows UI Automation
2. **Existing voice engine** can be extended for command detection
3. **Memory system** can track read state and anti-doubling
4. **Notifications** can alert user of new messages
5. **Safety framework** already handles confirmation gates

The implementation will add a new `whatsapp_monitor.py` module (in `actions/`) that uses Windows UI Automation to detect WhatsApp Desktop windows, read accessible text, and detect changes — without relying on coordinate-based mouse input, and respecting all privacy constraints.

*End of Phase 1*
---

## Phase 3 — Vocal Intelligence

### 3.1 Reuse Existing Voice Engine

The existing `voice_activation.py` engine will be extended, not replaced. Current capabilities:

- Wake word detection: "Hey Niang", "Niang IA"
- Two engines: openWakeWord (custom) + Vosk (French keyword spotting)
- Background mic loop with auto-restart and refractory cooldown
- Settings persistence in `config/app_settings.json`

### 3.2 Voice Commands for WhatsApp

| Command | Expected NIANG IA Response |
|---------|---------------------------|
| "Niang, lis mes nouveaux messages WhatsApp." | Read new messages aloud, announce senders |
| "Qui m'a écrit ?" | Identify last sender(s) |
| "Lis le dernier message." | Read most recent message |
| "Résume mes messages." | Gemini-assisted summary of recent conversations |
| "Lis les messages de [contact]." | Read messages from specific contact |
| "Arrête la lecture." | Stop current audio playback |
| "Active le mode silencieux." | Suppress TTS output, only log to UI |
| "Désactive la surveillance WhatsApp." | Stop monitoring thread |

### 3.3 Natural Voice Constraints

- NIANG IA must **not** read the same message twice (anti-doubling via memory)
- Must speak **naturally** in French (existing Vosk model) and optionally Wolof if TTS supports it
- Must respect user's "mode silencieux" preference
- Must wait for explicit confirmation before any action that changes state

*End of Phase 3*
---

## Phase 4 — Artificial Intelligence Intelligence

### 4.1 Gemini Model Reuse

**No second API configuration needed** — NIANG IA already has Gemini configured via `google-genai`. The existing `google import genai` and `types` imports in `main.py` will be used.

### 4.2 AI Capabilities for WhatsApp

| Capability | Implementation |
|------------|---------------|
| **Resumer les conversations** | Gemini prompt: "Résume les 5 derniers messages WhatsApp de cet échange en français, en mettant en avant les points clés et les actions demandées." |
| **Identifier les messages importants** | Gemini classification: urgency, personal vs professional vs group, keywords (urgence, rendez-vous, famille, etc.) |
| **Détecter les urgences** | Keyword detection + Gemini classification: "urgence", "ASAP", "important", horodatage |
| **Distinguer les messages** | Categorize as: personnel, professionnel, groupe, système (mises à jour) |
| **Proposer des réponses adaptées** | Gemini suggestion: "Voici une réponse adaptée au message de [contact] : [...]" (never auto-send) |
| **Comprendre les demandes vocales** | French (Vosk model) + Wolof if supported by existing TTS |

### 4.3 Gemini Prompt Template (Example)

```
Tu es NIANG IA, un assistant vocal amical et intelligent. L'utilisateur a de nouveaux messages WhatsApp. 
Voici les messages bruts (expéditeur, texte, horodatage) :

[sender1]: [text1] ([time1])
[sender2]: [text2] ([time2])

Tâche :
1. Catégorise chaque message comme : personnel, professionnel, ou groupe.
2. Identifie s'il y a urgence (mot-clé : urgence, ASAP, important, besoin immédiat).
3. Résume en 2 phrases maximum les points essentiels.
4. Propose une réponse naturelle en français pour chaque message important.
5. Si urgent, préfixe par "🚨 URGENT :".

Réponds au format JSON avec les champs : categories, urgences, resumé, propositions_reponse.

*End of Phase 4*
---

## Phase 5 — Intelligent Responses

### 5.1 Example Workflow

```
User: "Niang, responds to this message."
NIANG IA:
1. ✅ Reads the received message (via WhatsApp monitor)
2. ✅ Prepares a response using Gemini (context-aware, in French/Wolof)
3. ✅ Reads the proposed response aloud: "Voici ma proposition : 'Bonjour, je reviens vers toi dans l'heure.' Veux-tu que j'envoie cette réponse ?"
4. ⏳ Waits for explicit confirmation: "Oui" or "Non"
5. ✅ Sends only if mechanism is reliable and authorized
6. ❌ Otherwise, prepares text for manual send
```

### 5.2 Confirmation Gate

All message-sending actions must pass through the **safety.py confirmation gate** (RISK.HIGH for sending messages). The gate asks:

> "Veux-tu que j'envoie cette réponse ?"

No auto-send. Never bypass user confirmation.

### 5.3 Response Flowchart

```
User voice command
    ↓
NIANG IA detects WhatsApp messages (if monitoring active)
    ↓
NIANG IA asks: "Quel message vouloir répondre ?" (or lists last senders)
    ↓
User specifies contact/message
    ↓
NIANG IA reads message → Gemini prepares response → NIANG IA reads proposal
    ↓
User confirms "Oui" / "Non"
    ↓
If Oui → safety gate checks RISK → if confirmed, execute send_message action
    ↓
If Non → offer to edit the response or discard
```

*End of Phase 5*
---

## Phase 6 — Confidentiality

| Requirement | Implementation |
|-------------|---------------|
| **Surveillance désactivée par défaut** | Monitoring thread starts OFF. User must explicitly enable. |
| **Activation explicite par l'utilisateur** | Voice command "Niang, active la surveillance WhatsApp" or UI toggle. |
| **Aucun enregistrement permanent du contenu des messages par défaut** | Messages are read in-memory only. No persistent storage of message content. |
| **Ne jamais exposer les messages dans les journaux techniques** | Sanitize all logs — `[private]` redaction in `safety.py`. |
| **Possibilité d'activer le mode privé** | UI toggle: "Mode privé" — disables monitoring entirely, even if previously enabled. |
| **Ne jamais contourner le chiffrement WhatsApp** | Only use Windows UI Automation exposed text. No database extraction, no cookie/theft. |
| **Ne jamais extraire les cookies, jetons ou bases de données privées** | Forbidden. Code will explicitly avoid `whatsApp.db`, LevelDB, etc. |
| **Ne jamais envoyer un message sans confirmation explicite** | Safety.py confirmation gate — RISK.HIGH for `send_message`. |

### 6.1 Data Flow (Privacy-Preserving)

```
User enables monitoring
    ↓
WhatsApp Desktop window detected (UI Automation)
    ↓
Accessible text read element-by-element
    ↓
Anti-doubling check (memory + in-memory set)
    ↓
Gemini analysis (text sent to API, no storage)
    ↓
Voice output (TTS) or UI display
    ↓
✅ Message text NOT stored persistently
    ↓
❌ No logs with raw message content
```

*End of Phase 6*
---

## Phase 7 — Interface

### 7.1 WhatsApp Panel Design

Add to existing NIANG IA UI (ui.py) a collapsible panel with:

| Element | Description |
|---------|-------------|
| **État de connexion** | "WhatsApp : Connecté / Déconnecté" |
| **Surveillance activée/désactivée** | Toggle button |
| **Dernier expéditeur détecté** | Contact name (clickable) |
| **Nombre de nouveaux messages** | Badge counter (e.g., "3 nouveaux") |
| **Mode silencieux** | Checkbox — suppress TTS, show only in UI |
| **Mode privé** | Toggle — disables monitoring entirely |

### 7.2 Design Consistency

- Follow existing cyber/ocean/aurora/sunset themes
- Use same color palette (bg:#000000, pri:#00e5ff, etc.)
- Animated canvas matching current UI
- System tray integration (pystray) for on/off status

### 7.3 Panel Layout (Mockup)

```
+------------------------------------------+
|  NIANG IA — WhatsApp Monitor             |
|  [□ Mode silencieux] [□ Mode privé]      |
|  WhatsApp : ✗ Déconnecté                 |
|  Surveillance : ✗ Désactivée            |
|  Nouveaux messages : 0                   |
|  Dernier expéditeur : —                  |
|  [Actualiser] [Arrêter]                  |
+------------------------------------------+
```

*End of Phase 7*
---

## Phase 8 — Tests

### 8.1 Test Suites to Create

| Test Category | Description |
|---------------|-------------|
| **Détection de WhatsApp** | Test `is_whatsapp_open()` — mock WhatsApp process, verify psutil + title check. |
| **Lecture UI Automation** | Test accessible text extraction from WhatsApp mock window (pywinauto + UIA). |
| **Identification des contacts** | Test contact name extraction from UIA tree. |
| **Détection des nouveaux messages** | Test change detection between two UIA snapshots. |
| **Anti-doublons** | Test that same message not read twice (memory integration). |
| **Commandes vocales** | Test voice command parsing: "Niang, lis mes nouveaux messages". |
| **Résumés Gemini** | Test Gemini prompt output with sample WhatsApp messages. |
| **Confidentialité** | Test that no message content logged persistently. |
| **Confirmation avant envoi** | Test safety gate for send_message action. |
| **Absence de régression** | Run existing test suite, verify no breakage. |

### 8.2 Testing Strategy

1. **Unit tests** — `tests/test_whatsapp_monitor.py` — mock pywinauto/UIA
2. **Integration tests** — Requires WhatsApp Desktop running (optional)
3. **Voice command tests** — Parse vocal inputs against expected patterns
4. **Safety gate tests** — Confirm confirmation flow works for send_message
5. **End-to-end** — Run NIANG IA, enable monitoring, send test message, verify detection

### 8.3 Test Prerequisites

- WhatsApp Desktop installed and running (for integration tests)
- Python dependencies: `pywinauto`, `psutil`, `winotify`, `google-genai`
- Microsoft Inspect.exe available for diagnostics (optional)
- Gemini API key configured (for summary generation tests)

*End of Phase 8*
---

## Phase 9 — Final Report

### Expected Deliverables

| Item | Description |
|------|-------------|
| **NIANG_WHATSAPP_IMPLEMENTATION_REPORT.md** | Final report with: files created, files modified, dependencies used, tests executed and results, features actually operational, Windows UI Automation limitations, instructions for enabling monitoring. |
| **Fichiers créés** | `actions/whatsapp_monitor.py`, `actions/whatsapp_voice.py`, UI panel in `ui.py`, `tests/test_whatsapp_monitor.py`, `NIANG_WHATSAPP_IMPLEMENTATION_REPORT.md` |
| **Fichiers modifiés** | `NIANG_WHATSAPP_AUDIT.md` (this report), `main.py` (imports + monitoring thread startup), `config/app_settings.json` (new settings keys) |
| **Dépendances utilisées** | `pywinauto`, `psutil`, `winotify`, `google-genai` (déjà installés), `threading` (standard library) |
| **Tests exécutés et résultats** | Unitaires `tests/test_whatsapp_monitor.py` ; intégration (optionnel, WhatsApp Desktop requis) ; régression : aucun effet secondaire sur les fonctions existantes |
| **Fonctionnalités réellement opérationnelles** | Détection WhatsApp ouverte, lecture UI Automation des messages, identification expéditeurs, détection nouveaux messages, anti-doublons, commandes vocales, résumés Gemini, panneau interface, confidentialité |
| **Limitations de Windows UI Automation** | Certains contrôles WhatsApp UWP peuvent exposer peu ou pas de métadonnées accessibles ; fallback vers OCR local si nécessaire ; les messages chiffrés ne sont lisibles que via l'interface utilisateur visible ; pas de accès aux bases de données internes WhatsApp |
| **Instructions pour activer la surveillance** | 1. Lancer NIANG IA. 2. Cliquer sur "Activer la surveillance WhatsApp" dans le panneau ou dire "Niang, active la surveillance WhatsApp". 3. NIANG IA détectera WhatsApp Desktop s'il est ouvert. 4. Les nouveaux messages seront annoncés vocalement. 5. Désactiver avec "Niang, désactive la surveillance WhatsApp" ou le bouton du panneau. |

*End of Phase 9*