"""Language-model access for the AI testing tools.

The default provider calls a local Ollama server (http://127.0.0.1:11434)
running the llama3.2 model: free, offline after the model download, and on
this computer only. Another provider can be added by implementing chat().

Every exchange can be recorded to a JSONL file so results can be inspected
later and the generated test data replayed without the model.
"""

import hashlib
import json
import time
from pathlib import Path

import httpx


class ModelError(RuntimeError):
    pass


class OllamaProvider:
    def __init__(self, model: str = "llama3.2", host: str = "http://127.0.0.1:11434",
                 temperature: float = 0.4, seed: int | None = None, record_to: Path | None = None):
        self.model = model
        self.host = host
        self.temperature = temperature
        self.seed = seed
        self.record_to = record_to
        self.calls = 0
        self.seconds = 0.0
        self._http = httpx.Client(timeout=180)

    @property
    def name(self) -> str:
        return f"ollama:{self.model}"

    def available(self) -> bool:
        try:
            tags = self._http.get(f"{self.host}/api/tags", timeout=5).json()
        except httpx.HTTPError:
            return False
        return any(m["name"].split(":")[0] == self.model.split(":")[0] for m in tags.get("models", []))

    def chat(self, messages: list[dict], max_tokens: int = 400) -> dict:
        """Send a conversation and return the reply parsed as JSON."""
        options = {"temperature": self.temperature, "num_predict": max_tokens}
        if self.seed is not None:
            options["seed"] = self.seed
        body = {"model": self.model, "stream": False, "format": "json", "options": options, "messages": messages}
        started = time.perf_counter()
        try:
            response = self._http.post(f"{self.host}/api/chat", json=body)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ModelError(f"Ollama request failed: {exc}") from exc
        elapsed = time.perf_counter() - started
        self.calls += 1
        self.seconds += elapsed
        text = response.json()["message"]["content"]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = None
        if self.record_to is not None:
            self.record_to.parent.mkdir(parents=True, exist_ok=True)
            with self.record_to.open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "provider": self.name, "request_hash": request_hash(messages),
                    "seconds": round(elapsed, 2), "reply": text,
                }) + "\n")
        if parsed is None:
            raise ModelError(f"Model reply was not JSON: {text[:200]}")
        return parsed


def request_hash(messages: list[dict]) -> str:
    return hashlib.sha256(json.dumps(messages, sort_keys=True).encode()).hexdigest()[:16]
