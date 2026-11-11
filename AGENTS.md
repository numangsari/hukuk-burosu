# AGENTS.md

Bu proje Yazılım Stüdyosu'na bağlıdır. Kullanıcıyla Türkçe, kısa ve günlük dille konuş; kod adları İngilizce, yorumlar ve kayıt mesajları Türkçe olsun.

Projenin mimarisi, iş kuralları, güvenlik ve test kuralları `CLAUDE.md` dosyasındadır. Çalışmaya başlamadan önce onu oku; kalıcı kural değişince orayı güncelle. Bu dosyaya ayrı proje bilgisi yazma.

## Başlarken
- `.studio/project.json` ve ilgili `.studio/tasks/` kaydını oku.
- Çalışma alanı temizse `git pull --ff-only` yap; ayrışma veya çakışmada dur ve bildir.
- Ortak kurallar stüdyo deposundadır: `yazilim-studyosu/AGENTS.md` ve `kurallar/genel.md`.

## Çalışırken
- Sır, `.env`, gerçek müvekkil verisi, veritabanı dökümü ve yedek hiçbir yere kaydedilmez; yalnız ortam değişkeni adları yazılır.
- Mevcut kullanıcı değişikliğini ezme; yıkıcı işlemi önceden bildir; zorlayarak gönderme yapma.
- Her görevin başarı ölçütü ve en az bir davranış kontrolü olsun. Kontroller `.studio/project.json` içindedir.
- Görev kaydı `.studio/tasks/<kimlik>.json` dosyasıdır (`id`, `title`, `status`, `acceptance`, `next_step`, `blockers`, `updated_at`); anlamlı her adımda `next_step` güncellenir.
- Kapsamlı veya riskli değişiklikte (`risk_paths`) bağımsız denetim iste; kendi değişikliğini bağımsız inceleme sayma.
- Teslim stüdyonun `kurallar/teslim.md` adımlarıyla yapılır; gönderim kullanıcı onayıyla, düz `git push` ile.
- Ürün aşamasını, ortak kuralları ve yayımlamayı (sürüm paketi, `hukuk-burosu-releases`) yalnız açık kullanıcı kararıyla değiştir.
- Doğrulanmayan işi tamamlandı sayma; Mac ve Windows doğrulamasını ayrı raporla.
