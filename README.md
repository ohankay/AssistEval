# AssistEval

Mobil bankacılıktaki GenAI asistan için simülasyon, değerlendirme ve izleme platformu.
Amaç, asistan geliştirilirken kritik senaryoları sürekli koşup modelde kayma (drift) olup olmadığını yakalamak.

| Katman | Durum |
|---|---|
| **Simülasyon:** senaryoya (replik yönlendirme dokümanına) bağlı kalarak sohbet başlatma, yürütme, exit kriterinde bitirme, transcript kaydı | ✅ `src/assisteval/simulator` |
| **Değerlendirme:** senaryoların promptfoo ile koşulup skorlanması, HTML rapor | ✅ `src/assisteval/evaluation` |
| **Raporlama ve izleme:** sonuçların biriktirilmesi, drift dashboard'u, senaryo kütüphanesi arayüzü | ⏳ |

Hedef platform: **Windows x64, 64-bit Python 3.10–3.14**. Kurulum tamamen offline yapılır.

## Mimari

```
                       assisteval eval
                             │  senaryolardan promptfooconfig.yaml üretir
                             ▼
                    promptfoo (Node.js, pakette)
                             │  her senaryo için Python provider'ı çağırır
                             ▼
Senaryo (YAML) ──▶ runner (döngü, exit kontrolü) ──▶ assistant_client ──▶ Bankacılık asistanı
                     │   └─ simüle müşteri: ScriptUser | LLMUser (Groq → ileride Qwen / mock)
                     ▼
               runs/<zaman>_<id>.json  (transcript)
                             │
                             ▼
       promptfoo assertion'ları: durum, max-tur, icontains, regex, llm-rubric (LLM hakem)...
                             ▼
               runs/eval-<zaman>/rapor.html + sonuclar.json
```

| Modül | Görevi |
|---|---|
| `simulator/assistant_client.py` | LoginForMobileBranch → InitialLogin → SendSmsOtp → OtpLoginCompleteNew → ChatBotInsertConversation → Chat/Message. Token 4 dk'da bir (veya 401'de) yenilenir, conversationId korunur |
| `simulator/reply.py` | Asistanın JSON cevabını metin + kart + buton (başlık → aksiyon) olarak ayrıştırır |
| `simulator/scenario.py` | Senaryo YAML'ını yükler ve doğrular |
| `simulator/user.py` | Simüle müşteri: `ScriptUser` (adımları sırayla oynatır), `LLMUser` (persona + hedef + yönlendirme ile LLM'e karar verdirir) |
| `simulator/llm.py` | OpenAI uyumlu LLM istemcisi (şimdilik Groq, ileride vLLM / Ollama ile Qwen) + `MockLLM` |
| `simulator/runner.py` | Sohbet döngüsü, exit kuralları, transcript |
| `simulator/mock_assistant.py` | Gerçek servislerle aynı endpoint'leri taklit eden sahte sunucu + sahte hakem |
| `evaluation/promptfoo.py` | Senaryolardan promptfoo config'i üretir, promptfoo'yu bulur ve çalıştırır, sonucu özetler |
| `evaluation/provider.py` | promptfoo Python provider'ı: senaryoyu simülatörle koşar, sohbeti ve sonucu döner |
| `evaluation/asserts.py` | Transcript'e bakan assertion'lar (`durum`, `max-tur`) |

**conversationId kuralı:** her senaryo yeni bir conversationId ile başlar (modelde sıfırdan bağlam).
Senaryo içindeki tüm turlar aynı conversationId ile gider. `/get_started` açılış komutudur ve "tur 0" olarak kaydedilir.

## Kurulum (Windows x64, internet gerekmez)

Çalışacağı ortamda internet erişimi kısıtlı olduğu için her şey tek pakette gelir:
[`release/assisteval-windows-x64.zip`](release/assisteval-windows-x64.zip). İçeriği:
- Python 3.10–3.14 için tüm wheel'ler
- taşınabilir Node.js
- promptfoo
- `install.cmd`
- [kurulum rehberi](bundle/KURULUM_REHBERI.md)

```bat
install.cmd                               :: %USERPROFILE%\.assisteval altına offline kurar
assisteval init C:\AssistEval\calisma     :: config.yaml, .env, örnek senaryolar
cd /d C:\AssistEval\calisma
assisteval check                          :: kurulum, ayarlar ve promptfoo kontrolü (ağ gerektirmez)
```

`install.cmd` 64-bit Python arar. Sadece 32-bit Python varsa bunu açıkça söyler (kod 14).

Gizli bilgiler (test müşterisi, servis kullanıcısı şifreleri, LLM/hakem API anahtarları) çalışma klasöründeki
`.env` dosyasına yazılır. Gizli olmayan ayarlar (URL'ler, cihaz bilgisi, simülatör LLM'i `llm`, hakem `judge`)
`config.yaml`'a yazılır. `.env` her zaman `config.yaml`'ın yanından okunur, çıktılar da onun yanındaki
`runs/` klasörüne yazılır.

Simülatör LLM'i şimdilik **Groq** (`llm.provider: groq`). Anahtar `.env`'deki `GROQ_API_KEY`'den okunur; boşsa
`run`/`eval` başlarken terminalden (görünmez) sorulur ve hiçbir dosyaya yazılmaz. Kurum içi Qwen'e geçmek için
`config.yaml`'da `provider: openai`, `base_url` ve `model` vermek yeterlidir (örnek şablonda yorum satırı olarak var).

Ortama göre değişen ayarlar `.env`'den de verilebilir; doluysa `config.yaml`'ın önüne geçer: `ASSISTANT_BASE_URL`,
`CHATBOT_MESSAGE_URL`, `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_MODEL`, `JUDGE_PROVIDER`, `JUDGE_BASE_URL`, `JUDGE_MODEL`.

Geliştirme makinesinde repo kökü çalışma klasörü olarak kullanılabilir (`assisteval init .`): `config.yaml`,
`scenarios/` ve `runs/` git'e girmez, ayarlar kökteki `.env`'den okunur.

**Ağ notları:** AssistEval Windows sertifika deposunu kullanır (`truststore`), kurumsal CA'lar için ek ayar
gerekmez. Proxy için `HTTPS_PROXY` / `NO_PROXY`, özel CA dosyası için `REQUESTS_CA_BUNDLE` (Python) ve
`NODE_EXTRA_CA_CERTS` (promptfoo) kullanılabilir. promptfoo'nun telemetrisi ve güncelleme kontrolü kapalıdır.

## Kullanım

```bash
assisteval smoke                                   # bağlantı kontrolü: login + yeni sohbet + /get_started
assisteval smoke --mesaj "Kampanya listele"

# Sadece simülasyon (transcript üretir, değerlendirme yok)
assisteval run scenarios/ornek
assisteval run scenarios/ornek --llm mock          # LLM yokken yönlendirmeli mod

# Simülasyon + promptfoo değerlendirmesi
assisteval eval scenarios/ornek                    # tüm senaryolar
assisteval eval scenarios --etiket kritik          # sadece "kritik" etiketliler
assisteval promptfoo view                          # promptfoo arayüzü: koşum geçmişi, karşılaştırma

# Gerçek asistan, LLM ve hakem olmadan tamamen offline deneme
assisteval --assistant mock eval scenarios/ornek --llm mock --judge mock
```

`eval`, her koşum için `runs/eval-<zaman>/` klasörü oluşturur:
- `rapor.html`: tarayıcıda açılan rapor
- `sonuclar.json`: ham sonuçlar
- `promptfooconfig.yaml`: koşumun promptfoo ayarları

Bütün senaryolar geçerse komut 0, aksi halde 1 ile çıkar, yani CI'da doğrudan kullanılabilir.
promptfoo komutlarının tamamı `assisteval promptfoo ...` ile kullanılabilir.

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

degerlendirme:                # promptfoo assertion'ları
  - type: durum               # kısayol: sohbet bu durumla bitmeli
    value: SCRIPT_TAMAMLANDI
  - type: icontains
    value: kampanya
    metric: gorev
  - type: not-icontains
    value: anlayamadım
    metric: anlama
```

Yönlendirmeli örnek için `scenarios/ornek/EFT-001_kayitli_aliciya_eft.yaml` dosyasına bakın
(`persona`, `hedef`, `yonlendirme`, `test_verisi`, `cikis`, `degerlendirme` içinde `max-tur` ve `llm-rubric`).

**Buton tıklama:** butona tıklandığında asistana butonun aksiyonu (`payload`) gönderilir, aksiyon yoksa başlığı gönderilir.

### Değerlendirme (`degerlendirme`)

| type | Anlamı |
|---|---|
| `durum` | Kısayol. Sohbet verilen durum(lar)la bitmeli (`value`: tek durum veya liste) |
| `max-tur` | Kısayol. Sohbet en fazla `value` müşteri turunda bitmeli |
| diğerleri | promptfoo'ya olduğu gibi geçer: `icontains`, `not-icontains`, `regex`, `llm-rubric`, `python`, `javascript`... |

`degerlendirme` yazılmazsa varsayılan kural, sohbetin `HEDEF_TAMAMLANDI` veya `SCRIPT_TAMAMLANDI` ile bitmesidir.
Assertion'ların çalıştığı çıktı, sohbetin düz metnidir (`MÜŞTERİ: ...` / `ASİSTAN: ...` satırları).
`metric` adı verilen assertion'lar raporda kategori skoru olarak görünür (`gorev`, `politika`, `uslup`...).
Drift izlerken bu skorların koşumlar arasında nasıl değiştiğine bakılır.

`llm-rubric` hakemi `config.yaml`'daki `judge` ayarlarıdır, verilmezse `llm` ayarları kullanılır. Skorların
asistandaki değişimi yansıtması için hakem modeli sabit tutulmalıdır.

## Sonuç durumları

| Durum | Anlamı |
|---|---|
| `HEDEF_TAMAMLANDI` | Başarı ifadesi görüldü veya simülatör hedefe ulaşıldığına karar verdi |
| `SCRIPT_TAMAMLANDI` | Script adımları bitti |
| `BASARISIZ` | Asistanın cevabında hata ifadesi görüldü |
| `TIKANDI` | Simülatör ilerleyemedi (istenen buton yok, LLM tıkandığına karar verdi) |
| `DONGU` | Asistan art arda 3 kez aynı cevabı verdi |
| `MAX_TUR` | Tur sınırına ulaşıldı |
| `HATA` | Teknik hata (login, HTTP, LLM erişimi). Transcript yine de yazılır, promptfoo'da "error" görünür |

## Geliştirme

```bash
pip install -e ".[dev]"
npm install -g promptfoo@0.125.1        # uçtan uca değerlendirme testi için (yoksa o test atlanır)
pytest -q
```

Kaynak değiştiğinde offline paketi yeniden üretin ve `release/` ile birlikte commit'leyin. Bunun için internet,
`uv` ve `npm` gerekir:

```bash
python scripts/build_bundle.py
```

Script şunları yapar:
1. Python bağımlılıklarını Python 3.10–3.14 için Windows x64'e göre çözer ve her paketin uyumlu bir wheel'i
   olduğunu doğrular. Eksik varsa paket adını ve gereken wheel etiketini söyleyip durur.
2. Node.js'i nodejs.org'dan SHA256 doğrulamasıyla indirir.
3. promptfoo'yu opsiyonel sağlayıcıları olmadan, Windows x64 ikilileriyle (`@libsql`, `@esbuild`) kurar ve
   kullanılmayan dosyaları budar.

Node.js ve promptfoo sürümleri script'in başındaki `NODE_VERSION` / `PROMPTFOO_VERSION` sabitleridir.

CI'da iki workflow var:
- **`.github/workflows/ci.yml`:** Linux'ta promptfoo kurup uçtan uca `eval` testini koşar.
- **`.github/workflows/bundle.yml`:** zip'in kaynak ve sürümlerle güncel olduğunu kontrol eder. Ardından gerçek
  Windows'ta Python 3.10–3.14 için internetsiz kurulumu ve ağ kapalıyken simülasyon + promptfoo değerlendirmesini
  test eder, 32-bit Python'un reddedildiğini de doğrular.
