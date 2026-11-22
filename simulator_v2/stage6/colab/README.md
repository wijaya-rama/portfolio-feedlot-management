# Feedlot Simulator V2 di Google Colab

[Buka notebook pilot dan produksi di Colab](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage7-final-dataset-readiness/simulator_v2/stage6/colab/Feedlot_V2_Benchmark.ipynb)

## Mulai dari iPhone

1. Buka tautan di Safari dan masuk ke akun Google. Pilih **Minta Situs Web Desktop** jika menu Colab tersembunyi. Gunakan **File → Save a copy in Drive** jika diperlukan agar formulir dapat diisi.
2. Pilih **Runtime → Change runtime type → Hardware accelerator → None**. Jalankan sel **Check Environment**, **Get Verified Source**, **Install Dependencies**, kemudian **Connect Google Drive**. Berikan akses Drive saat Colab meminta izin.
3. Pilih **1500** dan jalankan **Select Simulation Size & Preflight**. Berhenti setelah preflight sambil menunggu bukti holdout estimator Stage 5. [Gerbang yang masih terbuka](../FINAL_DATASET_READINESS.md)
4. Setelah gerbang itu selesai dan Anda mengizinkan pilot, centang **Gerbang_estimator_selesai**, **Saya_menyetujui_pilot_1500**, dan **Mulai_atau_lanjutkan**. Jalankan **Run Simulation** dan ketik `MULAI 1500` saat diminta.
5. Sesudah runner selesai, jalankan **Validate Results**, **Save Results**, lalu **View Summary**. Paket berada di **My Drive → Feedlot_V2_Releases → placements-1500-… → dataset.tar**. Gunakan paket dari folder yang menunjukkan `status=completed` dan `validation_status=passed`.

Pilot memakai seed 42. Produksi 15.000 memiliki pilihan dan persetujuan tersendiri. Notebook memeriksa hasil pilot, SHA-256 paket yang tersimpan, audit penuh, 48 penutupan, dan kemampuan runtime sebelum mengizinkan konfirmasi `MULAI 15000`. Hasil 250 yang sudah tersimpan tetap menjadi bukti pengukuran. Alur baru langsung mengarah ke pilot 1.500.

## Pulihkan percobaan setelah Colab terputus

- Catat nama folder percobaan yang muncul saat mulai. Di runtime CPU baru, ulangi langkah persiapan dan preflight dengan ukuran yang sama. Masukkan nama folder ke **Attempt_ID**, nyalakan kotak persetujuan yang berlaku, jalankan **Run Simulation**, dan ketik `LANJUT 1500` atau `LANJUT 15000`.
- `last_verified_checkpoint=operations` melanjutkan dari tahap keuangan. `last_verified_checkpoint=finance` melanjutkan dari audit penuh. Jika operasi belum selesai disalin ke Drive, runtime baru mengulang operasi dari awal. Checkpoint memakai commit, seed, konfigurasi, versi runtime dan dependensi yang sama. Arsip checkpoint berisi state Python internal. Gunakan arsip dari percobaan Anda sendiri.
- Jika audit atau penyalinan paket akhir terputus, jalankan kembali **Save Results** jika dataset lokal masih ada dan sebelumnya lulus validasi. Jika runtime hilang, pemulihan dari checkpoint keuangan menjalankan audit penuh kembali sebelum menerbitkan berkas.
- Status Drive dapat tertinggal di `running` saat runtime hilang. Lihat `last_verified_checkpoint` dan `status.json`. Berkas `.partial` belum terverifikasi. Jika hash checkpoint berbeda, selesaikan di runtime asli bila state lokal masih dapat diverifikasi. Gunakan percobaan baru jika checkpoint dan state lokal sama-sama gagal.

Checkpoint hanya tersedia di batas fase. Colab dapat menghentikan sesi sebelum batas tersebut. Batas sumber daya yang ditampilkan adalah margin perencanaan. Notebook memakai CPU dan dependensi Python terpin pada penyimpanan lokal, lalu memeriksa hash dan ukuran data pada Drive yang ter-mount. [Arsitektur, estimasi dan bukti](../FINAL_DATASET_READINESS.md)
