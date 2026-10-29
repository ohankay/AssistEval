"""promptfoo Python provider'ı: her test için senaryoyu simülatörle koşar, sohbeti çıktı olarak döner.

promptfoo bu dosyayı kendi başlattığı Python sürecinde, dosya yolundan yükler
(PROMPTFOO_PYTHON = assisteval'in kurulu olduğu Python). Bu yüzden içe aktarmalar mutlak.

Dönen metadata (sonuç durumu, tur sayısı, transcript yolu) assertion'larda
context["providerResponse"]["metadata"] olarak okunur.
"""

from assisteval.config import load_settings
from assisteval.runtime import assistant_client, simulated_user
from assisteval.simulator.runner import HATA, run_scenario
from assisteval.simulator.scenario import load_scenario


def call_api(prompt, options, context):
    try:
        return _run((options or {}).get("config") or {}, (context or {}).get("vars") or {})
    except Exception as e:  # noqa: BLE001 - promptfoo'da traceback yerine okunur hata görünsün
        return {"error": f"{type(e).__name__}: {e}"}


def _run(cfg: dict, vars_: dict) -> dict:
    scenario_path = vars_["dosya"]
    settings = load_settings(cfg["config"])
    scenario = load_scenario(scenario_path)
    with assistant_client(settings, cfg.get("assistant", "real")) as client:
        user, llm_name = simulated_user(scenario, settings, cfg.get("llm", "openai"))
        meta = {
            "kaynak": "promptfoo",
            "asistan": cfg.get("assistant", "real"),
            "asistan_url": client.cfg.chatbot_message_url,
            "simulator_llm": llm_name,
        }
        transcript = run_scenario(scenario, client, user, meta)
    path = transcript.save(settings.output_dir)

    sonuc = transcript.data["sonuc"]
    result = {
        "output": transcript.render(),
        "metadata": {
            "senaryo_id": scenario.id,
            "sonuc": sonuc,
            "conversation_id": transcript.data["conversation_id"],
            "transcript": str(path),
        },
    }
    if sonuc["durum"] == HATA:  # teknik hata: promptfoo'da başarısız değil "hata" olarak görünsün
        result["error"] = f"{scenario.id}: {sonuc['gerekce']} (transcript: {path})"
    return result
