"""Simülatörün kullandığı LLM istemcileri.

OpenAICompatibleLLM: OpenAI uyumlu her endpoint. Şimdilik Groq (provider: groq), ileride
kurum içi Qwen (vLLM / Ollama / LM Studio, provider: openai). Geçiş için sadece
config.yaml'daki llm ayarları değişir, kod değişmez.

MockLLM: gerçek LLM yokken yönlendirmeli modu uçtan uca denemek için. Her turda
yönlendirmedeki sıradaki adımı alır, çift tırnak içindeki ifadeyi söyler; ifade
asistanın sunduğu bir butonun başlığıysa butona tıklar.
"""

import json
import re
import time

import requests

from ..config import LLMConfig
from .reply import _norm

QUOTED = re.compile(r'"([^"]+)"|“([^”]+)”')
BUTTON_LINE = re.compile(r"^\s*\[(.+?)\] →", re.MULTILINE)


class LLMError(Exception):
    pass


class OpenAICompatibleLLM:
    MAX_RATE_LIMIT_RETRY = 3  # Groq ücretsiz katmanında dakikalık sınır sık aşılır
    MAX_WAIT_SECONDS = 30

    def __init__(self, cfg: LLMConfig, http: requests.Session | None = None, sleep=time.sleep):
        self.cfg = cfg
        self.http = http or requests.Session()
        self.sleep = sleep

    @property
    def name(self) -> str:
        return f"{self.cfg.provider}:{self.cfg.model}"

    def chat(self, messages: list[dict]) -> str:
        if self.cfg.needs_key and not self.cfg.api_key:
            raise LLMError(f"{self.cfg.provider} API anahtarı yok (GROQ_API_KEY)")
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        body = {"model": self.cfg.model, "messages": messages, "temperature": self.cfg.temperature}
        headers = {"Authorization": f"Bearer {self.cfg.api_key}"}
        for attempt in range(self.MAX_RATE_LIMIT_RETRY + 1):
            try:
                resp = self.http.post(url, json=body, headers=headers, timeout=self.cfg.timeout_seconds)
            except requests.RequestException as e:
                raise LLMError(f"LLM'e ulaşılamadı ({url}): {e}") from e
            if resp.status_code == 429 and attempt < self.MAX_RATE_LIMIT_RETRY:
                self.sleep(_retry_after(resp, default=2 ** (attempt + 1), cap=self.MAX_WAIT_SECONDS))
                continue
            if resp.status_code != 200:
                raise LLMError(f"LLM HTTP {resp.status_code}: {resp.text[:300]}")
            return resp.json()["choices"][0]["message"]["content"] or ""
        raise LLMError("LLM rate limit aşıldı")  # döngüden 429 ile çıkılamaz; güvenlik için


def _retry_after(resp, default: float, cap: float) -> float:
    try:
        return min(float(resp.headers.get("retry-after", default)), cap)
    except (TypeError, ValueError):
        return min(default, cap)


class MockLLM:
    name = "mock"

    def __init__(self, yonlendirme: list[str]):
        self.yonlendirme = yonlendirme

    def chat(self, messages: list[dict]) -> str:
        turn = sum(1 for m in messages if m["role"] == "assistant")
        if turn >= len(self.yonlendirme):
            return json.dumps({"durum": "BITTI", "aksiyon": "mesaj", "deger": "", "gerekce": "Yönlendirme adımları tamamlandı"})

        instruction = self.yonlendirme[turn]
        match = QUOTED.search(instruction)
        phrase = (match.group(1) or match.group(2)) if match else instruction
        last_reply = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
        buttons = {_norm(b): b for b in BUTTON_LINE.findall(last_reply)}
        if _norm(phrase) in buttons:
            decision = {"aksiyon": "buton", "deger": buttons[_norm(phrase)]}
        else:
            decision = {"aksiyon": "mesaj", "deger": phrase}
        return json.dumps({"durum": "DEVAM", **decision, "gerekce": f"Yönlendirme {turn + 1}. adım"}, ensure_ascii=False)
