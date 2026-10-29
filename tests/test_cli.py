import json

from assisteval import __version__
from assisteval.cli import main


def test_init_check_and_offline_mock_run(tmp_path, monkeypatch, capsys):
    work = tmp_path / "calisma"
    assert main(["init", str(work)]) == 0
    assert (work / "config.yaml").exists() and (work / ".env").exists()
    assert sorted(p.name for p in (work / "scenarios" / "ornek").iterdir()) == [
        "EFT-001_kayitli_aliciya_eft.yaml", "KMP-001_kampanya_listele.yaml"]
    assert main(["init", str(work)]) == 0  # ikinci kez: mevcut dosyalara dokunmaz

    for name in ("CUSTOMER_ID", "GSM_NUMBER", "PASSWORD", "EXT_U_PASSWORD", "REG_EXT_U_PASSWORD", "REG_USER_ID"):
        monkeypatch.delenv(name, raising=False)
    capsys.readouterr()
    assert main(["--config", str(work / "config.yaml"), "check"]) == 1  # .env henüz boş
    report = json.loads(capsys.readouterr().out)
    assert report["version"] == __version__ and report["bits"] in (32, 64)
    assert "GSM_NUMBER" in report["env"]

    rc = main(["--config", str(work / "config.yaml"), "--assistant", "mock",
               "run", str(work / "scenarios" / "ornek"), "--llm", "mock", "--sessiz"])
    assert rc == 0
    runs = sorted((work / "runs").glob("*.json"))  # runs/ config.yaml'ın yanında
    assert len(runs) == 2
    durumlar = {json.loads(p.read_text(encoding="utf-8"))["sonuc"]["durum"] for p in runs}
    assert durumlar == {"HEDEF_TAMAMLANDI", "SCRIPT_TAMAMLANDI"}


def test_missing_config_is_reported(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "yok.yaml"), "smoke"]) == 2
    assert "assisteval init" in capsys.readouterr().err
