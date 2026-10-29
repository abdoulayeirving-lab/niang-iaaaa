"""Check and securely download official NIANG IA Windows releases."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

import requests


OWNER = "abdoulayeirving-lab"
REPOSITORY = "niang-iaaaa"
MAX_INSTALLER_BYTES = 200 * 1024 * 1024
REQUEST_TIMEOUT = (15, 60)
API_URL = f"https://api.github.com/repos/{OWNER}/{REPOSITORY}/releases/latest"
_VERSION_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")
_SHA256_RE = re.compile(r"^sha256:([0-9a-fA-F]{64})$")
_DOWNLOAD_HOSTS = {
    "github.com",
    "release-assets.githubusercontent.com",
    "objects.githubusercontent.com",
}


def _read_current_version() -> str:
    version_path = Path(__file__).resolve().parent / "VERSION.txt"
    version = version_path.read_text(encoding="ascii").strip()
    if not _VERSION_RE.fullmatch(version):
        raise RuntimeError(f"Version locale invalide dans {version_path}.")
    return version


CURRENT_VERSION = _read_current_version()


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    download_url: str
    size: int
    sha256: str
    release_url: str


def _parse_version(version: str) -> tuple[int, int, int]:
    match = _VERSION_RE.fullmatch(version)
    if not match:
        raise ValueError(f"Version NIANG IA invalide : {version!r}.")
    return tuple(int(part) for part in match.groups())


def _validate_download_url(url: str, tag: str, filename: str) -> str:
    parsed = urlsplit(url)
    expected_path = (
        f"/{OWNER}/{REPOSITORY}/releases/download/{tag}/{filename}"
    )
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.port not in (None, 443)
        or unquote(parsed.path) != expected_path
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("GitHub a fourni un lien d'installateur inattendu.")
    return url


def check_for_update(current_version: str = CURRENT_VERSION) -> UpdateInfo | None:
    """Return verified metadata for a newer stable installer, if available."""
    current = _parse_version(current_version)
    response = requests.get(
        API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "NIANG-IA-Updater",
        },
        timeout=REQUEST_TIMEOUT,
        allow_redirects=False,
    )
    try:
        response.raise_for_status()
        release = response.json()
    finally:
        response.close()

    if release.get("draft") or release.get("prerelease"):
        raise RuntimeError("La dernière publication GitHub n'est pas une version stable.")
    tag = release.get("tag_name")
    version_match = _VERSION_RE.fullmatch(tag or "")
    if not version_match:
        raise RuntimeError("Le tag de la dernière version GitHub est invalide.")
    version = ".".join(version_match.groups())
    if tuple(int(part) for part in version_match.groups()) <= current:
        return None

    filename = f"NIANG_IA_Setup_{version}.exe"
    asset = next(
        (
            item for item in release.get("assets", [])
            if item.get("name") == filename
        ),
        None,
    )
    if asset is None or asset.get("state") != "uploaded":
        raise RuntimeError(f"L'installateur {filename} n'est pas disponible dans la Release.")

    size = asset.get("size")
    if not isinstance(size, int) or not 0 < size <= MAX_INSTALLER_BYTES:
        raise RuntimeError("La taille de l'installateur GitHub est invalide ou trop élevée.")
    digest_match = _SHA256_RE.fullmatch(asset.get("digest") or "")
    if digest_match is None:
        raise RuntimeError("GitHub n'a pas fourni l'empreinte SHA-256 de l'installateur.")
    download_url = _validate_download_url(
        asset.get("browser_download_url", ""), tag, filename,
    )
    release_url = release.get("html_url", "")
    release_parts = urlsplit(release_url)
    if (
        release_parts.scheme != "https"
        or release_parts.hostname != "github.com"
        or release_parts.path != f"/{OWNER}/{REPOSITORY}/releases/tag/{tag}"
        or release_parts.query
        or release_parts.fragment
    ):
        raise RuntimeError("L'adresse de la Release GitHub est invalide.")

    return UpdateInfo(
        version=version,
        tag=tag,
        download_url=download_url,
        size=size,
        sha256=digest_match.group(1).lower(),
        release_url=release_url,
    )


def _downloads_directory() -> Path:
    return Path.home() / "Downloads"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _new_download_path(directory: Path, filename: str, sha256: str) -> Path:
    candidate = directory / filename
    if not candidate.exists():
        return candidate
    try:
        digest = _sha256_file(candidate)
    except OSError:
        digest = ""
    if digest == sha256:
        return candidate

    stem, suffix = candidate.stem, candidate.suffix
    for index in range(1, 1000):
        candidate = directory / f"{stem} ({index}){suffix}"
        if not candidate.exists():
            return candidate
        try:
            digest = _sha256_file(candidate)
        except OSError:
            digest = ""
        if digest == sha256:
            return candidate
    raise RuntimeError("Impossible de trouver un nom libre pour l'installateur téléchargé.")


def download_update(
    update: UpdateInfo,
    progress=None,
    download_directory: Path | None = None,
) -> Path:
    """Download an installer to Downloads and verify its size and SHA-256."""
    directory = Path(download_directory) if download_directory else _downloads_directory()
    directory.mkdir(parents=True, exist_ok=True)
    filename = f"NIANG_IA_Setup_{update.version}.exe"
    destination = _new_download_path(directory, filename, update.sha256)
    if destination.exists():
        return destination

    response = requests.get(
        update.download_url,
        headers={"User-Agent": "NIANG-IA-Updater"},
        timeout=REQUEST_TIMEOUT,
        stream=True,
        allow_redirects=True,
    )
    temporary_path = None
    try:
        response.raise_for_status()
        for redirect in [*response.history, response]:
            redirected_url = urlsplit(redirect.url)
            if (
                redirected_url.scheme != "https"
                or redirected_url.hostname not in _DOWNLOAD_HOSTS
                or redirected_url.username
                or redirected_url.password
            ):
                raise RuntimeError("Téléchargement refusé : redirection GitHub non sécurisée.")

        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{filename}.",
            suffix=".download",
            dir=directory,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            digest = hashlib.sha256()
            downloaded = 0
            if progress:
                progress(0)
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > update.size or downloaded > MAX_INSTALLER_BYTES:
                    raise RuntimeError("L'installateur téléchargé dépasse la taille annoncée.")
                temporary.write(chunk)
                digest.update(chunk)
                if progress:
                    progress(min(downloaded * 100 // update.size, 100))
            temporary.flush()
            os.fsync(temporary.fileno())

        if downloaded != update.size:
            raise RuntimeError(
                f"Téléchargement incomplet : {downloaded:,} octets reçus "
                f"sur {update.size:,}."
            )
        if digest.hexdigest() != update.sha256:
            raise RuntimeError("L'empreinte SHA-256 ne correspond pas à la Release GitHub.")
        destination = _new_download_path(directory, filename, update.sha256)
        os.link(temporary_path, destination)
        temporary_path.unlink()
        temporary_path = None
        if progress:
            progress(100)
        return destination
    finally:
        response.close()
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
