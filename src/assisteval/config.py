"""Ayarlar: gizli olmayanlar config.yaml'dan, gizli bilgiler .env / ortam değişkenlerinden."""

import os
from dataclasses import dataclass
from pathlib import Path

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


@dataclass
class LLMConfig:
    base_url: str
    model: str
    api_key: str = "yok"
    temperature: float = 0.0
    timeout_seconds: int = 120


@dataclass
class Settings:
    assistant: AssistantConfig
    llm: LLMConfig
    output_dir: Path


def load_settings(path: str | Path = "config.yaml") -> Settings:
    path = Path(path).resolve()
    if not path.exists():
        raise ConfigError(f"Ayar dosyası bulunamadı: {path} (çalışma klasörü için: assisteval init <klasör>)")
    # .env her zaman config.yaml'ın yanından okunur (çalışılan dizinden bağımsız)
    load_dotenv(path.parent / ".env")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))

    llm = dict(data.get("llm", {}))
    llm["api_key"] = os.environ.get("LLM_API_KEY", llm.get("api_key", "yok"))
    return Settings(
        assistant=AssistantConfig(**data["assistant"]),
        llm=LLMConfig(**llm),
        output_dir=path.parent / data.get("output_dir", "runs"),
    )
