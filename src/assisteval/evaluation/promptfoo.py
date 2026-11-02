"""Senaryolardan promptfoo config'i üretir ve paketle gelen promptfoo'yu çalıştırır.

promptfoo şu sırayla aranır:
  1. ASSISTEVAL_PROMPTFOO: entrypoint.js yolu (node ile çalışır, ASSISTEVAL_NODE veya PATH'teki node) ya da bir komut
  2. Offline paket: <kurulum>/node/node.exe + <kurulum>/promptfoo/node_modules/promptfoo/dist/src/entrypoint.js
  3. PATH'teki `promptfoo` komutu (geliştirme ortamı)
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import yaml

from ..config import Settings
from ..simulator.runner import HEDEF_TAMAMLANDI, SCRIPT_TAMAMLANDI
from ..simulator.scenario import Scenario

HERE = Path(__file__).resolve().parent
ENTRYPOINT = Path("promptfoo", "node_modules", "promptfoo", "dist", "src", "entrypoint.js")
DEFAULT_DURUM = [HEDEF_TAMAMLANDI, SCRIPT_TAMAMLANDI]

# Çalışma klasörüne kopyalanan dosyalar; config'te göreli yolla verilir (Windows'ta "C:" iki noktası
# promptfoo'nun "file://dosya.py:fonksiyon" sözdizimiyle karışmasın diye)
PROVIDER_FILE = "assisteval_provider.py"
ASSERTS_FILE = "assisteval_asserts.py"
# Hakem ayarlı değilken promptfoo varsayılanı olan bulut OpenAI adresine gitmesin: kapalı yerel port
NO_JUDGE_URL = "http://127.0.0.1:9/v1"


class PromptfooError(Exception):
    pass


def find_promptfoo() -> list[str]:
    override = os.environ.get("ASSISTEVAL_PROMPTFOO")
    if override:
        if override.endswith(".js"):
            node = os.environ.get("ASSISTEVAL_NODE") or shutil.which("node")
            if not node:
                raise PromptfooError("ASSISTEVAL_PROMPTFOO bir .js dosyası ama node bulunamadı (ASSISTEVAL_NODE)")
            return [node, override]
        return [override]
    home = Path(sys.prefix)
    node = home / "node" / ("node.exe" if os.name == "nt" else "node")
    if node.exists() and (home / ENTRYPOINT).exists():
        return [str(node), str(home / ENTRYPOINT)]
    found = shutil.which("promptfoo")
    if found:
        return [found]
    raise PromptfooError(
        "promptfoo bulunamadı. Offline paketle kurulumda otomatik gelir (install.cmd); "
        "geliştirme ortamında 'npm install -g promptfoo' veya ASSISTEVAL_PROMPTFOO ayarlayın."
    )


def promptfoo_env(settings: Settings | None) -> dict:
    env = dict(os.environ)
    env.update(
        PROMPTFOO_DISABLE_TELEMETRY="1",
        PROMPTFOO_DISABLE_UPDATE="1",
        PROMPTFOO_PYTHON=sys.executable,  # provider ve assertion'lar assisteval'in Python'unda çalışsın
        PYTHONIOENCODING="utf-8",
    )
    if settings:
        # Koşum geçmişi (promptfoo view) çalışma klasöründe dursun
        env["PROMPTFOO_CONFIG_DIR"] = str(settings.path.parent / ".promptfoo")
        # promptfoo'nun openai sağlayıcısı anahtar ister; yerel sunucu istemiyorsa yer tutucu yeterli.
        # Anahtar config dosyasına yazılmaz.
        env["OPENAI_API_KEY"] = settings.judge.api_key or "yok"
        # promptfoo'nun kendi kendine açtığı openai çağrıları da (varsa) buluta değil hakem sunucusuna gitsin
        env["OPENAI_BASE_URL"] = env["OPENAI_API_BASE_URL"] = settings.judge.base_url or NO_JUDGE_URL
    # İç ağdaki https LLM sunucusunun kurumsal CA'sı Windows deposunda: Node da o depoya güvensin
    if "--use-system-ca" not in env.get("NODE_OPTIONS", ""):
        env["NODE_OPTIONS"] = (env.get("NODE_OPTIONS", "") + " --use-system-ca").strip()
    return env


def run_promptfoo(args: list[str], settings: Settings | None, cwd: Path | None = None) -> int:
    return subprocess.run(find_promptfoo() + args, env=promptfoo_env(settings), cwd=cwd).returncode


def expand_assertions(scenario: Scenario) -> list[dict]:
    """Senaryodaki `degerlendirme` listesini promptfoo assertion'larına çevirir.

    Kısayollar: `durum` (izin verilen sonuç durumları) ve `max-tur`. Diğer her şey (icontains,
    regex, llm-rubric, python...) promptfoo'ya olduğu gibi geçer. Liste boşsa: sohbet tamamlanmış olmalı.
    """
    out = []
    for a in scenario.degerlendirme or [{"type": "durum"}]:
        if a["type"] == "durum":
            value = a.get("value", DEFAULT_DURUM)
            out.append({"type": "python", "value": f"file://{ASSERTS_FILE}:durum", "metric": a.get("metric", "gorev"),
                        "config": {"izinli": [value] if isinstance(value, str) else list(value)}})
        elif a["type"] == "max-tur":
            out.append({"type": "python", "value": f"file://{ASSERTS_FILE}:max_tur",
                        "metric": a.get("metric", "verimlilik"), "config": {"max": int(a["value"])}})
        else:
            out.append(dict(a))
    return out


def judge_provider(settings: Settings) -> dict:
    """llm-rubric hakemi: config.yaml'daki judge (yerel OpenAI uyumlu endpoint)."""
    judge = settings.judge
    config = {"apiBaseUrl": judge.base_url or NO_JUDGE_URL, "temperature": judge.temperature}
    if judge.max_tokens:
        config["max_tokens"] = judge.max_tokens
    if judge.extra_body:
        config["passthrough"] = dict(judge.extra_body)  # isteğe olduğu gibi eklenir
    return {"id": f"openai:chat:{judge.model or 'judge-ayarli-degil'}", "config": config}


def build_config(scenarios: list[Scenario], settings: Settings) -> dict:
    return {
        "description": f"AssistEval ({len(scenarios)} senaryo)",
        "prompts": ["{{senaryo}}"],
        "providers": [{
            "id": f"file://{PROVIDER_FILE}",
            "label": "asistan",
            "config": {"config": str(settings.path)},
        }],
        "defaultTest": {"options": {"provider": judge_provider(settings)}},
        "tests": [
            {
                "description": f"{s.id} · {s.baslik}",
                "vars": {"senaryo": s.id, "dosya": str(s.path.resolve())},
                "assert": expand_assertions(s),
                "metadata": {"senaryo_id": s.id, "etiketler": s.etiketler},
            }
            for s in scenarios
        ],
    }


def prepare_run(scenarios: list[Scenario], settings: Settings) -> Path:
    """runs/eval-<zaman>/ klasörünü config ve provider/assertion dosyalarıyla hazırlar."""
    run_dir = settings.output_dir / f"eval-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(HERE / "provider.py", run_dir / PROVIDER_FILE)
    shutil.copyfile(HERE / "asserts.py", run_dir / ASSERTS_FILE)
    config = build_config(scenarios, settings)
    (run_dir / "promptfooconfig.yaml").write_text(
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return run_dir


def summarize(results_path: Path) -> list[dict]:
    """promptfoo'nun JSON çıktısından senaryo başına özet."""
    data = json.loads(results_path.read_text(encoding="utf-8"))
    rows = []
    for r in data["results"]["results"]:
        components = (r.get("gradingResult") or {}).get("componentResults") or []
        rows.append({
            "senaryo": (r.get("testCase") or {}).get("description", "?"),
            "durum": "HATA" if r.get("error") and not components else ("GEÇTİ" if r.get("success") else "KALDI"),
            "skor": r.get("score"),
            "metrikler": r.get("namedScores") or {},
            "kalanlar": [
                f"{(c.get('assertion') or {}).get('type', '?')}: {c.get('reason', '')}"
                for c in components if not c.get("pass")
            ] + ([r["error"]] if r.get("error") and not components else []),  # assertion varken error = ilk neden
        })
    return rows
