# StajRadar

Kişisel staj arama sitesi: https://hefetas.github.io/staj-radar/ (GitHub Pages).
Bursa / Uludağ Üniversitesi Endüstri Mühendisliği öğrencisi için ilan toplama ve puanlama.
Sekmeler: Bugün (Sana özel), Uzaktan, Diğer, Takip, LinkedIn, CV, Beni Tanı, Kontrol listesi.
Özellikler: 👍/👎 ile kişiselleşen puan, Bursa'ya mesafe filtresi, "CV'yi uyarla" / firma özeti istemleri (Claude'a kopyala-yapıştır, API yok), .ics takvim, başvuru e-postası şablonu, cihazlar arası eşitleme.

## Yapı
- `scripts/radar.py`: ilanları tarar, puanlar, `docs/data/jobs.json` yazar, bildirim gönderir (GitHub Actions, 3 saatte bir).
- `docs/index.html`: yayındaki site (Pages `/docs`). `site/index.html` aynı dosyanın kopyası; birini değiştirince diğerini de eşitle.
- `config/`: `profile.json` (puan ağırlıkları), `sources.json` (kaynaklar), `cities.json`.
- `supabase/functions/tailor-cv`: NVIDIA ücretsiz API (build.nvidia.com) ile ilana özel İngilizce CV/ön yazı/e-posta. Supabase Edge Function, secret `NVIDIA_API_KEY`, `staj_is_allowed()` ile korunur; e-posta/telefon gönderilmeden gizlenir. Değişince Supabase'e yeniden deploy et.
- Test: `python -I -m unittest discover -s tests`
- Workflow'lar `docs/data` ve `.keepalive` dosyalarına otomatik commit atar; push öncesi `git pull --rebase`.

## Kod Yazım Kuralları
- Sade, okunabilir ve çalışan kod yaz. Gereksiz soyutlama, katman ve dosya ekleme.
- Sadece istenen şeyi yap; kapsam dışı refactor veya "ilerisi için" özellik ekleme.
- Gereksiz yorum yazma; sadece açık olmayan mantığı açıkla.
- Yeni bağımlılık eklemeden önce mevcut araçlarla çözülebiliyor mu bak.
- Kodu teslim etmeden önce çalıştığını doğrula (çalıştır / test et).

## Token Tasarrufu
- Yanıtlar kısa ve öz olsun; uzun açıklama, tekrar ve özet yazma.
- Dosyanın tamamını değil, sadece gereken kısmını oku.
- Küçük değişikliklerde dosyayı yeniden yazma, sadece ilgili satırları düzenle.
- Değiştirilmeyen kodu yanıtta tekrar gösterme.
- Gereksiz araç çağrısı ve keşif yapma; bilgi yeterliyse doğrudan uygula.
