# Handoff Stage 6

Konfigurasi [pilot-plan.1](pilot.json) mencakup 1.500 placement selama 1 Januari 2024–31 Desember 2025. Skala tujuan tetap 15.000 placement. Stage 5 melakukan aritmetika jadwal lot dan pengujian fixture 12 sapi. Eksekusi pilot memerlukan runner yang dapat membuat jadwal dan ledger sesuai skala, beserta persetujuan gerbang di bawah.

## Kapasitas dan throughput

- Rencana 60 lot × 25 ekor, satu lot setiap 12 hari. Carry-in 350 ekor melalui 14 lot pembukaan ber-WIP eksplisit. Stay skenario 155/175/195 hari. Penjualan sebagian, stress receiving, serta kasus hospital/recovery perlu diuji pada generator parametrik. Carry-out dicatat sebagai closing stock dan WIP.
- Sediakan 6 pen produksi × 90 ekor, dengan batas perencanaan 75 untuk menjaga ruang mutasi. Receiving 2 × 25 dengan stay 3 hari dan fleksibilitas satu lot cadangan. Hospital 2 × 16 dengan target aktif maksimal 24, peraturan triase serta jalur isolasi untuk overflow. Aritmetika memakai batas kolokasi lot serta puncak yard sebelum transfer hospital. Penugasan kompatibilitas, transfer dan overflow memerlukan hard gate per event.
- Gunakan dua window per hari (08.00–11.00 dan 15.00–17.00 Edmonton). Issue FIFO mengikuti bahan, batch dan bin. Dengan 8–11 kg DM/ekor-hari dan ransum 55–70% DM, ukuran penyimpanan dan throughput diestimasi pada beban puncak, dengan pembelian 7 hari plus buffer 7 hari. Kapasitas fisik bin per bahan, siklus truck/mixer, catchment freight, lead time, minimum lot, assay dan spoilage menggunakan proposal operasi sebelum jadwal disahkan. [Hasil perhitungan](evidence/pilot_capacity.json)
- Perkiraan dasar event ternak terdiri dari 350 opening, 1.500 receipt, sekitar 1.500 first placement transfer bila seluruh sapi keluar receiving ke pen produksi, serta 1.475–1.550 exit. Koreksi, transfer hospital dan pemindahan pen menambah volume tersebut. Ada sekitar 105 siklus inbound mingguan serta batas atas 14.620 pen-window delivery sebelum split load.

## Pengukuran

| Ukuran | Metode Stage 6 | Anggaran pilot yang diusulkan |
|---|---|---:|
| Wall clock | Awal input hingga publish atomik, median tiga cold builds satu seed pada mesin 4 vCPU/16 GiB | 600 detik |
| Peak RSS | Maksimum proses dan worker aktif, ambil profil tahap serta seluruh build | 6 GiB |
| Parquet | Jumlah byte aktual per fact/partisi, pisahkan bukti diagnostik | 2 GiB |
| Query lot-month | Filter satu lot dan 12 bulan pada Parquet via DuckDB, scan bytes/pushdown, ukur median dan p95 cold/warm | 10 s cold, 3 s warm |
| Manifest | Waktu hash file dan baris, jumlah file/partisi, verifikasi lineage | 45 detik |
| Rekonsiliasi | Replay full accounting serta rebuild partisi terdampak pada cutoff yang sama, bandingkan jurnal, closing dan hash | 120 detik |

Usulkan Parquet ZSTD per fact × business year/month, row group 65.536. Pisahkan snapshot restated dan receipt event keys dalam tabel fakta tanpa memecah partisi menurut sapi. Gunakan satu metode alokasi posting. Simpan alternatif pada pengujian atau sampel diagnostik. Delivery-window allocation menjadi grain publikasi cost trace, dengan slices lebih granular untuk audit. Pada asumsi 50–100 byte terkompresi per slice, sekitar 0,12–0,29 GB diperlukan per metode sebelum jurnal, index dan tabel lain. Ukur kompresi aktual pada pilot. Validasi bahwa agregasi mengikat kembali ke alokasi dan pen. Laporkan kecepatan, RAM, partisi serta validasi dengan ukuran input dan mesin yang sebenarnya. Pilot mendahului estimasi ulang anggaran rilis 15.000 dari roadmap.

## Gerbang kesiapan

- [x] Baseline Stage 1–4 dan V1 dipreservasi. Scope kandidat memakai versi baru untuk operasi Stage 5 dan bukti terpisah.
- [x] Cuaca retrospektif dan as-of sudah memiliki kontrak sumber berbeda, cakupan terukur serta fallback berlabel.
- [x] Kontrol fixture menguji persistensi keputusan, link tiket timbang, AF/DM, nutrien, stok, WIP, invoice, COGS, mortalitas dan penutupan.
- [x] Konfigurasi skala, kapasitas dan kriteria evaluasi dipatok sebelum pilot. [Protokol](EVALUATION.md)
- [ ] Implementasikan runner parametrik lintas 24 bulan dengan indeks event, checkpoint replay, ledger partitioned, dispatch pen, receiving/hospital, carry-in/out dan jadwal lot. Uji runner pada kasus kecil sebelum 1.500 placement. Fixture Stage 4 memiliki dokumen transaksi dan batas 12 sapi yang disengaja. Konfigurasi pilot belum menjadi entry point generator umum.
- [ ] Lengkapi spesifikasi phase feeding, pemeriksaan bahan dan planned-versus-realized intake, episode kesehatan, serta settlement. Setujui buku dan toleransi loss serta data pembukaan. Siapkan data carcass/grade berizin untuk analisis distribusi, dan harga historis bertanggal bila sasaran diperluas ke market realism.
- [ ] Arsip forecast vintage perlu verifikasi untuk klaim operasional historis. Klaim retrospektif full empirical membutuhkan 27 hari yang hilang dan data DST yang sesuai bila dipakai untuk analisis per hari bisnis. Skenario fallback dapat dipakai untuk pilot sintetis dengan pelaporan per sumber.
- [ ] Jalankan pemeriksaan performa, holdout dan multi-seed setelah gerbang tersebut selesai. Kumpulkan hasil operasi, nutrisi dan finance sebelum promosi dataset.

Tahap berikutnya adalah menyiapkan dan menguji runner Stage 6 pada data kecil, lalu meminta keputusan promosi untuk menjalankan konfigurasi pilot. Tidak ada pilot atau build rilis pada pekerjaan Stage 5.
