# actions/document_qa.py
# Kaizumi — question-answering over any document or web page
# (pdf, txt, md, html, docx, csv, pptx, xlsx, and http(s) URLs)

import os
import re
import sys
import zipfile
from pathlib import Path

from actions.pdf_reader import (
    _chunk_text,
    _pick_chunks,
    _ask_gemini,
)

try:
    from bs4 import BeautifulSoup
    _BS4 = True
except ImportError:
    _BS4 = False

try:
    import requests
    _REQUESTS = True
except ImportError:
    _REQUESTS = False


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


_URL_RE = re.compile(r"^(https?://)", re.IGNORECASE)

_SEARCH_DIRS = [
    Path.home() / "Documents",
    Path.home() / "Downloads",
    Path.home() / "Desktop",
]
_SEARCH_EXTENSIONS = {
    ".csv", ".docx", ".htm", ".html", ".json", ".log", ".md", ".pdf",
    ".pptx", ".txt", ".xlsx", ".xml",
}
_MAX_SEARCH_FILES = 300
_MAX_SEARCH_FILE_BYTES = 20 * 1024 * 1024
_MAX_SEARCH_RESULTS = 5
_MAX_OFFICE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024


def _search_roots(folder: str) -> list[Path]:
    folder = (folder or "").strip()
    if not folder or folder.lower() in ("all", "personal"):
        candidates = _SEARCH_DIRS
    else:
        aliases = {
            "documents": Path.home() / "Documents",
            "downloads": Path.home() / "Downloads",
            "desktop": Path.home() / "Desktop",
        }
        candidate = aliases.get(folder.lower(), Path(folder).expanduser())
        if not candidate.is_absolute():
            candidate = candidate.resolve()
        if not candidate.exists() or not candidate.is_dir():
            raise ValueError(f"Folder not found: {candidate}")
        candidates = [candidate]

    roots = []
    seen = set()
    for candidate in candidates:
        if not candidate.exists() or not candidate.is_dir():
            continue
        resolved = candidate.resolve()
        if resolved not in seen:
            roots.append(resolved)
            seen.add(resolved)
    if not roots:
        raise ValueError("No accessible document folders were found.")
    return roots


def _iter_search_files(roots: list[Path]):
    scanned = 0
    for root in roots:
        for current, dirs, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            dirs[:] = [
                name for name in dirs
                if not name.startswith(".")
                and not (current_path / name).is_symlink()
            ]
            for filename in filenames:
                path = current_path / filename
                if filename.startswith(".") or path.suffix.lower() not in _SEARCH_EXTENSIONS:
                    continue
                if path.is_symlink():
                    continue
                yield path
                scanned += 1
                if scanned >= _MAX_SEARCH_FILES:
                    return


def search_documents(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Search selected local document folders and return a few relevant excerpts."""
    params = parameters or {}
    query = str(params.get("query", "")).strip()
    if len(query) < 2:
        return "Give me at least two characters to search for, sir."

    try:
        roots = _search_roots(str(params.get("folder", "")))
    except (OSError, ValueError) as exc:
        return f"Could not search that folder: {exc}"

    terms = {
        term.lower() for term in re.findall(r"[\w'-]{2,}", query, flags=re.UNICODE)
    }
    if not terms:
        return "I couldn't find searchable words in that query, sir."

    results = []
    scanned = skipped = 0
    for path in _iter_search_files(roots):
        scanned += 1
        try:
            if path.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                skipped += 1
                continue
            text = _extract_text(str(path))
        except Exception as exc:
            print(f"[DocumentSearch] Skipped {path}: {exc}")
            skipped += 1
            continue

        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            continue
        lowered = normalized.lower()
        score = sum(lowered.count(term) for term in terms)
        if not score:
            continue

        positions = [lowered.find(term) for term in terms if lowered.find(term) >= 0]
        start = max(0, min(positions) - 100)
        excerpt = normalized[start:start + 320]
        if start:
            excerpt = "…" + excerpt
        if start + 320 < len(normalized):
            excerpt += "…"
        results.append((score, path, excerpt))

    results.sort(key=lambda result: (-result[0], str(result[1]).lower()))
    if not results:
        suffix = f" Skipped {skipped} unreadable or oversized file(s)." if skipped else ""
        return f"No matching documents found in the selected folders ({scanned} files checked).{suffix}"

    lines = [
        f"Found {len(results)} matching document(s) after checking {scanned} file(s).",
        "Matching excerpts are shared with Gemini to answer your question.",
    ]
    for score, path, excerpt in results[:_MAX_SEARCH_RESULTS]:
        lines.append(f"\n{path}\nRelevance: {score}\n{excerpt}")
    if skipped:
        lines.append(f"\nSkipped {skipped} unreadable or oversized file(s).")
    if scanned >= _MAX_SEARCH_FILES:
        lines.append(f"\nScan limit reached ({_MAX_SEARCH_FILES} files). Narrow the folder to search further.")
    return "\n".join(lines)


def _resolve_source(raw: str) -> str:
    """Return either a local path (str(Path)) or a URL. None if not found."""
    raw = (raw or "").strip().strip('"')
    if not raw:
        return None
    if _URL_RE.match(raw):
        return raw

    cand = Path(raw)
    if cand.is_absolute() and cand.exists():
        return str(cand)
    if cand.exists():
        return str(cand)

    for d in _SEARCH_DIRS:
        for root, _dirs, files in os.walk(d):
            for f in files:
                if f.lower() == cand.name.lower():
                    return str(Path(root) / f)
            break
        p = d / cand.name
        if p.exists():
            return str(p)
    return None


def _is_private_target(url: str) -> bool:
    """True if url resolves to a loopback/private/link-local/literal-IP host
    (SSRF guard: never fetch internal networks or cloud metadata)."""
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        host = (parsed.hostname or "").strip().strip("[]").lower()
        if parsed.scheme.lower() not in ("http", "https") or parsed.username or parsed.password:
            return True
    except (TypeError, ValueError):
        return True
    if not host:
        return True
    if host in {"localhost", "metadata.google.internal"} or \
            host.endswith((".localhost", ".local", ".internal")):
        return True

    import ipaddress
    try:
        return not ipaddress.ip_address(host).is_global
    except ValueError:
        pass

    import socket
    try:
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        }
    except Exception:
        return True  # unresolvable — fail closed
    if not addresses:
        return True
    try:
        return any(not ipaddress.ip_address(ip).is_global for ip in addresses)
    except Exception:
        return True


def _safe_get_url(url: str):
    if not _REQUESTS:
        raise RuntimeError("requests is not installed.")
    headers = {"User-Agent": "Mozilla/5.0 (Kaizumi/assistant)"}
    from urllib.parse import urljoin

    current = url
    for _ in range(6):
        if _is_private_target(current):
            raise RuntimeError("I can't fetch internal or private network URLs, sir.")
        resp = requests.get(
            current, headers=headers, timeout=20, allow_redirects=False, stream=True,
        )
        if resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            resp.close()
            if not location:
                raise RuntimeError("The page returned an invalid redirect.")
            current = urljoin(current, location)
            continue
        resp.raise_for_status()
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > 5 * 1024 * 1024:
            resp.close()
            raise RuntimeError("The web page exceeds the 5 MB download limit.")
        content = bytearray()
        for chunk in resp.iter_content(chunk_size=64 * 1024):
            content.extend(chunk)
            if len(content) > 5 * 1024 * 1024:
                resp.close()
                raise RuntimeError("The web page exceeds the 5 MB download limit.")
        resp._content = bytes(content)
        resp._content_consumed = True
        return resp
    raise RuntimeError("The page exceeded the redirect limit.")


def _extract_url_document(url: str) -> tuple[str, str]:
    resp = _safe_get_url(url)
    content_type = resp.headers.get("Content-Type", "").lower()
    if content_type and not any(
        kind in content_type
        for kind in (
            "text/html", "application/xhtml+xml", "text/plain",
            "application/json", "application/xml", "text/xml",
        )
    ):
        raise RuntimeError("This URL does not return a readable HTML or text page.")
    if _BS4:
        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("title")
        title = title_tag.get_text(" ", strip=True) if title_tag else ""
        if title_tag:
            title_tag.decompose()
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n", strip=True)
    else:
        title_match = re.search(r"<title[^>]*>(.*?)</title\s*>", resp.text, re.I | re.S)
        title = re.sub(r"\s+", " ", title_match.group(1)).strip() if title_match else ""
        raw = re.sub(
            r"<(script|style|noscript|title)\b[^>]*>.*?</\1\s*>",
            " ",
            resp.text,
            flags=re.I | re.S,
        )
        text = re.sub(r"<[^>]+>", " ", raw)
    return title, re.sub(r"\n{3,}", "\n\n", text)


def _extract_url(url: str) -> str:
    return _extract_url_document(url)[1]


def _extract_docx(path: Path) -> str:
    _validate_office_archive(path)
    with zipfile.ZipFile(str(path)) as z:
        xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:tc>", " | ", xml)
    xml = re.sub(r"</w:tr>", "\n", xml)
    xml = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    import html
    return html.unescape(text)


def _validate_office_archive(path: Path) -> None:
    with zipfile.ZipFile(str(path)) as archive:
        entries = archive.infolist()
        if len(entries) > 10_000 or sum(item.file_size for item in entries) > _MAX_OFFICE_UNCOMPRESSED_BYTES:
            raise ValueError(
                "Le contenu décompressé de ce document Office dépasse la limite de sécurité."
            )


def _extract_pptx(path: Path) -> str:
    _validate_office_archive(path)
    try:
        from pptx import Presentation
    except ImportError:
        raise RuntimeError("python-pptx is not installed.")
    prs = Presentation(str(path))
    lines = []
    for slide in prs.slides:
        slide_lines = []
        for shape in slide.shapes:
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    if any(cells):
                        slide_lines.append(" | ".join(cells))
            elif getattr(shape, "has_text_frame", False) and shape.text.strip():
                slide_lines.append(shape.text)
        if slide_lines:
            lines.append("\n".join(slide_lines))
    return "\n".join(lines)


def _extract_xlsx(path: Path) -> str:
    _validate_office_archive(path)
    try:
        from openpyxl import load_workbook
    except ImportError:
        raise RuntimeError("openpyxl is not installed.")
    wb = load_workbook(str(path), read_only=True, data_only=True)
    try:
        lines = []
        for ws in wb.worksheets:
            lines.append(f"[Sheet: {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                cells = [str(c) for c in row if c is not None and str(c).strip()]
                if cells:
                    lines.append(" | ".join(cells))
        return "\n".join(lines)
    finally:
        wb.close()


def _extract_text(source: str) -> str:
    if _URL_RE.match(source):
        return _extract_url(source)

    path = Path(source)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from actions.pdf_reader import _extract_text as _pdf_text
        return _pdf_text(path)

    if suffix in (".docx",):
        return _extract_docx(path)

    if suffix in (".pptx", ".ppt"):
        return _extract_pptx(path)

    if suffix in (".xlsx", ".xls"):
        return _extract_xlsx(path)

    if suffix in (".html", ".htm"):
        raw = path.read_text(encoding="utf-8", errors="replace")
        if _BS4:
            soup = BeautifulSoup(raw, "html.parser")
            for tag in soup(["script", "style", "noscript"]):
                tag.decompose()
            return soup.get_text("\n", strip=True)
        return re.sub(r"<[^>]+>", " ", raw)

    # default: plain text (txt, md, csv, log, json, any)
    return path.read_text(encoding="utf-8", errors="replace")


def _describe(source: str) -> str:
    if _URL_RE.match(source):
        return source
    p = Path(source)
    return f"{p.name} ({p.stat().st_size // 1024} KB)"


def read_document(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Preview any local document or a web page."""
    params = parameters or {}
    source = _resolve_source(str(params.get("source", params.get("path", ""))))
    if not source:
        return ("I couldn't find that document, sir. Give me a file name, path, "
                "or a web address.")

    try:
        text = _extract_text(source)
    except Exception as e:
        return f"Could not read that source: {e}"
    if not text.strip():
        return f"'{_describe(source)}' has no extractable text, sir."

    preview = text[:1400] + ("…" if len(text) > 1400 else "")
    return f"Source: {_describe(source)} — {len(text)} characters.\n\n{preview}"


def document_qa(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """Answer a question from any document or web page (lightweight RAG)."""
    params   = parameters or {}
    source   = _resolve_source(str(params.get("source", "")))
    question = str(params.get("question", params.get("query", ""))).strip()

    if not source:
        return ("I couldn't find that source, sir. Give a file name, path, or URL.")
    if not question:
        return "What would you like to know, sir?"

    try:
        text = _extract_text(source)
    except Exception as e:
        return f"Could not read that source: {e}"

    text_full = re.sub(r"\s+", " ", text).strip()
    if not text_full:
        return f"'{_describe(source)}' has no extractable text, sir."
    chunks = _chunk_text(text_full)
    picked = _pick_chunks(question, chunks)
    answer = _ask_gemini(question, "\n\n---\n\n".join(picked))
    return f"From {_describe(source)}:\n{answer}"