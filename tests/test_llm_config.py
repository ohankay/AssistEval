import json
import os
from importlib import resources

import pytest
import yaml

from assisteval.cli import main
from assisteval.config import ConfigError, load_settings
from assisteval.evaluation import promptfoo as pf
from assisteval.simulator.llm import LLMError, OpenAICompatibleLLM, list_models

ENVS = ("SIMULATOR_API_KEY", "JUDGE_API_KEY", "ASSISTANT_BASE_URL", "CHATBOT_MESSAGE_URL",
        "SIMULATOR_BASE_URL", "SIMULATOR_MODEL", "JUDGE_BASE_URL", "JUDGE_MODEL", "NO_PROXY", "no_proxy")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENVS:
        monkeypatch.setenv(name, "")  # monkeypatch sonradan eski haline getirir


def template() -> dict:
    return yaml.safe_load((resources.files("assisteval") / "templates" / "config.yaml").read_text(encoding="utf-8"))


def write_config(tmp_path, **sections):
    """Şablon config.yaml'ı alıp verilen bölümleri değiştirir (None → bölümü sil). .env yok."""
    data = template()
    for name, value in sections.items():
        if value is None:
            data.pop(name, None)
        else:
            data[name] = value
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def test_template_has_two_local_llms_and_no_cloud(tmp_path):
    s = load_settings(write_config(tmp_path))
    for cfg in (s.simulator, s.judge):
        assert cfg.configured and cfg.base_url.startswith("http://localhost")
        assert cfg.api_key == ""
    text = (resources.files("assisteval") / "templates" / "config.yaml").read_text(encoding="utf-8").lower()
    assert "groq" not in text and "provider" not in text


def test_simulator_and_judge_are_independent(tmp_path):
    s = load_settings(write_config(tmp_path, simulator={"base_url": "http://a:8000/v1", "model": "m1"},
                                   judge={"base_url": "http://b:11434/v1", "model": "m2", "temperature": 0.2}))
    assert (s.simulator.base_url, s.simulator.model) == ("http://a:8000/v1", "m1")
    assert (s.judge.base_url, s.judge.model, s.judge.temperature) == ("http://b:11434/v1", "m2", 0.2)


def test_missing_section_is_only_an_error_when_used(tmp_path):
    s = load_settings(write_config(tmp_path, judge=None))
    assert not s.judge.configured
    with pytest.raises(ConfigError, match="judge: base_url ve model gerekli"):
        s.judge.require()


def test_old_llm_section_and_provider_are_rejected_clearly(tmp_path):
    with pytest.raises(ConfigError, match="'llm' bölümü 'simulator'"):
        load_settings(write_config(tmp_path, llm={"provider": "groq", "model": "m"}))
    with pytest.raises(ConfigError, match="provider kaldırıldı"):
        load_settings(write_config(tmp_path, judge={"provider": "openai", "base_url": "http://x/v1", "model": "m"}))


def test_env_overrides_and_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("CHATBOT_MESSAGE_URL", "https://test/chat")
    monkeypatch.setenv("SIMULATOR_BASE_URL", "http://qwen:8000/v1")
    monkeypatch.setenv("SIMULATOR_MODEL", "qwen3")
    monkeypatch.setenv("JUDGE_MODEL", "hakem")
    monkeypatch.setenv("JUDGE_API_KEY", "j-key")
    s = load_settings(write_config(tmp_path, judge=None))
    assert s.assistant.chatbot_message_url == "https://test/chat"
    assert (s.simulator.base_url, s.simulator.model, s.simulator.api_key) == ("http://qwen:8000/v1", "qwen3", "")
    # hakem simülatörden bir şey devralmaz
    assert (s.judge.base_url, s.judge.model, s.judge.api_key) == ("", "hakem", "j-key")


def test_llm_hosts_bypass_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "kurum.local")
    load_settings(write_config(tmp_path, simulator={"base_url": "http://llm1:8000/v1", "model": "m"},
                               judge={"base_url": "https://llm2.kurum.local/v1", "model": "m"}))
    assert os.environ["NO_PROXY"] == os.environ["no_proxy"] == "kurum.local,llm1,llm2.kurum.local"


def test_extra_body_must_be_mapping(tmp_path):
    with pytest.raises(ConfigError, match="extra_body"):
        load_settings(write_config(tmp_path, simulator={"base_url": "http://x/v1", "model": "m", "extra_body": "x"}))


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

    def get(self, url, headers, timeout):
        self.calls.append((url, None, headers))
        return self.responses.pop(0)


def simulator_cfg(tmp_path, **extra):
    path = write_config(tmp_path, simulator={"base_url": "http://llm:8000/v1/", "model": "qwen", **extra})
    return load_settings(path).simulator


OK = FakeResp(200, {"choices": [{"message": {"content": "merhaba"}}]})


def test_request_to_local_server_without_key(tmp_path):
    http = FakeHttp([OK])
    llm = OpenAICompatibleLLM(simulator_cfg(tmp_path), http=http)
    assert llm.chat([{"role": "user", "content": "selam"}]) == "merhaba" and llm.name == "qwen"
    url, body, headers = http.calls[0]
    assert url == "http://llm:8000/v1/chat/completions"
    assert body == {"model": "qwen", "messages": [{"role": "user", "content": "selam"}], "temperature": 0}
    assert headers == {}  # anahtar yoksa Authorization gönderilmez


def test_key_max_tokens_and_extra_body(tmp_path, monkeypatch):
    monkeypatch.setenv("SIMULATOR_API_KEY", "s-key")
    cfg = simulator_cfg(tmp_path, max_tokens=256, extra_body={"chat_template_kwargs": {"enable_thinking": False}})
    http = FakeHttp([OK])
    OpenAICompatibleLLM(cfg, http=http).chat([])
    _, body, headers = http.calls[0]
    assert headers == {"Authorization": "Bearer s-key"}
    assert body["max_tokens"] == 256 and body["chat_template_kwargs"] == {"enable_thinking": False}


def test_busy_server_retry_then_give_up(tmp_path):
    waits = []
    http = FakeHttp([FakeResp(503, headers={"retry-after": "1.5"}), OK])
    assert OpenAICompatibleLLM(simulator_cfg(tmp_path), http=http, sleep=waits.append).chat([]) == "merhaba"
    assert waits == [1.5]
    http = FakeHttp([FakeResp(429)] * (OpenAICompatibleLLM.MAX_RETRY + 1))
    with pytest.raises(LLMError, match="429"):
        OpenAICompatibleLLM(simulator_cfg(tmp_path), http=http, sleep=lambda _: None).chat([])


def test_unconfigured_simulator_fails_before_request(tmp_path):
    cfg = load_settings(write_config(tmp_path, simulator=None)).simulator
    with pytest.raises(LLMError, match="simulator: base_url ve model gerekli"):
        OpenAICompatibleLLM(cfg, http=FakeHttp([])).chat([])


def test_list_models(tmp_path):
    http = FakeHttp([FakeResp(200, {"data": [{"id": "qwen"}, {"id": "llama"}]})])
    assert list_models(simulator_cfg(tmp_path), http=http) == ["qwen", "llama"]
    assert http.calls[0][0] == "http://llm:8000/v1/models"


def test_judge_provider_in_promptfoo_config(tmp_path, monkeypatch):
    monkeypatch.setenv("JUDGE_API_KEY", "j-key")
    s = load_settings(write_config(tmp_path, judge={"base_url": "http://hakem:8000/v1", "model": "qwen-judge",
                                                    "max_tokens": 512, "extra_body": {"top_k": 1}}))
    assert pf.judge_provider(s) == {"id": "openai:chat:qwen-judge", "config": {
        "apiBaseUrl": "http://hakem:8000/v1", "temperature": 0, "max_tokens": 512, "passthrough": {"top_k": 1}}}
    env = pf.promptfoo_env(s)
    assert env["OPENAI_API_KEY"] == "j-key" and env["OPENAI_BASE_URL"] == "http://hakem:8000/v1"
    assert "--use-system-ca" in env["NODE_OPTIONS"]


def test_unconfigured_judge_never_points_to_cloud(tmp_path):
    s = load_settings(write_config(tmp_path, judge=None))
    assert pf.judge_provider(s)["config"]["apiBaseUrl"] == pf.NO_JUDGE_URL
    assert pf.promptfoo_env(s)["OPENAI_BASE_URL"] == pf.NO_JUDGE_URL


def test_check_llm_pings_both_servers(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("assisteval.cli.list_models",
                        lambda cfg: ["qwen"] if cfg.section == "simulator" else ["baska"])
    main(["--config", str(write_config(tmp_path)), "check", "--llm"])
    report = json.loads(capsys.readouterr().out)
    assert report["simulator"]["baglanti"] == "tamam"
    assert "'qwen' sunucuda yok" in report["judge"]["baglanti"]
