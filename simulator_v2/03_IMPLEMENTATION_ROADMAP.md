# 03 · Roadmap implementasi

Status artefak ini adalah blueprint. Generator V2, ekspor produksi, perubahan dashboard, dan migrasi notebook memerlukan pekerjaan terpisah.

## Skala dan periode

Pertahankan **15.000 placement selama 1 Januari 2024–31 Desember 2025** sebagai skala rilis, dengan 40 pen produksi sebagai pembanding awal. Tambahkan receiving dan hospital dengan kapasitas yang dirancang terpisah. Carry-in berada di luar hitungan placement. Kapasitas yard, jumlah placement selama dua tahun, dan head count pada suatu saat adalah ukuran berbeda. V1 memiliki kapasitas nominal 7.790 ekor dan puncak 6.363 ekor pada catatan pemberian pakan. Profil rilis V2 perlu menyesuaikan occupancy dengan lama tinggal, turnover dan ruang untuk transfer. Pertahankan carry-out agar penutupan Desember menguji WIP hidup. Horizon kalender penuh memudahkan 24 penutupan dan perbandingan musim antar tahun. V1 aktual berhenti pada 4 Desember 2025.

| Profil | Skala dan kegunaan |
|---|---|
| Fixture deterministik | 8–30 sapi, 2 pen produksi, receiving, hospital dan dua bin. Kalender mencakup akhir bulan/tahun, episode sakit dan mati, draft parsial, koreksi terlambat, receipt/transfer/issue dan variance. Nilai transaksi kecil dihitung manual. |
| Pilot integrasi | 1.500 placement, 24 bulan, yard dengan kapasitas dan jumlah pen yang diperkecil. Uji cara kerja lintas hari, musim, lot, invoice, penyesuaian dan penutupan sebelum scale-up. |
| Portofolio | 15.000 placement, 24 bulan, 40 pen produksi sebagai starting design. Sekitar 2,65 juta animal-days bila pola lama tinggal mendekati V1. Dua feeding windows per hari dapat menghasilkan sekitar 5,3 juta line alokasi. Volume aktual bergantung pada carry-in/out, occupancy dan jumlah delivery. Gunakan Parquet dan konsumsi agregat untuk BI. |

Buat pilot dan fixture dengan konfigurasi terpisah. Estimasi volume rilis bukan target biologis. Ukur runtime, RSS, ukuran Parquet dan performa query pada pilot. Gunakan profiling sebelum materialisasi tambahan. Proposal anggaran awal untuk referensi mesin 4 vCPU, RAM 16 GiB adalah build rilis ≤ 15 menit, peak RSS ≤ 8 GiB, dan query lot-month tipikal ≤ 3 detik setelah read pertama. Baca sebagai ambang penerimaan yang diajukan dan catat spesifikasi mesin saat mengukur. Penyimpanan duplikat animal-day dan bobot laten seluruh sapi dapat dihindari dengan timeline, checkpoint dan estimator deterministik.

## Urutan pengerjaan dan kriteria keluar

| Tahap | Hasil | Kriteria keluar |
|---|---|---|
| 0 · Arsip dan spesifikasi | Generator V1 original, audit, aturan, kontrak awal, roadmap dan acceptance. | Hash sumber persis, perbandingan workbook/flat selesai, temuan dan keputusan tercatat. |
| 1 · Timeline dan fixture | Definisi skema run, lokasi, event, lot, identitas dan koreksi; replay state ternak; fixture lintas cutoff. | Satu lokasi aktif, kapasitas, transfer, sales/death, opening/closing, idempotency dan test as-of lulus. |
| 2 · Biologi, kesehatan dan bobot | Mesin state laten, observasi dan estimate; draft, keluar, episodik health; kalender musim dan baseline feed demand. | Feature boundaries diinspeksi, perturbation test lulus, error awal dan parameter transparan. |
| 3 · Bahan, stok dan feeding | Receipts/issue/transfer, FIFO, mix dan delivery, bunk dan alokasi pen. Hubungkan konsumsi ke update biologi, bandingkan bobot hidup vs metabolik. | Conservation AF/DM/sen; stok layer, biaya loss dan occupancy feeding window rekonsiliasi. |
| 4 · Akun, settlement dan close | Purchase, feed, yardage, vet, WIP, COGS, write-off, settlement, quote scenario dan close bulanan. | Buku per sapi dan akun seimbang; biaya terlambat dan restatement lulus; pasar terpisah dari WIP. |
| 5 · Integrasi cuaca dan kalibrasi | Input versi lengkap, kalender vs skenario sensitivitas, literatur dan provenance, backtest final. | Cakupan input, unit/offset, ketersediaan dan asumsi respons diuji. Jika cakupan penuh belum tersedia, rilis hanya dengan skenario musim yang dilabeli. |
| 6 · Rilis dataset dan BI | Pilot seluruh domain, uji multi-seed, build skala rilis dan review data. | Semua hard gate dan baseline regression lulus. Terbitkan ekspor V2 terpisah hanya setelah persetujuan rilis. |

Tahap 2 memakai adaptor demand/consumption yang deterministik pada fixture. Tahap 3 menggantinya dengan arus lengkap supaya delivery tidak dihitung dari future growth. Tahap 4 merujuk ledger fisik yang telah tervalidasi. Independensi stream RNG untuk biologis, observasi, kesehatan, pasar dan cuaca menjaga simulasi pembanding dapat diaudit.

## Log keputusan pengguna

Status seluruh baris **diusulkan**. Pilihan yang belum disetujui tetap eksplisit di konfigurasi dan laporan.

| Keputusan | Default yang diusulkan | Alternatif dan dampak | Dibutuhkan sebelum |
|---|---|---|---|
| D01 · Horizon dan yard | 15.000 placement, 2024–2025, mulai dari 40 pen produksi ditambah receiving/hospital | Yard lebih kecil mengurangi volume dan variasi cohort. Jumlah pen dan throughput dapat dikalibrasi ulang bersama occupancy | Profil rilis |
| D02 · Carry-in/out | Opening eksplisit dengan detail WIP; lanjutkan cohort sampai cutoff dan tampilkan carry-out | Warm-up memberi sejarah lebih lengkap dan memerlukan periode/input tambahan | Fixture ledger pembuka |
| D03 · Operasi, kesehatan dan pertumbuhan | Transfer sesuai kapasitas; jual bertahap; kalibrasi profil risiko, bobot, growth dan scan/timbang melalui range yang disetujui | Uniform cohort memperkecil kompleksitas tetapi mengurangi analisis variasi dan selection bias | Kalibrasi pilot |
| D04 · Cuaca | Skenario musim dahulu; arsip historis tetap referensi; perpanjang 27 hari sebelum mode historis penuh dan setujui literatur/sensitivitas | Histori sampai 4 Desember dengan fallback bertanda atau skenario musim penuh. Mode hourly memerlukan input baru | Mode historis dan pernyataan respons |
| D05 · Alokasi dan nutrisi | BW^0.75 sebagai proxy utama, BW dan equal-head sebagai pembanding. Tetapkan persamaan kebutuhan dan parameter intake setelah telaah | Model energi dapat menangkap fase/health lebih baik, dengan biaya kalibrasi lebih tinggi | Feed MVP dan publikasi FCR/COG |
| D06 · Gudang dan variance | FIFO per bahan × bin, landed cost inbound; refusal/shrink sebagai varians; tanpa carryover/refeed MVP | Moving weighted average mengubah unit cost; kapitalisasi waste normal atau carryover menambah kebijakan akun dan model | Desain ledger persediaan |
| D07 · Akun dan cutoff | Yardage inclusive berdasarkan active-day; biaya pembelian/feed/yardage/vet dikapitalisasi untuk manajemen; lock bulanan, delta periode terbuka; sale dan mortality release terpisah | Tarif efektif, daftar biaya, layanan hari keluar, approval restatement dan kalender close perlu diputuskan. Scope cash/finance dapat ditambah terpisah | Fixture penutupan |
| D08 · Harga, kelas dan grading | Quote live sintetis atau kosong; grid kontrak sintetis dan grade/yield yang ditelaah; fair value formal di luar MVP | Quote eksternal butuh dukungan penggunaan, kelas, geografi, dasar harga, ketersediaan dan costs to sell | Publikasi estimasi pasar |
| D09 · Mutu model dan anggaran | Gunakan holdout waktu/lot, baseline timbang terakhir, target per horizon dan strata serta anggaran pilot awal | Penilaian threshold dapat direvisi dari distribusi pilot yang sudah dibekukan, sebelum evaluasi holdout | Penerimaan model rilis |

## Langkah implementasi berikutnya

Pada tahap 1, buat fixture sintetis **12 sapi** dalam namespace V2 dengan dua pen produksi, receiving dan hospital. Mulai dari kontrak `animals`, `lots`, `locations`, `animal_events` dan `run_manifest`. Implementasikan replay untuk placement, transfer ke/dari hospital, penjualan parsial, kematian, opening dan carry-out di sekitar akhir bulan. Uji satu lokasi aktif, kapasitas, transfer net-zero, saldo per pen/yard, replay deterministik dan koreksi backdated di dua cutoff. Gunakan angka kecil yang bisa diverifikasi manual. Selesaikan tahap ini sebelum menambahkan mesin pertumbuhan atau pakan.
