# AssistEval – Claude Code çalışma kuralları

Mobil bankacılık GenAI asistanı için simülasyon + promptfoo değerlendirme platformu.
Kod `src/assisteval/`, testler `tests/` (pytest). Hedef: Windows x64, Python 3.10–3.14.

## Kurulum (geliştirme)
```
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
```

## Çalışma akışı (her değişiklikte uygula)
1. `main` üzerinde doğrudan çalışma; önce dal aç: `git checkout -b <kisa-aciklama>`.
2. Değişikliği yap; davranış değişiyorsa `tests/` altına test ekle/güncelle.
3. Testleri koş: `python -m pytest -q`. Hepsi geçmeden commit etme.
4. `src/**`, `bundle/**` veya `pyproject.toml` değiştiyse offline paket bayatlar ve
   `bundle.yml` CI'daki freshness kontrolü kırılır. Paketi yeniden üret:
   `pip install uv packaging && python scripts/build_bundle.py`
   ve `release/assisteval-windows-x64.zip` dosyasını da commit'e ekle.
5. Commit mesajı Türkçe, kısa ve ne yapıldığını anlatan tek satır (mevcut geçmişle uyumlu).
6. Push'u kullanıcı onayı olmadan yapma. Onay gelince: `git push -u origin <dal>`
   ve gerekiyorsa `gh pr create` ile PR aç.

## Dikkat
- Asistan uç noktalarına ait gerçek kimlik bilgileri, OTP, token `.env` dışında hiçbir dosyaya yazılmaz; `.env` commit edilmez.
- Türkçe karakterler korunmalı (UTF-8); çıktı yönlendirmede encoding'i bozma.
