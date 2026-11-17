from __future__ import annotations

import hashlib
import html
import io
import json
import os
import re
import tempfile
import time
import unicodedata
import warnings
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, unquote, urlsplit

import requests
from PIL import Image, UnidentifiedImageError

from agent import workspace_tools
from agent.secrets import detect_sensitive_data


MAX_QUERY_LENGTH = 120
MAX_RESULTS = 12
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_PIXELS = 80_000_000
MAX_REGISTRY_BYTES = 1_000_000
MAX_SEARCH_CACHE_BYTES = 5_000_000
MAX_SEARCH_CACHE_ENTRIES = 100
SEARCH_CACHE_TTLS = {"pixabay": 24 * 60 * 60, "unsplash": 15 * 60, "pexels": 10 * 60}
_PROVIDER_KEYS = {
    "pixabay": "NIANG_IA_PIXABAY_API_KEY",
    "unsplash": "NIANG_IA_UNSPLASH_ACCESS_KEY",
    "pexels": "NIANG_IA_PEXELS_API_KEY",
}
_PROVIDER_HOSTS = {
    "pixabay": {"pixabay.com", "cdn.pixabay.com"},
    "unsplash": {"api.unsplash.com", "images.unsplash.com"},
    "pexels": {"api.pexels.com", "images.pexels.com"},
}
_LICENSES = {
    "pixabay": (
        "Pixabay Content License",
        "https://pixabay.com/service/terms/",
    ),
    "unsplash": (
        "Unsplash License and API Guidelines; API images must remain hotlinked",
        "https://help.unsplash.com/api-guidelines/unsplash-api-guidelines",
    ),
    "pexels": ("Pexels License", "https://www.pexels.com/license/"),
}
_IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".webp"}
_IMAGE_FORMATS = {"AVIF", "GIF", "JPEG", "PNG", "WEBP"}
_TEXT_SUFFIXES = {".css", ".htm", ".html", ".js", ".jsx", ".md", ".mjs", ".tsx", ".vue"}
_IGNORED_DIRECTORIES = {
    ".git", ".hg", ".svn", ".venv", "build", "dist", "node_modules",
    "out", "target", "vendor", "__pycache__",
}
_PLACEHOLDER_PATTERN = re.compile(
    r"(?i)(?:placehold\.co|placeholder\.com|placeholder\.jpg|dummyimage\.com|"
    r"via\.placeholder|picsum\.photos|/placeholder(?:[-_/ .]|$)|"
    r"\b(?:todo|replace[-_ ]?me)\.(?:png|jpe?g|webp|avif)\b)"
)
_IMAGE_REFERENCE_PATTERN = re.compile(
    r"""(?ix)
    (?:src|poster|href)\s*=\s*["']([^"']+)["']
    |url\(\s*["']?([^)"']+)["']?\s*\)
    """
)
_TOKEN_PATTERN = re.compile(r"[^\W_]{2,}", re.UNICODE)


class VisualAssetError(RuntimeError):
    """A visual asset could not be searched, verified, or safely integrated."""


@dataclass(frozen=True)
class VisualAssetCandidate:
    candidate_id: str
    provider: str
    provider_asset_id: str
    query: str
    description: str
    tags: str
    source_url: str
    image_url: str
    preview_url: str
    download_url: str
    download_location: str
    author: str
    author_profile_url: str
    license_name: str
    license_url: str
    width: int
    height: int
    resource_type: str
    score: float
    score_factors: Mapping[str, float]
    popularity: int
    local_path: str = ""

    def public_data(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("download_url", None)
        data.pop("download_location", None)
        return data


class VisualAssetService:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        http_get: Callable[..., Any] = requests.get,
        clock: Callable[[], float] = time.monotonic,
        cache_path: str | os.PathLike[str] | None = None,
    ) -> None:
        self._environ = os.environ if environ is None else environ
        self._http_get = http_get
        self._clock = clock
        self._cache_path = (
            Path(cache_path)
            if cache_path is not None
            else Path(
                os.environ.get(
                    "LOCALAPPDATA",
                    str(Path.home() / "AppData" / "Local"),
                )
            ) / "NIANG IA" / "visual_asset_search_cache.json"
        )
        self._cache: dict[tuple[Any, ...], tuple[float, list[VisualAssetCandidate]]] = {}
        self._candidates: dict[str, VisualAssetCandidate] = {}
        self._request_count = 0

    def search(
        self,
        query: str,
        *,
        orientation: str = "any",
        min_width: int = 0,
        min_height: int = 0,
        limit: int = 8,
        allow_pexels: bool = False,
    ) -> dict[str, Any]:
        query = self._validate_query(query)
        if not isinstance(orientation, str) or orientation not in {
            "any", "landscape", "portrait", "square",
        }:
            raise VisualAssetError("Orientation must be any, landscape, portrait, or square.")
        if not self._valid_dimension(min_width) or not self._valid_dimension(min_height):
            raise VisualAssetError("Minimum image dimensions must be between 0 and 16000.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise VisualAssetError(f"Result limit must be between 1 and {MAX_RESULTS}.")
        if not isinstance(allow_pexels, bool):
            raise VisualAssetError("Pexels authorization must be a boolean.")

        provider_status: dict[str, str] = {}
        candidates: list[VisualAssetCandidate] = []
        providers = ("pixabay", "unsplash", "pexels") if allow_pexels else ("pixabay", "unsplash")
        for provider in providers:
            key = self._provider_key(provider)
            if not key:
                provider_status[provider] = "not_configured"
                continue
            try:
                found = self._search_provider(
                    provider, key, query, orientation, min_width, min_height, limit
                )
            except VisualAssetError as exc:
                provider_status[provider] = f"unavailable: {exc}"
                continue
            provider_status[provider] = "available"
            candidates.extend(found)
            if len(found) >= limit:
                break

        deduplicated: dict[str, VisualAssetCandidate] = {}
        for candidate in candidates:
            deduplicated.setdefault(candidate.candidate_id, candidate)
        ranked = sorted(
            deduplicated.values(),
            key=lambda item: (-item.score, -item.popularity, item.provider, item.provider_asset_id),
        )[:limit]
        for candidate in ranked:
            self._candidates[candidate.candidate_id] = candidate

        if allow_pexels and not self._provider_key("pexels"):
            provider_status["pexels"] = "not_configured"
        message = ""
        status = "ok" if ranked else "no_results"
        if not ranked and all(value == "not_configured" for value in provider_status.values()):
            status = "unavailable"
            message = (
                "No image-provider credentials are configured. Add an authorized provider "
                "key to the NIANG IA process environment; no provider request was made."
            )
        return {
            "status": status,
            "query": query,
            "orientation": orientation,
            "providers": provider_status,
            "results": [item.public_data() for item in ranked],
            "message": message,
            "notice": (
                "Results are ranked from provider metadata, tags, dimensions, orientation, "
                "and popularity. Composition and visual content still require review."
            ),
        }

    def inspect_local(
        self,
        workspace_root: str | os.PathLike[str],
        *,
        path: str = ".",
        limit: int = MAX_RESULTS,
    ) -> dict[str, Any]:
        root = workspace_tools._workspace_root(workspace_root)
        directory = workspace_tools._resolve_workspace_path(
            path, must_exist=True, workspace_root=root
        )
        if not directory.is_dir():
            raise VisualAssetError("The visual asset inspection path must be a directory.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_RESULTS:
            raise VisualAssetError(f"Result limit must be between 1 and {MAX_RESULTS}.")

        found: list[dict[str, Any]] = []
        scanned = 0
        for current, directories, filenames in os.walk(directory, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if not name.startswith(".") and name.lower() not in _IGNORED_DIRECTORIES
                and not (current_path / name).is_symlink()
            ]
            for filename in filenames:
                file_path = current_path / filename
                if file_path.suffix.lower() not in _IMAGE_SUFFIXES or file_path.is_symlink():
                    continue
                scanned += 1
                if scanned > 1000:
                    return {
                        "status": "limited",
                        "results": found,
                        "message": "Local image scan stopped at the 1000-file safety limit.",
                    }
                try:
                    content = file_path.read_bytes()
                    details = self._image_details(content)
                except (OSError, VisualAssetError):
                    continue
                relative = file_path.relative_to(root).as_posix()
                digest = hashlib.sha256(content).hexdigest()
                candidate_id = f"local:{digest[:20]}"
                candidate = VisualAssetCandidate(
                    candidate_id=candidate_id,
                    provider="local",
                    provider_asset_id=digest,
                    query="",
                    description=file_path.stem,
                    tags="",
                    source_url="",
                    image_url=relative,
                    preview_url=relative,
                    download_url="",
                    download_location="",
                    author="",
                    author_profile_url="",
                    license_name="Unknown; user confirmation required",
                    license_url="",
                    width=details["width"],
                    height=details["height"],
                    resource_type="local-image",
                    score=0.0,
                    score_factors={},
                    popularity=0,
                    local_path=relative,
                )
                self._candidates[candidate_id] = candidate
                found.append({
                    **candidate.public_data(),
                    "sha256": digest,
                    "rights_status": "unknown; confirm user-provided or authorized reuse",
                })
                if len(found) >= limit:
                    break
            if len(found) >= limit:
                break
        return {"status": "ok", "results": found, "scanned_files": scanned}

    def use_asset(
        self,
        candidate_id: str,
        workspace_root: str | os.PathLike[str],
        *,
        relative_path: str = "",
        placement: str = "",
        output_format: str = "original",
        reuse_authorized: bool = False,
    ) -> dict[str, Any]:
        candidate = self._candidates.get(candidate_id)
        if candidate is None:
            raise VisualAssetError("This asset was not returned by the current mission's search.")
        if not isinstance(output_format, str) or output_format not in {
            "original", "webp", "avif",
        }:
            raise VisualAssetError("Output format must be original, webp, or avif.")
        if not isinstance(reuse_authorized, bool):
            raise VisualAssetError("Reuse authorization must be a boolean.")
        root = workspace_tools._workspace_root(workspace_root)

        if candidate.provider == "local":
            if not reuse_authorized:
                raise VisualAssetError(
                    "Local image reuse requires explicit confirmation that the user provided "
                    "the image or has authorized its reuse."
                )
            return self._register_local(
                candidate, root, relative_path, placement, output_format
            )

        if candidate.provider == "unsplash":
            return self._use_unsplash(candidate, root, placement)

        if candidate.provider not in {"pixabay", "pexels"}:
            raise VisualAssetError("This provider cannot be saved as a local asset.")
        if not relative_path:
            raise VisualAssetError("A new project-relative image path is required.")
        content = self._download_provider_image(candidate)
        source_details = self._image_details(content)
        stored, details = self._format_image(content, source_details, output_format)
        target = self._resolve_new_file(root, relative_path, details["format"])
        digest = hashlib.sha256(stored).hexdigest()
        registry = self._read_registry(root)
        existing = next(
            (entry for entry in registry if entry.get("sha256") == digest), None
        )
        if existing:
            self._add_placement(existing, placement)
            self._write_registry(root, registry)
            return {
                "status": "deduplicated",
                "path": existing.get("file"),
                "image_url": existing.get("image_url"),
                "attribution": existing.get("attribution"),
                "registry": "assets/visual-assets.json",
                "sha256": digest,
            }

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with target.open("xb") as stream:
                stream.write(stored)
        except FileExistsError as exc:
            raise VisualAssetError("The destination already exists; no file was overwritten.") from exc
        entry = self._registry_entry(
            candidate,
            file=target.relative_to(root).as_posix(),
            image_url=target.relative_to(root).as_posix(),
            placement=placement,
            sha256=digest,
            details=details,
        )
        registry.append(entry)
        try:
            self._write_registry(root, registry)
        except Exception:
            target.unlink(missing_ok=True)
            raise
        return {
            "status": "saved",
            "path": entry["file"],
            "image_url": entry["image_url"],
            "attribution": entry["attribution"],
            "registry": "assets/visual-assets.json",
            "dimensions": {"width": details["width"], "height": details["height"]},
            "format": details["format"].lower(),
            "sha256": digest,
        }

    def verify_project(
        self,
        workspace_root: str | os.PathLike[str],
        *,
        check_external_urls: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(check_external_urls, bool):
            raise VisualAssetError("External URL verification must be a boolean.")
        root = workspace_tools._workspace_root(workspace_root)
        registry = self._read_registry(root, required=False)
        if not registry:
            return {
                "status": "FAIL",
                "checks": {
                    "presence": "FAIL",
                    "integrity": "NOT_TESTED",
                    "provenance": "NOT_TESTED",
                    "attribution": "NOT_TESTED",
                    "duplicates": "NOT_TESTED",
                    "placeholders": "NOT_TESTED",
                },
                "issues": ["No assets are registered in assets/visual-assets.json."],
                "visual_review": "NOT_TESTED",
            }

        issues: list[str] = []
        checks = {
            "presence": "PASS",
            "integrity": "PASS",
            "provenance": "PASS",
            "attribution": "PASS",
            "duplicates": "PASS",
            "placeholders": "PASS",
        }
        hashes: set[str] = set()
        entries_by_id: set[tuple[str, str]] = set()
        source_text = self._read_project_text(root)
        referenced_paths, missing_references = self._project_image_references(root, source_text)
        registered_paths: set[str] = set()

        for entry in registry:
            if not isinstance(entry, dict):
                checks["provenance"] = "FAIL"
                issues.append("Asset registry contains an invalid entry.")
                continue
            provider = entry.get("provider")
            provider_id = entry.get("provider_asset_id")
            key = (str(provider), str(provider_id))
            if not provider_id or key in entries_by_id:
                checks["duplicates"] = "FAIL"
                issues.append("Asset registry contains a missing or repeated provider ID.")
            entries_by_id.add(key)
            if not all(
                isinstance(entry.get(field), str) and entry[field].strip()
                for field in ("source_url", "license", "license_url", "attribution", "retrieved_at")
            ):
                checks["provenance"] = "FAIL"
                issues.append(f"Asset {provider_id or 'unknown'} is missing provenance metadata.")

            asset_url = entry.get("image_url", "")
            if provider == "unsplash":
                if not self._is_allowed_url(asset_url, {"images.unsplash.com"}):
                    checks["integrity"] = "FAIL"
                    issues.append(f"Unsplash asset {provider_id} has an invalid hotlink.")
                elif check_external_urls and not self._url_is_accessible(asset_url):
                    checks["integrity"] = "FAIL"
                    issues.append(f"Unsplash asset {provider_id} could not be reached.")
            else:
                relative = entry.get("file")
                if not isinstance(relative, str) or not relative:
                    checks["integrity"] = "FAIL"
                    issues.append(f"Asset {provider_id} has no local file.")
                    continue
                try:
                    target = workspace_tools._resolve_workspace_path(
                        relative, must_exist=True, workspace_root=root
                    )
                    content = target.read_bytes()
                    details = self._image_details(content)
                except (OSError, ValueError, workspace_tools.WorkspaceError, VisualAssetError):
                    checks["integrity"] = "FAIL"
                    issues.append(f"Asset file is missing or invalid: {relative}.")
                    continue
                registered_paths.add(target.relative_to(root).as_posix())
                digest = hashlib.sha256(content).hexdigest()
                if digest in hashes:
                    checks["duplicates"] = "FAIL"
                    issues.append(f"Duplicate image content detected: {relative}.")
                hashes.add(digest)
                if entry.get("sha256") != digest:
                    checks["integrity"] = "FAIL"
                    issues.append(f"Image hash changed since registration: {relative}.")
                if entry.get("width") != details["width"] or entry.get("height") != details["height"]:
                    checks["integrity"] = "FAIL"
                    issues.append(f"Image dimensions changed since registration: {relative}.")

            if not self._credit_present(entry, source_text):
                checks["attribution"] = "FAIL"
                issues.append(f"Visible image credit is missing for asset {provider_id}.")

        if missing_references:
            checks["integrity"] = "FAIL"
            issues.extend(
                f"Project image reference points to a missing local file: {item}."
                for item in missing_references
            )
        project_corpus = "\n".join(source_text.values()).casefold()
        for relative in registered_paths:
            normalized = relative.casefold()
            if normalized in project_corpus or f"/{normalized}" in project_corpus:
                referenced_paths.add(relative)
        unreferenced = registered_paths - referenced_paths
        if unreferenced:
            checks["presence"] = "FAIL"
            issues.extend(
                f"Registered image is not referenced by project files: {item}."
                for item in sorted(unreferenced)
            )
        if not registered_paths.intersection(referenced_paths) and not any(
            item.get("provider") == "unsplash"
            and isinstance(item.get("image_url"), str)
            and item.get("image_url").casefold() in project_corpus
            for item in registry if isinstance(item, dict)
        ):
            checks["presence"] = "FAIL"
            issues.append("Registered visual assets are not referenced by project files.")
        if _PLACEHOLDER_PATTERN.search(project_corpus):
            checks["placeholders"] = "FAIL"
            issues.append("A known placeholder image reference remains in project text.")

        status = "FAIL" if any(value == "FAIL" for value in checks.values()) else "PASS"
        return {
            "status": status,
            "checks": checks,
            "issues": issues,
            "registered_assets": len(registry),
            "local_image_references": len(referenced_paths),
            "visual_review": "NOT_TESTED: composition and semantic fit require visual review.",
            "optimization": self._optimization_summary(root, registry),
        }

    def _provider_key(self, provider: str) -> str:
        return str(self._environ.get(_PROVIDER_KEYS[provider], "")).strip()

    def _search_provider(
        self,
        provider: str,
        key: str,
        query: str,
        orientation: str,
        min_width: int,
        min_height: int,
        limit: int,
    ) -> list[VisualAssetCandidate]:
        cache_key = (provider, query.casefold(), orientation, min_width, min_height, limit)
        cached = self._cache.get(cache_key)
        now = self._clock()
        if cached and cached[0] > now:
            return cached[1]
        persistent_key = hashlib.sha256(
            json.dumps(cache_key, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        persisted = self._read_search_cache(provider, persistent_key, query)
        if persisted is not None:
            self._cache[cache_key] = (
                now + SEARCH_CACHE_TTLS[provider],
                persisted,
            )
            return persisted
        if self._request_count >= 12:
            raise VisualAssetError("The per-mission image search limit was reached.")
        self._request_count += 1
        try:
            if provider == "pixabay":
                raw_results = self._pixabay_search(
                    key, query, orientation, min_width, min_height, limit
                )
            elif provider == "unsplash":
                raw_results = self._unsplash_search(key, query, orientation, limit)
            else:
                raw_results = self._pexels_search(
                    key, query, orientation, min_width, min_height, limit
                )
        except VisualAssetError:
            raise
        except Exception as exc:
            raise VisualAssetError(f"{provider.title()} search failed.") from exc

        normalized = [
            candidate for candidate in raw_results
            if candidate.width >= min_width
            and candidate.height >= min_height
            and self._orientation_matches(candidate.width, candidate.height, orientation)
        ]
        ranked = [
            self._score(candidate, query, orientation, min_width, min_height)
            for candidate in normalized
        ]
        self._cache[cache_key] = (
            now + SEARCH_CACHE_TTLS[provider],
            ranked,
        )
        self._write_search_cache(provider, persistent_key, ranked)
        return ranked

    def _read_search_cache(
        self,
        provider: str,
        cache_key: str,
        query: str,
    ) -> list[VisualAssetCandidate] | None:
        path = self._cache_path
        if not path.exists():
            return None
        if path.is_symlink() or path.stat().st_size > MAX_SEARCH_CACHE_BYTES:
            raise VisualAssetError("The local visual search cache is unsafe or too large.")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisualAssetError("The local visual search cache is unreadable or invalid.") from exc
        if not isinstance(payload, dict) or payload.get("version") != 1:
            raise VisualAssetError("The local visual search cache has an invalid structure.")
        entries = payload.get("entries")
        if not isinstance(entries, list):
            raise VisualAssetError("The local visual search cache has an invalid structure.")
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("key") != cache_key:
                continue
            expires_at = entry.get("expires_at")
            raw_candidates = entry.get("candidates")
            if (
                isinstance(expires_at, bool)
                or not isinstance(expires_at, (int, float))
                or not isinstance(raw_candidates, list)
            ):
                raise VisualAssetError("A local visual search cache entry is invalid.")
            if expires_at <= time.time():
                return None
            candidates = []
            for raw in raw_candidates:
                if not isinstance(raw, dict):
                    raise VisualAssetError("A local visual search result is invalid.")
                try:
                    candidate = VisualAssetCandidate(**raw)
                except (TypeError, ValueError) as exc:
                    raise VisualAssetError("A local visual search result is invalid.") from exc
                if (
                    candidate.provider != provider
                    or not candidate.candidate_id.startswith(f"{provider}:")
                    or not self._candidate_urls_are_allowed(candidate)
                ):
                    raise VisualAssetError("A cached visual search result failed validation.")
                candidates.append(replace(candidate, query=query))
            return candidates
        return None

    def _write_search_cache(
        self,
        provider: str,
        cache_key: str,
        candidates: list[VisualAssetCandidate],
    ) -> None:
        path = self._cache_path
        entries: list[dict[str, Any]] = []
        if path.exists():
            if path.is_symlink() or path.stat().st_size > MAX_SEARCH_CACHE_BYTES:
                raise VisualAssetError("The local visual search cache is unsafe or too large.")
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VisualAssetError("The local visual search cache is unreadable or invalid.") from exc
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise VisualAssetError("The local visual search cache has an invalid structure.")
            existing = payload.get("entries")
            if not isinstance(existing, list):
                raise VisualAssetError("The local visual search cache has an invalid structure.")
            now = time.time()
            entries = [
                entry for entry in existing
                if isinstance(entry, dict)
                and isinstance(entry.get("expires_at"), (int, float))
                and entry["expires_at"] > now
                and entry.get("key") != cache_key
            ]
        cached_candidates = []
        for candidate in candidates:
            value = asdict(candidate)
            value["query"] = ""
            cached_candidates.append(value)
        entries.append({
            "key": cache_key,
            "expires_at": time.time() + SEARCH_CACHE_TTLS[provider],
            "candidates": cached_candidates,
        })
        payload = json.dumps(
            {"version": 1, "entries": entries[-MAX_SEARCH_CACHE_ENTRIES:]},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > MAX_SEARCH_CACHE_BYTES:
            raise VisualAssetError("The local visual search cache exceeds its size limit.")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=path.parent,
                prefix=".visual-search-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        except OSError as exc:
            raise VisualAssetError("The local visual search cache could not be written.") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _candidate_urls_are_allowed(self, candidate: VisualAssetCandidate) -> bool:
        if candidate.provider == "pixabay":
            return (
                self._is_allowed_url(candidate.source_url, {"pixabay.com"})
                and self._is_allowed_url(candidate.image_url, _PROVIDER_HOSTS["pixabay"])
                and self._is_allowed_url(candidate.download_url, _PROVIDER_HOSTS["pixabay"])
            )
        if candidate.provider == "unsplash":
            return (
                self._is_allowed_url(candidate.source_url, {"unsplash.com"})
                and self._is_allowed_url(candidate.image_url, {"images.unsplash.com"})
                and self._is_allowed_url(candidate.download_location, {"api.unsplash.com"})
            )
        if candidate.provider == "pexels":
            return (
                self._is_allowed_url(candidate.source_url, {"pexels.com", "www.pexels.com"})
                and self._is_allowed_url(candidate.image_url, {"images.pexels.com"})
                and self._is_allowed_url(candidate.download_url, {"images.pexels.com"})
            )
        return False

    def _pixabay_search(
        self, key: str, query: str, orientation: str,
        min_width: int, min_height: int, limit: int,
    ) -> list[VisualAssetCandidate]:
        params = {
            "key": key,
            "q": query,
            "lang": "en",
            "image_type": "all",
            "orientation": (
                "horizontal" if orientation == "landscape"
                else "vertical" if orientation == "portrait"
                else "all"
            ),
            "min_width": min_width,
            "min_height": min_height,
            "safesearch": "true",
            "per_page": min(20, limit * 2),
        }
        payload = self._request_json(
            "pixabay", "https://pixabay.com/api/", params=params
        )
        hits = payload.get("hits", []) if isinstance(payload, dict) else []
        if not isinstance(hits, list):
            raise VisualAssetError("Pixabay returned an invalid image list.")
        results = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            asset_id = hit.get("id")
            width, height = hit.get("imageWidth"), hit.get("imageHeight")
            if (
                not isinstance(asset_id, int)
                or not self._valid_dimension(width)
                or not self._valid_dimension(height)
                or width < 1
                or height < 1
            ):
                continue
            user = str(hit.get("user", ""))
            user_id = hit.get("user_id")
            profile = (
                f"https://pixabay.com/users/{quote(user, safe='')}-{user_id}/"
                if user and isinstance(user_id, int) else "https://pixabay.com/"
            )
            download_url = hit.get("largeImageURL") or hit.get("webformatURL")
            preview = hit.get("previewURL") or hit.get("webformatURL")
            source = hit.get("pageURL")
            if not self._is_allowed_url(source, {"pixabay.com"}):
                continue
            if not self._is_allowed_url(download_url, _PROVIDER_HOSTS["pixabay"]):
                continue
            if not self._is_allowed_url(preview, _PROVIDER_HOSTS["pixabay"]):
                preview = download_url
            results.append(VisualAssetCandidate(
                candidate_id=f"pixabay:{asset_id}",
                provider="pixabay",
                provider_asset_id=str(asset_id),
                query=query,
                description=str(hit.get("tags", "")),
                tags=str(hit.get("tags", "")),
                source_url=source,
                image_url=str(download_url),
                preview_url=str(preview),
                download_url=str(download_url),
                download_location="",
                author=user or "Pixabay contributor",
                author_profile_url=profile,
                license_name=_LICENSES["pixabay"][0],
                license_url=_LICENSES["pixabay"][1],
                width=width,
                height=height,
                resource_type=str(hit.get("type", "photo")),
                score=0.0,
                score_factors={},
                popularity=self._bounded_count(hit.get("downloads")),
            ))
        return results

    def _unsplash_search(
        self, key: str, query: str, orientation: str, limit: int,
    ) -> list[VisualAssetCandidate]:
        params: dict[str, Any] = {"query": query, "per_page": min(30, limit * 2)}
        if orientation in {"landscape", "portrait"}:
            params["orientation"] = orientation
        elif orientation == "square":
            params["orientation"] = "squarish"
        payload = self._request_json(
            "unsplash",
            "https://api.unsplash.com/search/photos",
            params=params,
            headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
        )
        hits = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(hits, list):
            raise VisualAssetError("Unsplash returned an invalid image list.")
        results = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            asset_id = hit.get("id")
            width, height = hit.get("width"), hit.get("height")
            urls, links = hit.get("urls"), hit.get("links")
            user = hit.get("user")
            if (
                not isinstance(asset_id, str)
                or not self._valid_dimension(width)
                or not self._valid_dimension(height)
                or width < 1
                or height < 1
                or not isinstance(urls, dict)
                or not isinstance(links, dict)
                or not isinstance(user, dict)
            ):
                continue
            image_url = urls.get("regular") or urls.get("raw")
            source = links.get("html")
            download_location = links.get("download_location")
            if not self._is_allowed_url(image_url, {"images.unsplash.com"}):
                continue
            if not self._is_allowed_url(source, {"unsplash.com"}):
                continue
            if not self._is_allowed_url(download_location, {"api.unsplash.com"}):
                continue
            author = str(user.get("name", "Unsplash contributor"))
            profile = user.get("links", {}).get("html") if isinstance(user.get("links"), dict) else None
            if not self._is_allowed_url(profile, {"unsplash.com"}):
                profile = "https://unsplash.com/"
            results.append(VisualAssetCandidate(
                candidate_id=f"unsplash:{asset_id}",
                provider="unsplash",
                provider_asset_id=asset_id,
                query=query,
                description=str(hit.get("alt_description") or hit.get("description") or ""),
                tags=" ".join(
                    str(item.get("title", ""))
                    for item in hit.get("tags", [])
                    if isinstance(item, dict)
                ),
                source_url=self._with_unsplash_utm(str(source)),
                image_url=str(image_url),
                preview_url=str(urls.get("small") or image_url),
                download_url="",
                download_location=str(download_location),
                author=author,
                author_profile_url=self._with_unsplash_utm(str(profile)),
                license_name=_LICENSES["unsplash"][0],
                license_url=_LICENSES["unsplash"][1],
                width=width,
                height=height,
                resource_type="photo",
                score=0.0,
                score_factors={},
                popularity=self._bounded_count(hit.get("likes")),
            ))
        return results

    def _pexels_search(
        self, key: str, query: str, orientation: str,
        min_width: int, min_height: int, limit: int,
    ) -> list[VisualAssetCandidate]:
        params: dict[str, Any] = {
            "query": query,
            "per_page": min(80, limit * 2),
        }
        if orientation in {"landscape", "portrait", "square"}:
            params["orientation"] = orientation
        if min_width and min_height:
            params["size"] = "large" if min_width >= 2000 or min_height >= 1200 else "medium"
        payload = self._request_json(
            "pexels",
            "https://api.pexels.com/v1/search",
            params=params,
            headers={"Authorization": key},
        )
        hits = payload.get("photos", []) if isinstance(payload, dict) else []
        if not isinstance(hits, list):
            raise VisualAssetError("Pexels returned an invalid image list.")
        results = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            asset_id = hit.get("id")
            width, height = hit.get("width"), hit.get("height")
            src = hit.get("src")
            if (
                not isinstance(asset_id, int)
                or not self._valid_dimension(width)
                or not self._valid_dimension(height)
                or width < 1
                or height < 1
                or not isinstance(src, dict)
            ):
                continue
            download_url = src.get("large2x") or src.get("original")
            preview = src.get("medium") or src.get("small")
            source = hit.get("url")
            profile = hit.get("photographer_url")
            if not self._is_allowed_url(download_url, {"images.pexels.com"}):
                continue
            if not self._is_allowed_url(source, {"pexels.com", "www.pexels.com"}):
                continue
            if not self._is_allowed_url(profile, {"pexels.com", "www.pexels.com"}):
                profile = "https://www.pexels.com/"
            results.append(VisualAssetCandidate(
                candidate_id=f"pexels:{asset_id}",
                provider="pexels",
                provider_asset_id=str(asset_id),
                query=query,
                description=str(hit.get("alt", "")),
                tags=str(hit.get("alt", "")),
                source_url=str(source),
                image_url=str(download_url),
                preview_url=str(preview if self._is_allowed_url(preview, {"images.pexels.com"}) else download_url),
                download_url=str(download_url),
                download_location="",
                author=str(hit.get("photographer", "Pexels contributor")),
                author_profile_url=str(profile),
                license_name=_LICENSES["pexels"][0],
                license_url=_LICENSES["pexels"][1],
                width=width,
                height=height,
                resource_type="photo",
                score=0.0,
                score_factors={},
                popularity=0,
            ))
        return results

    def _request_json(
        self,
        provider: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any:
        if not self._is_allowed_url(url, _PROVIDER_HOSTS[provider]):
            raise VisualAssetError(f"{provider.title()} API endpoint is not allowed.")
        try:
            response = self._http_get(
                url,
                params=params,
                headers={"User-Agent": "NIANG-IA-Visual-Assets/1.0", **(headers or {})},
                timeout=(5, 15),
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise VisualAssetError(f"{provider.title()} request failed.") from exc
        try:
            if response.status_code == 429:
                raise VisualAssetError(f"{provider.title()} quota is exhausted; retry later.")
            if response.status_code < 200 or response.status_code >= 300:
                raise VisualAssetError(
                    f"{provider.title()} returned HTTP {response.status_code}."
                )
            body = response.content
            if not isinstance(body, bytes) or len(body) > 5_000_000:
                raise VisualAssetError(f"{provider.title()} response exceeded the size limit.")
            try:
                return json.loads(body.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise VisualAssetError(f"{provider.title()} returned invalid JSON.") from exc
        finally:
            response.close()

    def _download_provider_image(self, candidate: VisualAssetCandidate) -> bytes:
        allowed = _PROVIDER_HOSTS[candidate.provider] - {
            "api.unsplash.com", "api.pexels.com",
        }
        current_url = candidate.download_url
        for _ in range(4):
            if not self._is_allowed_url(current_url, allowed):
                raise VisualAssetError("Image download URL is outside the provider allow-list.")
            try:
                response = self._http_get(
                    current_url,
                    headers={"User-Agent": "NIANG-IA-Visual-Assets/1.0"},
                    timeout=(5, 25),
                    allow_redirects=False,
                    stream=True,
                )
            except requests.RequestException as exc:
                raise VisualAssetError("The selected provider image could not be downloaded.") from exc
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location", "")
                    next_url = requests.compat.urljoin(current_url, location)
                    if not self._is_allowed_url(next_url, allowed):
                        raise VisualAssetError("Image download redirected outside the provider allow-list.")
                    current_url = next_url
                    continue
                if response.status_code < 200 or response.status_code >= 300:
                    raise VisualAssetError(
                        f"Image download returned HTTP {response.status_code}."
                    )
                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if not content_type.startswith("image/"):
                    raise VisualAssetError("Provider response is not an image.")
                chunks = []
                total = 0
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > MAX_IMAGE_BYTES:
                        raise VisualAssetError("Image download exceeds the 20 MB limit.")
                    chunks.append(chunk)
                content = b"".join(chunks)
                self._image_details(content)
                return content
            finally:
                response.close()
        raise VisualAssetError("Image download exceeded the redirect limit.")

    def _use_unsplash(
        self,
        candidate: VisualAssetCandidate,
        root: Path,
        placement: str,
    ) -> dict[str, Any]:
        key = self._provider_key("unsplash")
        if not key:
            raise VisualAssetError("Unsplash credentials are not configured.")
        if not placement or len(placement) > 300:
            raise VisualAssetError("An intended project placement is required for Unsplash.")
        if not self._is_allowed_url(candidate.download_location, {"api.unsplash.com"}):
            raise VisualAssetError("Unsplash download tracking URL is invalid.")
        self._request_json(
            "unsplash",
            candidate.download_location,
            headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
        )
        registry = self._read_registry(root)
        entry = self._registry_entry(
            candidate,
            file="",
            image_url=candidate.image_url,
            placement=placement,
            sha256="",
            details={"width": candidate.width, "height": candidate.height, "format": "REMOTE"},
        )
        self._merge_entry(registry, entry)
        self._write_registry(root, registry)
        return {
            "status": "registered_hotlink",
            "provider": "unsplash",
            "image_url": candidate.image_url,
            "source_url": candidate.source_url,
            "author": candidate.author,
            "author_profile_url": candidate.author_profile_url,
            "attribution": entry["attribution"],
            "registry": "assets/visual-assets.json",
            "placement": placement,
            "hotlink_required": True,
            "download_event_recorded": True,
        }

    def _register_local(
        self,
        candidate: VisualAssetCandidate,
        root: Path,
        relative_path: str,
        placement: str,
        output_format: str,
    ) -> dict[str, Any]:
        target = workspace_tools._resolve_workspace_path(
            candidate.local_path, must_exist=True, workspace_root=root
        )
        content = target.read_bytes()
        details = self._image_details(content)
        if output_format != "original":
            if not relative_path:
                raise VisualAssetError("A new destination is required for an optimized copy.")
            stored, optimized = self._format_image(content, details, output_format)
            output = self._resolve_new_file(root, relative_path, optimized["format"])
            output.parent.mkdir(parents=True, exist_ok=True)
            try:
                with output.open("xb") as stream:
                    stream.write(stored)
            except FileExistsError as exc:
                raise VisualAssetError("The destination already exists; no file was overwritten.") from exc
            target = output
            details = optimized
            content = stored
        if not placement or len(placement) > 300:
            raise VisualAssetError("A project placement or purpose is required.")
        digest = hashlib.sha256(content).hexdigest()
        entry = {
            "provider": "local",
            "provider_asset_id": candidate.provider_asset_id,
            "query": "",
            "file": target.relative_to(root).as_posix(),
            "image_url": target.relative_to(root).as_posix(),
            "source_url": "user-provided-or-project-local",
            "author": "User-provided or project-local",
            "author_profile_url": "",
            "license": "User-provided/project-local; reuse authorized by user",
            "license_url": "",
            "attribution": "No external attribution metadata was supplied.",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "width": details["width"],
            "height": details["height"],
            "format": details["format"].lower(),
            "resource_type": "local-image",
            "sha256": digest,
            "placements": [placement],
            "rights_review": "user-confirmed",
        }
        registry = self._read_registry(root)
        self._merge_entry(registry, entry)
        self._write_registry(root, registry)
        return {
            "status": "registered",
            "path": entry["file"],
            "sha256": digest,
            "registry": "assets/visual-assets.json",
        }

    def _registry_entry(
        self,
        candidate: VisualAssetCandidate,
        *,
        file: str,
        image_url: str,
        placement: str,
        sha256: str,
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        return {
            "provider": candidate.provider,
            "provider_asset_id": candidate.provider_asset_id,
            "query": candidate.query,
            "file": file,
            "image_url": image_url,
            "source_url": candidate.source_url,
            "author": candidate.author,
            "author_profile_url": candidate.author_profile_url,
            "license": candidate.license_name,
            "license_url": candidate.license_url,
            "attribution": f"Photo by {candidate.author} on {candidate.provider.title()}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "width": details["width"],
            "height": details["height"],
            "format": str(details["format"]).lower(),
            "resource_type": candidate.resource_type,
            "sha256": sha256,
            "placements": [placement] if placement else [],
            "score": candidate.score,
            "rights_review": "provider terms recorded; review model/property rights where relevant",
        }

    def _read_registry(
        self,
        root: Path,
        *,
        required: bool = True,
    ) -> list[dict[str, Any]]:
        path = workspace_tools._resolve_workspace_path(
            "assets/visual-assets.json", workspace_root=root
        )
        if not path.exists():
            if required:
                return []
            return []
        if path.is_symlink() or path.stat().st_size > MAX_REGISTRY_BYTES:
            raise VisualAssetError("The visual asset registry is unsafe or too large.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VisualAssetError("The visual asset registry is unreadable or invalid.") from exc
        if not isinstance(data, dict) or not isinstance(data.get("assets"), list):
            raise VisualAssetError("The visual asset registry has an invalid structure.")
        if not all(isinstance(item, dict) for item in data["assets"]):
            raise VisualAssetError("The visual asset registry contains an invalid entry.")
        return data["assets"]

    def _write_registry(self, root: Path, entries: list[dict[str, Any]]) -> None:
        directory = workspace_tools._resolve_workspace_path(
            "assets", workspace_root=root
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = workspace_tools._resolve_workspace_path(
            "assets/visual-assets.json", workspace_root=root
        )
        payload = json.dumps(
            {"version": 1, "assets": entries},
            ensure_ascii=False,
            indent=2,
        ) + "\n"
        if len(payload.encode("utf-8")) > MAX_REGISTRY_BYTES:
            raise VisualAssetError("The visual asset registry exceeds its size limit.")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=directory,
                prefix=".visual-assets-",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary_path = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_path, path)
            temporary_path = None
        except OSError as exc:
            raise VisualAssetError("The visual asset registry could not be written.") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _merge_entry(self, entries: list[dict[str, Any]], new_entry: dict[str, Any]) -> None:
        for existing in entries:
            if (
                existing.get("provider") == new_entry.get("provider")
                and existing.get("provider_asset_id") == new_entry.get("provider_asset_id")
            ):
                placements = existing.setdefault("placements", [])
                for placement in new_entry.get("placements", []):
                    if placement and placement not in placements:
                        placements.append(placement)
                return
        entries.append(new_entry)

    @staticmethod
    def _add_placement(entry: dict[str, Any], placement: str) -> None:
        if placement:
            placements = entry.setdefault("placements", [])
            if placement not in placements:
                placements.append(placement)

    def _read_project_text(self, root: Path) -> dict[str, str]:
        result: dict[str, str] = {}
        count = 0
        for current, directories, filenames in os.walk(root, followlinks=False):
            current_path = Path(current)
            directories[:] = [
                name for name in directories
                if not name.startswith(".") and name.lower() not in _IGNORED_DIRECTORIES
                and not (current_path / name).is_symlink()
            ]
            for filename in filenames:
                path = current_path / filename
                if path.suffix.lower() not in _TEXT_SUFFIXES or path.is_symlink():
                    continue
                count += 1
                if count > 2000:
                    return result
                try:
                    if path.stat().st_size > 2_000_000:
                        continue
                    result[path.relative_to(root).as_posix()] = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    continue
        return result

    def _project_image_references(
        self,
        root: Path,
        project_text: Mapping[str, str],
    ) -> tuple[set[str], list[str]]:
        references: set[str] = set()
        missing: list[str] = []
        for source_path, text in project_text.items():
            for match in _IMAGE_REFERENCE_PATTERN.finditer(text):
                raw = (match.group(1) or match.group(2) or "").strip()
                raw = unquote(html.unescape(raw.split("?", 1)[0].split("#", 1)[0]))
                if not raw or raw.startswith(("data:", "blob:", "//", "http:", "https:")):
                    continue
                if Path(raw).suffix.lower() not in _IMAGE_SUFFIXES:
                    continue
                source_file = root / source_path
                candidate = Path(raw)
                if candidate.is_absolute() or re.match(r"^[A-Za-z]:", raw):
                    missing.append(raw)
                    continue
                if raw.startswith("/"):
                    candidate = root / raw.lstrip("/")
                else:
                    candidate = source_file.parent / candidate
                try:
                    resolved = candidate.resolve(strict=True)
                    relative = resolved.relative_to(root).as_posix()
                    safe = workspace_tools._resolve_workspace_path(
                        relative, must_exist=True, workspace_root=root
                    )
                    if safe.is_file():
                        references.add(safe.relative_to(root).as_posix())
                except (OSError, ValueError, workspace_tools.WorkspaceError):
                    missing.append(raw)
        return references, missing

    def _credit_present(
        self,
        entry: Mapping[str, Any],
        project_text: Mapping[str, str],
    ) -> bool:
        provider = str(entry.get("provider", "")).casefold()
        author = str(entry.get("author", "")).strip().casefold()
        source_url = str(entry.get("source_url", "")).strip().casefold()
        author_profile_url = str(entry.get("author_profile_url", "")).strip().casefold()
        corpus = "\n".join(project_text.values()).casefold()
        if provider == "local":
            return True
        return bool(
            provider in corpus
            and author in corpus
            and (source_url in corpus or author_profile_url in corpus)
        )

    def _optimization_summary(
        self,
        root: Path,
        entries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        large: list[str] = []
        for entry in entries:
            relative = entry.get("file")
            if not isinstance(relative, str) or not relative:
                continue
            try:
                path = workspace_tools._resolve_workspace_path(
                    relative, must_exist=True, workspace_root=root
                )
                if path.stat().st_size > 2 * 1024 * 1024:
                    large.append(relative)
            except (OSError, ValueError, workspace_tools.WorkspaceError):
                continue
        return {
            "status": "FAIL" if large else "PASS",
            "large_files_over_2mb": large,
            "note": "Responsive markup and visual composition require separate review.",
        }

    def _score(
        self,
        candidate: VisualAssetCandidate,
        query: str,
        orientation: str,
        min_width: int,
        min_height: int,
    ) -> VisualAssetCandidate:
        query_tokens = set(self._tokens(query))
        content_tokens = set(self._tokens(candidate.description + " " + candidate.tags))
        text_match = len(query_tokens.intersection(content_tokens)) / max(1, len(query_tokens))
        width_score = min(1.0, candidate.width / max(1, min_width)) if min_width else 1.0
        height_score = min(1.0, candidate.height / max(1, min_height)) if min_height else 1.0
        resolution = min(width_score, height_score)
        orientation_score = (
            1.0 if self._orientation_matches(candidate.width, candidate.height, orientation) else 0.0
        )
        score = 0.60 * text_match + 0.30 * resolution + 0.10 * orientation_score
        factors = {
            "text_match": round(text_match, 4),
            "resolution": round(resolution, 4),
            "orientation": round(orientation_score, 4),
        }
        return VisualAssetCandidate(
            **{
                **asdict(candidate),
                "score": round(score, 4),
                "score_factors": factors,
            }
        )

    @staticmethod
    def _tokens(value: str) -> list[str]:
        normalized = unicodedata.normalize("NFKD", value.casefold())
        plain = "".join(char for char in normalized if not unicodedata.combining(char))
        return [token for token in _TOKEN_PATTERN.findall(plain) if len(token) > 2]

    @staticmethod
    def _orientation_matches(width: int, height: int, orientation: str) -> bool:
        if orientation == "landscape":
            return width >= height
        if orientation == "portrait":
            return height >= width
        if orientation == "square":
            return 0.9 <= width / max(1, height) <= 1.1
        return True

    @staticmethod
    def _valid_dimension(value: Any) -> bool:
        return (
            isinstance(value, int)
            and not isinstance(value, bool)
            and 0 <= value <= 16000
        )

    @staticmethod
    def _bounded_count(value: Any) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    @staticmethod
    def _validate_query(query: str) -> str:
        if not isinstance(query, str):
            raise VisualAssetError("Image search query must be text.")
        query = " ".join(query.split())
        if not query or len(query) > MAX_QUERY_LENGTH:
            raise VisualAssetError(
                f"Image search query must contain 1 to {MAX_QUERY_LENGTH} characters."
            )
        if detect_sensitive_data(query):
            raise VisualAssetError("Image search queries must not contain sensitive information.")
        if any(ord(char) < 32 for char in query):
            raise VisualAssetError("Image search query contains control characters.")
        return query

    @staticmethod
    def _is_allowed_url(url: Any, allowed_hosts: set[str]) -> bool:
        if not isinstance(url, str):
            return False
        try:
            parsed = urlsplit(url)
            return (
                parsed.scheme == "https"
                and parsed.hostname in allowed_hosts
                and parsed.username is None
                and parsed.password is None
                and parsed.port in (None, 443)
                and not parsed.fragment
            )
        except ValueError:
            return False

    @staticmethod
    def _with_unsplash_utm(url: str) -> str:
        separator = "&" if "?" in url else "?"
        return f"{url}{separator}utm_source=niang_ia&utm_medium=referral"

    @staticmethod
    def _image_details(content: bytes) -> dict[str, Any]:
        if not isinstance(content, bytes) or not content or len(content) > MAX_IMAGE_BYTES:
            raise VisualAssetError("Image is empty or exceeds the 20 MB limit.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(content)) as image:
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    image_format = image.format
                    width, height = image.size
        except (
            UnidentifiedImageError,
            OSError,
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
        ) as exc:
            raise VisualAssetError("Provider content is not a safe, decodable image.") from exc
        if image_format not in _IMAGE_FORMATS or width < 1 or height < 1:
            raise VisualAssetError("Image format or dimensions are unsupported.")
        if width * height > MAX_IMAGE_PIXELS:
            raise VisualAssetError("Image dimensions exceed the safe pixel limit.")
        return {"format": image_format, "width": width, "height": height}

    @classmethod
    def _format_image(
        cls,
        content: bytes,
        details: Mapping[str, Any],
        output_format: str,
    ) -> tuple[bytes, dict[str, Any]]:
        if output_format == "original":
            return content, dict(details)
        image_format = "WEBP" if output_format == "webp" else "AVIF"
        extensions = Image.registered_extensions()
        if f".{output_format}" not in extensions:
            raise VisualAssetError(f"This Pillow build cannot encode {output_format.upper()}.")
        try:
            with Image.open(io.BytesIO(content)) as image:
                converted = image.copy()
                if image_format == "WEBP" and converted.mode not in {"RGB", "RGBA"}:
                    converted = converted.convert("RGBA" if "A" in converted.getbands() else "RGB")
                if image_format == "AVIF" and converted.mode not in {"RGB", "RGBA"}:
                    converted = converted.convert("RGBA" if "A" in converted.getbands() else "RGB")
                output = io.BytesIO()
                options = {"quality": 84, "method": 6} if image_format == "WEBP" else {"quality": 80}
                if image_format == "WEBP" and converted.mode == "RGBA":
                    options["lossless"] = True
                converted.save(output, format=image_format, **options)
                data = output.getvalue()
        except (OSError, ValueError) as exc:
            raise VisualAssetError(f"Image optimization to {image_format} failed.") from exc
        if len(data) > MAX_IMAGE_BYTES:
            raise VisualAssetError("Optimized image exceeds the 20 MB limit.")
        optimized_details = cls._image_details(data)
        return data, optimized_details

    def _resolve_new_file(
        self,
        root: Path,
        relative_path: str,
        image_format: str,
    ) -> Path:
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or len(relative_path) > 300
            or Path(relative_path).is_absolute()
        ):
            raise VisualAssetError("Asset destination must be a relative project path.")
        target = workspace_tools._resolve_workspace_path(
            relative_path, workspace_root=root
        )
        expected_suffix = {
            "JPEG": {".jpg", ".jpeg"},
            "PNG": {".png"},
            "WEBP": {".webp"},
            "AVIF": {".avif"},
            "GIF": {".gif"},
        }.get(image_format)
        if expected_suffix is None or target.suffix.lower() not in expected_suffix:
            raise VisualAssetError(
                f"Asset destination extension must match the verified {image_format} format."
            )
        if target.exists() or target.is_symlink():
            raise VisualAssetError("Asset destination already exists or is a link.")
        return target

    def _url_is_accessible(self, url: str) -> bool:
        if not self._is_allowed_url(url, {"images.unsplash.com"}):
            return False
        try:
            response = self._http_get(
                url,
                headers={"User-Agent": "NIANG-IA-Visual-Assets/1.0"},
                timeout=(5, 10),
                allow_redirects=False,
                stream=True,
            )
        except requests.RequestException:
            return False
        try:
            return (
                response.status_code == 200
                and response.headers.get("Content-Type", "").lower().startswith("image/")
            )
        finally:
            response.close()
