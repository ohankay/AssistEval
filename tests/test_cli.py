import json

from assisteval import __version__
from assisteval.cli import main
from tests.fakes import FAKE_CREDS, FakeServer, point_workspace_to


def test_init_check_and_run(tmp_path, monkeypatch, capsys):
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

    with FakeServer() as srv:
        point_workspace_to(work, srv)
        for name in FAKE_CREDS:  # ilk check boş .env'i ortama yükledi; load_dotenv mevcut değeri ezmez
            monkeypatch.delenv(name, raising=False)
        capsys.readouterr()
        assert main(["--config", str(work / "config.yaml"), "check", "--llm"]) == 0
        report = json.loads(capsys.readouterr().out)
        assert report["env"] == "tamam" and report["simulator"]["baglanti"] == report["judge"]["baglanti"] == "tamam"
        rc = main(["--config", str(work / "config.yaml"), "run", str(work / "scenarios" / "ornek"), "--sessiz"])
    assert rc == 0
    runs = sorted((work / "runs").glob("*.json"))  # runs/ config.yaml'ın yanında
    assert len(runs) == 2
    durumlar = {json.loads(p.read_text(encoding="utf-8"))["sonuc"]["durum"] for p in runs}
    assert durumlar == {"HEDEF_TAMAMLANDI", "SCRIPT_TAMAMLANDI"}


def test_missing_config_is_reported(tmp_path, capsys):
    assert main(["--config", str(tmp_path / "yok.yaml"), "smoke"]) == 2
    assert "assisteval init" in capsys.readouterr().err


def test_promptfoo_passthrough_keeps_option_arguments(monkeypatch, tmp_path):
    from assisteval.evaluation import promptfoo as pf

    calls = []
    monkeypatch.setattr(pf, "run_promptfoo", lambda args, settings, cwd=None: calls.append(args) or 0)
    cfg = str(tmp_path / "yok.yaml")  # config olmadan da çalışmalı
    assert main(["--config", cfg, "promptfoo", "--version"]) == 0
    assert main(["--config", cfg, "promptfoo", "view", "--port", "15500", "-y"]) == 0
    assert calls == [["--version"], ["view", "--port", "15500", "-y"]]
