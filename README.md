# Staj Radar

Sen bakmazken de çalışan, staj ilanlarını tarayıp profiline göre puanlayan ve yeni eşleşmeleri sana bildiren kişisel bir sistem. Tamamen ücretsiz: GitHub Actions (tarama) + GitHub Pages (site) + Telegram/e-posta (bildirim).

```
GitHub Actions (3 saatte bir) → scripts/radar.py → docs/data/jobs.json → docs/index.html (siten)
                                      └→ yeni ve yüksek puanlı ilan → Telegram / e-posta
```

## Kaynaklar

| Kaynak | Kapsam | Not |
|---|---|---|
| Youthall (herkese açık staj listesi) | Türkiye | Giriş gerekmez. HTML ayrıştırma "en iyi çaba"; Youthall sayfa yapısını değiştirirse bozulabilir (sitedeki kaynak durumu satırında "hata" görünür). Kullanım koşullarını sen de kontrol et. |
| Arbeitnow | Almanya, Avrupa, UK | Ücretsiz genel API, anahtar yok. Daha çok yazılım ağırlıklı. |
| Adzuna | DE, GB, NL, AT | Ücretsiz anahtar gerekir (developer.adzuna.com); ayda ~1000 çağrı. Türkiye kapsamı yok. Anahtar yoksa atlanır. |
| RSS / Google Alerts | İstediğin her şey | `config/sources.json` → `rss.feeds`. Örn. Google Alerts'ten "Bursa staj mühendislik" için RSS akışı oluşturup ekle. |
| Firma kariyer sayfaları | İstediğin firmalar | `config/sources.json` → `careers.sites`. Sayfada "staj/intern" geçen bağlantıları yakalar. |

LinkedIn, Kariyer.net, Indeed gibi siteler otomatik taramaya izin vermediği için bilerek yok.

## Kurulum (yaklaşık 15 dk)

1. **GitHub'da yeni depo aç** (ör. `staj-radar`). Ücretsiz GitHub Pages için depo **public** olmalı. İçinde kişisel bilgi yok (ad, e-posta, telefon yok); yalnızca ilan listesi ve puanlama kuralları var.
2. Bu klasörün **tüm içeriğini** depoya yükle. `.github` klasörü gizlidir, onu da yüklediğinden emin ol.
3. **Settings → Pages**: Source "Deploy from a branch", Branch `main`, klasör `/docs`.
4. **Settings → Actions → General → Workflow permissions**: "Read and write permissions".
5. **Bildirim** için **Settings → Secrets and variables → Actions** altına secret ekle:
   - **ntfy (en kolayı, hesap/token yok):** Telefona ücretsiz **ntfy** uygulamasını kur, uygulamada **+** → "Subscribe to topic" ile kendi uydurduğun uzun, tahmin edilmesi zor bir kanal adına abone ol (örn. `staj-radar-` + rastgele harf/rakam). Aynı adı `NTFY_TOPIC` secret'ı olarak kaydet.
   - **Telegram (anlık):** Telegram'da @BotFather → `/newbot` → verdiği token'ı `TELEGRAM_BOT_TOKEN` olarak kaydet. Botuna bir mesaj yaz, sonra tarayıcıda `https://api.telegram.org/bot<TOKEN>/getUpdates` aç, `chat` → `id` değerini `TELEGRAM_CHAT_ID` olarak kaydet. (Token'ı kimseyle paylaşma.)
   - **E-posta (Gmail):** Google hesabında 2 adımlı doğrulama açık olsun, "Uygulama şifresi" oluştur. `SMTP_USER` (gmail adresin), `SMTP_PASS` (uygulama şifresi), `NOTIFY_EMAIL` (bildirimin geleceği adres).
   - **Adzuna (isteğe bağlı):** `ADZUNA_APP_ID`, `ADZUNA_APP_KEY`.
6. **Actions → Staj Radar → Run workflow** ile ilk taramayı elle başlat. İlk çalışmada tek bir özet bildirim gelir (bulunan ilan sayısı + en iyi 10); sonrasında sadece yeni ve puanı yeterli ilanlar bildirilir.
7. Siten `https://<kullanıcı-adın>.github.io/staj-radar/` adresinde açılır.

## Özelleştirme

- `config/profile.json`: anahtar kelime ağırlıkları, beceriler (Excel, SQL, Power BI, AutoCAD, Inventor), olumsuz kelimeler, bildirim eşiği (`notify_min_score`, varsayılan 35), şehir grupları. Konum ağırlıkları şu an hepsi 0 (tüm konumlar eşit); Bursa'yı öne çıkarmak için `location.weights.home` değerini artır.
- `config/sources.json`: kaynakları aç/kapat, firma kariyer sayfası ve RSS ekle.

## Bilmen gerekenler

- Staj sayılması için başlıkta (veya açıklamanın başında) "staj/intern/praktikum/werkstudent" gibi bir ifade gerekir. Sadece bu ifadeyi açıklamanın ortasında geçirenler elenir.
- Puan 10'un altındaki ilanlar saklanmaz (örn. satış/pazarlama stajları). İstersen `min_score_keep` ile değiştir.
- Sitedeki "Kaydet / Başvurdum / Gizle" işaretleri tarayıcında tutulur; telefon ve bilgisayar arasında otomatik eşitlenmez.
- Public depolarda 60 gün hareketsizlikte GitHub zamanlanmış çalışmaları durdurabilir. Yeni veri commit'leri genelde bunu önler ama arada Actions sekmesine bakmak iyi olur.
- Bu sistem ilan bulmaya yardım eder; başvuruyu sen yaparsın.
