"""Transcript'e bakan promptfoo Python assertion'ları.

Senaryo dosyasındaki kısayollar (type: durum, type: max-tur) bunlara çevrilir.
promptfoo bu dosyayı da dosya yolundan yükler; context["config"] assertion'ın ayarlarıdır.
"""


def _sonuc(context) -> dict:
    metadata = (context.get("providerResponse") or {}).get("metadata") or {}
    return metadata.get("sonuc") or {}


def durum(output, context):
    """Sohbet izin verilen bir sonuç durumuyla bitmeli (ör. HEDEF_TAMAMLANDI)."""
    izinli = context["config"]["izinli"]
    sonuc = _sonuc(context)
    ok = sonuc.get("durum") in izinli
    reason = f"Sonuç {sonuc.get('durum')} ({sonuc.get('gerekce', '')})"
    if not ok:
        reason += f"; beklenen: {', '.join(izinli)}"
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reason": reason}


def max_tur(output, context):
    """Sohbet en fazla N müşteri turunda bitmeli."""
    limit = int(context["config"]["max"])
    tur = _sonuc(context).get("tur_sayisi")
    ok = tur is not None and tur <= limit
    return {"pass": ok, "score": 1.0 if ok else 0.0, "reason": f"{tur} tur (sınır {limit})"}
