"""Sohbet döngüsü: sohbeti başlatır, simüle müşteriyle yürütür, exit kriterinde bitirir, transcript yazar."""

import json
import time
from datetime import datetime
from pathlib import Path

from .reply import Reply, _norm
from .scenario import Scenario
from .user import BITTI, DEVAM, TIKANDI

# Sonuç durumları
HEDEF_TAMAMLANDI = "HEDEF_TAMAMLANDI"  # başarı ifadesi görüldü veya simülatör hedefe ulaşıldı dedi
SCRIPT_TAMAMLANDI = "SCRIPT_TAMAMLANDI"  # script adımları bitti (başarı kararı değerlendirme fazında)
BASARISIZ = "BASARISIZ"  # hata ifadesi görüldü
SIMULATOR_TIKANDI = "TIKANDI"  # simülatör ilerleyemedi (buton yok, LLM tıkandı dedi...)
MAX_TUR = "MAX_TUR"
DONGU = "DONGU"  # asistan art arda aynı cevabı verdi
HATA = "HATA"  # teknik hata (login, HTTP, LLM erişimi...)

LOOP_LIMIT = 3


class Transcript:
    def __init__(self, scenario: Scenario, meta: dict):
        self.data = {
            "senaryo": scenario.to_dict(),
            "meta": meta,
            "conversation_id": None,
            "baslangic": _now(),
            "bitis": None,
            "turlar": [],
            "sonuc": None,
        }

    def add_assistant(self, tur: int, reply: Reply, sure_ms: int) -> None:
        self.data["turlar"].append(
            {"tur": tur, "rol": "asistan", "zaman": _now(), "sure_ms": sure_ms, "cevap": reply.to_dict(), "ham": reply.raw}
        )

    def add_customer(self, tur: int, decision, gonderilen: str, buton: dict | None) -> None:
        self.data["turlar"].append(
            {"tur": tur, "rol": "musteri", "zaman": _now(), "karar": decision.to_dict(), "gonderilen": gonderilen, "buton": buton}
        )

    def finish(self, durum: str, gerekce: str, tur_sayisi: int) -> None:
        self.data["bitis"] = _now()
        self.data["sonuc"] = {"durum": durum, "gerekce": gerekce, "tur_sayisi": tur_sayisi}

    def save(self, output_dir: Path) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        path = output_dir / f"{stamp}_{self.data['senaryo']['id']}.json"
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return path


def run_scenario(scenario: Scenario, client, user, meta: dict, on_event=None) -> Transcript:
    """on_event(rol, metin): konsola canlı yazdırmak için opsiyonel geri çağırım."""
    emit = on_event or (lambda *_: None)
    transcript = Transcript(scenario, meta)
    tur = 0
    try:
        t0 = time.monotonic()
        conv = client.new_conversation()
        transcript.data["conversation_id"] = conv.id
        reply = conv.send("/get_started")  # açılış komutu, simülatörün repliği sayılmaz
        transcript.add_assistant(0, reply, _ms(t0))
        emit("asistan", reply.render())

        recent: list[str] = []
        while True:
            if tur >= scenario.max_tur:
                transcript.finish(MAX_TUR, f"{scenario.max_tur} tur sınırına ulaşıldı", tur)
                break

            decision = user.next(reply)
            if decision.durum == BITTI:
                durum = SCRIPT_TAMAMLANDI if scenario.mod == "script" else HEDEF_TAMAMLANDI
                transcript.finish(durum, decision.gerekce, tur)
                break
            if decision.durum == TIKANDI:
                transcript.finish(SIMULATOR_TIKANDI, decision.gerekce, tur)
                break
            assert decision.durum == DEVAM

            tur += 1
            text, button = decision.deger, None
            if decision.aksiyon == "buton":
                found = reply.find_button(decision.deger)
                if not found:
                    transcript.add_customer(tur, decision, "", None)
                    transcript.finish(SIMULATOR_TIKANDI, f"'{decision.deger}' butonu asistanın cevabında yok", tur)
                    break
                button = found.to_dict()
                text = found.payload or found.title
            transcript.add_customer(tur, decision, text, button)
            emit("musteri", f"[{button['title']}] → {text}" if button else text)

            t0 = time.monotonic()
            reply = conv.send(text)
            transcript.add_assistant(tur, reply, _ms(t0))
            emit("asistan", reply.render())

            hit = _contains_any(reply.text, scenario.hata_ifadeleri)
            if hit:
                transcript.finish(BASARISIZ, f"Hata ifadesi görüldü: '{hit}'", tur)
                break
            hit = _contains_any(reply.text, scenario.basari_ifadeleri)
            if hit:
                transcript.finish(HEDEF_TAMAMLANDI, f"Başarı ifadesi görüldü: '{hit}'", tur)
                break

            recent = (recent + [_norm(reply.render())])[-LOOP_LIMIT:]
            if len(recent) == LOOP_LIMIT and len(set(recent)) == 1:
                transcript.finish(DONGU, f"Asistan art arda {LOOP_LIMIT} kez aynı cevabı verdi", tur)
                break
    except Exception as e:  # koşum yarıda kalsa bile transcript yazılsın
        transcript.finish(HATA, f"{type(e).__name__}: {e}", tur)
    return transcript


def _contains_any(text: str, phrases: list[str]) -> str | None:
    t = _norm(text)
    return next((p for p in phrases if _norm(p) in t), None)


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
