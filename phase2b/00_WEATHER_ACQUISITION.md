# Akuisisi cuaca historis sebelum Phase 2B-2

**Akuisisi terblokir per 21 November 2026.** Sebanyak **0 dari 704 hari** terverifikasi. Targetnya 1 Januari 2024 sampai 4 Desember 2025 di centroid Picture Butte, Alberta (WGS84 `49.87672, -112.77983`), dengan zona `America/Edmonton`. Tanggal, grid aktual, satuan respons, dan kelengkapan pengukuran belum dapat diperiksa. [Referensi lokasi dan kontrak Phase 2A](../phase2a/WEATHER_REFERENCE.md)

## Permintaan dan hasil

Codex Cloud menolak semua percobaan di tahap HTTPS CONNECT dengan HTTP 403. Kode HTTP penyedia tidak tersedia dan jumlah byte respons penyedia adalah nol. Permintaan Open-Meteo diulang sekali dengan URL persis dari Phase 2A. URL lengkap dan hasilnya dicatat dalam manifest percobaan. [Manifest percobaan](../phase2a/weather_attempt.json)

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

## Integrasi dan verifikasi

Build menggunakan jalur Phase 2A. Kedua manifest keluaran, `source_manifest.json` dan `transformation_manifest.json`, mencatat provenance cuaca yang sama. Tanpa snapshot, statusnya `blocked`. Tabel `weather_daily` berisi skema dengan nol baris. Jendela 15.000 sapi dan 90 lot tetap tercatat dengan cakupan observasi nol dan nilai fitur cuaca kosong.

Seluruh 661 kontrol rekonsiliasi lulus. Ke-11 tabel, laporan rekonsiliasi, dan hasil audit Phase 1 identik byte demi byte dengan commit awal `bbc9bfc`. Suite otomatis mencatat 43 tes lulus, 0 gagal, dan 1 dilewati karena snapshot ERA5 aktual belum tersedia.

Tes replay membangun dua keluaran identik byte demi byte dari satu snapshot fixture di direktori temporer tanpa akses jaringan. Tes ini juga membandingkan tabel dan metrik sapi, pakan, keuangan, dan biologi secara eksak dengan build tanpa cuaca. Replay data ERA5 aktual masih menunggu snapshot dari penyedia.

## Pengambilan dengan bantuan pengguna

1. Di komputer atau lingkungan yang diizinkan mengakses `archive-api.open-meteo.com`, buka checkout `analysis-rebuild`. Dari root repositori, jalankan berikut dengan Python 3.11 atau lebih baru.

   ```sh
   set -eu
   python -m pip install -e .
   snapshot=$(python -W error -m feedlot_analytics.cli fetch-weather --output work/weather)
   printf '%s\n' "$snapshot"
   tar -czf work/picture-butte-era5.tar.gz -C "$(dirname "$snapshot")" "$(basename "$snapshot")"
   ```

2. Unggah `work/picture-butte-era5.tar.gz` ke percakapan ini. Folder yang diarsipkan berisi `open_meteo_raw.json`, `weather_daily.csv`, dan `weather_manifest.json`. File manifest memuat waktu pengambilan UTC, koordinat grid, tanggal, satuan, null per variabel, dan SHA-256 untuk kedua file data.

3. Dari checkout yang sama, ekstrak tar dan arahkan `snapshot` ke folder versi `era5-…` hasil ekstraksi. Jalankan build dua kali ke direktori baru dan uji snapshot dengan suite yang sama.

   ```sh
   python -W error -m feedlot_analytics.cli build --weather-snapshot "$snapshot" --output work/era5-replay-one
   python -W error -m feedlot_analytics.cli build --weather-snapshot "$snapshot" --output work/era5-replay-two
   diff -qr work/era5-replay-one work/era5-replay-two
   FEEDLOT_WEATHER_SNAPSHOT="$snapshot" python -W error -m unittest discover -s tests -v
   ```

Jika permintaan gagal, simpan pesan galat untuk investigasi dan pertahankan status cuaca terblokir. Akuisisi ini berhenti sebelum analisis Phase 2B-2.
