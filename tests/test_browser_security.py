import unittest
from unittest.mock import patch

from actions.browser_security import BrowserURLPolicyError, validate_browser_url


class BrowserURLPolicyTests(unittest.TestCase):
    def test_normalizes_public_urls_and_resolves_hostnames(self):
        resolver = unittest.mock.Mock(return_value=["93.184.216.34"])

        url = validate_browser_url("example.com/article", resolve_host=resolver)

        self.assertEqual(url, "https://example.com/article")
        resolver.assert_called_once_with("example.com")

    def test_rejects_non_http_protocols_and_embedded_credentials(self):
        for url in ("file:///C:/Windows/win.ini", "javascript:alert(1)",
                    "javascript:123",
                    "https://user:password@example.com"):
            with self.subTest(url=url), self.assertRaises(BrowserURLPolicyError):
                validate_browser_url(url)

    def test_rejects_local_and_private_ip_addresses(self):
        for url in (
            "http://localhost/",
            "http://127.0.0.1/",
            "http://[::1]/",
            "http://169.254.169.254/latest/meta-data/",
            "http://192.168.1.1/",
            "http://service.internal/",
        ):
            with self.subTest(url=url), self.assertRaises(BrowserURLPolicyError):
                validate_browser_url(url)

    def test_rejects_public_hostnames_that_resolve_to_private_addresses(self):
        with self.assertRaises(BrowserURLPolicyError):
            validate_browser_url(
                "https://rebound.example.net",
                resolve_host=lambda _: ["8.8.8.8", "10.0.0.7"],
            )

    def test_rejects_unresolvable_hosts_and_allows_explicit_local_host(self):
        with self.assertRaises(BrowserURLPolicyError):
            validate_browser_url("https://offline.example.net", resolve_host=lambda _: [])

        self.assertEqual(
            validate_browser_url(
                "http://localhost:3000/",
                allowed_local_hosts={"localhost"},
            ),
            "http://localhost:3000/",
        )

    def test_reads_local_host_allowlist_from_environment(self):
        with patch.dict("os.environ", {"NIANG_IA_BROWSER_ALLOWED_LOCAL_HOSTS": "localhost"}):
            self.assertEqual(validate_browser_url("http://localhost:8000"), "http://localhost:8000")


if __name__ == "__main__":
    unittest.main()
