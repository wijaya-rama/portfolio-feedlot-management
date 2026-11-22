# Keputusan pilot 1.500 placement

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
