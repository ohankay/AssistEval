# AssistEval: Kurulum Rehberi (offline)

İnternet gerekmez. Tüm Python paketleri `wheelhouse` klasöründe.

Gereksinimler: Windows 10/11 (64 veya 32 bit), Python 3.10–3.14 (`py --version` ile kontrol edin).

## 1. Doğru paketi seçin

| Python'unuz | Paket |
|---|---|
| 64-bit (çoğu bilgisayar) | `assisteval-windows-x64.zip` |
| 32-bit | `assisteval-windows-x86.zip` |

Hangisi olduğunu bilmiyorsanız şu komut `64` veya `32` yazar:

```
py -c "import struct; print(struct.calcsize('P')*8)"
```

Yanlış paketi seçerseniz kurulum bunu söyler (hata kodu `14`).

## 2. Kurun

Zip'i bir klasöre açın (örneğin `C:\Araclar\assisteval`), o klasörde komut satırını açıp çalıştırın:

```
install.cmd
```

Çıktının sonunda `KURULUM TAMAM` görmelisiniz. Komut şu yola kurulur:
`%USERPROFILE%\.assisteval\Scripts\assisteval.exe`

Kısalık için aşağıdaki örneklerde sadece `assisteval` yazıldı. Komutu tam yoluyla çalıştırabilir ya da bu klasörü PATH'e ekleyebilirsiniz.

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

URL'ler, cihaz bilgisi ve LLM adresi `config.yaml` içindedir.

## 5. Kontrol ve ilk koşum

```
assisteval check                                   # kurulum + ayarlar (ağ gerektirmez)
assisteval --assistant mock run scenarios\ornek --llm mock   # sahte asistanla tamamen offline deneme
assisteval smoke --mesaj "Kampanya listele"        # gerçek asistana bağlantı kontrolü
assisteval run scenarios\ornek                     # gerçek asistana karşı senaryolar
```

Her koşumun transcript'i `runs\` klasörüne JSON olarak yazılır.

## Hata kodları (install.cmd)

| Kod | Anlamı | Çözüm |
|---|---|---|
| 10 | Python 3.10–3.14 bulunamadı | Python kurun (kurumsal yazılım merkezi veya python.org) |
| 11 | Sanal ortam oluşturulamadı | Kurulum klasörüne yazma izni olduğundan emin olun |
| 12 | Paket kurulamadı | Zip'in tam açıldığından ve `wheelhouse` klasörünün dolu olduğundan emin olun |
| 13 | `assisteval` komutu çalışmadı | Kurulum klasörünü silip tekrar kurun |
| 14 | Zip ile Python'un mimarisi farklı | Diğer zip'i kullanın veya uygun bitte Python kurun |
| 15 | Mevcut kurulum farklı mimaride | `%USERPROFILE%\.assisteval` klasörünü silip tekrar kurun |
| 16 | Kurulum sonrası doğrulama başarısız | Kurulum klasörünü silip tekrar kurun |

## Sorun giderme

- **SSL / sertifika hatası:** AssistEval Windows sertifika deposunu kullanır, kurumsal sertifikalar orada yüklüyse sorun çıkmaz. Özel bir CA dosyası gerekiyorsa `set REQUESTS_CA_BUNDLE=C:\yol\kurum-ca.pem` tanımlayın.
- **Proxy:** kurumsal proxy gerekiyorsa `set HTTPS_PROXY=http://proxy:port` tanımlayın. Proxy'den geçmemesi gereken iç adresler için `NO_PROXY` kullanın.
- **`.env içinde eksik değişkenler` hatası:** `assisteval check` hangi değişkenlerin boş olduğunu listeler.
