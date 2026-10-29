"""Senaryo dosyası (YAML) yükleme ve doğrulama.

İki mod var:
  script        → `adimlar` sırayla gönderilir (LLM gerekmez, en tekrarlanabilir mod)
  yonlendirmeli → simülatör LLM'i persona/hedef/yönlendirmeye göre replik üretir
"""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

MODES = ("script", "yonlendirmeli")


class ScenarioError(Exception):
    pass


@dataclass
class Step:
    """Script modunda bir adım: ya serbest mesaj ya da buton tıklaması."""

    mesaj: str | None = None
    buton: str | None = None


@dataclass
class Scenario:
    id: str
    baslik: str
    mod: str
    path: Path
    etiketler: list[str] = field(default_factory=list)
    persona: str = ""
    hedef: str = ""
    yonlendirme: list[str] = field(default_factory=list)
    adimlar: list[Step] = field(default_factory=list)
    test_verisi: dict = field(default_factory=dict)
    max_tur: int = 10
    basari_ifadeleri: list[str] = field(default_factory=list)
    hata_ifadeleri: list[str] = field(default_factory=list)
    basari_kriteri: str = ""
    basarisizlik_kriteri: str = ""
    degerlendirme: list[dict] = field(default_factory=list)  # promptfoo assertion'ları (+ kısayollar)

    def to_dict(self) -> dict:
        return {"id": self.id, "baslik": self.baslik, "mod": self.mod, "dosya": str(self.path), "etiketler": self.etiketler}


def load_scenario(path: str | Path) -> Scenario:
    path = Path(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    for key in ("id", "baslik", "mod"):
        if not data.get(key):
            raise ScenarioError(f"{path}: '{key}' alanı zorunlu")
    mod = data["mod"]
    if mod not in MODES:
        raise ScenarioError(f"{path}: mod '{mod}' geçersiz, {MODES} olmalı")

    adimlar = [_parse_step(path, i, s) for i, s in enumerate(data.get("adimlar") or [], 1)]
    if mod == "script" and not adimlar:
        raise ScenarioError(f"{path}: script modunda 'adimlar' boş olamaz")
    if mod == "yonlendirmeli" and not data.get("hedef"):
        raise ScenarioError(f"{path}: yonlendirmeli modda 'hedef' zorunlu")

    cikis = data.get("cikis") or {}
    return Scenario(
        id=str(data["id"]),
        baslik=data["baslik"],
        mod=mod,
        path=path,
        etiketler=list(data.get("etiketler") or []),
        persona=data.get("persona", ""),
        hedef=data.get("hedef", ""),
        yonlendirme=list(data.get("yonlendirme") or []),
        adimlar=adimlar,
        test_verisi=dict(data.get("test_verisi") or {}),
        max_tur=int(cikis.get("max_tur", 10)),
        basari_ifadeleri=list(cikis.get("basari_ifadeleri") or []),
        hata_ifadeleri=list(cikis.get("hata_ifadeleri") or []),
        basari_kriteri=cikis.get("basari", ""),
        basarisizlik_kriteri=cikis.get("basarisizlik", ""),
        degerlendirme=_parse_assertions(path, data.get("degerlendirme")),
    )


def _parse_assertions(path: Path, raw) -> list[dict]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(a, dict) and a.get("type") for a in raw):
        raise ScenarioError(f"{path}: 'degerlendirme' her biri 'type' alanı olan bir liste olmalı")
    return raw


def _parse_step(path: Path, i: int, raw) -> Step:
    if isinstance(raw, str):
        return Step(mesaj=raw)
    if isinstance(raw, dict) and len(raw) == 1 and next(iter(raw)) in ("mesaj", "buton"):
        return Step(**{k: str(v) for k, v in raw.items()})
    raise ScenarioError(f"{path}: {i}. adım 'mesaj: ...' veya 'buton: ...' olmalı")
