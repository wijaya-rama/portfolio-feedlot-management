# Produksi Feedlot V2 di Google Colab

[Buka notebook produksi di Colab](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage7-colab-live-monitoring/simulator_v2/stage6/colab/Feedlot_V2_Production.ipynb) · [Runbook satu halaman](RUNBOOK_PRODUKSI.md) · [Monitoring dan pemulihan](MONITORING_PRODUKSI.md)

Notebook CPU High-RAM mematok seed 42 dan menjalankan tepat **15.000 placement baru selama 2024–2025**. Preflight rencana menunjukkan 3.500 carry-in dan, pada skenario keterlambatan penjualan 35 hari, puncak 4.591 ekor serentak, tujuh pen produksi cadangan, dan dua pen receiving cadangan. Angka kapasitas tersebut berasal dari skenario perencanaan. Audit hasil produksi memeriksa receipt aktual, kapasitas dan rekonsiliasi carry-in/carry-out. [Konfigurasi terpin](../configs/stage7-production-15000.json) · [Bukti perencanaan](../evidence/stage7/preflight-15000.json)

Rilis memerlukan keputusan eksplisit untuk dataset sintetis dengan integritas operasional dan finansial. Forecast Stage 5 tetap berstatus `not_promoted`. Notebook mempertahankan nowcast operasional terpin, logika biologis, FIFO, warehouse, shipment, WIP dan COGS. Paket akhir mencantumkan kebijakan rilis dan bukti audit dalam `dataset/release_manifest.json`. [Rencana produksi dan bukti pilot](../PRODUCTION_PATH.md)

## Eksekusi dan penyimpanan

| Urutan | Gerbang sebelum melanjutkan |
|---|---|
| Operasi | Segel lokal operasi, unggah TAR ke nama sementara, cocokkan ukuran dan SHA-256 dari server Drive, ubah nama, lalu baca kembali metadata Drive |
| Finance | Pulihkan operasi yang terverifikasi, segel finance beserta hash checkpoint induk, ulangi verifikasi dan publikasi Drive |
| Audit dan paket akhir | Audit independen penuh, validasi 48 close original/restated, rekonsiliasi jumlah ternak, inventaris Parquet dan SHA-256 partisi/laporan, lalu unggah dan verifikasi paket di Drive |

Satu START menjalankan seluruh urutan. `attempt.json` mengikat slot file Drive tetap ke commit, konfigurasi, hash input, interpreter, NumPy, PyArrow dan zona waktu. Manifest checkpoint di dalam TAR mengikat file state, Parquet dan checkpoint induk. Metadata Drive menyimpan ukuran, SHA-256 paket dan hash segel. Nama final muncul lewat perubahan metadata setelah server mengonfirmasi isi. `status.json` menyimpan status operasi, fase, pembaruan berkala dan checkpoint terakhir yang terverifikasi. Jika penulisan status tertunda, sel **Status** memeriksa arsip final melalui API. Waktu pembaruan dicatat dalam UTC. [Upload dan ID berkas Drive](https://developers.google.com/workspace/drive/api/guides/manage-uploads) · [Metadata checksum Drive](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)

Gunakan akun Drive yang sama. Checkpoint berisi pickle state privat dan hanya boleh digunakan dari percobaan sendiri. **RESUME** memeriksa checksum server, lalu memeriksa SHA-256 salinan unduhan, identitas checkpoint dan hash berkas lokal sebelum pemuatan state. Satu runtime aktif per percobaan dijaga melalui lock lokal dan klaim dengan ID unik di Drive. Pemulihan paksa memerlukan runtime lama sudah berhenti.

## Risiko yang masih ada

- Pemulihan berlaku di batas fase. Operasi yang masih berjalan menyimpan roster, cadangan biologis, antrian, warehouse/FIFO dan writer yang aktif. Finance membentuk ulang sumber/posting di SQLite, menulis Parquet untuk dua view, serta memegang state indeks jurnal, saldo close, approval dan lineage. Commit SQLite atau satu close saja belum menyegel semua state itu. Checkpoint di tengah fase memerlukan desain transaksi lintas state dan writer beserta uji kesetaraan tambahan.
- Jika VM hilang sebelum operasi atau finance tersegel di Drive, fase bersangkutan bisa perlu diulang penuh. Runtime yang masih hidup dapat memakai segel lokal. Unggahan lengkap yang tertahan pada nama sementara dapat diverifikasi dan diterbitkan saat RESUME. Transfer parsial tanpa objek lengkap di server dimulai ulang. Jika VM hilang setelah checkpoint finance terbit, audit bisa diulang tanpa menghitung ulang operasi atau finance.
- Perkiraan operasi **3,77–5,65 jam**, finance **4,52–6,79 jam**, serta audit dan laporan **1,90–2,85 jam**. Total komputasi sekitar **10,2–15,3 jam**, ditambah staging, hash, transfer dan kemungkinan restore. Dengan AC, Sleep Windows nonaktif, dan browser terbuka, layar boleh padam. Kebijakan dan umur VM tetap ditentukan Colab. Google mendokumentasikan eksekusi latar belakang Pro+ hingga 24 jam bila CU cukup, dan manfaat serupa tersedia pada beberapa paket Google AI. CPU High-RAM dan saldo sekitar 664 CU saja belum mengidentifikasi paket akun. Periksa akses background execution di akun melalui halaman Colab sebelum mengandalkannya. Satu sesi dengan batas sekitar 12 jam bisa terputus sebelum keluaran akhir terverifikasi. [FAQ Colab](https://research.google.com/colaboratory/faq.html?hl=en) · [Panduan fitur langganan Colab](https://colab.research.google.com/notebooks/pro.ipynb)
- Batas awal **24 GiB RAM efektif**, **120 GiB disk lokal**, **85 GiB Drive** memakai pembacaan saat eksekusi, termasuk batas cgroup serta kuota server Drive. Runner memantau RSS dan cadangan runtime serta memeriksa ruang staging dan transfer. Puncak RAM atau disk produksi, durasi transfer terbesar dan izin Drive akun ini masih perlu verifikasi. Kredensial Drive disiapkan sebelum START. Bila otorisasi habis atau transfer gagal, runner berhenti di batas penyimpanan dan memberikan instruksi retry.

## Verifikasi sebelum START

1. Pastikan keputusan rilis integrity-only disetujui serta bukti pilot penuh 1.500 seed 42 dapat dirujuk. Pilih CPU High-RAM dan tinjau jendela sesi dari akun yang akan dipakai.
2. Jalankan **Uji koneksi Drive** pada akun itu. Uji mengunggah dan mengunduh beberapa byte, mengecek SHA-256 server, memublikasikan nama final, membaca manifest dan memindahkan folder uji ke Sampah. Kemudian jalankan **Preflight** untuk kapasitas, RAM efektif, disk dan Drive. Uji unit menggunakan pengganti API Drive karena akun Colab pengguna tidak terhubung saat pengembangan.
3. Jalankan **Uji tampilan progres** sebelum START atau RESUME. Setelah worker berjalan, pastikan URL folder dan heartbeat muncul di sel. Gunakan **Monitor Drive** di notebook terpisah untuk memeriksa snapshot Drive saat sel produksi sibuk. Dari iPhone, gunakan Safari dan pilih **Minta Situs Web Desktop** untuk mengakses kontrol Colab.

Uji lokal terfokus menggunakan fixture kecil. Cakupannya meliputi putus/ulang transfer, hilangnya respons setelah unggah selesai, checkpoint rusak, lock duplikat, ketidakcocokan kode/config/runtime, perbandingan hash terhadap run mulus, guard sumber daya, dan penolakan publikasi saat verifikasi gagal. Uji Stage 7 lama juga mematikan subprocess saat finance lalu menguji pemulihan. Preflight kapasitas 15.000 menjalankan pemeriksaan jadwal serta pasokan. Tidak ada run produksi 15.000 atau pilot 1.500 baru.

```bash
python -m pip install -r simulator_v2/stage6/colab/requirements-production.txt pytest
PYTHONTZPATH="" python -m pytest -q simulator_v2/stage6/tests
PYTHONTZPATH="" python -m simulator_v2.stage6.release_preflight 15000
```
