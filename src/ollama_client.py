"""Minimal client for a local Ollama server's /api/generate endpoint."""

import json

import requests


class OllamaError(RuntimeError):
    pass


def generate_json(
    prompt: str,
    model: str,
    base_url: str = "http://localhost:11434",
    timeout: int = 240,
    session: requests.Session | None = None,
) -> dict:
    """Send a prompt to Ollama and parse the response as JSON.

    Ollama is asked to constrain its output to JSON via `format: "json"`.
    Raises OllamaError if the server is unreachable or the response body
    isn't valid JSON.

    If `session` is given, the request is issued through it (rather than the
    module-level `requests` API) so a caller can abort an in-flight request
    by closing the session from another thread.
    """
    http = session if session is not None else requests
    try:
        resp = http.post(
            f"{base_url}/api/generate",
            json={
                "model": model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "think": False,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError as exc:
        raise OllamaError(
            f"Could not reach Ollama at {base_url}. Is it running? "
            f"(start it with `ollama serve`, and `ollama pull {model}` "
            f"if you haven't already)"
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise OllamaError(f"Ollama request failed: {exc}") from exc

    body = resp.json()
    raw_text = body.get("response", "")
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Model did not return valid JSON: {raw_text!r}") from exc
