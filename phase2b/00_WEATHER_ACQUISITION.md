# Akuisisi cuaca historis sebelum Phase 2B-2

**Snapshot terintegrasi dengan cakupan 704 dari 704 hari.** Arsip mencakup 1 Januari 2024 sampai 4 Desember 2025, termasuk 29 Februari 2024. Sembilan variabel tersedia pada setiap tanggal. [Kontrak cuaca Phase 2A](../phase2a/WEATHER_REFERENCE.md) · [Manifest snapshot](../phase2a/weather/era5-20261121T143547299379Z-fd9571517552/weather_manifest.json)

## Asal dan metadata respons

Pengguna memasok `picture_butte_era5.json` dan melaporkan unduhan langsung dari Open-Meteo di iPhone. Struktur dan satuan JSON sesuai dengan Historical Weather API. Permintaan Phase 2A menetapkan `models=era5`, `cell_selection=land`, dan centroid Picture Butte, Alberta (WGS84 `49.87672, -112.77983`). Respons memuat koordinat grid hasil pemilihan, tanpa URL, koordinat input, atau ID model. Atribusi ERA5 didasarkan pada asal unduhan yang dilaporkan dan permintaan terdokumentasi. Upaya pembandingan dengan URL persis yang tercantum di bawah mendapat HTTPS CONNECT 403 sebelum penyedia merespons, sehingga identitas model tidak dapat dikonfirmasi secara independen dari lampiran.

| Metadata | Nilai |
|---|---|
| Grid respons | `50.0, -112.75`, elevasi respons 906 m |
| Selisih dari koordinat permintaan | 0,12328° ke utara dan 0,02983° ke timur, sekitar 13,87 km |
| Zona, offset, dan format tanggal | `America/Edmonton`, `GMT-6`, −21.600 detik (UTC−06:00 tetap), ISO 8601 |
| Waktu unduhan asli | Tidak tersedia di JSON. Manifest menyimpan waktu pengarsipan UTC secara terpisah. |
| Validasi cakupan | 704 tanggal unik, urut, tanpa selang dan tanpa duplikat |
| Variabel hilang dan nilai kosong | 0 variabel hilang, 0 nilai kosong dari 6.336 pengukuran |

Pergeseran grid berada dalam toleransi Phase 2A sebesar 0,35° per koordinat. Batas hari mengikuti offset tetap penyedia untuk seluruh respons. Offset mengikuti metadata respons tanpa konversi tambahan untuk perubahan waktu musim panas. [Referensi lokasi dan kontrak offset](../phase2a/WEATHER_REFERENCE.md)

| Variabel | Satuan | Minimum | Maksimum |
|---|---|---:|---:|
| `temperature_2m_mean` | °C | −39,9 | 26,5 |
| `temperature_2m_min` | °C | −44,9 | 18,5 |
| `temperature_2m_max` | °C | −32,3 | 35,6 |
| `apparent_temperature_mean` | °C | −45,1 | 25,6 |
| `wind_speed_10m_max` | km/jam | 5,4 | 40,4 |
| `wind_gusts_10m_max` | km/jam | 9,4 | 81,0 |
| `precipitation_sum` | mm | 0 | 57,1 |
| `snowfall_sum` | cm | 0 | 8,12 |
| `relative_humidity_2m_mean` | % | 18 | 98 |

Seluruh pengukuran lulus pemeriksaan batas fisik dan urutan suhu minimum, rerata, dan maksimum. Nilai minimum udara −44,9 °C dan suhu terasa harian terendah −45,1 °C sama-sama terjadi pada 13 Januari 2024. Gust harian tertinggi mencapai 81 km/jam pada 27 Oktober 2024. Nilai ekstrem dipertahankan sebagaimana tercatat dalam arsip.

## Integrasi dan verifikasi

| Tabel | Baris | Cakupan |
|---|---:|---|
| `weather_daily` | 704 | Seluruh tanggal dan sembilan variabel |
| `animal_weather_exposure` | 15.000 | Semua jendela inklusif masuk–keluar lengkap untuk suhu, angin, dan salju |
| `lot_weather_exposure` | 90 | Semua jendela inklusif hari pakan pertama–terakhir lengkap untuk suhu, angin, dan salju |

Snapshot berisi JSON asli tanpa perubahan byte, CSV harian, dan manifest dengan SHA-256 kedua file. Kedua manifest build memuat provenance yang sama. Build dengan argumen snapshot menyelesaikan pengecualian `weather_source_unavailable` sehingga tersisa 163 entri di `audit_exceptions`. Build baseline tanpa argumen snapshot tersedia untuk membandingkan hasil sebelumnya.

Seluruh 661 kontrol baseline lulus dengan hasil identik. Kedua file sumber dan ketujuh tabel kanonik noncuaca cocok byte demi byte dengan baseline `096dcbc`. Laporan audit Phase 1 juga identik. Seluruh 44 tes lulus, 0 gagal, dan 0 dilewati, termasuk tes integrasi arsip aktual. Dua build independen dari arsip yang sama menghasilkan 11 tabel CSV dan tiga laporan JSON identik byte demi byte.

Jalankan dari root repositori setelah memasang paket dengan `python -m pip install -e .`.

```sh
snapshot=phase2a/weather/era5-20261121T143547299379Z-fd9571517552
python -W error -m feedlot_analytics.cli build --weather-snapshot "$snapshot" --output work/era5-replay-one
python -W error -m feedlot_analytics.cli build --weather-snapshot "$snapshot" --output work/era5-replay-two
diff -qr work/era5-replay-one work/era5-replay-two
python -W error -m unittest discover -s tests -v
```

Data cuaca adalah reanalisis historis untuk grid representatif. Data sapi, pakan, kesehatan, dan keuangan berasal dari studi kasus simulasi. Fitur eksposur bersifat deskriptif. Integrasi ini berhenti sebelum analisis Phase 2B-2.

## Riwayat percobaan dan sumber alternatif

Pada percobaan sebelumnya, Codex Cloud menolak semua koneksi di tahap HTTPS CONNECT dengan HTTP 403. Kode HTTP penyedia tidak tersedia dan jumlah byte respons penyedia adalah nol. Permintaan Open-Meteo diulang sekali dengan URL persis dari Phase 2A. URL lengkap dan hasilnya dicatat dalam manifest percobaan. [Manifest percobaan](../phase2a/weather_attempt.json)

| Sumber | Permintaan |
|---|---|
| Open-Meteo Historical Weather API | [Permintaan harian ERA5 lengkap](https://archive-api.open-meteo.com/v1/archive?latitude=49.87672&longitude=-112.77983&models=era5&timezone=America%2FEdmonton&start_date=2024-01-01&end_date=2025-12-04&daily=temperature_2m_mean%2Ctemperature_2m_min%2Ctemperature_2m_max%2Capparent_temperature_mean%2Cwind_speed_10m_max%2Cwind_gusts_10m_max%2Cprecipitation_sum%2Csnowfall_sum%2Crelative_humidity_2m_mean&temperature_unit=celsius&wind_speed_unit=kmh&precipitation_unit=mm&timeformat=iso8601&cell_selection=land) |
| NASA POWER | [Seri meteorologi harian untuk koordinat dan periode target](https://power.larc.nasa.gov/api/temporal/daily/point?parameters=T2M,T2M_MIN,T2M_MAX,RH2M,WS10M_MAX,PRECTOTCORR&community=AG&longitude=-112.77983&latitude=49.87672&start=20240101&end=20251204&format=JSON&time-standard=LST) |
| Environment and Climate Change Canada (ECCC) | [Inventaris stasiun MSC GeoMet di sekitar Picture Butte](https://api.weather.gc.ca/collections/climate-stations/items?bbox=-113.2,49.45,-112.4,50.2&limit=100&f=json) dan [portal iklim historis](https://climate.weather.gc.ca/) |
| Copernicus Climate Data Store (CDS) | [Katalog ERA5 single-level hourly time-series](https://cds.climate.copernicus.eu/api/catalogue/v1/collections/reanalysis-era5-single-levels-timeseries) |
| Destination Earth Data Hub | [Metadata Zarr ERA5, nama penyimpanan lama](https://data.earthdatahub.destine.eu/era5/reanalysis-era5-single-levels-v0.zarr/.zmetadata) |
| Google Research ARCO-ERA5 | [Metadata penyimpanan Zarr publik](https://storage.googleapis.com/gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3/.zmetadata) |

## Pilihan sumber resmi

- **Open-Meteo tetap pilihan utama.** Permintaan menetapkan `models=era5` dengan grid ERA5 0,25°. Keluaran agregat harian mencakup suhu udara dan suhu terasa (°C), kecepatan angin maksimum dan gust (km/jam), presipitasi (mm), salju (cm), dan kelembapan relatif (%). Format ISO memakai satu offset UTC untuk seluruh respons. Data Open-Meteo berlisensi CC BY 4.0 dengan atribusi kepada Open-Meteo dan Copernicus Climate Change Service ERA5. Endpoint gratis digunakan sesuai ketentuan nonkomersial. [Dokumentasi Open-Meteo](https://open-meteo.com/en/docs/historical-weather-api) · [Ketentuan](https://open-meteo.com/en/terms)
- **CDS menyediakan ERA5 resmi sebagai alternatif satu model.** Produk titik ERA5 per jam memakai grid 0,25° dan memilih grid terdekat. Suhu 2 m (K), komponen angin 10 m dan gust (m/s), serta presipitasi total (m) dapat diambil dari produk titik. Single-level lengkap menyediakan variabel tambahan seperti snowfall dalam meter ekuivalen air. Definisi batas hari, konversi salju, dan perhitungan turunan seperti suhu terasa perlu ditetapkan sebelum hasil dapat dimasukkan ke pipeline. Unduhan melalui CDS memerlukan akun dan penerimaan ketentuan dataset CC BY 4.0. [Produk titik](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels-timeseries) · [Produk single-level lengkap](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels)
- **NASA POWER menawarkan seri harian publik.** Grid meteorologi 0,5° × 0,625°. MERRA-2 mendasari seri historis dan NASA dapat menambahkan GEOS-IT untuk data terkini. Kandidat mencakup suhu rerata/minimum/maksimum (°C), kelembapan relatif (%), kecepatan angin maksimum (m/s), dan presipitasi terkoreksi (mm/hari). Batas hari `LST` berarti waktu matahari lokal. Permintaan ini belum menyediakan padanan untuk gust, suhu terasa, atau total salju yang turun per hari. NASA menyediakan data secara gratis dengan panduan atribusi. [Sumber meteorologi](https://power.larc.nasa.gov/docs/methodology/data/sources_meteorology/) · [API harian](https://power.larc.nasa.gov/docs/services/api/temporal/daily/) · [Atribusi](https://power.larc.nasa.gov/docs/referencing/)
- **ECCC menawarkan observasi stasiun.** Arsip harian menyediakan suhu (°C), presipitasi (mm), salju (cm), dan gust maksimum (km/jam), bergantung pada stasiun dan instrumen. Resolusi spasial berupa titik stasiun. Pemilihan stasiun tunggal, jarak, kelengkapan tanggal, dan batas hari stasiun masih perlu diverifikasi. Layanan terbuka MSC menyertakan ECCC Data Server End-use Licence. [Arsip harian](https://api.weather.gc.ca/collections/climate-daily?f=html) · [Akses dan lisensi](https://api.weather.gc.ca/?f=html)
- **Google Research dan Destination Earth menyediakan arsip Zarr ERA5 per jam.** Cakupan dan variabel untuk permintaan ini belum diperiksa dari metadata penyimpanan. Earth Data Hub mendokumentasikan penggunaan token akses untuk penyimpanan atmosfer. Keduanya memerlukan pengolahan per jam sebelum bisa memenuhi kontrak tanggal dan satuan harian. [Google Research ARCO-ERA5](https://github.com/google-research/arco-era5) · [Earth Data Hub](https://earthdatahub.destine.eu/collections/era5/datasets/era5-single-levels-atmosphere)
