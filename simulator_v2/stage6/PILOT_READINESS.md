# Keputusan pilot 1.500 placement

## Stage 7 · Arsip 250 dan pilot khusus evaluasi

Evaluasi terlebih dahulu arsip 250 yang sudah tersimpan. Analisis satu seed memberikan bukti awal Stage 5. Pilot 1.500 tersedia dengan otorisasi khusus evaluasi, dan audit penuh tetap berlaku. Promosi dan produksi 15.000 menunggu holdout lengkap, bukti penerimaan operasi, dan kapasitas runtime terverifikasi. [Keputusan terbaru dan bukti](FINAL_DATASET_READINESS.md) · [Panduan Colab](colab/README.md)

## Stage 6B.1 · HOLD

Stage 6B.1 menyelesaikan investigasi mortalitas berlebih, optimasi audit lintas domain dan posting, kontrak validasi dua mode (`full` vs `incremental`), serta perencanaan pasokan pakan berbasis bahan. Seluruh 249 tes regresi (termasuk 8 tes baru Stage 6B.1), 62 subtes, 241 hash baseline Stage 1–4, determinisme cold-run, dan ekuivalensi semantik 78 tabel lulus penuh. [Laporan lengkap Stage 6B.1](STAGE6B1.md) · [Bukti Stage 6B.1](evidence/stage6b1/)

- **Perbaikan kebenaran dan pasokan terverifikasi.** Dua cacat struktural klinis (hazard akut tetap berlaku pada kasus kronis; `recovery_daily` hanya diuji per 2 hari tanpa compounding) diperbaiki secara backwards-compatible, skenario sintetis berversi `stage6b1-baseline-health.1` menurunkan mortalitas dari `44/308` (`37,25` kematian/100 animal-years) menjadi `5/308` (`4,01` kematian/100 animal-years) pada 250 placement dengan skenario adverse lama tetap dipertahankan, dan perencanaan stok spesifik bahan menghilangkan 2 pembatalan load silase menjadi `0` shortage melalui PO/receipt eksplisit.
- **Performa meningkat signifikan namun anggaran 600 detik belum tercapai.** Pada mesin yang sama (`diagnostic`), wall clock turun `46,0%` (`105,50` → `56,93` dtk), audit lintas domain turun `70,0%` (`29,55` → `8,88` dtk), dan fingerprint jurnal turun `74,2%` (`4,38` → `1,13` dtk). Pada estimasi referensi EPYC untuk 1.500 placement (belum dieksekusi), fingerprint (`27–32` dtk) kini masuk anggaran `45` dtk dan Peak RSS (`2,5–2,9` GiB) aman di bawah `6` GiB, tetapi wall clock (`~1.339–1.591` dtk), audit penuh (`~192–228` dtk), dan Parquet (`2,00–2,38` GiB) masih melewati target perencanaan `600` dtk / `120` dtk / `2` GiB. Build 250 placement penuh juga belum dapat dijalankan dalam batas timeout perintah tunggal `600` dtk pada VM Intel Xeon 2,30 GHz ini (`~820` dtk terproyeksi).
- **Keterbatasan pemodelan tetap terbuka.** Parameter kesehatan, pertumbuhan, asupan, karkas, dan harga tetap sintetis tanpa klaim kalibrasi lapangan; evaluasi estimator holdout 7/30/60 hari (5 seed) dan penerimaan operasional headroom/overflow 1.500 placement belum dijalankan.
- **Rekomendasi terukur:** Pertahankan status **HOLD** sampai (1) build 250 dan 500 placement penuh diverifikasi pada runner tanpa batas 600 dtk, (2) disepakati apakah anggaran pilot perlu disesuaikan untuk build penuh ~25–30 menit atau audit bulanan diparalelkan lebih lanjut, dan (3) gerbang evaluasi Stage 5 terpenuhi.

## Stage 6B · HOLD

Preflight membuktikan kalender penuh, carry-in dan carry-out ber-WIP, dua window pakan harian, serta 24 penutupan per view untuk ukuran yang diuji. Stage 4 menjalankan posting dan close. Nama periode serta snapshot original dan restated dapat direkonstruksi dari partisi kandidat. [Pengukuran dan hasil Stage 6B](STAGE6B.md)

- **Lulus pada skala terukur.** Kapasitas fisik, pergerakan, persamaan stok, yardage, horizon akses pakan, pemilihan forecast, AF/DM/nutrien, FIFO, clearing, GL/WIP, release, lock dan restatement lulus. Uji Stage 4 mencakup invoice dan reversals. Stage 6B menguji packer adjustment dan koreksi yardage pada runtime.
- **Anggaran pilot belum tercapai.** Pipeline masih memproses pertumbuhan per segmen, alokasi per rilis, ekspansi sumber dan posting penuh dua view, kemudian membaca ulang puluhan juta baris pada proyeksi pilot. Model berbasis workload memproyeksikan wall clock dan rekonsiliasi di atas anggaran pada mesin terukur. Anggaran Stage 5 ditetapkan untuk mesin acuan 4 vCPU dan 16 GiB. [Proyeksi dan anggaran](evidence/stage6b/scaling.json)
- **Kapasitas pilot masih perlu verifikasi.** Angka pen yang diskalakan menguji batas fisik pada preflight. Headroom produksi, aturan prioritas hospital, overflow, kebijakan segregasi lot, dan cadence inbound pada 1.500 placement perlu pengujian sesuai rencana. [Rencana Stage 5](../stage5/STAGE6_HANDOFF.md)
- **Kalibrasi masih sintetis.** Holdout estimator 7/30/60 hari dan protokol multi-seed Stage 5 belum tercakup. Arsip yang diterima mendukung replay retrospektif dengan fallback musiman. Vintage forecast historis, kesehatan, gain dan intake, karkas dan pricing memerlukan data terukur untuk penggunaan komersial. [Protokol evaluasi](../stage5/EVALUATION.md)

## Stage 6A

**Stage 6A menetapkan HOLD untuk eksekusi pilot 1.500 placement.** Diagnostic runner memenuhi kontrol integrasi seed-42 dan kasus adversarial terkontrol. Promosi pilot memerlukan verifikasi kapasitas konfigurasi pilot dan pengukuran yang menunjukkan proses dapat berakhir dalam anggaran yang disepakati. Stage 6A berakhir pada dataset diagnostik.

## Cakupan yang diperiksa

- Kalender lintas tahun dengan carry-in ber-WIP eksplisit, carry-out, sebagian lot dijual bertahap, dan penutupan per bulan.
- Motor operasi maju dalam waktu, kapasitas per event, jalur overflow yang eksplisit, serta jalur pengadaan yang memisahkan open PO dari receipt.
- Rekonsiliasi ternak, akses pakan, AF/DM, nutrien, FIFO, sen CAD, WIP, release dan as-of/restatement. Kasus adversarial memeriksa kekurangan bahan, penuh receiving/produksi/hospital, mortalitas dengan atau tanpa perawatan, grade kosong, posting packer setelah cutoff, perubahan DST dan invariansi asupan terhadap biaya.
- Checkpoints operasi harian, staging posting di disk, grain journal posting per sapi/delivery, ZSTD bulanan, dan cold build pembanding. [Hasil diagnostik](RESULTS.md)

## Gerbang promosi

1. Gunakan Stage 5 handoff untuk mematok jadwal 1.500 placement, carry-in per cohort, headroom pen, penanganan overflow hospital, lead time, kapasitas dan strategi pengadaan. Jalankan uji konfigurasi yang terkontrol di bawah skala pilot, termasuk periode 24 bulan, backlog dan beberapa seed. [Handoff Stage 5](../stage5/STAGE6_HANDOFF.md)
2. Ukur ulang pada beban menengah. Prioritaskan close Stage 4 yang menghimpun jurnal kumulatif dan menghitung ulang fingerprint historis dalam satu close, lalu audit bulanan yang memuat indeks satu partisi. Target handoff ialah build 600 detik, RSS 6 GiB, Parquet 2 GiB dan rekonsiliasi 120 detik pada mesin acuan. Ketua proses dapat menentukan batas promotable berdasarkan pengukuran tersebut. Kinerja query lot-month dan pemulihan partisi terdampak masih memerlukan pengukuran.
3. Jalankan evaluasi bobot terdaftar ketika jumlah lot dan pasangan tiket memungkinkan. Populasi diagnostik dipakai untuk menguji kronologi dan distribusi, dengan horizon produksi yang dipersingkat. [Protokol evaluasi Stage 5](../stage5/EVALUATION.md)
4. Pertahankan label kalibrasi sintetis. Koefisien penyakit, respons biologis cuaca, carcass dan pricing memerlukan data pembanding berizin untuk klaim komersial. Rekonstruksi kondisi historis lengkap memerlukan arsip cuaca dan forecast yang tersedia pada cutoff yang sesuai. [Telaah ilmiah Stage 5](../stage5/REVIEW.md) · [Kontrak cuaca](../stage5/WEATHER.md)
