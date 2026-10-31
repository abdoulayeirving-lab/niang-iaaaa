# actions/web_search.py
# Kaizumi — Web Search
# Primary: Gemini google_search (yeni google.genai SDK)
# Fallback: DuckDuckGo (ddgs)

import json
import os
import sys
from pathlib import Path


def get_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent

BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"

def _get_api_key() -> str:
    from api_keys import next_key
    return next_key()


def _serper_search(query: str, max_results: int = 6) -> str:
    from api_keys import load_env_file
    import requests

    load_env_file()
    api_key = os.environ.get("SERPER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SERPER_API_KEY is not configured in the local .env file.")

    response = requests.post(
        "https://google.serper.dev/search",
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        json={"q": query, "num": max_results},
        timeout=(10, 30),
    )
    try:
        if response.status_code in {401, 403}:
            raise RuntimeError(
                "Serper rejected the API key. Check SERPER_API_KEY in .env."
            )
        if response.status_code == 429:
            raise RuntimeError(
                "Serper search quota or rate limit reached. Check the Serper account."
            )
        response.raise_for_status()
        payload = response.json()
    finally:
        response.close()

    if not isinstance(payload, dict):
        raise RuntimeError("Serper returned an unexpected response.")

    lines = [f"Search results for: {query}"]
    answer_box = payload.get("answerBox")
    if isinstance(answer_box, dict):
        answer = answer_box.get("answer") or answer_box.get("snippet")
        if answer:
            lines.extend(["", str(answer)])
        answer_link = answer_box.get("link")
        if answer_link:
            lines.append(f"Source: {answer_link}")

    organic = payload.get("organic", [])
    if isinstance(organic, list):
        for index, item in enumerate(organic[:max_results], 1):
            if not isinstance(item, dict):
                continue
            title = str(item.get("title", "")).strip()
            snippet = str(item.get("snippet", "")).strip()
            link = str(item.get("link", "")).strip()
            if title or snippet or link:
                lines.append("")
                if title:
                    lines.append(f"{index}. {title}")
                if snippet:
                    lines.append(f"   {snippet}")
                if link:
                    lines.append(f"   {link}")

    if len(lines) == 1:
        return f"No results found for: {query}"
    return "\n".join(lines)


def _gemini_search(query: str) -> str:
    from google import genai

    client = genai.Client(api_key=_get_api_key())
    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=query,
        config={"tools": [{"google_search": {}}]}
    )
    text = ""
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            text += part.text
    if not text.strip():
        raise ValueError("Empty response")
    return text.strip()



def _ddg_search(query: str, max_results: int = 6) -> list:
    try:
        from ddgs import DDGS
    except ImportError:
        from duckduckgo_search import DDGS
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append({
                "title":   r.get("title", ""),
                "snippet": r.get("body", ""),
                "url":     r.get("href", ""),
            })
    return results

def _format_ddg(query: str, results: list) -> str:
    if not results:
        return f"No results found for: {query}"
    lines = [f"Search results for: {query}\n"]
    for i, r in enumerate(results, 1):
        if r.get("title"):   lines.append(f"{i}. {r['title']}")
        if r.get("snippet"): lines.append(f"   {r['snippet']}")
        if r.get("url"):     lines.append(f"   {r['url']}")
        lines.append("")
    return "\n".join(lines).strip()


def _compare(items: list, aspect: str) -> str:
    query = f"Compare {', '.join(items)} in terms of {aspect}. Give specific facts and data."
    try:
        return _gemini_search(query)
    except Exception as e:
        print(f"[WebSearch] ⚠️ Gemini compare failed: {e}")
        all_results = {}
        for item in items:
            try:
                all_results[item] = _ddg_search(f"{item} {aspect}", max_results=3)
            except Exception:
                all_results[item] = []
        lines = [f"Comparison — {aspect.upper()}\n{'─'*40}"]
        for item in items:
            lines.append(f"\n▸ {item}")
            for r in all_results.get(item, [])[:2]:
                if r.get("snippet"):
                    lines.append(f"  • {r['snippet']}")
        return "\n".join(lines)


def web_search(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    params = parameters or {}
    query  = params.get("query", "").strip()
    mode   = params.get("mode", "search").lower()
    items  = params.get("items", [])
    aspect = params.get("aspect", "general")

    if not query and not items:
        return "Please provide a search query, sir."

    if items and mode != "compare":
        mode = "compare"

    if player:
        player.write_log(f"[Search] {query or ', '.join(items)}")

    print(f"[WebSearch] 🔍 Query: {query!r}  Mode: {mode}")

    try:
        if mode == "compare" and items:
            print(f"[WebSearch] 📊 Comparing: {items}")
            result = _compare(items, aspect)
            print("[WebSearch] ✅ Compare done.")
            return result

        from api_keys import load_env_file
        load_env_file()
        if os.environ.get("SERPER_API_KEY", "").strip():
            print("[WebSearch] 🌐 Serper search...")
            try:
                result = _serper_search(query)
                print("[WebSearch] ✅ Serper OK.")
                return result
            except Exception as e:
                print(f"[WebSearch] ⚠️ Serper failed ({e}), trying Gemini...")
                serper_error = str(e)
        else:
            serper_error = ""

        print("[WebSearch] 🌐 Gemini search...")
        try:
            result = _gemini_search(query)
            print("[WebSearch] ✅ Gemini OK.")
            return result
        except Exception as e:
            print(f"[WebSearch] ⚠️ Gemini failed ({e}), trying DDG...")
            try:
                results = _ddg_search(query)
            except Exception as ddg_error:
                errors = [f"Gemini: {e}", f"DuckDuckGo: {ddg_error}"]
                if serper_error:
                    errors.insert(0, f"Serper: {serper_error}")
                raise RuntimeError("; ".join(errors)) from ddg_error
            result  = _format_ddg(query, results)
            if not results and serper_error:
                return (
                    f"Search failed. Serper: {serper_error}; Gemini: {e}. "
                    "DuckDuckGo returned no results."
                )
            print(f"[WebSearch] ✅ DDG: {len(results)} results.")
            return result

    except Exception as e:
        print(f"[WebSearch] ❌ Failed: {e}")
        return f"Search failed, sir: {e}"