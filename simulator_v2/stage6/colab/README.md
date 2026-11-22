# Evaluasi holdout dan pilot Feedlot V2 di Colab

[Buka notebook di Colab](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage7-forecast-review/simulator_v2/stage6/colab/Feedlot_V2_Benchmark.ipynb)

Untuk produksi 15.000 dengan tujuan rilis integritas data sintetis, gunakan [notebook produksi dan panduannya](README_PRODUKSI.md).

## Langkah berikutnya di iPhone

1. Buka notebook di Safari dan masuk ke akun Google. Pilih **Minta Situs Web Desktop** jika menu Colab tersembunyi. Bila diperlukan, pilih **File → Save a copy in Drive**. Pilih **Runtime → Change runtime type → Hardware accelerator → None**.
2. Jalankan sel persiapan dari **Check Environment** sampai **Connect Google Drive**. Izinkan mount Drive ketika diminta.
3. Centang **Evaluasi_arsip_tersimpan** dan jalankan **Evaluate Saved Dataset**. Ganti nilai bawaan 250 di `Arsip_di_My_Drive` dengan path relatif arsip pilot 1.500, yaitu `Feedlot_V2_Evaluation_Pilots/evaluation-1500-…/dataset-evaluation-only.tar`. Biarkan `status.json` di folder yang sama dengan paket.
4. Buka laporan baru `holdout-1500-seed-42-5221f92c9596-v2.json` di **My Drive → Feedlot_V2_Holdout**. Bandingkan `B` dengan `legacy_B` pada MAE dan bias, lalu periksa coverage dan jumlah pasangan berinterval. Sel ini membaca arsip yang sudah ada dan tidak menjalankan simulator. [Telaah laporan lama](../FORECAST_REVIEW.md)

## Bukti yang bisa diperoleh dari paket 250

Paket yang dilaporkan pengguna berasal dari commit `39770fb` dan memuat seed 42. Pemeriksaan dilakukan terhadap kode penerbit, konfigurasi, struktur tabel dan bukti versi repository. Isi paket privat baru dibaca saat pengguna menjalankan sel di Colab. Konfigurasi 250 menjadwalkan 60 lot. Split hash membagi **18 lot dan 75 placement** ke holdout lot sebelum penyaringan tiket, usia anchor dan waktu pengukuran. Dukungan aktual per horizon, terutama di irisan lot dan waktu, baru diketahui setelah membaca arsip.

Tiket timbang dan koreksinya, movement ledger, master hewan/lot/lokasi, saldo pembukaan dan kejadian klinis memungkinkan estimasi A/B melalui replay cutoff mingguan. Tabel `weight_estimates` Stage 6 berisi nowcast Model B pada waktu keputusan. Evaluator merekonstruksi kedua model dengan fitur yang tersedia pada origin untuk menilai bobot pada waktu timbang aktual. Pembacaan mengecek status audit penuh, hash arsip dan partisi input, serta jumlah receipt. Evaluasi menggunakan tabel observasi dan kejadian, termasuk koreksi tiket yang sudah tersedia pada cutoff yang relevan.

- Origin dipatok pada Senin pukul 08.00 Edmonton. Horizon 7/30/60 hari dihitung sebagai waktu UTC berlalu. Pasangan memakai tiket non-entry pertama dalam jendela ±3 hari, untuk hewan yang aktif di origin. Tiket yang terpilih berulang pada horizon yang sama memakai origin terdekat dengan target nominal, lalu yang paling awal jika seri.
- Outcome memakai vintage 1 Februari 2026. Estimasi hanya memakai fakta efektif sebelum origin dan sudah tersedia saat itu. Anchor stale diperiksa di origin. Model B revisi menerapkan batas 35 hari pada nowcast hingga origin, lalu memakai ADG origin untuk waktu setelahnya. Laporan juga menghitung skor Model B lama dan jumlah pasangan yang terkena batas lama.
- Laporan menampilkan MAE, bias, cakupan dan dukungan untuk holdout lot, waktu, irisan, carry-in, dan jenis tiket. Interval 90% memakai kuantil residual vintage development yang tersedia pada `min(origin, 1 Juli)`, dengan bobot sama per lot dan tanpa lot holdout atau carry-in. Interval dilaporkan jika fold memiliki minimal 100 pasangan kalibrasi. Dukungan primer dan strata tampil berdampingan; irisan lot–waktu memakai strata. Coverage prediksi menggunakan pasangan dengan tiket yang memenuhi syarat.
- Stage 5 mensyaratkan minimal **100 pasangan, 60 sapi, 8 lot, dan cakupan 70% per horizon**. Lima seed yang dipatok adalah 42, 171, 382, 901, dan 1009. Sedikitnya empat seed harus memenuhi metrik primer dan semua seed harus melewati hard gate. Laporan ini selalu menyatakan `stage5_status=incomplete`. Evaluasi promosi lengkap masih memerlukan seed lain, bootstrap per lot, serta pemeriksaan ketahanan dan determinisme sesuai protokol. [Protokol Stage 5](../../stage5/EVALUATION.md)

## Otorisasi pilot 1.500 khusus evaluasi

Jika Anda ingin mengumpulkan data tambahan, pilih **1500**, lalu jalankan **Select Simulation Size & Preflight**. Centang **Jalankan_pilot_evaluasi** di **Run Evaluation-Only Pilot**, jalankan sel, dan ketik `MULAI EVALUASI 1500`. Ini menjalankan satu seed 42 dengan prasyarat sumber daya Stage 7. Setelah runner selesai, jalankan **Validate Results**, **Save Results**, lalu **View Summary**.

Hasil berada di **My Drive → Feedlot_V2_Evaluation_Pilots → evaluation-1500-… → dataset-evaluation-only.tar**. `status.json` memisahkan audit penuh yang lulus dari holdout yang belum lengkap melalui `purpose=evaluation_only`, `stage5_status=incomplete` dan `promotion_eligible=false`. Gerbang fisik, finansial, kronologi, 48 close, inventaris dan integritas publikasi tetap berlaku. Untuk membaca ulang paket pilot, masukkan path paket itu ke **Evaluate Saved Dataset**. Pilot ini menambah sampel seed 42, sedangkan persyaratan lima seed tetap terbuka.

## Pemulihan dan produksi

- Untuk memulihkan pilot, ulangi persiapan dengan ukuran **1500**. Masukkan nama folder lama di **Attempt_ID**, centang **Jalankan_pilot_evaluasi**, jalankan sel, dan ketik `LANJUT EVALUASI 1500`. Checkpoint `operations` melanjutkan ke keuangan. Checkpoint `finance` melanjutkan ke audit penuh. Fase yang belum tersegel diulang. Checkpoint harus berasal dari percobaan Anda sendiri dengan kode, konfigurasi dan runtime yang sesuai.
- Bila hasil sudah lulus audit lokal dan transfer terputus, jalankan kembali **Save Results**. Jika runtime hilang, gunakan checkpoint Drive. `status=completed` dan `validation_status=passed` menandakan paket evaluasi sudah lolos audit dan verifikasi penyalinan.
- Pilihan **15000** menyediakan preflight di notebook evaluasi ini. Notebook produksi khusus memerlukan keputusan rilis integritas yang eksplisit. Status promosi forecast Stage 5 mengikuti protokol evaluasinya. [Arsitektur dan gerbang produksi](../FINAL_DATASET_READINESS.md)
