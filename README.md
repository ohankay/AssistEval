# AssistEval

Mobil bankacılıktaki GenAI asistan için simülasyon, değerlendirme ve izleme platformu.
Amaç, asistan geliştirilirken kritik senaryoları sürekli koşup modelde kayma (drift) olup olmadığını yakalamak.

| Katman | Durum |
|---|---|
| **Simülasyon:** senaryoya (replik yönlendirme dokümanına) bağlı kalarak sohbet başlatma, yürütme, exit kriterinde bitirme, transcript kaydı | ✅ `assisteval/simulator` |
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
| `assisteval/simulator/assistant_client.py` | LoginForMobileBranch → InitialLogin → SendSmsOtp → OtpLoginCompleteNew → ChatBotInsertConversation → Chat/Message. Token 4 dk'da bir (veya 401'de) yenilenir, conversationId korunur |
| `assisteval/simulator/reply.py` | Asistanın JSON cevabını metin + kart + buton (başlık → aksiyon) olarak ayrıştırır |
| `assisteval/simulator/scenario.py` | Senaryo YAML'ını yükler ve doğrular |
| `assisteval/simulator/user.py` | Simüle müşteri: `ScriptUser` (adımları sırayla oynatır), `LLMUser` (persona + hedef + yönlendirme ile LLM'e karar verdirir) |
| `assisteval/simulator/llm.py` | OpenAI uyumlu LLM istemcisi (vLLM / Ollama ile Qwen) + `MockLLM` |
| `assisteval/simulator/runner.py` | Sohbet döngüsü, exit kuralları, transcript |
| `assisteval/simulator/mock_assistant.py` | Gerçek servislerle aynı endpoint'leri taklit eden sahte sunucu |

**conversationId kuralı:** her senaryo yeni bir conversationId ile başlar (modelde sıfırdan bağlam).
Senaryo içindeki tüm turlar aynı conversationId ile gider. `/get_started` açılış komutudur ve "tur 0" olarak kaydedilir.

## Kurulum

```bash
pip install -r requirements.txt
cp .env.example .env   # test müşterisi ve servis kullanıcısı bilgilerini doldurun
```

Gizli olmayan ayarlar (URL'ler, cihaz bilgisi, LLM endpoint'i) `config.yaml`'da durur.

## Kullanım

```bash
# Faz 0: bağlantı kontrolü (login + yeni sohbet + /get_started)
python -m assisteval smoke
python -m assisteval smoke --mesaj "Kampanya listele"

# Senaryo koşumu
python -m assisteval run scenarios/ornek                      # klasördeki tüm senaryolar
python -m assisteval run scenarios/ornek/KMP-001_kampanya_listele.yaml
python -m assisteval run scenarios/ornek --llm mock           # LLM yokken yönlendirmeli mod

# Gerçek asistana erişim olmadan her şeyi sahte sunucuyla denemek
python -m assisteval --assistant mock run scenarios/ornek --llm mock
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

## Testler

```bash
python -m pytest -q
```
