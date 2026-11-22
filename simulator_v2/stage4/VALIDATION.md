# Validasi penerimaan Stage 4

Semua gate kritis harus lulus sebelum direktori keluaran diterbitkan. [Laporan gate mesin](evidence/validation.json)

| Gate | Bukti |
|---|---|
| Jurnal, sumber, cutoff | Dua kaki seimbang per ID. Waktu sumber dan approval tersedia untuk buku asli. Reversal valid sekali, memiliki referensi, dan mengikuti akun outcome setelah exit |
| Warehouse dan FIFO | Nilai dan gram AF tutup cocok per bin/layer dengan replay warehouse. DM dijembatani melalui assay dan pembulatan. Issue provisi sekali. Delta invoice +25 sen terlacak sampai sink |
| Kliring dan recovery | Kliring diperiksa per delivery/mix dan akun. Hanya pending bertanggal dengan alasan terdokumentasi yang dapat terbuka. Persediaan lot untuk recovery cocok dengan kontrol |
| Ternak dan WIP | Empat bridge bulanan Stage 1. 338 ekor-hari unik. Buku pembantu cocok dengan kontrol. Lima sale dan dua death memiliki satu release masing-masing. Ketujuh WIP keluar nol |
| Biaya feed dan sensitivitas | Fixture merekonsiliasi 1.616,46 issued, 1.462,40 dasar konsumsi, 154,06 luar konsumsi. Semua kebijakan mengikuti 2.924.400 g DM asli. Biaya kumulatif sama di tiap penutupan. Hanya metode metabolik ada di buku posting |
| Penutupan | Trial balance, piutang, WIP, warehouse dan roll-forward antarbulan lulus. Lock diuji dengan replay sebelum koreksi. Restatement memakai ID induk, approval, dan cutoff berbeda |
| Reproduksi | Dua proses dingin dengan hash seed 1 dan 2 menghasilkan hash baris dan file yang sama. Stempel waktu manifest adalah provenance build |
| Proteksi baseline | Stage 1–3 dibangun ulang dan dicocokkan ke indeks yang diterbitkan. Stage 3.5 dibangun ulang dan indeksnya identik. Build Stage 4 juga memeriksa 86 berkas arsip Stage 3.5 dan 28 tabel sumber kanonik. Generator, workbook, dan flat CSV V1 cocok dengan hash audit. Semua perubahan Git berada dalam Stage 4 |

Suite V1 dan Stage 1–3.5 dijalankan bersama dengan uji Stage 4. Angka pembanding manual untuk feed, WIP, yardage, outcome, invoice dan sensitivitas berada di [rekonsiliasi](RECONCILIATION.md) dan [uji](tests/test_controls.py). Tes juga menolak duplicate principal release, konflik retry, approval/sumber masa depan, biaya setelah kematian, dan kapitalisasi sebelum receipt.

Kebijakan terpilih menghasilkan nol exception clearing. Celah cakupan pasar sengaja dipertahankan. Toleransi proses, harga beli/packer, vet, yardage dan quote merupakan asumsi sintetis yang memerlukan persetujuan serta kalibrasi sebelum penggunaan operasional. [Regresi dan bukti](evidence/regression.json) · [Handoff Stage 5](STAGE5_HANDOFF.md)
