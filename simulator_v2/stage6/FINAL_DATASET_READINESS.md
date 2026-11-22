# Kesiapan dataset 15.000 placement

## Keputusan

**Pilot 1.500 tersedia dengan otorisasi khusus evaluasi. Promosi menunggu bukti holdout Stage 5. Produksi 15.000 masih HOLD.** Jadwal memuat tepat 15.000 placement dalam 731 hari bisnis Edmonton. Kelayakan operasi didukung oleh preflight, sedangkan kebutuhan memori dan durasi fase terbesar belum terbukti pada skala produksi. Anggaran lama 600 detik adalah tolok ukur rekayasa. Build ini tidak memakai batas waktu 600 detik.

Persiapan berangkat dari `d9143232d8cbeea7cabf9d3841eb906fb19606fd`. Commit `39770fb9e2867127f1ddac671ac694997e26b864` adalah sumber hasil 250 yang dilaporkan pengguna. Pilot evaluasi 1.500 seed 42 telah selesai menurut laporan pengguna. Produksi 15.000 belum dijalankan. Bukti lama tetap berada di jalur semula. [Panduan Colab untuk iPhone](colab/README.md)

## Kapasitas operasional

| Rencana | Pilot 1.500 | Produksi 15.000 |
|---|---:|---:|
| Lot masuk | 60 × 25 setiap 12 hari | 150 × 100 setiap 4–5 hari |
| Carry-in ber-WIP | 14 lot / 350 ekor | 35 lot / 3.500 ekor |
| Receiving / produksi / hospital | 2 × 30 / 23 × 30 / 2 × 16 | 3 × 115 / 57 × 115 / 4 × 20 |
| Target maksimum bed hospital terisi | 24 dari 32 | 60 dari 80 |
| Puncak serentak pada asumsi draft +21 hari | 450 | 4.356 |
| Pen produksi terpakai / cadangan pada +21 hari | 19 / 4 | 48 / 9 |
| Puncak serentak pada stress +35 hari | 483 | 4.591 |
| Carry-out pada asumsi +21 hari, sebelum simulasi biologis | 377 | 4.156 |
| Batas shipment setiap Selasa | 70 ekor | 285 ekor |
| Beban maksimum per window / slot dalam window sore | 27 / 36 | 64 / 72 |
| Batas penerimaan supplier per hari | 65 ton AF | 500 ton AF |

- Receiving berlangsung 2–4 hari. Satu pen receiving atau produksi diisi satu lot pada satu waktu. Pen yang penuh atau tidak tersisa membuat antrian eksplisit. Rumah sakit boleh menangani beberapa lot dari yard yang sama dan mencatat ternak klinis satu per satu. Kasus berat yang tidak mendapat bed masuk triase di lokasi. Ketika pulih, ternak kembali ke pen produksi yang kompatibel. Uji bed penuh memastikan triase dan transfer. Preflight jadwal tidak memprediksi distribusi klinis atau jumlah hari bed terisi. Laporan pilot akan memuat peak hospital dan kejadian aktual. Gerbang rilis menahan publikasi bila ada penempatan tertunda, triase akibat penuh, return tertunda atau pembatalan load akibat bahan habis.
- Stay minimum ditetapkan per lot pada 155/175/195 hari. Draft mingguan memakai ambang 490 kg, serta ambang 440 kg setelah 21 hari melewati stay minimum. Draft tetap membutuhkan bukti bobot as-of dan status klinis yang memenuhi syarat. Penjualan parsial maksimal 65% dari lot per shipment dan tunduk pada kuota mingguan. Preflight memperkirakan kapasitas dengan asumsi semua ternak memenuhi syarat pada tanggal yang ditentukan. Simulasi aktual juga mempertimbangkan tiket terlambat, hewan sakit, variasi bobot, dan kematian.
- Gudang punya batas bin, stok awal, reorder dan target terpisah untuk silase, jelai dan oat. Jam 05.30 digunakan untuk receipt dan transfer sebelum dua window pakan Edmonton. PO mengirim 60% pada hari ke-3 dan 40% pada hari ke-5. Kasus stress meningkatkan bagian adaptasi dari 10% ke 25% serta menunda receipt kedua ke hari ke-6. Preflight memakai 11 kg DM per ekor per hari dan desain 550 / 5.000 ekor selama 56 hari. Uji memakai PO, assay, receipt, issue dan replay FIFO aktual. Batas supplier diterapkan terhadap total AF masuk per hari.
- Kapasitas mixer/truk per load 5 / 8 ton AF. Model menyediakan 3 / 6 pasangan peralatan dengan siklus 10 menit, setara 36 / 72 slot pada window sore dua jam. Slot mencakup kerja paralel dan bahan siap pakai. Timestamp mencatat awal window logis. Waktu loading, antrean rute dan jam kerja staf perlu data operasional jika ingin menafsirkan hasil sebagai studi utilisasi per alat.
- Biaya yardage CAD 1,25 / 1,10 per ekor-hari dan freight CAD 42,50 / 38,00 per ekor menyatakan asumsi tarif sintetis untuk skala layanan berbeda. Komponen yang dimodelkan mencakup pembelian, feed, layanan vet, yardage dan settlement packer. Model ini tidak memasukkan daftar gaji, shift, depresiasi, atau operating expense yard lengkap. Margin yang disajikan adalah kontribusi dari biaya yang dimodelkan.

[Konfigurasi pilot](configs/stage7-pilot-1500.json) · [Konfigurasi produksi](configs/stage7-production-15000.json) · [Bukti preflight](evidence/stage7/)

## Kendali mekanistik dan penggunaan analitis

- Kapasitas dicek per pergerakan. Movement ledger merekonsiliasi stock, pen dan lot. Publikasi kedua konfigurasi rilis mensyaratkan jumlah receipt aktual tepat sama dengan jadwal. Carry-in membawa biaya pembukaan eksplisit dan carry-out membawa state serta WIP penutupan.
- Feed plan memakai observasi yang eligible pada cutoff. Audit melacak lot dan akses pakan, massa AF/DM, reserve energi/protein, feed loss, alokasi konsumsi, dan FIFO gram serta sen CAD. Retrospektif cuaca terpisah dari jalur keputusan. Tanpa forecast vintage, jalur operasional memakai seasonal fallback berlabel. Keputusan penjualan memakai estimasi yang tersedia saat itu.
- Sumber, parent link, jurnal dua baris, clearing dan pelepasan WIP direkonsiliasi ke COGS bila dijual dan mortality expense bila mati. `as_known` terkunci setiap akhir periode. `restated` membawa cutoff akhir dan identitas approval aktif. Audit membandingkan WIP dan COGS yang terbit dengan hasil close, dan penerimaan gudang dengan replay. Mode incremental tetap menolak partisi hilang atau rusak. Publikasi Colab memakai audit penuh.
- Skenario kesehatan baseline dan pertumbuhan, intake, hubungan cuaca, harga, grade dan karkas memakai parameter sintetis. Aritmetika kapasitas dan distribusi yang terbit membantu analisis portofolio. Validasi komersial membutuhkan kalibrasi empiris serta data berizin. Stress lead time, overflow, penjualan terlambat, dan skenario kesehatan adverse historis dipakai untuk uji sensitivitas.

## Pemulihan dan batas fase

Satu scheduler mencakup semua lot dan tanggal, lalu buku yang sama membentuk dua view penutupan. Memulai batch lot independen akan memutus urutan FIFO, persaingan pen, identitas sumber, saldo WIP dan close kumulatif. Implementasi membatasi restart pada dua titik yang sudah tersegel.

| Titik yang tersimpan | State yang diverifikasi sebelum pemulihan | Fase berikutnya |
|---|---|---|
| Operasi selesai | Parquet operasional, spool dokumen settlement dan alokasi pakan, movement ledger/timeline dan replay, input WIP dan penjualan, warehouse FIFO snapshot, cuaca, konfigurasi dan inventaris hash | Posting, close dan Parquet keuangan |
| Keuangan selesai | Semua bukti operasi di atas, jurnal dan sumber, state hasil close dan approval, hash checkpoint induk | Audit lengkap, ringkasan dan publikasi atomik |

Penanda lokal diterbitkan setelah inventaris fase lengkap. Notebook memverifikasi salinan arsip di Drive sebelum melanjutkan. Core memeriksa SHA-256 setiap berkas, versi, commit, runtime, hash konfigurasi dan hubungan induk. Staging SQLite bersifat sementara. Checkpoint keuangan disimpan setelah kedua view selesai dan tidak bergantung pada transaksi SQLite yang sedang terbuka. Parquet serta laporan akhir diterbitkan hanya setelah audit penuh. State aktif, termasuk cadangan biologis dan antrean suplai, tidak dilanjutkan dari pertengahan fase operasi. Fase yang terputus diulang dari batas terakhir. Resume per hari atau bulan akan memerlukan pemulihan writer Parquet dan state operasi yang masih hidup, ditambah bukti replay deterministik.

Pada uji lintas proses, proses dihentikan paksa setelah operasi dan sebelum keuangan selesai. Proses baru memakai salinan checkpoint operasi, membuat checkpoint keuangan, menolak satu partisi yang diubah, lalu menyelesaikan audit setelah partisi dipulihkan. Semua hash partisi dan laporan deterministik sama dengan referensi yang dijalankan terus. Uji notebook memakai direktori lokal untuk menirukan mount Drive, sehingga sesi Colab dan persistensi Drive yang sebenarnya masih perlu terverifikasi pada pilot. [Bukti restart dan pengujian](evidence/stage7/)

## Sumber daya dan rilis

Rencana terbaru memisahkan evaluasi forecast, keputusan rilis integritas, dan kecukupan runtime. Gunakan laporan performa pilot yang sudah selesai untuk memperkirakan fase terpanjang. [Jalur produksi dan perbandingan development](PRODUCTION_PATH.md)

| Ukuran | Colab 250 terukur dan dilaporkan pengguna | Pilot 1.500, proyeksi linear | Produksi 15.000, proyeksi linear |
|---|---:|---:|---:|
| Wall time runner termasuk audit | 621,43 detik | 62 menit | 10,4 jam |
| Audit penuh di dalam wall time | 121,60 detik | 12 menit | 2,0 jam |
| Parquet | 0,37 GiB | 2,22 GiB | 22,2 GiB |
| Peak RSS | 0,59 GiB | 3,54 GiB | 35,4 GiB |

Kolom proyeksi hanya mengalikan pengukuran dengan 6 atau 60. Pertumbuhan animal-days, variasi jumlah pen aktif, perubahan grain, rasio kompresi, I/O, dan perbedaan CPU dapat menggeser estimasi. Contoh rentang sensitivitas 0,8–1,5× dari estimasi linear adalah 50–93 menit dan 8,3–15,5 jam. Ini tidak termasuk waktu paket, hash tambahan, restore atau transfer Drive. RSS linear menunjukkan risiko, bukan pengukuran atau batas atas. Waktu satu fase panjang tetap penting meski ada checkpoint.

- Pada 250, lingkungan dilaporkan Python 3.13.18, 2 CPU logis, RAM tersedia 11,45 GiB dan disk kosong sekitar 225 GiB. Dataset dilaporkan completed, audit passed, 58 carry-in, 55 carry-out dan 48 close. Paket berada di `My Drive/Feedlot_V2_Benchmarks/placements-250-20261122-110450-ad280072/dataset.tar`.
- Parquet memakai buffer terbatas dan dibagi per bulan. Yardage untuk posting kini dibaca dari Parquet. Namun `StoredRecords.keys_seen`, referensi sumber, serta peta global `financial_sources` saat audit bertambah bersama volume. Audit alokasi menahan indeks satu bulan. Diagnostics menahan agregat per animal-day. SQLite staging membesar dan masih memakai storage temporer in-memory untuk query. Contoh Stage 6B.1 pada 100 placement mencatat 342.529 sumber keuangan untuk 18.132 animal-days. Jika kepadatan baris itu bertahan, sekitar 2,7 juta animal-days menghasilkan sekitar 51 juta sumber. Dengan asumsi 130–170 byte per entri saat dimuat sebagai ID, timestamp dan dict Python, indeks audit ini sendiri sekitar 6–8 GiB. Ini ilustrasi pertumbuhan state, terpisah dari proyeksi durasi berdasarkan hasil Colab 250. Ukur fase terberat dan penggunaan disk/Drive pada pilot sebelum memberi persetujuan produksi. [Bukti jumlah baris historis](evidence/stage6b1/measurements.json)
- Notebook memeriksa RAM tersedia / disk lokal / ruang Drive minimal 8 / 20 / 12 GiB untuk pilot. Batas perencanaan awal produksi adalah 24 / 120 / 85 GiB. Hitung ulang dari pengukuran pilot sebelum membuka eksekusi produksi, dengan margin untuk ketidakpastian skala. Cadangan disk mencakup spool dan SQLite, salinan Parquet staging dan satu arsip lokal. Penyimpanan Drive mencakup dua checkpoint dan paket audit. Batas perkiraan perlu digantikan dengan pengukuran pilot ketika tersedia.
- Colab High-RAM dapat dipertimbangkan bila opsi tersedia pada akun saat itu tanpa pembelian tambahan, RAM aktual melewati pemeriksaan, dan fase terpanjang selesai pada sesi yang tersedia. Alur CLI yang sama berjalan pada runtime Linux dengan sumber daya memadai. Codex yang dipakai untuk tes memiliki batas memori cgroup 8 GiB, sehingga cocok untuk validasi kecil. Belum ada runtime bebas biaya tambahan yang terbukti bisa menyelesaikan profil produksi. Laptop Windows 8 GB tidak diperlukan.

### Gerbang aktif

1. **Holdout estimator Stage 5.** Bukti fixture Stage 5 hanya berisi 12 sapi. Jalankan Model A/B pada 7/30/60 hari dengan pemisahan lot dan waktu, cutoff label terkunci, kalibrasi interval dari development, lima seed dan ambang sampel yang dibekukan. Laporan pilot seed 42 memberi bukti diagnostik dan menunjukkan bias 60 hari melewati toleransi. Evaluasi lima seed masih terbuka. [Telaah forecast](FORECAST_REVIEW.md) [Protokol](../stage5/EVALUATION.md)
2. **Penerimaan pilot.** Evaluasi ulang arsip pilot 1.500 seed 42 yang sudah tersimpan dengan evaluator revisi 2. Simpan bukti operasi dari run asal. Catat RSS, durasi setiap fase, ruang staging dan ukuran checkpoint, peak hospital, backlog, shortage, serta 48 close. Paket evaluasi terverifikasi menjadi bukti operasi. Promosi juga memerlukan penyelesaian holdout lima seed. [Alur evaluasi dan status notebook](colab/README.md)
3. **Kapasitas produksi.** Cocokkan hasil pilot dengan runtime yang benar-benar tersedia. Jika RAM atau durasi fase masih tidak mencukupi, pindahkan indeks lineage dan audit yang tumbuh bersama volume ke disk dan pertimbangkan checkpoint lebih rapat. Jalankan ulang uji kesetaraan sebelum menggunakan perubahan itu untuk produksi. Angka 15.000 tetap menjadi target penerimaan aktual.
