from importlib import resources

import pytest
import yaml

from assisteval.config import GROQ_BASE_URL, ConfigError, ensure_api_key, load_settings
from assisteval.simulator.llm import LLMError, OpenAICompatibleLLM

KEY_ENVS = ("GROQ_API_KEY", "LLM_API_KEY", "JUDGE_API_KEY")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in KEY_ENVS:
        monkeypatch.setenv(name, "")  # monkeypatch sonradan eski haline getirir


def write_config(tmp_path, llm: dict, judge: dict | None = None):
    """Şablon config.yaml'ı alıp llm/judge bölümlerini değiştirir (.env yok)."""
    data = yaml.safe_load((resources.files("assisteval") / "templates" / "config.yaml").read_text(encoding="utf-8"))
    data["llm"] = llm
    if judge is not None:
        data["judge"] = judge
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_template_uses_groq_by_default(tmp_path):
    s = load_settings(write_config(tmp_path, yaml.safe_load(
        (resources.files("assisteval") / "templates" / "config.yaml").read_text(encoding="utf-8"))["llm"]))
    assert s.llm.provider == "groq" and s.llm.base_url == GROQ_BASE_URL
    assert s.llm.api_key == "" and s.llm.needs_key
    assert s.judge.provider == "groq" and s.judge.model == s.llm.model


def test_groq_key_from_env_shared_with_judge(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    s = load_settings(write_config(tmp_path, {"provider": "groq", "model": "m"}))
    assert s.llm.api_key == "gsk_test" and s.judge.api_key == "gsk_test"


def test_judge_with_other_provider_does_not_inherit_groq(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    s = load_settings(write_config(tmp_path, {"provider": "groq", "model": "m"},
                                   {"provider": "openai", "base_url": "http://localhost:8000/v1", "model": "qwen"}))
    assert s.judge.base_url == "http://localhost:8000/v1" and s.judge.api_key == "yok"
    assert s.llm.base_url == GROQ_BASE_URL


def test_local_openai_provider_needs_no_key(tmp_path):
    s = load_settings(write_config(tmp_path, {"provider": "openai", "base_url": "http://localhost:8000/v1", "model": "qwen"}))
    assert not s.llm.needs_key and s.llm.api_key == "yok"
    ensure_api_key(s.llm, "x", prompt=lambda _: pytest.fail("sorulmamalı"))


def test_invalid_provider(tmp_path):
    with pytest.raises(ConfigError, match="provider"):
        load_settings(write_config(tmp_path, {"provider": "bilinmeyen", "model": "m"}))


def test_ensure_api_key_prompts_once_and_exports(tmp_path):
    s = load_settings(write_config(tmp_path, {"provider": "groq", "model": "m"}))
    asked = []
    ensure_api_key(s.llm, "Simülatör", prompt=lambda msg: asked.append(msg) or " gsk_girilen ")
    ensure_api_key(s.judge, "Hakem", prompt=lambda _: pytest.fail("ikinci kez sorulmamalı"))
    assert len(asked) == 1
    assert s.llm.api_key == s.judge.api_key == "gsk_girilen"
    import os
    assert os.environ["GROQ_API_KEY"] == "gsk_girilen"  # promptfoo provider süreci görsün


def test_ensure_api_key_without_terminal_fails_clearly(tmp_path, monkeypatch):
    s = load_settings(write_config(tmp_path, {"provider": "groq", "model": "m"}))
    monkeypatch.setattr("sys.stdin", None)  # promptfoo'nun başlattığı süreç gibi: terminal yok
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        ensure_api_key(s.llm, "Simülatör")


class FakeResp:
    def __init__(self, status, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json, headers, timeout):
        self.calls.append((url, json, headers))
        return self.responses.pop(0)


def groq_cfg(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    return load_settings(write_config(tmp_path, {"provider": "groq", "model": "llama"})).llm


def test_groq_request_and_rate_limit_retry(tmp_path, monkeypatch):
    ok = FakeResp(200, {"choices": [{"message": {"content": "merhaba"}}]})
    http = FakeHttp([FakeResp(429, headers={"retry-after": "1.5"}), ok])
    waits = []
    llm = OpenAICompatibleLLM(groq_cfg(tmp_path, monkeypatch), http=http, sleep=waits.append)
    assert llm.chat([{"role": "user", "content": "selam"}]) == "merhaba"
    assert waits == [1.5]
    url, body, headers = http.calls[0]
    assert url == GROQ_BASE_URL + "/chat/completions"
    assert body["model"] == "llama" and headers["Authorization"] == "Bearer gsk_test"
    assert llm.name == "groq:llama"


def test_rate_limit_gives_up(tmp_path, monkeypatch):
    http = FakeHttp([FakeResp(429)] * (OpenAICompatibleLLM.MAX_RATE_LIMIT_RETRY + 1))
    llm = OpenAICompatibleLLM(groq_cfg(tmp_path, monkeypatch), http=http, sleep=lambda _: None)
    with pytest.raises(LLMError, match="429"):
        llm.chat([])


def test_missing_groq_key_raises_before_request(tmp_path):
    cfg = load_settings(write_config(tmp_path, {"provider": "groq", "model": "m"})).llm
    with pytest.raises(LLMError, match="GROQ_API_KEY"):
        OpenAICompatibleLLM(cfg, http=FakeHttp([])).chat([])
