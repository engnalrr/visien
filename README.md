# Visien 1.3

![Visien](docs/assets/screenshot.png)

**Proje sayfası:** https://engnalrr.github.io/visien/ · **İndir:** [Releases](https://github.com/engnalrr/visien/releases/latest) · [Değişiklikler](CHANGELOG.md)

**Yapay zekâ videoları ve görselleri için iyileştirme stüdyosu.** Visien, DLSS 5 Neural Rendering'i
(Merserk'in **Visual Enhancer** uygulaması üzerinden) ve kendi AI modellerini (SeedVR2, RIFE, yüz onarımı) Topaz
tarzı bir masaüstü arayüzünde birleştirir. Klibin birkaç saniyesinde ayar dener, kaynakla yan yana karşılaştırır,
beğendiğin ayarı kuyruğa atıp bütün dosyaları işlersin.

- Kendi penceresinde açılan masaüstü uygulaması (tarayıcı gerekmez)
- **Easy mode:** presetin üstünde sekiz kısa ayar (Realism, AI Restore, Output Size, Sharpness, Film Grain,
  Smooth Motion, Original Colors, Faces). **Advanced:** her kart ve her ayar.
- **Her ayarın üstüne gelince** ne işe yaradığını anlatan kısa İngilizce açıklama
- **AI modelleri** (Visien'in kendi AI ortamında, ekran kartında çalışır):
  - **SeedVR2** (ByteDance): yumuşak, sıkıştırılmış AI videosunda gerçek dokuyu geri getirir, 1080p'ye büyütür
  - **RIFE 4.26** (Practical-RIFE): ara kare üretir (24 → 48/60 fps), sahne geçişlerini korur
  - **Yüz onarımı:** GFPGAN 1.4 (ticari kullanım serbest) ya da CodeFormer (yalnızca ticari olmayan kullanım)
  - **Color Match:** render'dan sonra kaynağın renklerini geri getirir (ürün, marka, ten rengi); DLSS'in eklediği
    ayrıntıya ve ışığa dokunmaz
- **Clean Shot Starts:** çok planlı videolarda her planın ilk karelerinin "işlenmemiş" görünmesini engeller
- **Karşılaştırma kopyası:** çıktının yanına altlı üstlü (ya da yan yana) RAW / NEURAL ENHANCED etiketli video
- Visual Enhancer'daki bütün kartlar: DLSS Neural Rendering, DLSS Super Resolution, Ray Reconstruction,
  RTX Super Resolution, RTX Video HDR, DLSS / FSR / NVIDIA Frame Generation, ReShade, Coloring, Sharpening,
  Grain, NVIDIA Video Super Resolution, Lightweight Upscale
- AI kartları ve Visual Enhancer kartları tek bir sırada çalışır; sırayı oklarla değiştirebilirsin
- Önizleme: oynatma başlığından itibaren 1–10 saniye ya da tek görsel; Split, Side by side, Top / bottom,
  Source ve Visien görünümleri; yakınlaştırma, kaydırma, kare kare ilerleme, kayıpsız (PNG) kare karşılaştırma
- Kuyruk: çoklu dosya, sıralama, durdurma, yeniden deneme, kalan süre, kayıt
- Hazır presetler, özellikle AI çıktılarını daha gerçekçi göstermek için (aşağıda)

---

## Bilgisayarda olması gerekenler

| Gereksinim | Not |
| --- | --- |
| **Windows 11, 64-bit** | Visual Enhancer Windows 11 istiyor. Visien arayüzü Windows 10'da da açılır. |
| **NVIDIA GeForce RTX ekran kartı** | Neural Rendering için RTX; Frame Generation için RTX 40 veya 50 serisi. AI modelleri için en az 12 GB, önerilen 16 GB ekran kartı belleği (RTX 5070 Ti 16 GB'ta test edildi). SeedVR2 7B için 24 GB önerilir. |
| *(ya da)* **AMD Radeon RX 7000 / 9000** | Yalnızca **AI kartları** çalışır (SeedVR2, RIFE, yüz onarımı); Visual Enhancer'ın DLSS / RTX kartları NVIDIA ister. Visien AMD kartını tanır ve AI ortamını AMD'nin PyTorch'u (ROCm) ile kurar (RX 9070 XT 16 GB'ta test edildi). |
| **Güncel NVIDIA sürücüsü** | NVIDIA App veya nvidia.com/drivers üzerinden (CUDA 12.8 destekli sürücü). |
| **Visual Enhancer v18 ya da yenisi** (19.5 ile denendi) | Ayrıca indirilir (aşağıda). Visien bunu içermez. |
| **Microsoft Edge WebView2 Runtime** | Windows 11'de hazır gelir. Yoksa kurulum uyarır: https://go.microsoft.com/fwlink/p/?LinkId=2124703 |
| **Bellek (RAM)** | 16 GB; SeedVR2 Block Swap kullanırken 32 GB ve üstü. |
| **Boş disk alanı** | Tam paket açıldığında ~10 GB. Önizleme önbelleği varsayılan en fazla 10 GB; çıktılar ve SeedVR2'nin ara dosyaları için ayrıca yer. |
| **İnternet** | Tam pakette gerekmez. İnce pakette kurulumda Python, paketler ve ffmpeg (~200 MB), AI modelleri için ~9 GB indirilir. |
| *(DLSS Frame Generation için)* | Windows Ayarları › Sistem › Ekran › Grafik › **Donanım hızlandırmalı GPU zamanlaması** açık olmalı. |

Visien sisteme Python kurmaz, sistem ayarlarını değiştirmez; her şey kendi klasörünün içine kurulur.

## Kurulum

| Paket | Boyut | İçinde |
| --- | --- | --- |
| **Visien-1.2.0-full.zip** (önerilen) | ~8 GB | Uygulama, kendi Python'u ve paketleri (`runtime\python`), ffmpeg, AI ortamı (`ai\site-packages`: PyTorch CUDA 12.8, OpenCV, spandrel) ve önerilen modeller (`models`: SeedVR2 3B FP8 + VAE, RIFE 4.26, GFPGAN 1.4, YuNet). Kurulumda internet gerekmez. |
| **Visien-1.2.0.zip** (ince) | ~2 MB | Yalnızca uygulama. `install.bat` Python, paketler ve ffmpeg'i indirir; AI modelleri Ayarlar › AI models › **Install recommended** ile iner. |

İkisinde de **Visual Enhancer yoktur** (lisansı yeniden dağıtıma izin vermiyor). **CodeFormer** de pakette yoktur:
lisansı ticari olmayan kullanımla sınırlı olduğu için onu Ayarlar › AI models'ten, lisansı onaylayarak sen eklersin.

1. Zip'i kalıcı bir yere aç (ör. `D:\Apps\Visien`). Yolda Türkçe karakter olmaması önerilir. Tam paket büyük
   olduğu için Windows'un kendi "Tümünü ayıkla" komutu birkaç dakika sürebilir; 7-Zip daha hızlıdır.
2. **`install.bat`** dosyasına çift tıkla. Tam pakette yalnızca bilgisayarı denetler (ekran kartı, AI ortamı,
   modeller) ve kısayolları oluşturur; ince pakette eksikleri indirir. Sonuç `check.log` dosyasına yazılır.
3. Masaüstünde ve Başlat menüsünde **Visien** kısayolu oluşur. `Visien.bat` ile de açabilirsin.

Klasörü sonradan başka bir yere taşırsan `install.bat`'ı yeniden çalıştır (kısayollar yeni yere göre yenilenir).
Windows "bilinmeyen yayımcı" uyarısı gösterirse bunun nedeni dosyaların imzasız olmasıdır. Kaldırmak için klasörü
ve iki kısayolu silmen yeterli.

## AMD Radeon ekran kartıyla kullanma

Visien, Radeon RX 7000 / 9000 serisi ve Ryzen AI Max'ta AI kartlarını AMD'nin Windows için PyTorch'u (ROCm 7.14)
ile ekran kartında çalıştırır:

- **Ayarlar › AI models › AI runtime › Install** AMD sürümünü kurar (~1,5 GB). NVIDIA bilgisayardan kopyalanan bir
  tam paket açıldıysa aynı satırda **Update: switches PyTorch to the AMD Radeon (ROCm) build** görünür; modeller
  yeniden inmez, yalnızca PyTorch değişir.
- AMD'de kullanılacak presetler: **Realism · SeedVR2 Restore**, **Realism · Faces**, **Realism · Faces · CodeFormer**,
  **Smooth 60 · RIFE**. Bu presetlerdeki Visual Enhancer kartları (Neural Rendering, DLSS SR, RTX Super Resolution,
  Grain) AMD'de otomatik atlanır, AI kartları çalışır; Visien bunu önizlemede uyarı olarak yazar. Yalnızca Visual
  Enhancer kartı olan presetler (Visien, Natural Skin, Clean 4K …) AMD'de çalışmaz.
- Çıktı videosu AMD'nin donanım kodlayıcısıyla (AMF) yazılır.
- RX 9070 XT'de ölçülen: RIFE 12 saniyelik klibi 60 fps'e ~25 saniyede, SeedVR2 720p'de ~4 saniye/kare, GFPGAN
  ~25 ms/yüz. Her AI modelinin ilk çalıştırması AMD'nin kernel derlemesi yüzünden 15-40 saniye fazla sürer.

## Visual Enhancer'ı bağlama

Visien, Visual Enhancer kartlarını onun resmî komut satırı aracı `VE_CLI.exe` ile çalıştırır.

1. Ayarlar'da **Download page** düğmesine bas ya da
   https://github.com/Merserk/dlss5-visual-enhancer/releases/latest adresine git.
2. **Assets** altındaki büyük `.zip` paketini indir ("Source code" arşivleri çalıştırılabilir dosya içermez).
3. Zip'i **İndirilenler**, Masaüstü veya Belgeler'e ya da Visien'in `engine` klasörüne tamamen aç.
4. **Find automatically**'ye bas. Üst çubukta `Visual Enhancer 18.0 · RTX …` yazar. Başka bir yere açtıysan
   **Choose folder…** ile `VE_CLI.exe`'nin olduğu klasörü seç.

Yalnızca AI kartlarını (SeedVR2, RIFE, yüz onarımı) kullanan bir ayar Visual Enhancer olmadan da çalışır; çıktıyı
Visien kendisi yazar.

## Kullanım

1. **Add** ile video ve görselleri ekle ya da pencereye sürükle-bırak. Dosyalar yerinde kalır, kopyalanmaz.
2. Soldaki listeden bir dosya seç. Video ve görsel ardışık düzenleri ayrı ayarlanır, ikisi de aynı presette saklanır.
3. Sağ panelin üstünden **Easy** ya da **Advanced**'i seç:
   - **Easy:** üstte presetin açıklaması, altında sekiz ayar. Bir ayarı değiştirmek alttaki kartları da ayarlar;
     **Runs** satırı hangi adımların hangi sırayla çalışacağını gösterir. Hiçbir şeyi kaybetmeden Advanced'e
     geçebilirsin.
   - **Advanced:** kartları aç/kapat, sırasını oklarla değiştir, ayarlarını gir. Varsayılandan farklı değerler
     yeşil görünür; ↺ varsayılana döndürür. **AI** rozetli kartlar Visien'in kendi modelleridir.
4. Her kartın, ayarın ve düğmenin üstüne gelince kısa bir açıklama çıkar.
5. Zaman çizgisinde bir yere tıkla ve **Preview**'a bas (1/3/5/10 saniye). SeedVR2 açıkken önce 1–2 saniye dene.
6. Beğendiğinde dosyaları seç ve **Render**'a bas. Kuyruk alttaki panelde; **Stop** o anki işi durdurur.

**Export Settings** kartının altındaki satır çıktının boyutunu ve kare hızını gösterir
(`854×480 · 24 fps → 3840×2160 · 24 fps`). Ayarlar birbirine uymazsa Render düğmesi kapanır ve sebebi kartların
altında yazar; SeedVR2 uzun sürecekse yaklaşık süreyi de yazar.

## Renkler, çok planlı videolar ve karşılaştırma

### Color Match (renkleri koru)

DLSS 5 Neural Rendering gerçekçiliği biraz da renkle oynayarak sağlar; ürün videosunda bu, ürünün rengini
kaydırabilir. **Color Match** kartı (Easy mode'da **Original Colors**) en sonda çalışır ve sonucu kaynakla
karşılaştırır, ama yalnızca **geniş alanlardaki rengi** düzeltir:

- Sonuç ve kaynak birkaç yüz piksellik bulanık bir ızgaraya indirilir, CIELAB'de farkları alınır; fark yeniden
  büyütülüp sonuca eklenir. İnce doku, keskin kenarlar ve yerel kontrast (DLSS'in kattığı her şey) olduğu gibi kalır.
- **Original Colors:** ton ve doygunluğun ne kadarı kaynağa döner (100 = birebir; 60–80 DLSS'in rengini biraz bırakır).
- **Original Brightness:** genel parlaklık ve kontrastın ne kadarı döner. 0'da DLSS'in ışığı kalır.
- **Precision:** Broad (geniş alanlar), Balanced, Fine (etiket, logo gibi küçük nesneler de).
- Kare üretimi (RIFE, Frame Generation) ve büyütmeden sonra da çalışır; kaynak zaman olarak hizalanır.

### Clean Shot Starts (plan başları)

Neural Rendering, DLSS ve SeedVR2 her kareyi önceki karelerden yararlanarak üretir. Klibin başında ve her
kesmeden sonra elinde önceki kare olmadığı için planın ilk 1–3 karesi farklı renkte, "render edilmemiş" gibi
çıkar. **Export › Clean Shot Starts** (varsayılan açık) kesmeleri bulur, her planın önüne o planın sonraki
karelerinden ters çevrilmiş kısa bir ısınma ekler, bütün kartları bu uzatılmış video üzerinde çalıştırır ve
ısınma karelerini son dosyayı yazarken çıkarır. Süre, kare sayısı ve ses kaynakla aynı kalır. HDR çıktıda atlanır.

### Karşılaştırma kopyası

**Export › Comparison** *Top / bottom* ya da *Side by side* seçilirse, çıktının yanına `<ad>_compare.mp4`
(görselde `.png`) yazılır: üstte kaynak, altta sonuç, köşelerinde **RAW** ve **NEURAL ENHANCED** etiketleri
(ikisi de değiştirilebilir, örneğin VISIEN ya da müşterinin adı). Kaynak, sonucun boyutuna ve kare hızına
getirilir, ses kaynaktan gelir. **Fit 1080p** her yarıyı en fazla 1920 piksel yapar (paylaşmak için);
**Full size** sonucun çözünürlüğünü kullanır.

## AI modelleri

| Model | Ne yapar | Hız (RTX 5070 Ti, 16 GB) | Lisans | Boyut |
| --- | --- | --- | --- | --- |
| **SeedVR2 3B FP8** | Tek adımlı difüzyonla restorasyon: bulanık, "boyanmış", sıkıştırılmış AI videosunda gerçek doku ve keskinlik. 480p–720p klipleri 1080p'ye çıkarır. | 480p → 1080p: kare başına ~3,5 s | Apache 2.0 | 3,4 GB + 0,5 GB VAE |
| SeedVR2 7B (isteğe bağlı) | Daha fazla ayrıntı; yaklaşık 3 kat yavaş, 16 GB kartta Block Swap ile | — | Apache 2.0 | 8,3 GB |
| **RIFE 4.26** | Ara kare: 24 → 48/60 fps, sahne geçişinde kareleri karıştırmaz | 480p, 2 s → 60 fps: ~4 s | MIT | 25 MB |
| **GFPGAN 1.4** | Bozulan, eriyen yüzleri onarır; doğal sonuç için %40–60 güç | kare başına ~0,1 s | Apache 2.0 | 350 MB |
| CodeFormer (isteğe bağlı) | En doğal yüz onarımı (Fidelity ayarlı) | GFPGAN'a yakın | **NTU S-Lab 1.0: ticari olmayan kullanım** | 380 MB |
| **Color Match** | Kaynağın renklerini geri getirir; ayrıntıya ve DLSS ışığına dokunmaz | 4K: kare başına ~0,2 s (okuma/yazma dahil) | Visien | model yok |

- AI kartları varsayılan sırada **Visual Enhancer kartlarından önce** çalışır: SeedVR2 → Face Restore → Neural
  Rendering → DLSS → RIFE → RTX Super Resolution → renk/keskinlik/gren. Neural Rendering, onarılmış yüzlere
  gerçek cilt dokusunu geri koyar; RIFE büyütmeden önce çalıştığı için 4 kat az piksel işler.
- Adımlar arasında görüntü kayıpsız (FFV1 / PNG) taşınır; ses kaynaktan alınır.
- **SeedVR2 bellek ayarı otomatik:** Visien, PyTorch'u ekran kartının kendi belleğiyle sınırlar. Bellek yetmezse
  Windows'un sistem RAM'ine taşıyıp işi 50–100 kat yavaşlatması yerine iş hata verir ve Visien daha küçük VAE
  parçaları ve Block Swap ile kendiliğinden yeniden dener.
- **SeedVR2 hangi kaynakta:** 480p–1080p AI çıktılarında. 1440p ve üstünde 16 GB kartta çok yavaşlar (3380×1440'ta
  kare başına ~30 s); bu kaynaklarda Output Size'ı *Short side 1080* yap ya da SeedVR2'siz bir preset kullan.
- **CodeFormer lisansı:** NTU S-Lab License 1.0 yalnızca ticari olmayan kullanıma izin verir. Müşteri işleri ve
  ticari projeler için GFPGAN'ı kullan (varsayılan o). CodeFormer'ı kurarken lisansı onaylaman istenir.
- Modeller resmî kaynaklarından iner (Hugging Face `numz/SeedVR2_comfyUI`, GitHub sürümleri) ve yayımlanan
  SHA-256 değerleriyle doğrulanır.

## Presetler

| Preset | Ne yapar | Ek model |
| --- | --- | --- |
| **Visien** (önerilen) | Neural Rendering (Style 0, Intensity 1.20, Local Structure 0.85, Automatic Mask), DLSS **DLAA** temizliği, RTX Super Resolution ile **kısa kenarı 2160** (1080p → 4K; 4K klip 4K kalır). H.265 MP4, Best. | — |
| **Visien 60** | Visien + NVIDIA Video Frame Generation ile 60 fps, sahne geçişi algılama. | — |
| **Visien Film** | Visien + hafif, hareketli film greni (Amount 12). | — |
| **Visien Native** | Yalnızca Neural Rendering + DLAA, kaynak boyutunda. En hızlı deneme. | — |
| **Realism · Natural Skin** | Plastik ya da fazla doygun görünen AI klipleri için: daha yumuşak Neural Rendering, sakin renk ve parlak alanlar (Saturation −6, Highlights −12), 4K, ince gren. | — |
| **Realism · SeedVR2 Restore** | En güçlü temizlik: SeedVR2 3B dokuyu geri getirir ve küçük klipleri 1080p'ye çıkarır, sonra Neural Rendering, RTX 4K, ince gren. Yavaş: önce 1–2 saniye önizle. | SeedVR2 3B |
| **Realism · SeedVR2 Detail (7B)** | Aynısı, ayrıntı için ayarlanmış 7B "sharp" modelle. Kahraman planları ve fotoğraflar için. | SeedVR2 7B |
| **Realism · Faces** | Yüzü bozulan planlar için: GFPGAN %45 güçte, sonra Neural Rendering, 4K, gren. Ticari kullanım serbest. | GFPGAN |
| **Realism · Faces · CodeFormer** | Aynısı CodeFormer ile (Fidelity 0.7). Yalnızca ticari olmayan işler. | CodeFormer |
| **Product · True Color** | Ürün, ambalaj ve marka çekimleri: Visien'in neural rendering'i ve 4K, sonra Color Match kaynağın renklerini birebir geri koyar (Original Colors 100, Fine). | AI ortamı |
| **Realism · Natural Colors** | Visien görünümü, renklerin çoğu kaynaktan (Color Match %70): ten, yemek, moda. | AI ortamı |
| **Smooth 60 · RIFE** | Visien + RIFE 4.26 ile 60 fps (büyütmeden önce, sahne geçişi korumalı). | RIFE |
| **Clean 4K** | Görünümü değiştirmeden büyütme: DLAA + RTX Super Resolution ile 4K. Neural Rendering yok, hızlı. | — |

Presetin üstünde Easy mode ayarlarını değiştirip **Preset › Save as new preset…** ile kendi presetini kaydedebilirsin.
Presetler Visual Enhancer'ın preset biçimindedir (`schema_version 41`); **Export current settings…** ile dışarı
aldığın dosyayı Visual Enhancer da açar (AI kartlarının ayarlarını Visual Enhancer yok sayar).

Ekran görüntündeki Visual Enhancer ayarının birebir kopyası için: Visual Enhancer'ı kapat (ayarlar kapanırken
kaydedilir) ve Visien'de **Preset › Copy settings from Visual Enhancer**'a bas.

### Görüntüleyici

| | |
| --- | --- |
| **Split** | Sürüklenebilir ayırıcı; solda kaynak, sağda Visien |
| **Side by side** | İki pano, yakınlaştırma ve kaydırma birlikte |
| **Top / bottom** | Kaynak üstte, Visien altta |
| **Source / Visien** | Tek görüntü |
| **Lossless** | Oynatma kopyaları yerine kayıpsız PNG kare (piksel düzeyinde karşılaştırma) |
| **Fit / 1:1** | Ekrana sığdır / gerçek piksel |

**Kısayollar:** `Boşluk` oynat/durdur · `←/→` kare (Shift ile 10 kare) · `P` önizleme · `1` Split ·
`2` Side by side · `3` Source · `4` Visien · `5` Top / bottom · `F` sığdır · `Z` 1:1 · `L` Lossless · `Q` kuyruk ·
`Ctrl+Enter` Render.

## Dosyalar nereye gider

| Ne | Nerede |
| --- | --- |
| Render çıktıları | `Videolar\Visien` (Ayarlar › Output). Adın sonuna `_Visien` eklenir; var olan dosyanın üstüne yazılmaz. |
| Önizlemeler | `data\previews` (kayıpsız FFV1; Ayarlar'dan sınır ve temizleme) |
| AI ortamı ve modeller | `ai\site-packages`, `models\` |
| AI ara dosyaları | `data\cache` (iş bitince silinir) |
| Ayarlar, kuyruk, medya listesi, kendi presetlerin | `data\` |
| Günlükler | `data\visien.log`, her AI adımı için `data\logs\ai-*.log`; Visual Enhancer günlüğünün yolu kuyruktaki işte yazar |

## Sorun giderme

- **"Visual Enhancer not connected"**: Ayarlar › *Find automatically*.
- **Pencere açılmıyor**: WebView2 eksik ya da bozuk olabilir; Visien tarayıcıda açılır. `Visien (browser).bat`
  her zaman tarayıcıda açar. Ayrıntı `data\visien.log`.
- **"CUDA 999 / engine poisoned"**: ekran kartı o an iş kabul etmedi (çoğunlukla aynı anda GPU kullanan başka bir
  program). Visien kendiliğinden yeniden dener; sürerse diğer GPU programlarını kapat ya da Windows'u yeniden başlat.
- **SeedVR2 çok yavaş**: klip 1080p'den büyükse Output Size'ı *Short side 1080* yap. Aynı anda Topaz, Resolve ya da
  bir oyun açıksa kapat. Ayrıntı `data\logs\ai-seedvr2-*.log` (her aşamanın süresi ve bellek kullanımı).
- **"Out of GPU memory"**: Visien önce daha küçük parçalarla kendisi yeniden dener. Yine olursa Advanced ›
  SeedVR2 › Block Swap'ı artır ya da Temporal Window'u 5'te tut.
- **Yüzlerde titreme**: Face Restore Strength'i %40–60'ta tut, Temporal Smoothing'i artır.
- **AI modeli kurulamadı**: Ayarlar › AI models'te hata metni yazar; internet bağlantısını kontrol edip Install'a
  yeniden bas. İndirmeler kaldığı yerden değil baştan başlar.
- Kurulum denetimini yeniden çalıştırmak için `install.bat` (sonuç `check.log`).

## Paylaşma ve ürünleştirme

Paylaşmak için **Visien-1.2.0-full.zip**'i ver; alan kişi açar, `install.bat`'ı çalıştırır ve Visual Enhancer'ı
indirir. Paketi istediğin zaman yeniden üretmek için Visien'de **Ayarlar › Share Visien › Create full package**
(Visien klasörünün dışında bir klasör seç; ~9 GB, birkaç dakika). Küçük paket için **Create small package**.
Aynısı komut satırından: `runtime\python\python.exe dev\build_full_package.py full D:\Paylaş\Visien-full.zip`.

Ürün olarak satmayı düşünüyorsan bilmen gerekenler (hukuki görüş değildir):

- **Visual Enhancer** (Merserk) *Merserk Source License 1.0* ile dağıtılıyor: çıktıları ticari olarak kullanmana
  izin veriyor; uygulamayı yazılı izin olmadan yeniden dağıtmayı, başka bir ürüne koymayı ya da yeniden
  markalamayı yasaklıyor. Visien onu içermez; ücretli satıştan önce Merserk'ten yazılı izin almanı öneririm.
- **AI modelleri:** SeedVR2 (ByteDance Seed, Apache 2.0), Practical-RIFE (hzwer, MIT; mimari kodu
  ComfyUI-Frame-Interpolation'dan, MIT), GFPGAN (TencentARC, Apache 2.0), YuNet (OpenCV, MIT) pakete girebilir.
  SeedVR2'yi çalıştıran kod `vendor\seedvr2` altında, numz/ComfyUI-SeedVR2_VideoUpscaler'dan (Apache 2.0, değiştirilmeden).
  **CodeFormer** NTU S-Lab License 1.0 ile ticari olmayan kullanımla sınırlıdır; pakete konmaz, kullanıcı kendi
  onayıyla indirir. Ticari bir üründe CodeFormer'ı varsayılan yapma.
- **PyTorch** (BSD-3) ve içindeki NVIDIA CUDA kütüphaneleri NVIDIA'nın yeniden dağıtım koşullarıyla gelir; OpenCV
  (Apache 2.0), spandrel (MIT), diğer paketlerin lisansları `ai\site-packages\*.dist-info` içinde.
- **NVIDIA DLSS, RTX, NVENC** NVIDIA'nın ticari markalarıdır; pazarlamada "NVIDIA onaylı" izlenimi verme.
- Python (PSF), FastAPI (MIT), Uvicorn (BSD-3), pywebview (BSD-3), pythonnet (MIT), ffmpeg (BtbN GPL derlemesi,
  GPLv3; lisans ve kaynak bilgisi `tools\ffmpeg` içinde). Yazı tipleri SIL Open Font License 1.1
  (`ui\assets\fonts\LICENSE-fonts.txt`).
- Visien'in kendi kodu için bir lisans dosyası eklenmedi; nasıl lisanslayacağına sen karar ver.

---

## English summary

**Visien** is a desktop enhancement studio for AI-generated video and images. It drives
[Visual Enhancer](https://github.com/Merserk/dlss5-visual-enhancer) by Merserk (DLSS 5 Neural Rendering and the
NVIDIA RTX / VFX stages) through its `VE_CLI.exe`, and adds its own GPU models: **SeedVR2** (ByteDance, one-step
diffusion restoration), **RIFE 4.26** frame interpolation and **face restoration** (GFPGAN 1.4, or CodeFormer for
non-commercial work). Everything runs in one ordered pipeline with lossless hand-offs, a native app window, an
**Easy mode** with seven simple controls on top of a preset, hover help on every control, short lossless
previews, a render queue and ready-made realism presets.

**Requirements:** Windows 11 64-bit, an NVIDIA GeForce RTX GPU (12 GB+ for the AI models, 16 GB recommended;
RTX 40/50 for frame generation) with a current driver, WebView2 (built into Windows 11), ~10 GB of disk, and
Visual Enhancer v18 or newer downloaded separately (Visien does not include it). On an **AMD Radeon RX 7000/9000**
only the AI stages run (SeedVR2, RIFE, face restoration), through AMD's ROCm build of PyTorch, which Visien installs
for the detected card; Visual Enhancer's DLSS/RTX stages need NVIDIA.

**Install:** `Visien-1.2.0-full.zip` (~8 GB) contains Python, all packages, ffmpeg, the AI runtime and the
recommended models, so setup needs no internet. Run `install.bat`, start **Visien** from the desktop shortcut and
press **Find automatically** to connect Visual Enhancer. The slim package downloads everything instead.

**Licensing:** Visual Enhancer: Merserk Source License 1.0 (outputs may be used commercially; the app may not be
redistributed). SeedVR2 and GFPGAN: Apache 2.0; RIFE and YuNet: MIT. CodeFormer: NTU S-Lab License 1.0
(non-commercial only) and is never bundled. NVIDIA, DLSS and RTX are trademarks of NVIDIA Corporation.
