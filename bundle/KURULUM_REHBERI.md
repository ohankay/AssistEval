# AssistEval: Kurulum Rehberi (offline)

İnternet gerekmez. Paketin içinde her şey hazır gelir:
- `wheelhouse`: Python paketleri
- `node`: taşınabilir Node.js
- `promptfoo`: değerlendirme motoru

Gereksinimler: Windows 10/11 64-bit, **64-bit** Python 3.10–3.14 (`py --version` ile kontrol edin).

## 1. Python'unuzun 64-bit olduğunu kontrol edin

```
py -c "import struct; print(struct.calcsize('P')*8)"
```

Çıktı `64` olmalı. 32-bit Python desteklenmez, kurulum bunu söyler (hata kodu `14`).

## 2. Kurun

`assisteval-windows-x64.zip` dosyasını bir klasöre açın (örneğin `C:\Araclar\assisteval`). O klasörde komut satırını açıp çalıştırın:

```
install.cmd
```

Çıktının sonunda `KURULUM TAMAM` görmelisiniz. Kurulum yeri `%USERPROFILE%\.assisteval`:

| Yol | İçerik |
|---|---|
| `Scripts\assisteval.exe` | komut |
| `node\node.exe` | Node.js (promptfoo için) |
| `promptfoo\` | promptfoo |

Kısalık için aşağıdaki örneklerde sadece `assisteval` yazıldı. Komutu tam yoluyla çalıştırabilir ya da `Scripts` klasörünü PATH'e ekleyebilirsiniz.

Ayarlar:
- `set ASSISTEVAL_HOME=D:\assisteval`: başka bir klasöre kurmak için
- `set ASSISTEVAL_PYTHON=C:\Python312\python.exe`: belirli bir Python kullanmak için

Güncelleme: yeni zip'i açıp `install.cmd`'yi tekrar çalıştırın. Mevcut kurulum güncellenir, çalışma klasörünüze dokunulmaz.

## 3. Çalışma klasörü oluşturun

```
assisteval init C:\AssistEval\calisma
cd /d C:\AssistEval\calisma
```

Bu komut `config.yaml`, `.env`, `.env.example` ve `scenarios\ornek\` dosyalarını oluşturur.

## 4. Gizli bilgileri girin

`.env` dosyasını açıp test müşterisi ve servis kullanıcısı bilgilerini doldurun. Değerler "Login to GetStarted" Postman collection'ındaki değişkenlerle aynıdır.

**`.env` dosyasını kimseyle paylaşmayın ve git'e eklemeyin.**

URL'ler, cihaz bilgisi, simülatör LLM'i (`llm`) ve değerlendirme hakemi (`judge`) `config.yaml` içindedir.

## 5. Kontrol ve ilk koşum

```
assisteval check                                              # kurulum + ayarlar + promptfoo (ağ gerektirmez)
assisteval --assistant mock eval scenarios\ornek --llm mock --judge mock   # tamamen offline deneme
assisteval smoke --mesaj "Kampanya listele"                   # gerçek asistana bağlantı kontrolü
assisteval eval scenarios\ornek                               # gerçek asistan + değerlendirme
assisteval promptfoo view                                     # promptfoo arayüzü (koşum geçmişi)
```

Çıktıların yeri:
- Her sohbetin transcript'i: `runs\` klasörü
- Her değerlendirme koşumu: `runs\eval-<zaman>\` klasörü
  - `rapor.html`: tarayıcıda açılır
  - `sonuclar.json`: ham sonuçlar
  - `promptfooconfig.yaml`: koşumun promptfoo ayarları

## Hata kodları (install.cmd)

| Kod | Anlamı | Çözüm |
|---|---|---|
| 10 | Python 3.10–3.14 bulunamadı | 64-bit Python kurun (kurumsal yazılım merkezi veya python.org) |
| 11 | Sanal ortam oluşturulamadı | Kurulum klasörüne yazma izni olduğundan emin olun |
| 12 | Python paketleri kurulamadı | Zip'in tam açıldığından ve `wheelhouse` klasörünün dolu olduğundan emin olun |
| 13 | `assisteval` komutu çalışmadı | Kurulum klasörünü silip tekrar kurun |
| 14 | Sadece 32-bit Python var | 64-bit Python 3.10–3.14 kurun |
| 15 | Mevcut kurulum 64-bit değil | `%USERPROFILE%\.assisteval` klasörünü silip tekrar kurun |
| 16 | Kurulum sonrası doğrulama başarısız | Kurulum klasörünü silip tekrar kurun |
| 17 | Node.js / promptfoo kopyalanamadı veya çalışmadı | Zip'in tam açıldığından emin olun (`node`, `promptfoo` klasörleri), sonra kurulum klasörünü silip tekrar kurun |

## Sorun giderme

- **SSL / sertifika hatası:** AssistEval Windows sertifika deposunu kullanır, kurumsal sertifikalar orada yüklüyse sorun çıkmaz. Özel bir CA dosyası gerekiyorsa `set REQUESTS_CA_BUNDLE=C:\yol\kurum-ca.pem` tanımlayın. promptfoo'nun hakeme bağlanırken kullanacağı CA için ayrıca `set NODE_EXTRA_CA_CERTS=C:\yol\kurum-ca.pem` tanımlayın.
- **Proxy:** kurumsal proxy gerekiyorsa `set HTTPS_PROXY=http://proxy:port` tanımlayın. Proxy'den geçmemesi gereken iç adresler (asistan, LLM) için `NO_PROXY` kullanın.
- **`.env içinde eksik değişkenler` hatası:** `assisteval check` hangi değişkenlerin boş olduğunu listeler.
- **promptfoo dışarıya bağlanır mı?** Hayır. Telemetri ve güncelleme kontrolü kapalıdır, paylaşım (`promptfoo share`) kullanılmaz. Koşum geçmişi çalışma klasöründeki `.promptfoo\` altında tutulur.
