import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from niang_ia.visual_assets import VisualAssetError, VisualAssetService


def _image_bytes():
    from PIL import Image

    image = Image.new("RGB", (640, 360), color=(20, 40, 60))
    output = io.BytesIO()
    image.save(output, format="JPEG")
    return output.getvalue()


class _Response:
    def __init__(self, value=None, *, status_code=200, content_type="application/json"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self.content = (
            json.dumps(value).encode("utf-8")
            if value is not None
            else b""
        )
        self._closed = False

    def iter_content(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def close(self):
        self._closed = True


def _pixabay_hit(
    asset_id=17,
    *,
    width=640,
    height=360,
    download_url="https://cdn.pixabay.com/photo/2026/01/car.jpg",
):
    return {
        "id": asset_id,
        "imageWidth": width,
        "imageHeight": height,
        "user": "Photo Maker",
        "user_id": 45,
        "tags": "black luxury car",
        "pageURL": f"https://pixabay.com/photos/car-{asset_id}/",
        "largeImageURL": download_url,
        "webformatURL": download_url,
        "previewURL": download_url,
        "type": "photo",
        "downloads": 120,
    }


class VisualAssetServiceTests(unittest.TestCase):
    def test_search_ranks_and_filters_orientation_without_exposing_provider_keys(self):
        requests_seen = []

        def fake_get(url, **kwargs):
            requests_seen.append((url, kwargs))
            if "pixabay.com/api/" in url:
                return _Response({"hits": [
                    _pixabay_hit(),
                    _pixabay_hit(18, width=360, height=640),
                ]})
            if "api.unsplash.com" in url:
                return _Response({"results": []})
            raise AssertionError(f"Unexpected provider request: {url}")

        with tempfile.TemporaryDirectory() as directory:
            service = VisualAssetService(
                environ={"NIANG_IA_PIXABAY_API_KEY": "test-key-not-for-output"},
                http_get=fake_get,
                cache_path=Path(directory) / "cache.json",
            )
            result = service.search("black luxury car", orientation="landscape")
        self.assertEqual(result["status"], "ok")
        self.assertEqual([item["candidate_id"] for item in result["results"]], ["pixabay:17"])
        self.assertNotIn("test-key-not-for-output", json.dumps(result))
        self.assertTrue(any("pixabay.com/api/" in url for url, _ in requests_seen))

    def test_no_configured_provider_key_makes_no_network_request(self):
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("No API key means no provider call.")

        result = VisualAssetService(environ={}, http_get=fail_if_called).search("a landscape")
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["results"], [])

    def test_pexels_is_not_used_without_explicit_allow_flag(self):
        requests_seen = []

        def fake_get(url, **kwargs):
            requests_seen.append(url)
            if "api.pexels.com" in url:
                return _Response({"photos": [{
                    "id": 29,
                    "width": 1200,
                    "height": 800,
                    "alt": "black luxury car",
                    "src": {
                        "large2x": "https://images.pexels.com/photos/car.jpg",
                        "medium": "https://images.pexels.com/photos/car.jpg",
                    },
                    "url": "https://www.pexels.com/photo/car-29/",
                    "photographer": "Photo Author",
                    "photographer_url": "https://www.pexels.com/@photoauthor/",
                }]})
            raise AssertionError(f"Unexpected provider request: {url}")

        with tempfile.TemporaryDirectory() as directory:
            service = VisualAssetService(
                environ={"NIANG_IA_PEXELS_API_KEY": "pexels-key"},
                http_get=fake_get,
                cache_path=Path(directory) / "cache.json",
            )
            skipped = service.search("black luxury car")
            self.assertEqual(requests_seen, [])
            self.assertEqual(skipped["status"], "unavailable")

            allowed = service.search("black luxury car", allow_pexels=True)
            self.assertEqual(allowed["status"], "ok")
            self.assertEqual(allowed["results"][0]["provider"], "pexels")
            self.assertEqual(len(requests_seen), 1)

    def test_sensitive_query_is_rejected_before_provider_request(self):
        service = VisualAssetService(
            environ={"NIANG_IA_PIXABAY_API_KEY": "configured"},
            http_get=lambda *_args, **_kwargs: self.fail("unexpected provider request"),
        )
        with self.assertRaises(VisualAssetError):
            service.search("my token is sk-123456789012345678901234")

    def test_saved_image_keeps_provenance_and_verifier_reports_broken_references(self):
        image_bytes = _image_bytes()

        def download_get(url, **kwargs):
            if "pixabay.com/api/" in url:
                return _Response({"hits": [_pixabay_hit()]})
            if "api.unsplash.com" in url:
                return _Response({"results": []})
            response = _Response(status_code=200, content_type="image/jpeg")
            response.content = image_bytes
            return response

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = VisualAssetService(
                environ={"NIANG_IA_PIXABAY_API_KEY": "test-key"},
                http_get=download_get,
                cache_path=root / "cache.json",
            )
            search = service.search("black luxury car")
            saved = service.use_asset(
                search["results"][0]["candidate_id"],
                root,
                relative_path="assets/images/hero.jpg",
                placement="Hero image",
            )
            html = (
                '<img src="/assets/images/hero.jpg" alt="Black luxury car">'
                '<a href="https://pixabay.com/photos/car-17/">'
                "Photo by Photo Maker on Pixabay</a>"
            )
            (root / "index.html").write_text(html, encoding="utf-8")
            report = service.verify_project(root)

            self.assertEqual(saved["status"], "saved")
            self.assertEqual(report["status"], "PASS", report["issues"])
            self.assertEqual(report["visual_review"].split(":")[0], "NOT_TESTED")
            registry = json.loads(
                (root / "assets" / "visual-assets.json").read_text(encoding="utf-8")
            )
            self.assertEqual(registry["assets"][0]["source_url"], "https://pixabay.com/photos/car-17/")
            (root / "index.html").write_text(
                html.replace("/assets/images/hero.jpg", "/assets/images/missing.jpg"),
                encoding="utf-8",
            )
            broken = service.verify_project(root)
            self.assertEqual(broken["status"], "FAIL")
            self.assertTrue(any("missing local file" in issue for issue in broken["issues"]))

    def test_html_disguised_as_image_is_rejected_and_destination_is_not_created(self):
        def fake_get(url, **kwargs):
            if "pixabay.com/api/" in url:
                return _Response({"hits": [_pixabay_hit()]})
            if "api.unsplash.com" in url:
                return _Response({"results": []})
            response = _Response(status_code=200, content_type="image/jpeg")
            response.content = b"<html>not an image</html>"
            return response

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = VisualAssetService(
                environ={"NIANG_IA_PIXABAY_API_KEY": "test-key"},
                http_get=fake_get,
                cache_path=root / "cache.json",
            )
            candidate = service.search("black luxury car")["results"][0]["candidate_id"]
            with self.assertRaises(VisualAssetError):
                service.use_asset(
                    candidate,
                    root,
                    relative_path="assets/images/hero.jpg",
                    placement="Hero image",
                )
            self.assertFalse((root / "assets" / "images" / "hero.jpg").exists())

    def test_unsplash_choice_tracks_download_and_requires_hotlink_attribution(self):
        requests_seen = []
        image_url = "https://images.unsplash.com/photo-1?auto=format"
        source_url = "https://unsplash.com/photos/car"

        def fake_get(url, **kwargs):
            requests_seen.append((url, kwargs))
            if url.endswith("/search/photos"):
                return _Response({"results": [{
                    "id": "photo-1",
                    "width": 1200,
                    "height": 800,
                    "alt_description": "black luxury car",
                    "urls": {"regular": image_url, "small": image_url},
                    "links": {
                        "html": source_url,
                        "download_location": "https://api.unsplash.com/photos/photo-1/download",
                    },
                    "user": {
                        "name": "Photo Artist",
                        "links": {"html": "https://unsplash.com/@photoartist"},
                    },
                    "likes": 42,
                }]})
            if url.endswith("/download"):
                return _Response({})
            raise AssertionError(f"Unexpected provider request: {url}")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            service = VisualAssetService(
                environ={"NIANG_IA_UNSPLASH_ACCESS_KEY": "test-key"},
                http_get=fake_get,
                cache_path=root / "cache.json",
            )
            result = service.search("black luxury car", orientation="landscape")
            candidate_id = result["results"][0]["candidate_id"]
            selected = service.use_asset(
                candidate_id,
                root,
                placement="Hero image",
            )
            (root / "index.html").write_text(
                f'<img src="{image_url}" alt="Car">'
                f'<a href="{selected["source_url"]}">'
                "Photo by Photo Artist on Unsplash</a>",
                encoding="utf-8",
            )
            report = service.verify_project(root)
            self.assertEqual(selected["status"], "registered_hotlink")
            self.assertTrue(selected["download_event_recorded"])
            self.assertTrue(any(url.endswith("/download") for url, _ in requests_seen))
            self.assertEqual(report["status"], "PASS", report["issues"])

    def test_pixabay_search_cache_persists_for_a_day_without_storing_query_or_api_key(self):
        requests_seen = []

        def fake_get(url, **kwargs):
            requests_seen.append(url)
            if "pixabay.com/api/" in url:
                return _Response({"hits": [_pixabay_hit()]})
            if "api.unsplash.com" in url:
                return _Response({"results": []})
            raise AssertionError(f"Unexpected provider request: {url}")

        with tempfile.TemporaryDirectory() as directory:
            cache_path = Path(directory) / "cache.json"
            first = VisualAssetService(
                environ={"NIANG_IA_PIXABAY_API_KEY": "private-key"},
                http_get=fake_get,
                cache_path=cache_path,
            )
            first.search("private project phrase")
            cache_text = cache_path.read_text(encoding="utf-8")
            self.assertNotIn("private project phrase", cache_text)
            self.assertNotIn("private-key", cache_text)
            second = VisualAssetService(
                environ={"NIANG_IA_PIXABAY_API_KEY": "private-key"},
                http_get=lambda *_args, **_kwargs: self.fail("Cached searches must not call providers."),
                cache_path=cache_path,
            )
            cached = second.search("private project phrase")
            self.assertEqual(cached["results"][0]["candidate_id"], "pixabay:17")
            self.assertEqual(
                sum("pixabay.com/api/" in url for url in requests_seen),
                1,
            )


if __name__ == "__main__":
    unittest.main()
