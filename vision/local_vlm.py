"""Local-only image description through the Ollama chat API."""

from __future__ import annotations

import base64
import os
from typing import Any

import requests


OLLAMA_API_URL = "http://127.0.0.1:11434/api/chat"
DEFAULT_MODEL = "qwen3-vl:2b"
CONNECT_TIMEOUT_SECONDS = 5
READ_TIMEOUT_SECONDS = 300


def describe_image(
    image: bytes,
    question: str,
    *,
    model: str | None = None,
    http_post: Any = requests.post,
) -> str:
    """Describe an image locally; the image is sent only to loopback Ollama."""
    if not image:
        raise ValueError("The captured screen image is empty.")
    if not question or not question.strip():
        raise ValueError("A question about the screen is required.")

    selected_model = (
        model or os.environ.get("NIANG_IA_VISION_MODEL", DEFAULT_MODEL)
    ).strip()
    if not selected_model:
        raise ValueError("NIANG_IA_VISION_MODEL must name an installed Ollama model.")

    try:
        response = http_post(
            OLLAMA_API_URL,
            json={
                "model": selected_model,
                "messages": [{
                    "role": "user",
                    "content": question.strip(),
                    "images": [base64.b64encode(image).decode("ascii")],
                }],
                "stream": False,
                "options": {"temperature": 0.2},
            },
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
        )
    except requests.ConnectionError as exc:
        raise RuntimeError(
            "Ollama is not running on this PC. Start Ollama and run "
            f"`ollama pull {selected_model}`, then try again."
        ) from exc
    except requests.Timeout as exc:
        raise RuntimeError(
            f"Ollama did not finish the local vision request within "
            f"{READ_TIMEOUT_SECONDS} seconds."
        ) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach local Ollama: {exc}") from exc

    try:
        if response.status_code == 404:
            raise RuntimeError(
                f"Ollama model '{selected_model}' is not installed. "
                f"Run `ollama pull {selected_model}` and try again."
            )
        if response.status_code >= 400:
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = str(body.get("error", "")).strip()
            except (ValueError, TypeError):
                pass
            raise RuntimeError(
                f"Local Ollama vision failed (HTTP {response.status_code})"
                + (f": {detail}" if detail else ".")
            )
        payload = response.json()
    finally:
        response.close()

    if not isinstance(payload, dict):
        raise RuntimeError("Ollama returned an unexpected response.")
    message = payload.get("message")
    answer = message.get("content") if isinstance(message, dict) else None
    if not isinstance(answer, str) or not answer.strip():
        raise RuntimeError("The local vision model returned no description.")
    return answer.strip()
