import os
import unittest
from unittest.mock import Mock, patch

from actions import web_search


class SerperSearchTests(unittest.TestCase):
    def test_serper_search_formats_answer_and_source_links(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "answerBox": {"answer": "Official answer", "link": "https://example.com/answer"},
            "organic": [{
                "title": "Official documentation",
                "snippet": "Current documentation text.",
                "link": "https://example.com/docs",
            }],
        }

        with (
            patch("api_keys.load_env_file"),
            patch.dict("os.environ", {"SERPER_API_KEY": "test-serper-key"}),
            patch("requests.post", return_value=response) as post,
        ):
            result = web_search._serper_search("test query")

        self.assertIn("Official answer", result)
        self.assertIn("https://example.com/answer", result)
        self.assertIn("Official documentation", result)
        self.assertIn("https://example.com/docs", result)
        self.assertEqual(post.call_args.args[0], "https://google.serper.dev/search")
        self.assertEqual(post.call_args.kwargs["headers"]["X-API-KEY"], "test-serper-key")
        self.assertNotIn("test-serper-key", result)
        response.close.assert_called_once_with()

    def test_serper_rejects_invalid_key_with_actionable_error(self):
        response = Mock()
        response.status_code = 401

        with (
            patch("api_keys.load_env_file"),
            patch.dict("os.environ", {"SERPER_API_KEY": "invalid-key"}),
            patch("requests.post", return_value=response),
        ):
            with self.assertRaisesRegex(RuntimeError, "Check SERPER_API_KEY"):
                web_search._serper_search("test query")

        response.close.assert_called_once_with()

    def test_web_search_prefers_serper_when_key_is_configured(self):
        with (
            patch("api_keys.load_env_file"),
            patch.dict("os.environ", {"SERPER_API_KEY": "test-serper-key"}),
            patch.object(web_search, "_serper_search", return_value="Serper result") as serper,
            patch.object(web_search, "_gemini_search") as gemini,
            patch.object(web_search, "_ddg_search") as ddg,
        ):
            result = web_search.web_search({"query": "test query"})

        self.assertEqual(result, "Serper result")
        serper.assert_called_once_with("test query")
        gemini.assert_not_called()
        ddg.assert_not_called()

    def test_load_env_file_reads_serper_key_without_overriding_environment(self):
        from api_keys import load_env_file

        with (
            patch("api_keys.DOTENV_PATH") as dotenv_path,
            patch.dict("os.environ", {"KAIZUMI_GEMINI_API_KEY": "existing-env-key"}, clear=True),
        ):
            dotenv_path.read_text.return_value = (
                "SERPER_API_KEY='local-serper-key'\n"
                "KAIZUMI_GEMINI_API_KEY=file-gemini-key\n"
                "UNSUPPORTED_SECRET=ignored\n"
            )
            load_env_file()

            self.assertEqual(os.environ["SERPER_API_KEY"], "local-serper-key")
            self.assertEqual(os.environ["KAIZUMI_GEMINI_API_KEY"], "existing-env-key")
            self.assertNotIn("UNSUPPORTED_SECRET", os.environ)


if __name__ == "__main__":
    unittest.main()
