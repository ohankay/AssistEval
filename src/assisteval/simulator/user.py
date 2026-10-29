"""Simüle müşteri: her turda asistanın son cevabına bakıp sıradaki hamleye karar verir."""

import json
import re
from dataclasses import dataclass

from .reply import Reply
from .scenario import Scenario

DEVAM, BITTI, TIKANDI = "DEVAM", "BITTI", "TIKANDI"

THINK = re.compile(r"<think>.*?</think>", re.DOTALL)


@dataclass
class Decision:
    durum: str
    aksiyon: str = "mesaj"  # "mesaj" | "buton"
    deger: str = ""
    gerekce: str = ""

    def to_dict(self) -> dict:
        return {"durum": self.durum, "aksiyon": self.aksiyon, "deger": self.deger, "gerekce": self.gerekce}


class ScriptUser:
    """Senaryodaki adımları sırayla oynatır."""

    def __init__(self, scenario: Scenario):
        self.steps = scenario.adimlar
        self.index = 0

    def next(self, last_reply: Reply) -> Decision:
        if self.index >= len(self.steps):
            return Decision(BITTI, gerekce="Script adımları tamamlandı")
        step = self.steps[self.index]
        self.index += 1
        if step.buton:
            return Decision(DEVAM, "buton", step.buton, f"Script {self.index}. adım")
        return Decision(DEVAM, "mesaj", step.mesaj, f"Script {self.index}. adım")


class LLMUser:
    """Persona + hedef + yönlendirmeye göre LLM ile replik üretir."""

    MAX_FORMAT_RETRY = 2

    def __init__(self, scenario: Scenario, llm):
        self.llm = llm
        self.messages = [{"role": "system", "content": build_system_prompt(scenario)}]

    def next(self, last_reply: Reply) -> Decision:
        # Roller ters çevrilir: asistanın cevabı LLM'e "user", simülatörün kendi replikleri "assistant" olarak gider
        self.messages.append({"role": "user", "content": "ASİSTAN:\n" + last_reply.render()})
        attempt_messages = list(self.messages)
        for _ in range(self.MAX_FORMAT_RETRY + 1):
            raw = self.llm.chat(attempt_messages)
            decision = parse_decision(raw)
            if decision:
                self.messages.append({"role": "assistant", "content": json.dumps(decision.to_dict(), ensure_ascii=False)})
                return decision
            attempt_messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Geçersiz format. Sadece istenen JSON nesnesini döndür."},
            ]
        return Decision(TIKANDI, gerekce=f"Simülatör LLM'i geçerli JSON üretemedi: {raw[:200]}")


def parse_decision(raw: str) -> Decision | None:
    text = THINK.sub("", raw or "")
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    durum = str(data.get("durum", "")).upper()
    aksiyon = str(data.get("aksiyon", "mesaj")).lower()
    deger = str(data.get("deger") or "").strip()
    if durum not in (DEVAM, BITTI, TIKANDI) or aksiyon not in ("mesaj", "buton"):
        return None
    if durum == DEVAM and not deger:
        return None
    return Decision(durum, aksiyon, deger, str(data.get("gerekce", "")))


def build_system_prompt(s: Scenario) -> str:
    yonlendirme = "\n".join(f"{i}. {y}" for i, y in enumerate(s.yonlendirme, 1)) or "(yok, sadece hedefe odaklan)"
    test_verisi = "\n".join(f"- {k}: {v}" for k, v in s.test_verisi.items()) or "(yok)"
    return f"""Sen bir bankacılık asistanını test eden MÜŞTERİ SİMÜLATÖRÜSÜN. Mobil bankacılık uygulamasındaki dijital asistanla konuşan gerçek bir müşteriyi canlandırıyorsun.

## Persona
{s.persona or "Sıradan bir banka müşterisi."}

## Hedefin
{s.hedef}

## Yönlendirme (bu sıraya ve talimatlara bağlı kal)
{yonlendirme}

## Test verisi
{test_verisi}

## Bitiş koşulları
Başarı: {s.basari_kriteri or "Hedef gerçekleşti."}
Başarısızlık: {s.basarisizlik_kriteri or "Asistan hedefe ulaşmanı engelledi veya aynı yerde takıldı."}

## Kurallar
- Sadece müşteri olarak konuş. Asla asistan gibi cevap verme.
- Kısa, doğal Türkçe cümleler kur; bir mesajda tek bir şey iste.
- Yönlendirmede olmayan bir bilgi istenirse test verisini kullan; orada da yoksa bilmediğini söyle, uydurma.
- Asistanın sunduğu butonlar "[Başlık] → aksiyon" şeklinde listelenir. Yönlendirmeye uyan bir buton varsa butona tıkla (aksiyon: "buton", deger: buton başlığı).
- Hedef gerçekleştiyse durum "BITTI". Asistan reddediyor, aynı yerde dönüyor veya yönlendirmeyle ilerlenemiyorsa "TIKANDI".

## Cevap formatı
Sadece aşağıdaki JSON nesnesini döndür, başka hiçbir şey yazma:
{{"durum": "DEVAM" | "BITTI" | "TIKANDI", "aksiyon": "mesaj" | "buton", "deger": "<mesaj metni veya buton başlığı>", "gerekce": "<kısa açıklama>"}}"""
