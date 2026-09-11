"""LLM backends behind one interface.

Local Ollama for free iteration, Anthropic for quality, HuggingFace for hosted demos.
Nothing above this module knows which is active - swap with LLM_BACKEND in .env.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from .config import Settings, get_settings


class LLMBackend(ABC):
    name: str

    @abstractmethod
    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str: ...


class OllamaBackend(LLMBackend):
    name = "ollama"

    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.model = settings.ollama_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "options": {"num_predict": max_tokens, "temperature": 0.0},
        }
        with httpx.Client(timeout=180.0) as client:
            r = client.post(f"{self.base_url}/api/generate", json=payload)
            r.raise_for_status()
            return r.json()["response"].strip()


class AnthropicBackend(LLMBackend):
    name = "anthropic"

    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise RuntimeError(
                "LLM_BACKEND=anthropic but ANTHROPIC_API_KEY is empty. "
                "Set it in .env, or switch to LLM_BACKEND=ollama."
            )
        from anthropic import Anthropic

        self.client = Anthropic(api_key=settings.anthropic_api_key)
        self.model = settings.anthropic_model

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=0.0,
            system=system or "You are a precise assistant.",
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in msg.content if b.type == "text").strip()


class HuggingFaceBackend(LLMBackend):
    """Serverless inference via HF's OpenAI-compatible router.

    Exists so the public demo can generate answers on free CPU hosting, where
    neither Ollama nor a GPU is available. Same interface as the other two.
    """

    name = "huggingface"

    def __init__(self, settings: Settings) -> None:
        if not settings.hf_token:
            raise RuntimeError(
                "LLM_BACKEND=huggingface but HF_TOKEN is empty. "
                "Create a read token at huggingface.co/settings/tokens."
            )
        self.token = settings.hf_token
        self.model = settings.hf_model
        self.base_url = settings.hf_base_url.rstrip("/")

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    def complete(self, prompt: str, system: str = "", max_tokens: int = 1024) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        with httpx.Client(timeout=180.0) as client:
            r = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.token}"},
                json={
                    "model": self.model,
                    "messages": messages,
                    "max_tokens": max_tokens,
                    "temperature": 0.0,
                },
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()


_BACKENDS: dict[str, type[LLMBackend]] = {
    "huggingface": HuggingFaceBackend,
    "ollama": OllamaBackend,
    "anthropic": AnthropicBackend,
}


def get_llm(settings: Settings | None = None) -> LLMBackend:
    settings = settings or get_settings()
    key = settings.llm_backend.lower()
    if key not in _BACKENDS:
        raise ValueError(f"Unknown LLM_BACKEND={key!r}. Options: {sorted(_BACKENDS)}")
    return _BACKENDS[key](settings)
