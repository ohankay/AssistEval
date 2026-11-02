"""Simülatörün kullandığı LLM istemcileri.

OpenAICompatibleLLM: kurum içi sunucuda çalışan OpenAI uyumlu endpoint (vLLM, Ollama, LM Studio,
TGI...). Adres, model ve istek ayarları config.yaml'daki `simulator` bölümünden gelir.
"""

import time

import requests

from ..config import ConfigError, LLMConfig



class LLMError(Exception):
    pass


class OpenAICompatibleLLM:
    # Yerel sunucu meşgulken (kuyruk dolu, model yükleniyor) 429/5xx döner: bekleyip yeniden dene
    RETRY_STATUS = (429, 502, 503, 504)
    MAX_RETRY = 3
    MAX_WAIT_SECONDS = 30

    def __init__(self, cfg: LLMConfig, http: requests.Session | None = None, sleep=time.sleep):
        self.cfg = cfg
        self.http = http or requests.Session()
        self.sleep = sleep

    @property
    def name(self) -> str:
        return self.cfg.model

    def chat(self, messages: list[dict]) -> str:
        try:
            self.cfg.require()
        except ConfigError as e:
            raise LLMError(str(e)) from e
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        body = {**self.cfg.extra_body, "model": self.cfg.model, "messages": messages, "temperature": self.cfg.temperature}
        if self.cfg.max_tokens:
            body["max_tokens"] = self.cfg.max_tokens
        for attempt in range(self.MAX_RETRY + 1):
            try:
                resp = self.http.post(url, json=body, headers=_auth(self.cfg), timeout=self.cfg.timeout_seconds)
            except requests.RequestException as e:
                raise LLMError(f"LLM'e ulaşılamadı ({url}): {e}") from e
            if resp.status_code in self.RETRY_STATUS and attempt < self.MAX_RETRY:
                self.sleep(_retry_after(resp, default=2 ** (attempt + 1), cap=self.MAX_WAIT_SECONDS))
                continue
            if resp.status_code != 200:
                raise LLMError(f"LLM HTTP {resp.status_code} ({url}): {resp.text[:300]}")
            try:
                return resp.json()["choices"][0]["message"]["content"] or ""
            except (ValueError, KeyError, IndexError, TypeError) as e:
                raise LLMError(f"LLM cevabı OpenAI formatında değil ({url}): {resp.text[:300]}") from e
        raise LLMError("LLM sunucusu meşgul, yeniden denemeler tükendi")  # güvenlik için; buraya düşülmez


def list_models(cfg: LLMConfig, http=None) -> list[str]:
    """Sunucudaki modeller (GET /models): bağlantı ve model adı kontrolü için."""
    url = cfg.base_url.rstrip("/") + "/models"
    try:
        resp = (http or requests).get(url, headers=_auth(cfg), timeout=min(cfg.timeout_seconds, 15))
    except requests.RequestException as e:
        raise LLMError(f"ulaşılamadı ({url}): {e}") from e
    if resp.status_code != 200:
        raise LLMError(f"HTTP {resp.status_code} ({url}): {resp.text[:200]}")
    try:
        return [m["id"] for m in resp.json().get("data", [])]
    except (ValueError, KeyError, TypeError, AttributeError) as e:
        raise LLMError(f"/models cevabı OpenAI formatında değil ({url})") from e


def _auth(cfg: LLMConfig) -> dict:
    # Çoğu yerel sunucu anahtar istemez; boşsa başlık hiç gönderilmez
    return {"Authorization": f"Bearer {cfg.api_key}"} if cfg.api_key else {}


def _retry_after(resp, default: float, cap: float) -> float:
    try:
        return min(float(resp.headers.get("retry-after", default)), cap)
    except (TypeError, ValueError):
        return min(default, cap)
