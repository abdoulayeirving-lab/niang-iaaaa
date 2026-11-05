import unittest

from agent.secrets import detect_sensitive_data, redact_if_sensitive


class AgentSecretDetectionTests(unittest.TestCase):
    def test_detects_common_named_credentials_without_returning_values(self):
        mission = "Use password: correct-horse-battery and token=long-private-value"

        categories = detect_sensitive_data(mission)

        self.assertIn("credential_assignment", categories)
        self.assertNotIn("correct-horse-battery", categories)
        self.assertNotIn("long-private-value", categories)

    def test_detects_common_provider_tokens_and_private_key_headers(self):
        self.assertIn(
            "recognized_token",
            detect_sensitive_data("Use ghp_123456789012345678901234567890AB"),
        )
        self.assertIn(
            "private_key",
            detect_sensitive_data("-----BEGIN PRIVATE KEY-----"),
        )

    def test_redaction_does_not_claim_to_find_every_secret(self):
        obvious = "api_key=AIza012345678901234567890123456789012"
        uncommon = "my private phrase is oceanic and quiet"

        self.assertEqual(redact_if_sensitive(obvious, "[redacted]"), "[redacted]")
        self.assertEqual(redact_if_sensitive(uncommon, "[redacted]"), uncommon)


if __name__ == "__main__":
    unittest.main()
