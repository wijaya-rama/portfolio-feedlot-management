# Kebijakan akuntansi manajemen · stage4-management.1

Semua nilai transaksi adalah sen CAD bulat. `policy.json` menyimpan skenario akuisisi, carry-in, tarif, koreksi, quote, dan klasifikasi loss. Nilai synthetic berfungsi untuk uji akuntansi. WIP manajemen mengakumulasi biaya per sapi. Nilai pasar merupakan analisis non-posting dari bobot estimasi dan quote live. Pengukuran laporan keuangan Kanada bergantung pada kerangka yang berlaku, termasuk IFRS IAS 41 atau ASPE Section 3041, serta bukti penilaian dan biaya jual. [Aturan bisnis V2](../01_V2_BUSINESS_RULES.md) · [IAS 41](https://www.ifrs.org/issued-standards/list-of-standards/ias-41-agriculture/)

## Akun dan sumber

| Akun | Fungsi |
|---|---|
| 1100, 1110, 1200, 1300 | Persediaan pakan gudang, refusal pulih, WIP ternak, piutang packer |
| 2100, 2110, 2120, 2130, 2140 | Akrual receiving feed, utang akuisisi, akrual yardage/operasi, akrual vet, delta invoice pemasok |
| 2200, 2210, 2220, 2230 | Kliring issue/mix, distribusi/bunk, alokasi loss, refusal menunggu klasifikasi |
| 3100 | Kontrol pembukaan persediaan dan WIP dari sumber carry-in |
| 4100 dan 4110 | Pendapatan penjualan dan delta settlement packer |
| 5100 dan 5200 | COGS penjualan dan write-off mortalitas |
| 5300–5350 | Loss proses abnormal (5300), selisih count (5310), spoilage (5320), disposal/varians lain (5330), shrink (5340), kerusakan (5350) |

| Peristiwa sumber | Jurnal dan jejak |
|---|---|
| Stage 1 opening ternak | Dr 1200 / Cr 3100 berdasarkan dua dokumen biaya carry-in dan baris event pembuka |
| Stage 1 receipt ternak | Dr 1200 / Cr 2110 berdasarkan harga sintetis per sapi, ditautkan ke receipt dan lot |
| Warehouse opening dan receiving landed cost | Dr 1100 / Cr 3100 atau 2100. PO, receipt, freight, dan lapisan FIFO berada pada Stage 3.5 |
| Issue FIFO, mix dan delivery | Issue Dr 2200 / Cr 1100 per layer. Load Dr 2210 / Cr 2200. Nilai loss mixer dan distribusi melalui 2220 dengan identitas delivery atau mix. Transfer antarbin menggerakkan kuantitas dan nilai layer dengan efek gudang agregat nol |
| Bunk, refusal dan biaya individu | Dr 1200, 1110, 5300 atau 2230 / Cr 2210 atau 2220. Settlement → exposure → alokasi metabolik → sapi. Koreksi ditautkan ke approval dan journal ID yang dibalik |
| Yardage | Dr 1200 / Cr 2120 sebesar 120 sen/hari hingga Januari dan 130 sen/hari mulai 1 Februari. Satu baris per sapi-hari aktif, termasuk hari masuk dan keluar. Tarif 31 Januari dikoreksi +10 sen per sapi-hari, tersedia 2 Februari |
| Layanan vet | Dr 1200 / Cr 2130 sekali per layanan treatment atau repeat treatment bertanggal. Lima transaksi sintetis berbasis sumber klinis. Kolom biaya overhead terpisah bernilai nol pada fixture |
| Sale/mortality | Dr 5100 atau 5200 / Cr 1200 pada exit tervalidasi. Biaya layanan yang tersedia setelah exit langsung memakai akun outcome. Mortalitas tidak memiliki revenue. Sale provisional Dr 1300 / Cr 4100. Packer final memposting delta ke 1300/4110 |
| Invoice supplier | Akrual delta 2140 berpasangan dengan stok tersisa, tujuan historis atau akun outcome. Tautan split → layer dan sink → mix/delivery/settlement/alokasi. Revisi settlement membalik alokasi invoice sebelumnya dan memposting pengganti |
| Count, spoilage, shrink, kerusakan | Nilai lawan 1100 berasal dari layer dan alasan yang disetujui. Allowance warehouse 0 bps untuk fixture. Receiving correction yang disetujui menggunakan 2100 |

Akun kliring mengendalikan nilai. Setiap saldo terbuka harus memiliki pool, tanggal dan alasan. Jurnal memakai satu debit dan satu kredit per ID, disajikan juga sebagai dua kaki bertanda. Saldo biaya hewan yang keluar ditutup satu kali. Piutang, utang dan akrual adalah posisi penutupan sebelum pembayaran. Cash collection, settlement utang, pajak, overhead umum, bunga dan biaya jual di luar model.

## Absorpsi dan bukti fisik

- Mixing normal jika loss AF / issue AF paling banyak 110 bps untuk ransum umum. Ransum uji tangan memakai 0 bps. Mixing yang memenuhi toleransi mengikuti AF hasil produksi yang berhasil dikirim. Distribusi normal jika loss AF / loaded AF paling banyak 60 bps. Keduanya memakai DM konsumsi teralokasi pada window tujuan untuk pembagian biaya ke sapi. Jika window tanpa basis konsumsi, biaya masuk varians. Angka AF dan DM fisik tetap berasal dari Stage 3.5.
- Refusal teramati menerima klasifikasi sintetis `synthetic_observed`. Tiket uji tangan menandai 500 g AF untuk recovery. Refusal teramati nonrecoverable sampai 500 bps AF delivery boleh diserap. Sisa teramati melebihi allowance dan refusal inferensi karena tidak ada akses masuk varians. Satu bunk loss 50 g AF merupakan varians. Nilai refusal dibagi dengan bobot AF, kemudian bagian normal dibagi dengan bobot DM teralokasi dari metode metabolik.
- Recovery masuk persediaan lot terpisah pada biaya sumber. Fixture menyimpan lot 500 g AF hingga akhir. Disposisi parsial yang disetujui memakai nilai tersisa lot dan mengurangi stok ke akun distribusi delivery berikutnya atau varians disposal. Fixture belum memiliki penerimaan pakan rework oleh mixer atau aliran fisik refeeding.
- Jika bukti refusal hilang, mode `unclassified` menahan refusal teramati yang belum terklasifikasi di 2230 dengan pool, tanggal dan pengecualian. Bukti recovery bertag dan inferensi tanpa akses tetap dapat ditangani sesuai kategorinya. Gabungan bps ini adalah parameter skenario. Sensitivitas memakai ambang lebih ketat 90/45/300 bps dan basis konsumsi tanpa absorpsi 0/0/0 bps. Ketiga kebijakan mempertahankan tag recovery.
- Pembagian nilai memakai metode sisa terbesar dan ID stabil. Basis invoice berasal dari gram AF di setiap arus lapisan/mix/delivery dan dari gram DM pada porsi konsumsi individu. Satu metode konsumsi diposting. Metode alternatif tahap sebelumnya tetap menjadi bukti operasional.

## Cutoff dan persetujuan

`effective_at` dan `service_date` mengikuti peristiwa layanan. `source_posted_at` merekam waktu pencatatan sumber, `available_at` menyatakan ketersediaan bukti dan `posted_at` jurnal memakai waktu pertama sumber dapat dibukukan. Ganti konteks dari tanggal layanan ke bulan posting saat waktu tersebut melampaui lock. Load transaksi bertentangan ditolak. Reversal mensyaratkan ID original, nilai berlawanan, approval bersumber, serta outcome sapi yang diketahui pada saat routing. Tanggal layanan tetap ikut historis.

Snapshot asli memakai pengetahuan hingga waktu lock dan cutoff fisik akhir hari. Snapshot revisi berizin menautkan close asli dan close sebelumnya. Revisi pakan dan tarif yang diotorisasi dapat disajikan pada vintage sumber yang telah ditentukan melalui `period_routing_at` dalam proyeksi analitis. Buku posting asli dan semua transaksi delta tetap utuh. Delta supplier dan packer yang independen mengikuti waktu dokumen mereka. Lock buatan fixture berada tepat di tengah malam lokal setelah periode, termasuk 12 Maret untuk akhir horizon parsial.

## Definisi margin

- **Sales gross margin** adalah pendapatan bersih penjualan dikurangi COGS sapi terjual.
- **Mortality burden** adalah write-off WIP akibat kematian, termasuk biaya sah yang tiba kemudian.
- **Operating feed variance** adalah loss proses dan varians gudang yang dibebankan, termasuk bagian invoice terkait.
- **Modeled yard contribution** adalah pendapatan bersih dikurangi COGS, mortalitas dan operating feed variance. Kapitalisasi loss menunda biaya selama masih berada pada sapi aktif. Pelaporan bersifat akuntansi manajemen dalam lingkup fixture.
