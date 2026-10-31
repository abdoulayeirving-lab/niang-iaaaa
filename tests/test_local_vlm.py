import unittest
from unittest.mock import Mock

import requests

from vision.local_vlm import OLLAMA_API_URL, describe_image


class LocalVisionTests(unittest.TestCase):
    def test_sends_image_to_local_ollama_and_returns_description(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "message": {"content": "A settings window is open."}
        }
        post = Mock(return_value=response)

        result = describe_image(
            b"screen bytes",
            "Describe the visible window.",
            model="qwen3-vl:2b",
            http_post=post,
        )

        self.assertEqual(result, "A settings window is open.")
        self.assertEqual(post.call_args.args[0], OLLAMA_API_URL)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["model"], "qwen3-vl:2b")
        self.assertEqual(payload["messages"][0]["content"], "Describe the visible window.")
        self.assertEqual(post.call_args.kwargs["timeout"], (5, 300))
        response.close.assert_called_once_with()

    def test_missing_model_has_pull_instructions(self):
        response = Mock()
        response.status_code = 404
        response.json.return_value = {"error": "model not found"}

        with self.assertRaisesRegex(RuntimeError, r"ollama pull qwen3-vl:2b"):
            describe_image(
                b"image",
                "Describe the screen.",
                http_post=Mock(return_value=response),
            )

        response.close.assert_called_once_with()

    def test_offline_ollama_error_is_actionable(self):
        post = Mock(side_effect=requests.ConnectionError("connection refused"))

        with self.assertRaisesRegex(RuntimeError, "Start Ollama"):
            describe_image(b"image", "Describe the screen.", http_post=post)

    def test_empty_image_or_question_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "image is empty"):
            describe_image(b"", "Describe it.")
        with self.assertRaisesRegex(ValueError, "question"):
            describe_image(b"image", " ")


if __name__ == "__main__":
    unittest.main()
