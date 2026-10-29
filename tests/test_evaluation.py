import json
from pathlib import Path

import pytest

from assisteval.cli import main
from assisteval.config import load_settings
from assisteval.evaluation import asserts
from assisteval.evaluation import promptfoo as pf
from assisteval.evaluation.provider import call_api
from assisteval.simulator.scenario import Scenario


@pytest.fixture
def work(tmp_path):
    folder = tmp_path / "calisma"
    assert main(["init", str(folder)]) == 0
    return folder


def scenario(degerlendirme):
    return Scenario(id="T-1", baslik="t", mod="script", path=Path("t.yaml"), degerlendirme=degerlendirme)


def test_expand_assertions_shortcuts_and_passthrough():
    out = pf.expand_assertions(scenario([
        {"type": "durum", "value": "HEDEF_TAMAMLANDI"},
        {"type": "max-tur", "value": 6, "metric": "hiz"},
        {"type": "llm-rubric", "value": "Nazik", "metric": "uslup"},
    ]))
    assert out[0] == {"type": "python", "value": f"file://{pf.ASSERTS_FILE}:durum", "metric": "gorev",
                      "config": {"izinli": ["HEDEF_TAMAMLANDI"]}}
    assert out[1]["config"] == {"max": 6} and out[1]["metric"] == "hiz"
    assert out[2] == {"type": "llm-rubric", "value": "Nazik", "metric": "uslup"}
    # degerlendirme yoksa: sohbet tamamlanmış olmalı
    assert pf.expand_assertions(scenario([]))[0]["config"]["izinli"] == pf.DEFAULT_DURUM


def test_asserts_read_provider_metadata():
    ctx = {"providerResponse": {"metadata": {"sonuc": {"durum": "MAX_TUR", "gerekce": "sınır", "tur_sayisi": 9}}}}
    assert asserts.durum("", {**ctx, "config": {"izinli": ["HEDEF_TAMAMLANDI"]}})["pass"] is False
    assert asserts.durum("", {**ctx, "config": {"izinli": ["MAX_TUR"]}})["pass"] is True
    assert asserts.max_tur("", {**ctx, "config": {"max": 8}})["pass"] is False
    assert asserts.max_tur("", {**ctx, "config": {"max": 9}})["pass"] is True


def test_provider_runs_scenario_and_returns_transcript(work):
    cfg = {"config": str(work / "config.yaml"), "assistant": "mock", "llm": "mock"}
    dosya = str(work / "scenarios" / "ornek" / "EFT-001_kayitli_aliciya_eft.yaml")
    result = call_api("EFT-001", {"config": cfg}, {"vars": {"senaryo": "EFT-001", "dosya": dosya}})
    assert "error" not in result
    assert "MÜŞTERİ: [buton: Onayla]" in result["output"]
    assert result["metadata"]["sonuc"]["durum"] == "HEDEF_TAMAMLANDI"
    assert Path(result["metadata"]["transcript"]).exists()


def test_provider_reports_errors_instead_of_raising(work):
    result = call_api("x", {"config": {"config": str(work / "config.yaml")}}, {"vars": {"dosya": "yok.yaml"}})
    assert "FileNotFoundError" in result["error"]


def test_config_has_no_secrets_and_relative_files(work, monkeypatch):
    monkeypatch.setenv("JUDGE_API_KEY", "gizli-anahtar")
    settings = load_settings(work / "config.yaml")
    from assisteval.simulator.scenario import load_scenario

    s = load_scenario(work / "scenarios" / "ornek" / "KMP-001_kampanya_listele.yaml")
    run_dir = pf.prepare_run([s], settings, "mock", "mock")
    text = (run_dir / "promptfooconfig.yaml").read_text(encoding="utf-8")
    assert "gizli-anahtar" not in text
    assert "file://assisteval_provider.py" in text and (run_dir / pf.ASSERTS_FILE).exists()
    assert pf.promptfoo_env(settings)["OPENAI_API_KEY"] == "gizli-anahtar"


def _promptfoo_available() -> bool:
    try:
        pf.find_promptfoo()
        return True
    except pf.PromptfooError:
        return False


@pytest.mark.skipif(not _promptfoo_available(), reason="promptfoo kurulu değil")
def test_eval_end_to_end_offline(work, capsys):
    rc = main(["--config", str(work / "config.yaml"), "--assistant", "mock",
               "eval", str(work / "scenarios" / "ornek"), "--llm", "mock", "--judge", "mock"])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "2/2 senaryo geçti" in out
    run_dir = next((work / "runs").glob("eval-*"))
    assert (run_dir / "rapor.html").exists()
    rows = pf.summarize(run_dir / "sonuclar.json")
    assert {r["durum"] for r in rows} == {"GEÇTİ"}
    assert json.loads((run_dir / "sonuclar.json").read_text(encoding="utf-8"))["results"]["stats"]["successes"] == 2
