"""Ayarlar: gizli olmayanlar config.yaml'dan, gizli bilgiler .env / ortam değişkenlerinden."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

import yaml
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


@dataclass
class Credentials:
    customer_id: str
    gsm_number: str
    password: str
    otp: str
    ext_u_name: str
    ext_u_password: str
    # Cihaz kaydı (LoginForMobileBranch) farklı bir servis kullanıcısıyla yapılıyor
    reg_ext_u_name: str
    reg_ext_u_password: str
    reg_user_id: str

    @classmethod
    def from_env(cls) -> "Credentials":
        names = {
            "customer_id": "CUSTOMER_ID",
            "gsm_number": "GSM_NUMBER",
            "password": "PASSWORD",
            "otp": "OTP",
            "ext_u_name": "EXT_U_NAME",
            "ext_u_password": "EXT_U_PASSWORD",
            "reg_ext_u_name": "REG_EXT_U_NAME",
            "reg_ext_u_password": "REG_EXT_U_PASSWORD",
            "reg_user_id": "REG_USER_ID",
        }
        missing = [env for env in names.values() if not os.environ.get(env)]
        if missing:
            raise ConfigError(f".env içinde eksik değişkenler: {', '.join(missing)} (.env.example'a bakın)")
        return cls(**{field: os.environ[env] for field, env in names.items()})


@dataclass
class AssistantConfig:
    base_url: str
    chatbot_message_url: str
    device: dict
    main_resource_code: str
    main_resource_code_dashboard: str
    main_resource_id: int
    channel_id: int = 5
    language_id: int = 1
    token_refresh_seconds: int = 240
    timeout_seconds: int = 60


# İki LLM var, ikisi de kurum içi sunucularda çalışan OpenAI uyumlu endpoint (vLLM, Ollama, LM Studio, TGI...):
#   simulator → yönlendirmeli modda müşteriyi oynar
#   judge     → değerlendirmede llm-rubric hakemi (promptfoo)
# Birbirinden bağımsızdır; isteyen ikisine aynı sunucuyu/modeli yazabilir. Bulut sağlayıcı varsayılanı yoktur.
LLM_SECTIONS = ("simulator", "judge")
LLM_FIELDS = ("base_url", "model", "temperature", "timeout_seconds", "max_tokens", "extra_body")


@dataclass
class LLMConfig:
    section: str
    base_url: str = ""
    model: str = ""
    api_key: str = ""  # çoğu yerel sunucu istemez; vLLM --api-key / iç gateway için .env'den
    temperature: float = 0.0
    timeout_seconds: int = 120
    max_tokens: int | None = None
    # İsteğe olduğu gibi eklenen alanlar, ör. Qwen3 + vLLM: {chat_template_kwargs: {enable_thinking: false}}
    extra_body: dict = field(default_factory=dict)

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.model)

    def require(self) -> None:
        if not self.configured:
            raise ConfigError(f"config.yaml {self.section}: base_url ve model gerekli "
                              f"(veya .env: {self.section.upper()}_BASE_URL / {self.section.upper()}_MODEL)")


@dataclass
class Settings:
    assistant: AssistantConfig
    simulator: LLMConfig  # simüle müşteri LLM'i (yönlendirmeli mod)
    judge: LLMConfig  # değerlendirmede llm-rubric hakemi (promptfoo)
    output_dir: Path
    path: Path  # config.yaml'ın tam yolu


def load_settings(path: str | Path = "config.yaml") -> Settings:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"Ayar dosyası bulunamadı: {path} (çalışma klasörü için: assisteval init <klasör>)")
    # .env her zaman config.yaml'ın yanından okunur (çalışılan dizinden bağımsız)
    load_dotenv(path.parent / ".env")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    _apply_env_overrides(data)

    if "llm" in data:
        raise ConfigError("config.yaml: 'llm' bölümü 'simulator' olarak değişti, provider ayarı kaldırıldı "
                          "(yeni şablon: assisteval init <boş klasör>)")
    simulator, judge = (_llm_config(data.get(name), name) for name in LLM_SECTIONS)
    _bypass_proxy(simulator, judge)
    return Settings(
        assistant=AssistantConfig(**data["assistant"]),
        simulator=simulator,
        judge=judge,
        output_dir=path.parent / data.get("output_dir", "runs"),
        path=path,
    )


# Ortama göre değişen ayarlar .env'den de verilebilir; doluysa config.yaml'daki değerin önüne geçer
ENV_OVERRIDES = {
    "ASSISTANT_BASE_URL": ("assistant", "base_url"),
    "CHATBOT_MESSAGE_URL": ("assistant", "chatbot_message_url"),
    "SIMULATOR_BASE_URL": ("simulator", "base_url"),
    "SIMULATOR_MODEL": ("simulator", "model"),
    "JUDGE_BASE_URL": ("judge", "base_url"),
    "JUDGE_MODEL": ("judge", "model"),
}


def _apply_env_overrides(data: dict) -> None:
    for env, (section, key) in ENV_OVERRIDES.items():
        value = os.environ.get(env, "").strip()
        if value:
            if not isinstance(data.get(section), dict):
                data[section] = {}
            data[section][key] = value


def _llm_config(raw, section: str) -> LLMConfig:
    raw = dict(raw or {})
    unknown = sorted(set(raw) - set(LLM_FIELDS))
    if unknown:
        hint = " (provider kaldırıldı: her LLM OpenAI uyumlu yerel endpoint)" if "provider" in unknown else ""
        raise ConfigError(f"config.yaml {section}: bilinmeyen alan {', '.join(unknown)}{hint}")
    if raw.get("extra_body") is not None and not isinstance(raw["extra_body"], dict):
        raise ConfigError(f"config.yaml {section}.extra_body bir sözlük olmalı")
    raw["extra_body"] = raw.get("extra_body") or {}
    raw = {k: v for k, v in raw.items() if v is not None}
    return LLMConfig(section=section, api_key=os.environ.get(f"{section.upper()}_API_KEY", "").strip(), **raw)


def _bypass_proxy(*cfgs: LLMConfig) -> None:
    """LLM sunucuları kurum içinde: makinede HTTPS_PROXY tanımlıysa bile onlara proxy'siz gidilsin.

    NO_PROXY'e eklenir; hem requests (simülatör) hem promptfoo (hakem, alt süreç) bunu okur.
    """
    hosts = {urlsplit(c.base_url).hostname for c in cfgs if c.base_url}
    hosts.discard(None)
    if not hosts:
        return
    current = os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or ""
    entries = [h.strip() for h in current.split(",") if h.strip()]
    entries += sorted(h for h in hosts if h not in entries)
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = ",".join(entries)
