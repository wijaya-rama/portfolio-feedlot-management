# Checkpoint Phase 2A · Highwood Feeders

Phase 2A membangun fondasi Pandas untuk studi kasus feedlot simulasi. Unit analisis utama adalah `animal_id`. Ras, jenis kelamin, dan frame individu berasal dari `Dim_Cattle`. Seluruh 90 lot berisi lebih dari satu ras. Ada 1.447 sapi dengan ras yang berbeda dari label dominan lot.

Branch `analysis-rebuild` melanjutkan audit Phase 1 di `bb313f3`. CSV dan seluruh 10 lembar Excel dibaca dengan grain sumber masing-masing. Dashboard HTML digunakan ketika menjalankan ulang audit Phase 1. [Dokumen Phase 1](analysis_audit/) · [Kontrak dan contoh penggunaan](phase2a/DATA_MODEL.md)

## Rebuild dan verifikasi

Jalankan dari root repositori dengan Python 3.11 atau lebih baru. Versi paket analitis tercantum di `pyproject.toml`. Verifikasi Phase 2A menggunakan Python 3.12.14.

```sh
python -m pip install -e .
python -W error analysis_audit/audit_sources.py > /tmp/feedlot-phase1.json
python -W error -m feedlot_analytics.cli build --output work/phase2a
python -W error -m unittest discover -s tests -v
```

Build menulis tabel CSV, `source_manifest.json`, `transformation_manifest.json` dan `reconciliation.json`. Manifest mencatat SHA-256, tipe data, null, grain, kunci, lineage, eligibilitas, kontrol dan batas pelaporan. Dengan sumber dan versi perangkat lunak yang sama, kedua hasil rebuild dapat dibandingkan byte per byte. Direktori output yang sudah berisi versi berbeda dipertahankan. Gunakan nama direktori baru untuk build dengan input berbeda. [Ringkasan rekonsiliasi yang dilacak Git](phase2a/reconciliation.json)

Audit Phase 1 menghasilkan JSON yang identik pada dua eksekusi. Build Phase 2A melewati 661 kontrol. Untuk suite baru, 30 tes lulus, 0 gagal, dan 1 dilewati karena snapshot ERA5 aktual belum tersedia. Pengayaan end-to-end dengan fixture pengujian menjaga data sapi dan ledger tetap identik.

## Tabel yang dihasilkan

| Tabel | Grain dan kunci | Baris |
|---|---|---:|
| `animal_closeout` | Satu outcome per `animal_id` | 15.000 |
| `animal_health_summary` | Satu ringkasan per `animal_id`, termasuk sapi tanpa catatan perawatan | 15.000 |
| `animal_scale_stage` | Satu penimbangan tercatat per `animal_id, weigh_stage` | 74.268 |
| `lot_closeout` | Satu lot tuntas per `lot_id` | 90 |
| `lot_feed_reconciliation` | Satu jembatan pakan terkirim–teralokasi per `lot_id` | 90 |
| `pen_day_feed` | Satu hari pengiriman tercatat per `pen_id, feed_date` | 16.085 |
| `weather_daily` | Satu hari per `date` di lokasi referensi | 0, akses terblokir |
| `kpi_catalog` | Satu definisi per `metric_id, version` | 33 |
| `audit_exceptions` | Satu temuan per `rule, source_table, source_key` | 164 |
| `animal_weather_exposure` | Satu jendela masuk–keluar per `animal_id` | 15.000 |
| `lot_weather_exposure` | Satu jendela hari pakan pertama–terakhir per `lot_id` | 90 |

## Kontrol dan KPI

- 15.000 sapi masuk, 14.760 terjual, 240 mati, 90 lot, dan 40 kandang. Dari 2.100 sapi yang dirawat tercatat 2.220 kejadian perawatan.
- Pendapatan CAD 45.710.188,31 dikurangi biaya tercatat CAD 41.328.195,32 menghasilkan margin seluruh outcome CAD 4.381.992,99. Jembatan alternatif adalah margin sapi terjual CAD 4.894.187,63 dikurangi kerugian mortalitas CAD 512.194,64. Ledger mencakup pembelian, pakan teralokasi, yardage, biaya veteriner, dan pendapatan.
- Pakan terkirim 28.544.013,42 kg DM dan CAD 10.219.542,92. Alokasi individual 28.544.013,02 kg DM dan CAD 10.219.543,49. Selisih terkirim dikurangi teralokasi adalah +0,40 kg DM dan −CAD 0,57. Semua lot memenuhi batas 0,005 kg DM atau CAD per ekor masuk untuk masing-masing ukuran. Kedua sumber mencatat 2.650.584 head-days dengan konvensi inklusif.
- Biaya tindakan veteriner langsung CAD 143.194,84 termasuk dalam biaya veteriner closeout CAD 413.194,84, bersama biaya dasar CAD 18 per ekor.

| KPI | Definisi | Hasil |
|---|---|---:|
| Margin seluruh outcome per ekor masuk | CAD 4.381.992,99 ÷ 15.000 | CAD 292,13 |
| Margin seluruh outcome per ekor terjual | CAD 4.381.992,99 ÷ 14.760 | CAD 296,88 |
| Margin sapi terjual per ekor terjual | CAD 4.894.187,63 ÷ 14.760 | CAD 331,58 |
| ADG sapi terjual | Total gain ÷ total financial DOF inklusif, sapi eligible yang sama | 1,618056 kg/hari |
| FCR sapi terjual | Total DM teralokasi ÷ total gain, sapi eligible yang sama | 6,673576 kg DM/kg gain |
| Feed COG sapi terjual | Total biaya pakan teralokasi ÷ total gain, sapi eligible yang sama | CAD 2,389641/kg gain |
| Dressing yield sapi terjual | Total HCW ÷ total bobot hidup keluar, sapi eligible yang sama | 61,0050% |
| Morbiditas tercatat | Sapi dengan ≥1 kejadian perawatan ÷ sapi masuk dalam kohor | 14,00% |
| Prime + AAA | Sapi terjual dengan grade Prime atau AAA ÷ sapi terjual dengan grade | 76,57% |

Rasio agregat dan rata-rata rasio individu memiliki kolom terpisah. Untuk ADG antarpenimbangan, penyebutnya adalah hari yang berlalu sejak penimbangan sebelumnya. Gunakan ukuran populasi dan penyebut yang diterbitkan bersama KPI. Untuk analisis pertumbuhan dan karkas, perhatikan seleksi sapi yang bertahan hingga penimbangan atau penjualan.

## Referensi cuaca dan batas bukti

Referensi menggunakan centroid kota Picture Butte pada 49,87672° N dan 112,77983° W, zona `America/Edmonton`. Permintaan ERA5 mencakup 704 hari dari 1 Januari 2024 sampai 4 Desember 2025. Percobaan 21 November 2026 mendapat penolakan HTTPS CONNECT 403 dari proxy, sebelum ada respons penyedia. `weather_daily` hanya berisi skema. Kedua tabel eksposur mempertahankan jendela dan expected days dengan fitur cuaca kosong. [Sumber lokasi dan prosedur akuisisi](phase2a/WEATHER_REFERENCE.md) · [Catatan percobaan](phase2a/weather_attempt.json)

Kode dan seed simulator belum tersedia. Data memperlihatkan variasi waktu pada pengiriman pakan, dengan Desember 2025 hanya mencakup empat hari. Label `winterFCR` pada HTML memakai kohor masuk Q3/Q4 2024. Bukti ini belum mengidentifikasi aturan musim di simulator atau efek biologis cuaca. Data perpindahan, sensus independen kandang, metode alokasi pakan dan perincian settlement juga belum tersedia. [Audit rekonsiliasi Phase 1](analysis_audit/02_DATA_QUALITY_AND_RECONCILIATION.md)

## Handoff Phase 2B

Mulai dari `analysis-rebuild` dan gunakan `feedlot_analytics.build` sebagai titik masuk. Cocokkan hash dan hasil rekonsiliasi dengan checkpoint ini. Untuk cuaca, ambil snapshot ERA5 yang terdokumentasi dari lingkungan dengan akses dan jalankan ulang integrasi pada snapshot tersebut. Tetapkan peran tanggal dan unit kohor sebelum membuat perbandingan.

| Urutan | Notebook | Fokus |
|---|---|---|
| 00 | Validasi sumber dan cakupan | Hash, kontrol, eligible head, kalender, dan pengecualian |
| 01 | Ekonomi closeout dan pengadaan | Jembatan margin, mortalitas, lot, asal dan basis pembelian |
| 02 | Pakan, pertumbuhan dan eksposur | Bridge pakan, ADG/FCR/COG, interval penimbangan dan cakupan cuaca |
| 03 | Kesehatan dan karkas | First pull, kejadian berulang, biaya, grade, volume dan seleksi penyintas |
| 04 | Skenario manajemen | Break-even dan sensitivitas dengan asumsi eksplisit |
| 05 | Validasi ekspor | Paritas KPI, filter dan total untuk keluaran berikutnya |
