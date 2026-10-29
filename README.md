# AssistEval

Mobil bankacılıktaki GenAI asistan için simülasyon, değerlendirme ve izleme platformu.
Amaç, asistan geliştirilirken kritik senaryoları sürekli koşup modelde kayma (drift) olup olmadığını yakalamak.

| Katman | Durum |
|---|---|
| **Simülasyon:** senaryoya (replik yönlendirme dokümanına) bağlı kalarak sohbet başlatma, yürütme, exit kriterinde bitirme, transcript kaydı | ✅ `src/assisteval/simulator` |
| **Değerlendirme:** transcript'lerin promptfoo ile skorlanması | ⏳ |
| **Raporlama ve izleme:** sonuçların biriktirilmesi, drift dashboard'u, senaryo kütüphanesi arayüzü | ⏳ |

## Mimari

```
Senaryo (YAML) ──▶ runner (döngü, exit kontrolü) ──▶ assistant_client ──▶ Bankacılık asistanı
                     │   └─ simüle müşteri: ScriptUser | LLMUser (Qwen / mock)
                     ▼
               runs/<zaman>_<id>.json  (transcript)
```

| Modül | Görevi |
|---|---|
| `src/assisteval/simulator/assistant_client.py` | LoginForMobileBranch → InitialLogin → SendSmsOtp → OtpLoginCompleteNew → ChatBotInsertConversation → Chat/Message. Token 4 dk'da bir (veya 401'de) yenilenir, conversationId korunur |
| `src/assisteval/simulator/reply.py` | Asistanın JSON cevabını metin + kart + buton (başlık → aksiyon) olarak ayrıştırır |
| `src/assisteval/simulator/scenario.py` | Senaryo YAML'ını yükler ve doğrular |
| `src/assisteval/simulator/user.py` | Simüle müşteri: `ScriptUser` (adımları sırayla oynatır), `LLMUser` (persona + hedef + yönlendirme ile LLM'e karar verdirir) |
| `src/assisteval/simulator/llm.py` | OpenAI uyumlu LLM istemcisi (vLLM / Ollama ile Qwen) + `MockLLM` |
| `src/assisteval/simulator/runner.py` | Sohbet döngüsü, exit kuralları, transcript |
| `src/assisteval/simulator/mock_assistant.py` | Gerçek servislerle aynı endpoint'leri taklit eden sahte sunucu |

**conversationId kuralı:** her senaryo yeni bir conversationId ile başlar (modelde sıfırdan bağlam).
Senaryo içindeki tüm turlar aynı conversationId ile gider. `/get_started` açılış komutudur ve "tur 0" olarak kaydedilir.

## Kurulum (Windows, internet gerekmez)

Çalışacağı ortamda internet erişimi kısıtlı olduğu için tüm bağımlılıklar hazır paketlerin içinde gelir.
Python'unuzun mimarisine uygun zip'i kullanın:

| Python | Paket |
|---|---|
| 64-bit (çoğu bilgisayar) | [`release/assisteval-windows-x64.zip`](release/assisteval-windows-x64.zip) |
| 32-bit | [`release/assisteval-windows-x86.zip`](release/assisteval-windows-x86.zip) |

Her zip; Python 3.10–3.14 için o mimarinin tüm wheel'lerini, `install.cmd`'yi ve
[kurulum rehberini](bundle/KURULUM_REHBERI.md) içerir. Kısaca:

```bat
install.cmd                               :: %USERPROFILE%\.assisteval altına offline kurar
assisteval init C:\AssistEval\calisma     :: config.yaml, .env, örnek senaryolar
cd /d C:\AssistEval\calisma
assisteval check                          :: kurulum ve ayar kontrolü (ağ gerektirmez)
```

`install.cmd` Python'un mimarisini (32/64 bit) kontrol eder. Yanlış zip seçilirse hangi paketin gerektiğini söyler.

Gizli bilgiler (test müşterisi, servis kullanıcısı şifreleri) çalışma klasöründeki `.env` dosyasına,
gizli olmayan ayarlar (URL'ler, cihaz bilgisi, LLM endpoint'i) `config.yaml`'a yazılır. `.env` her zaman
`config.yaml`'ın yanından okunur, transcript'ler de onun yanındaki `runs/` klasörüne yazılır.

**Ağ notları:** AssistEval Windows sertifika deposunu kullanır (`truststore`), kurumsal CA'lar için ek ayar
gerekmez. Proxy için `HTTPS_PROXY` / `NO_PROXY`, özel CA dosyası için `REQUESTS_CA_BUNDLE` kullanılabilir.

## Kullanım

```bash
assisteval smoke                                   # bağlantı kontrolü: login + yeni sohbet + /get_started
assisteval smoke --mesaj "Kampanya listele"

assisteval run scenarios/ornek                     # klasördeki tüm senaryolar
assisteval run scenarios/ornek/KMP-001_kampanya_listele.yaml
assisteval run scenarios/ornek --llm mock          # LLM yokken yönlendirmeli mod

assisteval --assistant mock run scenarios/ornek --llm mock   # sahte asistanla tamamen offline deneme
```

## Senaryo formatı

İki mod var:

- **`script`**: `adimlar` sırayla gönderilir. LLM gerekmez, en tekrarlanabilir mod (regresyon için ideal).
- **`yonlendirmeli`**: simülatör LLM'i persona, hedef ve yönlendirmeye göre replik üretir, butonlara tıklar ve hedefe ulaşılıp ulaşılmadığına karar verir.

```yaml
id: KMP-001
baslik: Kampanyaları listeleyip birinin detayına bakma
etiketler: [kritik, kampanya]
mod: script
adimlar:
  - mesaj: Kampanya listele
  - buton: Detay              # buton başlığıyla tıklanır; kart butonları "Kart Başlığı › Detay" olarak görünür
cikis:
  max_tur: 5
  hata_ifadeleri: ["anlayamadım"]
```

Yönlendirmeli örnek için `scenarios/ornek/EFT-001_kayitli_aliciya_eft.yaml` dosyasına bakın
(`persona`, `hedef`, `yonlendirme`, `test_verisi`, `cikis.basari`, `cikis.basari_ifadeleri`...).

**Buton tıklama:** butona tıklandığında asistana butonun aksiyonu (`payload`) gönderilir, aksiyon yoksa başlığı gönderilir.

## Sonuç durumları

| Durum | Anlamı |
|---|---|
| `HEDEF_TAMAMLANDI` | Başarı ifadesi görüldü veya simülatör hedefe ulaşıldığına karar verdi |
| `SCRIPT_TAMAMLANDI` | Script adımları bitti (başarı kararı değerlendirme fazında verilecek) |
| `BASARISIZ` | Asistanın cevabında hata ifadesi görüldü |
| `TIKANDI` | Simülatör ilerleyemedi (istenen buton yok, LLM tıkandığına karar verdi) |
| `DONGU` | Asistan art arda 3 kez aynı cevabı verdi |
| `MAX_TUR` | Tur sınırına ulaşıldı |
| `HATA` | Teknik hata (login, HTTP, LLM erişimi). Transcript yine de yazılır |

## Geliştirme

```bash
pip install -e ".[dev]"
pytest -q
```

Kaynak değiştiğinde offline paketleri yeniden üretin (internet gerektirir) ve `release/` ile birlikte commit'leyin:

```bash
python scripts/build_bundle.py          # ikisi birden; tek mimari için: x64 veya x86
```

Script, bağımlılıkları her mimari ve Python 3.10–3.14 için Windows'a göre çözer. Her paketin uyumlu bir
wheel'i olduğunu doğrular, eksik varsa paket adını ve gereken wheel etiketini söyleyip durur.
C eklentisi opsiyonel olan PyYAML için ayrıca saf Python wheel'i eklenir, çünkü 32-bit + Python 3.14 için
hazır wheel'i yok.

CI (`.github/workflows/bundle.yml`) zip'lerin kaynakla güncel olduğunu kontrol eder. Ayrıca gerçek Windows'ta
x64/x86 × Python 3.10–3.14 için internetsiz kurulumu, sahte asistanla offline koşumu ve yanlış mimari
tespitini test eder.
