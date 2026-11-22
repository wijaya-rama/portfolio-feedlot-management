# Integrasi cuaca dan cakupan

Arsip dari Historical Weather API Open-Meteo terdiri dari 704 tanggal berurutan pada 1 Januari 2024–4 Desember 2025, termasuk 29 Februari 2024. Ada sembilan variabel dan 6.336 nilai tanpa null. Loader Stage 5 memeriksa SHA-256 JSON mentah dan CSV dari manifest, tanggal, panjang seri, satuan, grid dan batas fisik. Sumber terdokumentasi meminta `models=era5`, land cell, dan centroid Picture Butte, Alberta, 49,87672° N dan 112,77983° W. Respons memberi grid 50,00° N dan 112,75° W, elevasi 906 m, sekitar 13,87 km dari centroid. Payload tidak memuat identitas model atau waktu pengunduhan asli. Atribusi model mengikuti permintaan dan riwayat unduhan yang dilaporkan pengguna. Sumber berlisensi CC BY 4.0. [Manifest asli](../../phase2a/weather/era5-20261121T143547299379Z-fd9571517552/weather_manifest.json) · [Dokumentasi Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)

| Variabel arsip | Definisi dan satuan |
|---|---|
| `temperature_2m_mean`, `temperature_2m_min`, `temperature_2m_max` | Rerata, minimum, maksimum suhu udara 2 m, °C |
| `apparent_temperature_mean` | Rerata suhu terasa produk penyedia, °C |
| `wind_speed_10m_max`, `wind_gusts_10m_max` | Maksimum angin dan gust 10 m, km/jam |
| `precipitation_sum`, `snowfall_sum` | Total presipitasi mm dan salju cm |
| `relative_humidity_2m_mean` | Rerata kelembapan relatif 2 m, % |

Suhu udara rerata merupakan satu-satunya forcing termal saat ini. Rerata satu hari digunakan sebagai konstanta selama interval asli. Suhu terasa penyedia dan angin maksimum harian belum menyediakan indeks thermal sapi. Wind chill kandang, heat-load berjam-jam, pendinginan malam, kelembapan simultan, bedding, bulu, sun/wind exposure, dan efek badai intrahari memerlukan input tambahan. Pengembangan HLI membutuhkan setidaknya kecepatan angin, kelembapan dan suhu black globe atau estimasi yang divalidasi. Daily cukup untuk sensitivitas pemeliharaan agregat. UTC hourly dan catatan pen diperlukan untuk kalibrasi per feeding window atau analisis heat-stress ekstrem. [Gaughan dkk., 2008](https://pubmed.ncbi.nlm.nih.gov/17911236/) · [BCRC Winter Management](https://www.beefresearch.ca/topics/winter-management-of-beef-cattle/)

## Kalender dan mode

Respons menamai `America/Edmonton` dengan offset tetap UTC−06. Setiap label arsip dipetakan ke interval setengah terbuka 06.00 UTC hingga 06.00 UTC berikutnya. Hari bisnis memakai IANA `America/Edmonton`, termasuk hari 23 dan 25 jam. Saat offset −07, arsip berganti pukul 23.00 waktu bisnis. Ada 230 label dengan batas yang berbeda dari tanggal bisnis yang namanya sama. Stage 5 memotong langkah biologi pada batas sumber UTC. Offset arsip tetap dan DST bisnis diperlakukan sesuai kontrak masing-masing.

| Mode | Aturan |
|---|---|
| Retrospektif | Menggunakan reanalisis sebagai forcing eksogen pada intervalnya. Konsumsi dan biaya diambil dari keputusan operasional yang sudah dibekukan. Bobot retrospektif tidak memasok estimator, tiket skala, alokasi atau buku posting. |
| Operasional as-of | Memakai skenario musiman yang ditetapkan sebelumnya. API internal juga dapat memakai forecast bertimestamp terbit dan tersedia pada atau sebelum awal hari bisnis. Vintage intrahari tidak dipakai dalam versi ini. Forecast historis ber-vintage belum tersedia. |
| Sensitivitas | Suhu buatan konstan dengan input yang dipasangkan. Setiap hasil membawa jenis sumber sehingga observasi arsip dan fallback dapat dianalisis terpisah. |

Arsip reanalisis diterbitkan dengan jeda. Dokumentasi penyedia menyebut jeda beberapa hari untuk ERA5, sementara setiap vintage arsip historis tidak melekat pada sumber ini. Waktu arsip lokal tahun 2026 hanya membuktikan penyimpanan ulang. Mode as-of tidak memakai hari, forecast, atau statistik arsip yang baru diketahui kemudian. [Open-Meteo Historical Weather API](https://open-meteo.com/en/docs/historical-weather-api) · [Open-Meteo Open Data](https://github.com/open-meteo/open-data)

## Desember 2025

Permintaan tanggal 5–31 Desember dengan parameter sumber yang sama mendapat HTTP CONNECT 403 sebelum endpoint penyedia memberi respons. Seluruh 27 label tanggal tersebut tetap kosong pada arsip. Untuk horizon 731 hari, cakupan interval arsip adalah **16.895 dari 17.544 jam**. Fallback mengisi 649 jam, yaitu 27 hari penuh serta satu jam terakhir pada 4 Desember. Ada 703 hari bisnis seluruhnya terliput arsip. Fixture juga mulai 31 Desember 2023, sebelum tanggal label pertama. Periode itu memakai fallback kecuali bagian yang sudah masuk interval arsip 1 Januari 2024 UTC−06.

Nilai fallback bulanan adalah skenario suhu sintetis yang dipatok di konfigurasi. Hasil biologi menurut sumber dilaporkan dalam `by_weather_source`, termasuk hari-sapi dan DMI setiap kelompok. Input arsip, fallback dan forecast tetap dapat diaudit melalui `weather_source_id` dan `weather_kind`. [Bukti cakupan](evidence/weather.json)
