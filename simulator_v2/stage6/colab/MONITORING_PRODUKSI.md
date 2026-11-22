# Monitoring produksi Stage 7

[Buka notebook produksi](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage7-colab-live-monitoring/simulator_v2/stage6/colab/Feedlot_V2_Production.ipynb) · [Buka Monitor Drive baca-saja](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage7-colab-live-monitoring/simulator_v2/stage6/colab/Feedlot_V2_Status.ipynb)

## Temuan insiden

START dan RESUME pada notebook lama memanggil `jalankan()` yang menjalankan CLI melalui `Popen(..., start_new_session=True)` dan `wait()`. CLI berjalan dengan `-u` dan memanggil `print(..., flush=True)`. Kedua opsi memastikan byte dikirim ke file descriptor proses. Notebook mewariskan file descriptor stdout/stderr ke CLI dan tidak membacanya untuk dikirim melalui `sys.stdout` kernel. Worker simulator sendiri menggabungkan stdout/stderr ke log lokal per fase. Pesan folder, fase dan heartbeat berasal dari CLI supervisor. Log worker diteruskan saat ada kegagalan worker.

Uji reproduksi menggunakan proses unbuffered yang menulis URL, fase dan heartbeat ke stdout/stderr. Pada jalur lama, byte terlihat di tingkat file descriptor dan tidak sampai ke stream Python yang berperan sebagai output sel. Pada jalur baru, subprocess berhenti menunggu sampai stream sel menerima heartbeat. Uji ini memastikan output diteruskan saat proses masih berjalan. Colab juga meneruskan output subprocess ke `sys.stdout` pada implementasi perintah shell bawaannya. [Implementasi Google Colab](https://github.com/googlecolab/colabtools/blob/main/google/colab/_system_commands.py)

Setelah dua interupsi manual, status pertama yang dilaporkan adalah `interrupted` pada `operations`, dengan `KeyboardInterrupt` dan tanpa checkpoint Drive terverifikasi. Hasil interupsi kedua, klaim terkini, dan metadata arsip aktual memerlukan pembacaan Drive oleh pemilik akun. Interupsi manual menjelaskan penghentian yang terlihat pada status pertama.

## Cara memantau

1. Di notebook produksi jalankan **Uji tampilan progres**. Pastikan tiga pesan muncul berurutan di sel yang sama dan heartbeat uji muncul saat sel masih aktif. Uji ini menggunakan subprocess singkat.
2. Setelah memulai atau melanjutkan percobaan yang sudah Anda otorisasi, amati URL folder, `Fase … dimulai`, dan heartbeat nyata sekitar 15 detik setelah worker aktif. Heartbeat berikutnya muncul sekitar tiap 120 detik selama worker berjalan. Aktivitas staging dan transfer juga melaporkan progres saat loop bergerak. Pesan heartbeat memuat fase, waktu fase, waktu eksekusi dan checkpoint Drive terakhir yang terverifikasi.
3. Buka notebook **Monitor Drive** di tab terpisah, hubungkan akun Drive yang sama, tempel ID folder, lalu jalankan **Baca status dan verifikasi metadata**. Periksa `recorded_status`, `phase`, `updated_at`, `last_heartbeat`, `claim_lock`, `archives`, dan `issues`. Jalankan ulang sel baca untuk mengambil snapshot baru. Untuk akses cepat dari ponsel, buka langsung `status.json` di folder percobaan.
4. Cocokkan heartbeat di sel produksi dengan heartbeat yang muncul di Monitor Drive sebelum meninggalkan laptop. Nilai `last_heartbeat: null` berarti snapshot tidak memiliki heartbeat yang dapat ditampilkan. Status lama yang sudah ditimpa oleh interupsi dapat kehilangan informasi heartbeat. Monitor memeriksa checksum server dan rantai induk. Pemeriksaan isi checkpoint terjadi lagi saat RESUME.

## Memilih tindakan pada percobaan yang sudah berhenti

| Hasil Monitor Drive | Tindakan |
|---|---|
| `issues` berisi masalah atau arsip `inconsistent` / `parent_unverified` | Simpan hasil diagnostik dan selesaikan ketidaksesuaian sebelum memulai ulang pekerjaan. |
| Status masih aktif atau runtime lama masih bekerja | Tetap pantau runtime lama. |
| `claim_lock.state=released` atau `unclaimed`, `issues=[]`, runtime lama sudah berhenti | Gunakan **RESUME** dengan ID yang sama setelah pengguna siap melanjutkan. |
| `claim_lock.state=unreleased`, `issues=[]` | Klaim bisa aktif atau tertinggal. Setelah memastikan runtime lama benar-benar berhenti, gunakan **STOP/RECOVER** dengan ID yang sama. |
| `archives.operations.state=absent` dan tidak ada checkpoint lokal tersegel | RESUME akan mengulang operasi dari awal setelah pengguna memberi otorisasi. Arsip `staged_verified` dapat dipublikasikan saat RESUME setelah verifikasi. |

Notebook monitoring memakai checkout terpin tersendiri. Worker produksi tetap dijalankan dari commit simulator `9afdbb6cf413395a3fb0b7b4ed5d2f0fa0e6da2e`. Commit itu, versi manifest dan skema checkpoint tetap berlaku untuk percobaan lama. Untuk RESUME, versi Python, NumPy, PyArrow dan data zona waktu juga harus cocok dengan manifest. Monitor menampilkan runtime yang tercatat.
