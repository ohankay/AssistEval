"""Ayarlar: gizli olmayanlar config.yaml'dan, gizli bilgiler .env / ortam değişkenlerinden."""

import getpass
import os
import sys
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


# LLM sağlayıcıları. Hepsi OpenAI uyumlu /chat/completions konuşur; fark varsayılan URL ve anahtar.
#   groq   → Groq bulut API'si (geçici). Anahtar zorunlu: GROQ_API_KEY, yoksa terminalden sorulur.
#   openai → OpenAI uyumlu herhangi bir endpoint: kurum içi Qwen (vLLM / Ollama / LM Studio).
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_KEY_ENV = "GROQ_API_KEY"
PROVIDERS = ("groq", "openai")


@dataclass
class LLMConfig:
    base_url: str = ""
    model: str = ""
    provider: str = "openai"
    api_key: str = ""
    temperature: float = 0.0
    timeout_seconds: int = 120

    @property
    def needs_key(self) -> bool:
        return self.provider == "groq"


@dataclass
class Settings:
    assistant: AssistantConfig
    llm: LLMConfig  # simülatör LLM'i (yönlendirmeli mod)
    judge: LLMConfig  # değerlendirmede llm-rubric hakemi (promptfoo); verilmezse llm ile aynı
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

    llm_yaml = dict(data.get("llm") or {})
    judge_yaml = dict(data.get("judge") or {})
    llm = _llm_config(llm_yaml, "LLM_API_KEY", "llm")
    # Hakem, verilmeyen alanları llm'den alır; sağlayıcı değişiyorsa URL/anahtar llm'den taşınmaz
    same_provider = str(judge_yaml.get("provider", llm.provider)).lower() == llm.provider
    inherited = {k: v for k, v in llm_yaml.items() if k != "api_key" and (same_provider or k != "base_url")}
    judge = _llm_config({**inherited, **judge_yaml}, "JUDGE_API_KEY", "judge",
                        fallback_key=llm.api_key if same_provider else "")
    return Settings(
        assistant=AssistantConfig(**data["assistant"]),
        llm=llm,
        judge=judge,
        output_dir=path.parent / data.get("output_dir", "runs"),
        path=path,
    )


# Ortama göre değişen ayarlar .env'den de verilebilir; doluysa config.yaml'daki değerin önüne geçer
ENV_OVERRIDES = {
    "ASSISTANT_BASE_URL": ("assistant", "base_url"),
    "CHATBOT_MESSAGE_URL": ("assistant", "chatbot_message_url"),
    "LLM_PROVIDER": ("llm", "provider"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "LLM_MODEL": ("llm", "model"),
    "JUDGE_PROVIDER": ("judge", "provider"),
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


def _llm_config(raw: dict, key_env: str, section: str, fallback_key: str = "") -> LLMConfig:
    provider = str(raw.get("provider", "openai")).lower()
    if provider not in PROVIDERS:
        raise ConfigError(f"config.yaml {section}.provider geçersiz: {provider} (seçenekler: {', '.join(PROVIDERS)})")
    raw = {**raw, "provider": provider}
    if provider == "groq":
        raw.setdefault("base_url", GROQ_BASE_URL)
    if not raw.get("base_url") or not raw.get("model"):
        raise ConfigError(f"config.yaml {section}: base_url ve model gerekli")
    raw["api_key"] = (
        os.environ.get(key_env)
        or (os.environ.get(GROQ_KEY_ENV) if provider == "groq" else None)
        or raw.get("api_key")
        or fallback_key
        or ("" if provider == "groq" else "yok")  # yerel endpoint'ler anahtar istemez
    )
    return LLMConfig(**raw)


def ensure_api_key(cfg: LLMConfig, label: str, prompt=None) -> None:
    """Anahtar isteyen sağlayıcıda anahtar yoksa terminalden (görünmez) sorar.

    Anahtar hiçbir dosyaya yazılmaz; sadece bu sürecin ortamına konur ki promptfoo'nun
    başlattığı provider süreci de aynı anahtarı görsün.
    """
    if not cfg.needs_key or cfg.api_key:
        return
    key = os.environ.get(GROQ_KEY_ENV, "").strip()
    if not key:
        if prompt is None:
            if not _interactive():
                raise ConfigError(f"{label} için {GROQ_KEY_ENV} tanımlı değil (.env'e yazın veya terminalden çalıştırın)")
            prompt = getpass.getpass
        key = prompt(f"{label} için Groq API anahtarı ({GROQ_KEY_ENV}, yazarken görünmez): ").strip()
        if not key:
            raise ConfigError(f"{label} için Groq API anahtarı girilmedi")
        os.environ[GROQ_KEY_ENV] = key
    cfg.api_key = key


def _interactive() -> bool:
    """Gerçekten bir terminal var mı? Windows'ta stdin NUL'a bağlıyken isatty() yine True döner;
    getpass da konsoldan okuduğu için sonsuza kadar bekler. Bu yüzden konsol modu ayrıca sorulur."""
    try:
        if not sys.stdin or not sys.stdin.isatty():
            return False
    except (AttributeError, ValueError):
        return False
    if os.name != "nt":
        return True
    import ctypes
    import msvcrt

    try:
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
    except (OSError, ValueError, AttributeError):
        return False
    mode = ctypes.c_uint32()
    return bool(ctypes.windll.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))
