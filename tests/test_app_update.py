import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_update


class FakeResponse:
    def __init__(self, *, payload=None, chunks=(), url=None, history=()):
        self.payload = payload
        self.chunks = chunks
        self.url = url or app_update.API_URL
        self.history = list(history)
        self.closed = False

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        yield from self.chunks

    def close(self):
        self.closed = True


def release_payload(version="1.0.15", *, digest=None, download_url=None):
    tag = f"v{version}"
    filename = f"NIANG_IA_Setup_{version}.exe"
    return {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "html_url": f"https://github.com/{app_update.OWNER}/{app_update.REPOSITORY}/releases/tag/{tag}",
        "assets": [{
            "name": filename,
            "state": "uploaded",
            "size": len(b"installer"),
            "digest": digest or f"sha256:{hashlib.sha256(b'installer').hexdigest()}",
            "browser_download_url": download_url or (
                f"https://github.com/{app_update.OWNER}/{app_update.REPOSITORY}"
                f"/releases/download/{tag}/{filename}"
            ),
        }],
    }


class UpdateCheckTests(unittest.TestCase):
    def test_detects_newer_stable_release_and_its_verified_installer(self):
        response = FakeResponse(payload=release_payload())
        with patch.object(app_update.requests, "get", return_value=response) as get:
            update = app_update.check_for_update("1.0.14")

        self.assertEqual(update.version, "1.0.15")
        self.assertEqual(update.tag, "v1.0.15")
        self.assertEqual(update.size, len(b"installer"))
        self.assertEqual(update.sha256, hashlib.sha256(b"installer").hexdigest())
        self.assertEqual(get.call_args.args[0], app_update.API_URL)
        self.assertFalse(get.call_args.kwargs["allow_redirects"])
        self.assertTrue(response.closed)

    def test_reports_no_update_for_same_or_newer_version(self):
        response = FakeResponse(payload=release_payload("1.0.14"))
        with patch.object(app_update.requests, "get", return_value=response):
            self.assertIsNone(app_update.check_for_update("1.0.14"))

    def test_rejects_untrusted_download_link_and_missing_digest(self):
        payload = release_payload(download_url="https://attacker.example/setup.exe")
        with patch.object(
            app_update.requests, "get",
            return_value=FakeResponse(payload=payload),
        ):
            with self.assertRaisesRegex(ValueError, "lien d'installateur"):
                app_update.check_for_update("1.0.14")

        payload = release_payload(digest=None)
        payload["assets"][0]["digest"] = None
        with patch.object(
            app_update.requests, "get",
            return_value=FakeResponse(payload=payload),
        ):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                app_update.check_for_update("1.0.14")

    def test_does_not_offer_prerelease(self):
        payload = release_payload()
        payload["prerelease"] = True
        with patch.object(
            app_update.requests, "get",
            return_value=FakeResponse(payload=payload),
        ):
            with self.assertRaisesRegex(RuntimeError, "pas une version stable"):
                app_update.check_for_update("1.0.14")


class UpdateDownloadTests(unittest.TestCase):
    def make_update(self, payload=None):
        payload = payload or release_payload()
        asset = payload["assets"][0]
        return app_update.UpdateInfo(
            version=payload["tag_name"][1:],
            tag=payload["tag_name"],
            download_url=asset["browser_download_url"],
            size=asset["size"],
            sha256=asset["digest"].split(":", 1)[1],
            release_url=payload["html_url"],
        )

    def test_downloads_to_downloads_and_verifies_sha256(self):
        update = self.make_update()
        response = FakeResponse(
            chunks=[b"inst", b"aller"],
            url="https://release-assets.githubusercontent.com/asset",
        )
        progress = []
        with tempfile.TemporaryDirectory() as folder, patch.object(
            app_update.requests, "get", return_value=response,
        ):
            path = app_update.download_update(
                update, progress=progress.append, download_directory=Path(folder),
            )
            self.assertEqual(path.read_bytes(), b"installer")
            self.assertEqual(path.name, "NIANG_IA_Setup_1.0.15.exe")
            self.assertEqual(progress, [0, 44, 100, 100])
            self.assertTrue(response.closed)
            self.assertEqual(
                [item.name for item in Path(folder).iterdir()],
                ["NIANG_IA_Setup_1.0.15.exe"],
            )

    def test_rejects_bad_hash_and_cleans_partial_download(self):
        update = self.make_update()
        update = app_update.UpdateInfo(
            **{**update.__dict__, "sha256": "0" * 64}
        )
        response = FakeResponse(
            chunks=[b"installer"],
            url="https://release-assets.githubusercontent.com/asset",
        )
        with tempfile.TemporaryDirectory() as folder, patch.object(
            app_update.requests, "get", return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "SHA-256"):
                app_update.download_update(update, download_directory=Path(folder))
            self.assertEqual(list(Path(folder).iterdir()), [])
            self.assertTrue(response.closed)

    def test_rejects_insecure_redirect(self):
        update = self.make_update()
        unsafe_redirect = Mock(url="http://attacker.example/installer")
        response = FakeResponse(
            url="https://release-assets.githubusercontent.com/asset",
            history=[unsafe_redirect],
        )
        with tempfile.TemporaryDirectory() as folder, patch.object(
            app_update.requests, "get", return_value=response,
        ):
            with self.assertRaisesRegex(RuntimeError, "redirection GitHub"):
                app_update.download_update(update, download_directory=Path(folder))
            self.assertTrue(response.closed)
            self.assertEqual(list(Path(folder).iterdir()), [])


if __name__ == "__main__":
    unittest.main()
