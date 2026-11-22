# Runbook produksi 15.000

[Buka notebook produksi di Colab](https://colab.research.google.com/github/wijaya-rama/portfolio-feedlot-management/blob/stage7-colab-drive-recovery/simulator_v2/stage6/colab/Feedlot_V2_Production.ipynb) · [Kebutuhan dan risiko](README_PRODUKSI.md)

| Tindakan | Langkah |
|---|---|
| Persiapan | Di Colab pilih **Runtime → Change runtime type**, CPU dan **High-RAM**. Pada laptop Windows gunakan AC, matikan Sleep dan biarkan browser terbuka. Layar boleh padam. Jalankan **Persiapan runtime**, **Hubungkan Drive**, **Uji koneksi Drive**, lalu **Preflight**. Konfirmasi akses Drive diselesaikan di sini. |
| **START** | Centang **Setujui_rilis_integritas** dan jalankan sel persetujuan. Pada **START**, centang **Siap_mulai**, jalankan sel dan ketik `MULAI 15000`. Simpan tautan atau ID folder Drive yang tercetak. Operasi, simpan Drive, finance, simpan Drive, audit dan publikasi berjalan otomatis. |
| **STATUS** | Dari laptop atau iPhone buka folder Drive percobaan, lalu baca `status.json`. Pada runtime baru, jalankan persiapan dan hubungkan Drive, isi **ID_folder_Drive** di sel **Status**, lalu jalankan. `possibly_interrupted` berarti status lama, sehingga periksa sesi lama sebelum mengambil alih. |
| **STOP** | Hentikan sel aktif dengan tombol **Stop/Interrupt**. Tunggu sampai eksekusi berhenti. Periksa status dan checkpoint terakhir. Jika perlu mematikan runtime lama secara paksa, gunakan **Runtime → Disconnect and delete runtime**. Disk lokal pada runtime itu akan hilang. |
| **RESUME** | Untuk kegagalan transfer, perbaiki kuota atau akses Drive. Gunakan runtime yang sama jika masih hidup agar segel lokal dapat dipakai. Pada runtime baru, ulangi persiapan dan hubungkan akun Drive yang sama. Jalankan kembali persetujuan, isi ID folder di **RESUME**, jalankan sel dan ketik `LANJUT 15000`. Untuk checkpoint final yang korup, pulihkan salinan asli yang tepercaya atau periksa penyebab bersama pemilik sebelum memulai percobaan baru. |
| **STOP/RECOVER** | Gunakan bila RESUME menyatakan percobaan masih terkunci dan runtime sebelumnya sudah dihentikan/dihapus. Jalankan persiapan, hubungkan Drive dan jalankan persetujuan. Isi ID folder di **STOP/RECOVER**, centang **Runtime_lama_sudah_berhenti**, jalankan sel, lalu ketik `PULIHKAN 15000`. |
| Selesai | Pada sel **Status** pastikan `status=completed`, `validation_status=passed` dan ada SHA-256 untuk `dataset-integrity-only.tar`. Dalam arsip, `dataset/release_manifest.json` mencatat 15.000 placement, 48 close dan kebijakan integrity-only. |

Jika transfer gagal, fase berikutnya tertahan. Checkpoint Drive yang terverifikasi dipertahankan. Interupsi di tengah operasi, finance atau audit dapat mengulang seluruh pekerjaan dalam fase yang belum selesai. Finance dapat kehilangan hingga sekitar **6,8 jam komputasi** menurut perkiraan perencanaan, ditambah waktu pemulihan atau transfer.
