import json
from pathlib import Path

import pytest

from assisteval.simulator.llm import MockLLM
from assisteval.simulator.mock_assistant import MockBank, MockServer
from assisteval.simulator.runner import BASARISIZ, DONGU, HATA, HEDEF_TAMAMLANDI, MAX_TUR, SCRIPT_TAMAMLANDI, SIMULATOR_TIKANDI, run_scenario
from assisteval.simulator.scenario import Scenario, Step, load_scenario
from assisteval.simulator.user import LLMUser, ScriptUser, parse_decision
from tests.test_assistant_client import make_client

EXAMPLES = Path(__file__).parent.parent / "src" / "assisteval" / "templates" / "scenarios" / "ornek"


@pytest.fixture
def client():
    with MockServer(MockBank()) as srv:
        yield make_client(srv)


def script(*steps, **kw) -> Scenario:
    return Scenario(id="T", baslik="t", mod="script", path=Path("t.yaml"), adimlar=list(steps), **kw)


def test_example_script_scenario(client, tmp_path):
    s = load_scenario(EXAMPLES / "KMP-001_kampanya_listele.yaml")
    t = run_scenario(s, client, ScriptUser(s), {})
    assert t.data["sonuc"]["durum"] == SCRIPT_TAMAMLANDI
    clicked = [x for x in t.data["turlar"] if x["rol"] == "musteri"][1]
    assert clicked["buton"]["title"] == "Market Kampanyası › Detay"
    saved = json.loads(t.save(tmp_path).read_text(encoding="utf-8"))
    assert saved["conversation_id"] and saved["turlar"][0]["tur"] == 0  # /get_started = tur 0


def test_example_guided_scenario_with_mock_llm(client):
    s = load_scenario(EXAMPLES / "EFT-001_kayitli_aliciya_eft.yaml")
    t = run_scenario(s, client, LLMUser(s, MockLLM(s.yonlendirme)), {})
    assert t.data["sonuc"] == {"durum": HEDEF_TAMAMLANDI, "gerekce": "Başarı ifadesi görüldü: 'başarıyla gerçekleştirildi'", "tur_sayisi": 4}


def test_missing_button_stops_as_stuck(client):
    s = script(Step(buton="Olmayan Buton"))
    t = run_scenario(s, client, ScriptUser(s), {})
    assert t.data["sonuc"]["durum"] == SIMULATOR_TIKANDI


def test_error_phrase_fails(client):
    s = script(Step(mesaj="saçma sapan"), hata_ifadeleri=["anlayamadım"])
    assert run_scenario(s, client, ScriptUser(s), {}).data["sonuc"]["durum"] == BASARISIZ


def test_loop_detection(client):
    s = script(*[Step(mesaj="/kampanyalar")] * 5)
    assert run_scenario(s, client, ScriptUser(s), {}).data["sonuc"]["durum"] == DONGU


def test_max_turns(client):
    s = script(Step(mesaj="Kampanya listele"), Step(mesaj="Para göndermek istiyorum"), max_tur=1)
    assert run_scenario(s, client, ScriptUser(s), {}).data["sonuc"]["durum"] == MAX_TUR


def test_technical_error_still_produces_transcript():
    class Broken:
        def new_conversation(self):
            raise ConnectionError("erişim yok")

    s = script(Step(mesaj="x"))
    t = run_scenario(s, Broken(), ScriptUser(s), {})
    assert t.data["sonuc"]["durum"] == HATA and "erişim yok" in t.data["sonuc"]["gerekce"]


def test_parse_decision_handles_qwen_think_and_noise():
    d = parse_decision('<think>düşünüyorum {x}</think>\nTabii: {"durum": "devam", "aksiyon": "buton", "deger": "Onayla"}')
    assert (d.durum, d.aksiyon, d.deger) == ("DEVAM", "buton", "Onayla")
    assert parse_decision("JSON yok") is None
    assert parse_decision('{"durum": "DEVAM", "deger": ""}') is None


def test_llm_user_retries_on_bad_format(client):
    class Flaky:
        def __init__(self):
            self.calls = 0

        def chat(self, messages):
            self.calls += 1
            return "pardon" if self.calls == 1 else '{"durum": "BITTI", "aksiyon": "mesaj", "deger": "", "gerekce": "ok"}'

    s = Scenario(id="T", baslik="t", mod="yonlendirmeli", path=Path("t.yaml"), hedef="test")
    llm = Flaky()
    t = run_scenario(s, client, LLMUser(s, llm), {})
    assert t.data["sonuc"]["durum"] == HEDEF_TAMAMLANDI and llm.calls == 2
