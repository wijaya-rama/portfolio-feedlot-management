# Simulator V2 · Stage 6

## Stage 6B.1

[Laporan Stage 6B.1](STAGE6B1.md) memuat analisis akar masalah mortalitas dan jembatan epidemiologi, skenario kesehatan berversi (`stage6b1-baseline-health.1`), optimasi audit lintas domain dan posting, kontrak validasi `full` vs `incremental`, perencanaan stok spesifik bahan, serta bukti ringkas di [evidence/stage6b1/](evidence/stage6b1/).

## Stage 6B

[Preflight 24 bulan](STAGE6B.md) memuat pengukuran, konfigurasi skala, ekuivalensi dan rekonsiliasi. [Keputusan kesiapan pilot](PILOT_READINESS.md) menjelaskan gerbang untuk skala 1.500 placement. Baseline Stage 6A berada di [commit 8dfbaa3](https://github.com/wijaya-rama/portfolio-feedlot-management/commit/8dfbaa3160dc88a9b673cd0772a2d7813866e5ee).

## Stage 6A

Stage 6A menjalankan operasi feedlot sintetis maju dalam waktu dengan konfigurasi lot, kapasitas, kalender, pembukaan, kesehatan, pakan, pembiayaan, dan seed. Dataset diagnostik meliputi 100 placement dan delapan sapi carry-in. Besaran biologis, treatment, grading, harga, dan nilai portofolio berasal dari skenario sintetis.

| Dokumen | Isi |
|---|---|
| [Audit dan rancangan](DESIGN.md) | Komponen yang digunakan kembali, urutan operasi dan asumsi |
| [Kamus data](DATA_DICTIONARY.md) | Grain, hubungan, waktu, dan unit |
| [Hasil diagnostik](RESULTS.md) | Rekonsiliasi, distribusi, outlier, regresi, dan hasil pengukuran |
| [Keputusan pilot](PILOT_READINESS.md) | Syarat promosi dan risiko tersisa |
| [Dataset diagnostik](evidence/diagnostic/) | Parquet ZSTD, hash, konfigurasi, kontrol, dan laporan terstruktur |

## Reproduksi

Gunakan Python 3.11 atau lebih baru dari root repositori. PyArrow mengikuti pin Stage 1. Pilih direktori keluaran baru untuk setiap build.

```sh
python -m venv work/stage6-venv
work/stage6-venv/bin/python -m pip install -e . -r simulator_v2/stage6/colab/requirements-production.txt pytest
PYTHONHASHSEED=107 work/stage6-venv/bin/python -m simulator_v2.stage6 --output work/stage6-a
PYTHONHASHSEED=218 work/stage6-venv/bin/python -m simulator_v2.stage6 --output work/stage6-b
cmp work/stage6-a/hashes.json work/stage6-b/hashes.json
work/stage6-venv/bin/python -m pytest -q tests simulator_v2/stage{1,2,3,3_5,4,5,6}/tests
```

Pakai `--config` untuk memilih kontrak JSON dan `--seed` untuk menimpa seed. Konfigurasi [diagnostik](configs/diagnostic.json) dan [uji kekurangan stok](configs/adversarial-shortage.json) menggunakan kontrak yang sama. Masukkan placement sebagai tanggal, jumlah ekor dan bobot referensi lot. Tambahkan cohort pembukaan dengan status, lokasi, bobot, umur, DOF, biaya WIP per ekor dan dokumen asal. Aktifkan arsip untuk jalur biologis retrospektif. Untuk operasi, tetapkan forecast sintetis dengan tanggal target, issue time dan availability UTC, atau gunakan fallback kalender dari kalibrasi.

## Build dan lineage

Generator menulis keluaran ke direktori sementara dan mempublikasikannya atomik setelah gate lulus. State pertumbuhan menyimpan bobot dan cadangan nutrien aktif. Dokumen dispatch untuk posting di-checkpoint per hari. SQLite sementara memegang input buku, sumber dan jurnal selama posting. Histori Parquet dipartisi menurut bulan bisnis dan ditulis dalam buffer 8.192 baris. Sebagian tabel master serta crosswalk kecil atau lintas waktu memakai satu partisi. Skrip staging dan dependensi Python standar tidak dibutuhkan untuk membaca Parquet.

`run_manifest.json` menyimpan konfigurasi, versi, runtime, hash input dan horizon. Commit checkout saat build merekam garis dasar Git yang sedang aktif. Hash file sumber mengidentifikasi kode kerja yang persis digunakan. `hashes.json` mencakup tiap Parquet dan artefak deterministik. Waktu aktual, RSS dan informasi runtime dicatat di luar indeks deterministik. File Parquet menyimpan `run_id` dan metadata versi skema.

## Audit awal

- Komponen yang dapat dipakai kembali pada skala berbeda meliputi validasi source/replay dan SOH Stage 1, skema profil, sampler tiket serta fungsi estimator Stage 2, FIFO dan formula/dispatch Stage 3, rilis bertahap Stage 3.5, buku dan close Stage 4, serta fungsi pertumbuhan dan kontrak cuaca Stage 5.
- Komponen yang terikat fixture mencakup konstanta horizon dan 12 master Stage 1, jadwal treatment dan timbang Stage 2, pen/dispatch dan stok skrip Stage 3/3.5, tarif/dokumen biaya dan penerimaan 12 sapi Stage 4, serta orkestrasi, evaluasi dan proyeksi aritmetika Stage 5.
- Stage 6A membentuk sumber baru dari scheduler dan menyuplai data ke fungsi yang diterima. Dokumen Stage 1–5, arsip cuaca dan bukti V1 tetap berada pada path serta commit terbitnya.
