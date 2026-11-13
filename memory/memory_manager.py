"""
memory_manager.py — Kaizumi Hafıza Sistemi
============================================
Düzeltmeler:
  - _MEMORY_EVERY_N_TURNS: 3 → 1 (her turda kontrol)
  - Stage 1 YES/NO check daha geniş kriterlere sahip
  - Extraction prompt daha kapsamlı ve agresif
  - Projeleri, favori şeyleri, arkadaşları daha iyi yakalar
"""

import json
import os
import re
import shutil
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from threading import Lock
from pathlib import Path
import sys
from typing import Iterator


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


BASE_DIR         = get_base_dir()
MEMORY_PATH      = BASE_DIR / "memory" / "long_term.json"
INSTALLER_PROFILE_PATH = BASE_DIR / "memory" / "installer_profile.json"
BACKUP_DIR       = BASE_DIR / "memory" / "backups"
ARCHIVE_PATH     = BASE_DIR / "memory" / "long_term_archive.json"
CONVERSATION_DB_PATH = BASE_DIR / "memory" / "conversations.sqlite3"
MAX_BACKUPS      = 20
_lock            = Lock()
_conversation_lock = Lock()
MAX_VALUE_LENGTH = 400

# Values that look like secrets are never stored — passwords, API keys,
# bearer tokens, credit-card-ish numbers, etc.
# Keys are matched broadly (token/auth/session/cookie/credential as a word);
# values are matched only on high-signal secret shapes to avoid false
# positives like "I booked a session with the dentist".
_SECRET_KEY_RE = re.compile(
    r"(?i)(api[_-]?key|secret|password|passwd|bearer|authorization|"
    r"client[_-]?secret|access[_-]?token|refresh[_-]?token|"
    r"(^|[^a-z])(token|auth|session|cookie|credential|id[_-]?token|"
    r"app[_-]?password|client[_-]?id)([^a-z]|$))"
)
_SECRET_VAL_RE = re.compile(
    r"(?i)(AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{16,}|"
    r"AKIA[0-9A-Z]{16}|ghp_[0-9A-Za-z]{20,}|xox[baprs]-[0-9A-Za-z-]{10,}|"
    r"(api[_-]?key|secret|password|bearer|authorization|access[_-]?token)"
    r"[=: ]+[^\s]{6,})"
)
_SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b(api[_ -]?key|client[_ -]?secret|access[_ -]?token|"
    r"refresh[_ -]?token|password|passwd|authorization|bearer|secret)"
    r"\b\s*(?:is|equals|=|:)\s*[\"']?([^\s,;\"']+)"
)
_SECRET_TOKEN_RE = re.compile(
    r"(?i)\b(?:AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z]{16,}|"
    r"AKIA[0-9A-Z]{16}|gh[pousr]_[0-9A-Za-z]{20,}|"
    r"xox[baprs]-[0-9A-Za-z-]{10,})\b"
)
_MEMORY_SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "about", "as", "at", "be", "but", "by", "did",
    "do", "for", "from", "how", "i", "in", "is", "it", "me", "my", "of",
    "on", "or", "said", "that", "the", "this", "to", "was", "what", "when",
    "where", "who", "with", "you", "your", "à", "au", "aux", "avec", "ce",
    "ces", "dans", "de", "des", "du", "elle", "en", "et", "il", "je", "la",
    "le", "les", "ma", "mes", "mon", "ou", "par", "pour", "que", "qui", "sa",
    "se", "son", "sur", "ta", "te", "tes", "ton", "tu", "un", "une", "vos",
    "votre",
}


@contextmanager
def _conversation_database() -> Iterator[sqlite3.Connection]:
    CONVERSATION_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(CONVERSATION_DB_PATH, timeout=15)
    try:
        connection.execute("PRAGMA busy_timeout = 15000")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS conversations ("
            "id INTEGER PRIMARY KEY, occurred_at TEXT NOT NULL, "
            "user_text TEXT NOT NULL, assistant_text TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts "
            "USING fts5(user_text, assistant_text)"
        )
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _redact_transcript_secrets(text: str) -> str:
    text = _SECRET_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", text
    )
    return _SECRET_TOKEN_RE.sub("[REDACTED]", text)


def archive_conversation(user_text: str, assistant_text: str) -> None:
    """Keep a searchable local copy of each completed text conversation turn."""
    user_text = _redact_transcript_secrets(str(user_text or "").strip())
    assistant_text = _redact_transcript_secrets(str(assistant_text or "").strip())
    if not user_text and not assistant_text:
        return
    occurred_at = datetime.now().astimezone().isoformat(timespec="seconds")
    with _conversation_lock, _conversation_database() as connection:
        cursor = connection.execute(
            "INSERT INTO conversations (occurred_at, user_text, assistant_text) "
            "VALUES (?, ?, ?)",
            (occurred_at, user_text, assistant_text),
        )
        connection.execute(
            "INSERT INTO conversations_fts (rowid, user_text, assistant_text) "
            "VALUES (?, ?, ?)",
            (cursor.lastrowid, user_text, assistant_text),
        )


def _search_conversations(query: str, limit: int = 5) -> list[dict]:
    tokens = re.findall(r"[\w'-]+", str(query or ""), flags=re.UNICODE)
    tokens = [
        token for token in tokens
        if len(token) > 1 and token.casefold() not in _MEMORY_SEARCH_STOPWORDS
    ][:12]
    if not tokens or not CONVERSATION_DB_PATH.exists():
        return []
    match_query = " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)
    with _conversation_lock, _conversation_database() as connection:
        rows = connection.execute(
            "SELECT c.occurred_at, c.user_text, c.assistant_text "
            "FROM conversations_fts f "
            "JOIN conversations c ON c.id = f.rowid "
            "WHERE conversations_fts MATCH ? "
            "ORDER BY bm25(conversations_fts, 3.0, 1.0), c.id DESC "
            "LIMIT ?",
            (match_query, max(1, min(int(limit), 10))),
        ).fetchall()
    return [
        {"occurred_at": row[0], "user_text": row[1], "assistant_text": row[2]}
        for row in rows
    ]


def _conversation_excerpt(text: str, query: str, limit: int = 900) -> str:
    if len(text) <= limit:
        return text
    terms = re.findall(r"[\w'-]+", query, flags=re.UNICODE)
    folded = text.casefold()
    positions = [folded.find(term.casefold()) for term in terms]
    positions = [position for position in positions if position >= 0]
    start = max(0, min(positions, default=0) - limit // 3)
    end = min(len(text), start + limit)
    excerpt = text[start:end]
    return ("…" if start else "") + excerpt + ("…" if end < len(text) else "")


def _redact_conversation_detail(detail: str) -> int:
    detail = str(detail or "").strip()
    if len(detail) < 3 or not CONVERSATION_DB_PATH.exists():
        return 0
    pattern = re.compile(rf"(?<!\w){re.escape(detail)}(?!\w)", re.IGNORECASE)
    changed = 0
    with _conversation_lock, _conversation_database() as connection:
        connection.create_function("casefold", 1, str.casefold)
        rows = connection.execute(
            "SELECT id, user_text, assistant_text FROM conversations "
            "WHERE instr(casefold(user_text), casefold(?)) > 0 "
            "OR instr(casefold(assistant_text), casefold(?)) > 0",
            (detail, detail),
        ).fetchall()
        for row_id, user_text, assistant_text in rows:
            updated_user = pattern.sub("[forgotten]", user_text)
            updated_assistant = pattern.sub("[forgotten]", assistant_text)
            if (updated_user, updated_assistant) == (user_text, assistant_text):
                continue
            connection.execute(
                "UPDATE conversations SET user_text = ?, assistant_text = ? "
                "WHERE id = ?",
                (updated_user, updated_assistant, row_id),
            )
            connection.execute(
                "DELETE FROM conversations_fts WHERE rowid = ?", (row_id,)
            )
            connection.execute(
                "INSERT INTO conversations_fts (rowid, user_text, assistant_text) "
                "VALUES (?, ?, ?)",
                (row_id, updated_user, updated_assistant),
            )
            changed += 1
    return changed


def _remove_fact_from_file(path: Path, category: str, key: str) -> None:
    if not path.exists():
        return
    data = _valid_memory(path)
    if data is None:
        return
    values = data.get(category)
    if not isinstance(values, dict) or key not in values:
        return
    del values[key]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _remove_category_from_file(path: Path, category: str) -> None:
    if not path.exists():
        return
    data = _valid_memory(path)
    if data is None or category not in data:
        return
    del data[category]
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _memory_backup_files() -> Iterator[Path]:
    try:
        return BACKUP_DIR.glob("long_term_*.json")
    except OSError as exc:
        print(f"[Memory] Could not list memory backups: {exc}")
        return iter(())


def _delete_conversation_archive() -> None:
    for path in (
        CONVERSATION_DB_PATH,
        Path(f"{CONVERSATION_DB_PATH}-wal"),
        Path(f"{CONVERSATION_DB_PATH}-shm"),
    ):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[Memory] Could not delete {path.name}: {exc}")


def _empty_memory() -> dict:
    return {
        "identity":      {},
        "preferences":   {},
        "projects":      {},
        "relationships": {},
        "wishes":        {},
        "notes":         {}
    }


def _valid_memory(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _newest_backup() -> Path | None:
    try:
        backups = sorted(
            BACKUP_DIR.glob("long_term_*.json"),
            key=lambda p: p.name,
            reverse=True,
        )
    except OSError:
        return None
    for candidate in backups:
        if _valid_memory(candidate) is not None:
            return candidate
    return None


def _write_backup() -> None:
    """Copy the current long_term.json into memory/backups (keep last MAX_BACKUPS)."""
    if not MEMORY_PATH.exists():
        return
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = BACKUP_DIR / f"long_term_{stamp}.json"
        shutil.copy2(MEMORY_PATH, backup)
        backups = sorted(BACKUP_DIR.glob("long_term_*.json"), key=lambda p: p.name, reverse=True)
        for old in backups[MAX_BACKUPS:]:
            try:
                old.unlink()
            except OSError:
                pass
    except OSError as e:
        print(f"[Memory] Backup failed (non-fatal): {e}")


def load_memory() -> dict:
    if not MEMORY_PATH.exists() and not INSTALLER_PROFILE_PATH.exists():
        return _empty_memory()

    with _lock:
        data = _empty_memory()
        if MEMORY_PATH.exists():
            loaded = _valid_memory(MEMORY_PATH)
            if loaded is None:
                backup = _newest_backup()
                if backup is not None:
                    loaded = _valid_memory(backup)
                    print(f"[Memory] long_term.json unreadable - restoring from {backup.name}")
                if loaded is not None:
                    try:
                        MEMORY_PATH.write_text(
                            json.dumps(loaded, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    except OSError:
                        pass
            if loaded is None:
                print("[Memory] Load error: no valid memory file and no valid backup.")
                return data
            data.update(loaded)
            for key in _empty_memory():
                if key not in data:
                    data[key] = {}

        if not INSTALLER_PROFILE_PATH.exists():
            return data

        try:
            profile = json.loads(INSTALLER_PROFILE_PATH.read_text(encoding="utf-8-sig"))
            if not isinstance(profile, dict):
                raise ValueError("Installer profile must be a JSON object")
            _recursive_update(data, profile)
            tmp = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".tmp")
            tmp.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(tmp, MEMORY_PATH)
            _write_backup()
            INSTALLER_PROFILE_PATH.unlink()
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            print(f"[Memory] ⚠️ Could not import installer profile: {e}")
        return data


def save_memory(memory: dict) -> None:
    if not isinstance(memory, dict):
        return
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _write_backup()
        tmp = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".tmp")
        tmp.write_text(
            json.dumps(memory, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        os.replace(tmp, MEMORY_PATH)
        _write_backup()


def _truncate_value(val: str) -> str:
    if isinstance(val, str) and len(val) > MAX_VALUE_LENGTH:
        return val[:MAX_VALUE_LENGTH].rstrip() + "…"
    return val


def _recursive_update(target: dict, updates: dict) -> bool:
    changed = False
    for key, value in updates.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue

        if isinstance(value, dict) and "value" not in value:
            if key not in target or not isinstance(target[key], dict):
                target[key] = {}
                changed = True
            if _recursive_update(target[key], value):
                changed = True
        else:
            if isinstance(value, dict) and "value" in value:
                new_val = _truncate_value(str(value["value"]))
            else:
                new_val = _truncate_value(str(value))

            if _SECRET_KEY_RE.search(str(key)) or _SECRET_VAL_RE.search(str(value)):
                continue

            entry    = {"value": new_val, "updated": datetime.now().strftime("%Y-%m-%d")}
            existing = target.get(key, {})
            if not isinstance(existing, dict) or existing.get("value") != new_val:
                target[key] = entry
                changed = True

    return changed


def update_memory(memory_update: dict) -> dict:
    if not isinstance(memory_update, dict) or not memory_update:
        return load_memory()

    memory = load_memory()
    if _recursive_update(memory, memory_update):
        prune_memory(memory)
        save_memory(memory)
        print(f"[Memory] 💾 Saved: {list(memory_update.keys())}")
    return memory


def prune_memory(memory: dict, cap: int = 500) -> None:
    """Safety valve only — never silently lose memories.

    Categories grow up to `cap` entries; anything older/overflow is APPENDED
    to long_term_archive.json instead of being deleted. Backups are kept in
    memory/backups on every save.
    """
    if not isinstance(memory, dict):
        return
    archive: dict[str, dict] = {}
    for cat_name, cat in memory.items():
        if not isinstance(cat, dict):
            continue
        if len(cat) <= cap:
            continue
        ordered = sorted(
            cat.items(),
            key=lambda kv: str(kv[1].get("updated", "")) if isinstance(kv[1], dict) else "",
            reverse=True,
        )
        memory[cat_name] = dict(ordered[:cap])
        overflow = dict(ordered[cap:])
        if overflow:
            archive[cat_name] = overflow
        print(f"[Memory] Archived {len(overflow)} older {cat_name} entries (nothing deleted)")

    if not archive:
        return
    try:
        existing: dict = {}
        if ARCHIVE_PATH.exists():
            try:
                existing = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    existing = {}
            except (OSError, json.JSONDecodeError):
                existing = {}
        for cat_name, entries in archive.items():
            bucket = existing.setdefault(cat_name, {})
            bucket.update(entries)
        ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = ARCHIVE_PATH.with_suffix(ARCHIVE_PATH.suffix + ".tmp")
        tmp.write_text(json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ARCHIVE_PATH)
    except OSError as e:
        print(f"[Memory] Could not write archive (entries kept in memory): {e}")


def should_extract_memory(user_text: str, assistant_text: str, api_key: str) -> bool:
    """
    Stage 1: Hızlı YES/NO kontrolü.
    Öncekinden daha geniş kriterler — favori şeyler, projeler, arkadaşlar da dahil.
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        # Her iki tarafı da gönder — Kaizumi'nin söyledikleri de bilgi içerebilir
        combined = f"User: {user_text[:300]}\nKaizumi: {assistant_text[:200]}"

        prompt = (
            "Does this conversation contain ANY of the following?\n"
            "- Personal facts (name, age, city, job, birthday, nationality)\n"
            "- Preferences or favorites (food, color, music, sport, game, film, book, etc.)\n"
            "- Active projects or goals the user is working on\n"
            "- People in the user's life (friends, family, partner, colleagues)\n"
            "- Things the user wants to do or buy in the future\n"
            "- Any other fact worth remembering long-term\n\n"
            "Reply only YES or NO.\n\nConversation:\n"
            f"{combined}"
        )
        check = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        return "YES" in (check.text or "").upper()
    except Exception as e:
        print(f"[Memory] ⚠️ Stage1 check failed: {e}")
        return False


def extract_memory(user_text: str, assistant_text: str, api_key: str) -> dict:
    """
    Stage 2: Detaylı çıkarım. Her iki tarafı da analiz eder.
    """
    try:
        from google import genai

        client = genai.Client(api_key=api_key)

        combined = f"User: {user_text[:500]}\nKaizumi: {assistant_text[:300]}"

        prompt = (
            "Extract ALL memorable personal facts from this conversation. Any language.\n"
            "Return ONLY valid JSON. Use {} if truly nothing is worth saving.\n\n"
            "Category guide:\n"
            "  identity      → name, age, birthday, city, country, job, school, nationality, language\n"
            "  preferences   → ANY favorite or preferred thing:\n"
            "                  favorite_food, favorite_color, favorite_music, favorite_film,\n"
            "                  favorite_game, favorite_sport, favorite_book, favorite_artist,\n"
            "                  favorite_country, hobbies, interests, dislikes, etc.\n"
            "  projects      → projects being built, ongoing work, goals, ideas in progress\n"
            "                  (e.g. kaizumi: 'Building a personal AI assistant')\n"
            "  relationships → people mentioned: friends, family, partner, colleagues\n"
            "                  (e.g. best_friend_ali: 'Best friend, met in university')\n"
            "  wishes        → future plans, things to buy, travel plans, dreams\n"
            "  notes         → anything else worth remembering (habits, schedule, etc.)\n\n"
            "IMPORTANT:\n"
            "- Be LIBERAL: if something MIGHT be worth remembering, include it.\n"
            "- Extract from BOTH user and Kaizumi turns.\n"
            "- Skip: weather, reminders, search results, one-time commands.\n"
            "- Use concise English values regardless of conversation language.\n\n"
            "Format:\n"
            '{"identity":{"name":{"value":"Ali"}},\n'
            ' "preferences":{"favorite_color":{"value":"blue"}, "hobby":{"value":"gaming"}},\n'
            ' "projects":{"kaizumi":{"value":"Personal AI assistant on Windows"}},\n'
            ' "relationships":{"friend_yusuf":{"value":"close friend"}},\n'
            ' "wishes":{"buy_guitar":{"value":"wants an acoustic guitar"}},\n'
            ' "notes":{"works_at_night":{"value":"usually active late at night"}}}\n\n'
            f"Conversation:\n{combined}\n\nJSON:"
        )

        resp = client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=prompt,
        )
        raw = (resp.text or "").strip()

        import re
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        if not raw or raw == "{}":
            return {}

        return json.loads(raw)

    except json.JSONDecodeError:
        return {}
    except Exception as e:
        if "429" not in str(e):
            print(f"[Memory] ⚠️ Extract failed: {e}")
        return {}


def format_memory_for_prompt(memory: dict | None) -> str:
    if not memory:
        return ""

    lines = []

    identity  = memory.get("identity", {})
    id_fields = ["name", "age", "birthday", "city", "job", "language", "school", "nationality"]
    for field in id_fields:
        entry = identity.get(field)
        if entry:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"{field.title()}: {val}")
    for key, entry in identity.items():
        if key in id_fields:
            continue
        val = entry.get("value") if isinstance(entry, dict) else entry
        if val:
            lines.append(f"{key.replace('_', ' ').title()}: {val}")

    prefs = memory.get("preferences", {})
    if prefs:
        lines.append("")
        lines.append("Preferences:")
        for key, entry in list(prefs.items())[:25]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    projects = memory.get("projects", {})
    if projects:
        lines.append("")
        lines.append("Active Projects / Goals:")
        for key, entry in list(projects.items())[:12]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    rels = memory.get("relationships", {})
    if rels:
        lines.append("")
        lines.append("People in their life:")
        for key, entry in list(rels.items())[:15]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    wishes = memory.get("wishes", {})
    if wishes:
        lines.append("")
        lines.append("Wishes / Plans / Wants:")
        for key, entry in list(wishes.items())[:12]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key.replace('_', ' ').title()}: {val}")

    notes = memory.get("notes", {})
    if notes:
        lines.append("")
        lines.append("Other notes:")
        for key, entry in list(notes.items())[:12]:
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val:
                lines.append(f"  - {key}: {val}")

    if not lines:
        return ""

    header = "[WHAT YOU KNOW ABOUT THIS PERSON — use naturally, never recite like a list]\n"
    result = header + "\n".join(lines)
    if len(result) > 3200:
        result = result[:3197] + "…"

    return result + "\n"


def remember(key: str, value: str, category: str = "notes") -> str:
    valid = {"identity", "preferences", "projects", "relationships", "wishes", "notes"}
    if category not in valid:
        category = "notes"
    if _SECRET_KEY_RE.search(key) or _SECRET_VAL_RE.search(str(value)):
        return "I can't store that — it looks like a secret (password or key)."
    update_memory({category: {key: {"value": value}}})
    return f"Remembered: {category}/{key} = {value}"


def forget(key: str, category: str = "notes") -> str:
    memory = load_memory()
    cat    = memory.get(category, {})
    archived = _valid_memory(ARCHIVE_PATH) if ARCHIVE_PATH.exists() else {}
    archived_cat = archived.get(category, {}) if archived else {}
    if key in cat or key in archived_cat:
        entry = cat.get(key, archived_cat.get(key))
        value = entry.get("value", "") if isinstance(entry, dict) else str(entry)
        if key in cat:
            del cat[key]
            memory[category] = cat
            save_memory(memory)
        _remove_fact_from_file(ARCHIVE_PATH, category, key)
        try:
            for backup in _memory_backup_files():
                _remove_fact_from_file(backup, category, key)
        except OSError as exc:
            print(f"[Memory] Could not update memory backups: {exc}")
        _redact_conversation_detail(str(value or key.replace("_", " ")))
        return f"Forgotten: {category}/{key}"
    return f"Not found: {category}/{key}"


def _search_dict(memory: dict, q: str, category: str = "") -> list[str]:
    findings = []
    for cat_name, cat in memory.items():
        if category and cat_name != category:
            continue
        if not isinstance(cat, dict):
            continue
        for key, entry in cat.items():
            val = entry.get("value") if isinstance(entry, dict) else entry
            if val is None:
                continue
            val_s = str(val)
            key_s = str(key).replace("_", " ")
            if q in key_s.lower() or q in val_s.lower():
                findings.append(f"{cat_name}/{key}: {val_s}")
    return findings


def search_memory(query: str, category: str = "") -> str:
    """Search long-term facts and the local full-text conversation archive."""
    if not query or not query.strip():
        return ""
    q = query.lower().strip()
    memory   = load_memory()
    findings = _search_dict(memory, q, category)

    try:
        if ARCHIVE_PATH.exists():
            archive = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
            if isinstance(archive, dict):
                findings += _search_dict(archive, q, category)
    except (OSError, json.JSONDecodeError):
        pass

    findings = list(dict.fromkeys(findings))
    conversations = _search_conversations(query)
    if not findings and not conversations:
        return f"I don't have anything saved matching '{query}', sir."
    if len(findings) > 8:
        findings = findings[:8]
    sections = []
    if findings:
        sections.append("Saved facts: " + "; ".join(findings))
    if conversations:
        excerpts = []
        for item in conversations:
            user_text = _conversation_excerpt(item["user_text"], query)
            assistant_text = _conversation_excerpt(item["assistant_text"], query)
            excerpts.append(
                f"[{item['occurred_at']}] User: {user_text} | "
                f"NIANG IA: {assistant_text}"
            )
        sections.append("Relevant past conversations:\n" + "\n".join(excerpts))
    return "I remember: " + "\n".join(sections)


# Alias — eski import'larla uyumluluk için
forget_memory = forget


def clear_memory(category: str = "") -> str:
    """Clear all long-term memory, or just one category.
    Returns a short confirmation string."""
    cat = category.strip().lower()
    if cat in {"conversations", "history"}:
        with _conversation_lock:
            _delete_conversation_archive()
        return "Conversation archive cleared."
    if cat:
        memory = load_memory()
        if cat in memory:
            memory[cat] = {}
            save_memory(memory)
            _remove_category_from_file(ARCHIVE_PATH, cat)
            try:
                for backup in _memory_backup_files():
                    _remove_category_from_file(backup, cat)
            except OSError as exc:
                print(f"[Memory] Could not update memory backups: {exc}")
            return f"Cleared '{cat}' memory."
        return f"Category '{cat}' not found. Categories: " + ", ".join(memory.keys())
    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        tmp = MEMORY_PATH.with_suffix(MEMORY_PATH.suffix + ".tmp")
        tmp.write_text(
            json.dumps(_empty_memory(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        os.replace(tmp, MEMORY_PATH)
        for path in (ARCHIVE_PATH, INSTALLER_PROFILE_PATH):
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                print(f"[Memory] Could not delete {path.name}: {exc}")
        try:
            for backup in BACKUP_DIR.glob("long_term_*.json"):
                backup.unlink()
        except OSError as exc:
            print(f"[Memory] Could not clear memory backups: {exc}")
    with _conversation_lock:
        _delete_conversation_archive()
    return "All memory cleared."