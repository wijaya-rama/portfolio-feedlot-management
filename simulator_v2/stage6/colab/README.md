# Panduan Google Colab · Stage 6B.1

[**Buka Feedlot V2 Benchmark di Google Colab**](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage6b1-colab-prep/simulator_v2/stage6/colab/Feedlot_V2_Benchmark.ipynb)

## Jalankan 250 placement

1. Buka tautan dengan Safari atau Chrome di iPhone atau dengan browser komputer, lalu masuk ke akun Google. Di Safari iPhone, pilih **Minta Situs Web Desktop** dari menu halaman jika menu Colab tersembunyi. Jika Colab meminta salinan yang dapat diedit, gunakan **File → Save a copy in Drive**.
2. Pilih **Runtime → Change runtime type → Hardware accelerator → None**, lalu sambungkan runtime Python 3. Gunakan runtime CPU yang tersedia pada akun. Langkah ini tidak memerlukan pembelian Compute Units atau pengaktifan Google Cloud billing.
3. Tekan ▶ pada **Check Environment**, **Get Verified Source**, **Install Dependencies**, dan **Connect Google Drive** secara berurutan. Berikan izin Drive saat diminta. Jalankan **Select Simulation Size** dengan **250** terpilih dan kedua kotak pilot kosong.
4. Centang **Mulai_simulasi**, tekan ▶ pada **Run Simulation**, lalu ketik **250** saat diminta dan tekan Enter. Sebaiknya pertahankan tab aktif. Jika iPhone menyulitkan pengoperasian, gunakan browser komputer.
5. Setelah runner selesai, tekan ▶ pada **Validate Results**, **Save Results**, dan **View Summary**. Di Drive, buka **My Drive → Feedlot_V2_Benchmarks → placements-250-…**. Gunakan `dataset.tar` dari folder dengan `status.json` bernilai `completed` dan `validation_status` bernilai `passed`.

Notebook mengambil commit `39770fb9e2867127f1ddac671ac694997e26b864` dan menjalankan CLI Stage 6 dengan seed 42, konfigurasi baseline kesehatan `stage6b1-baseline-health.1`, dan persediaan khusus silase, jelai, dan oat. Kalender bisnis Edmonton mencakup seluruh 2024–2025, termasuk carry-in, carry-out dan 24 penutupan per view. Runner menjalankan audit penuh sebelum menerbitkan Parquet lokal. Notebook memeriksa laporan audit, inventaris partisi dan SHA-256, kemudian menyimpan konfigurasi, manifest versi kode, hash deterministik, laporan validasi dan performa, log, serta satu arsip dataset di Drive.

## Sumber daya dan ukuran

Gunakan Linux x86_64, CPython 3.11–3.13, Git, dan Drive. Notebook menginstal `numpy==2.3.5`, `pyarrow==19.0.1`, dan `tzdata==2025.2` dari wheel ke lingkungan lokal yang terisolasi. Batas awal untuk 250 adalah **4 GiB RAM tersedia**, **6 GiB disk lokal kosong**, dan **1 GiB ruang Drive yang dilaporkan**. Batas awal untuk 500 dan 1.500 masing-masing adalah 5/8/2 GiB dan 8/16/6 GiB, kemudian disesuaikan dari hasil ukuran sebelumnya. Batas ini menyediakan ruang kerja dan cadangan untuk staging dan arsip. Durasi, puncak RSS, ukuran Parquet, dan waktu audit ditampilkan sebagai pengukuran runtime yang benar-benar menjalankan notebook. Perkiraan untuk ukuran berikutnya hanya dipakai untuk pemeriksaan sumber daya. Target referensi 600 detik tidak membatasi durasi Colab.

Jalankan 500 setelah hasil 250 berstatus `completed` di Drive dan sumber daya cukup. Pilihan 1.500 memakai konfigurasi kandidat dari rencana Stage 5 dengan 350 carry-in, profil baseline yang sama, dan algoritme skala Stage 6B. Pilot masih **HOLD** sampai 250 dan 500 lulus, gerbang kesiapan Stage 5 selesai, dan Anda menyetujui eksekusi. Dua kotak pilot mencatat konfirmasi tersebut. Skala 15.000 menunggu rilis terpisah dengan persetujuan eksplisit. [Gerbang kesiapan pilot](../PILOT_READINESS.md) · [Rencana Stage 5](../../stage5/pilot.json)

## Percobaan terputus

Checkpoint dispatch harian dan SQLite membantu runner dalam satu build. Pemulihan lengkap state ternak, feed warehouse, RNG, keuangan, dan publikasi belum tersedia. Setelah proses simulasi berhenti atau runtime hilang, ulangi langkah dari awal dengan ukuran dan seed yang sama. Notebook membuat folder percobaan baru dan menyimpan status lama sebagai catatan. `running`, `awaiting_validation`, `validated`, `interrupted`, `save_failed`, serta berkas `.partial` menandakan paket final belum terkonfirmasi.

Jika tahap penyalinan Drive gagal sementara runtime masih hidup dan audit sudah lulus, periksa ruang atau sambungan Drive lalu ulangi **Save Results**. Jika Drive tidak sempat menerima pembaruan saat runtime berhenti, status lama mungkin tetap `running`. Audit incremental menghasilkan `complete_independent_audit=false` dan mencakup sebagian pemeriksaan. Paket final memerlukan audit penuh.
