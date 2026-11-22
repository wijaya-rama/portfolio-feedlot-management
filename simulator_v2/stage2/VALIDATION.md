# Validasi Stage 2

## Cakupan fixture

Seed 42 menghasilkan 12 profil, 32 event klinis, 1.730 langkah biologis, 33 kesempatan timbang, 30 tiket asli, satu koreksi dan 662 estimasi harian. Tiga kesempatan timbang hilang. Sebanyak 739 baris estimasi di 110 snapshot mencakup estimasi harian, forecast backtest, input keputusan draft dan revisi contoh. Publikasi menjalankan 57 pemeriksaan, terdiri dari 49 kontrol Stage 1 dan delapan kontrol lineage serta integritas Stage 2. [Laporan kontrol](evidence/validation.json) · [Indeks hash](evidence/hashes.json)

| Suite | Hasil |
|---|---:|
| Stage 1 | 33/33 |
| Regresi V1 | 87/87 |
| Stage 2 | 38/38 |
| Kontrol publikasi | 57/57 |

Regresi V1 juga menjalankan 60 subtes dan menghasilkan satu peringatan deprecasi dari plugin pytest AnyIO. Build bukti menggunakan CPython 3.12.14 dan PyArrow 19.0.1. Dua proses baru dengan `PYTHONHASHSEED` berbeda menghasilkan indeks, baris dan file identik di luar manifest build.

SOH Stage 1 merekonsiliasi **2 opening + 10 receipt − 5 sale − 2 death = 5 closing**, dengan 15 transfer internal dan 338 ekor-hari. Rebuild Stage 1 seed 42 cocok dengan indeks hash file dan snapshot yang sudah diterima. Snapshot penuh `SYN-SNAPSHOT-5a322d6ce57e58cbe5b6d5ef` memuat 34 mutasi efektif dari 37 record mentah. [Bukti penerimaan Stage 1](../stage1/evidence/hashes.json) · [Hitungan manual](../stage1/FIXTURE_TIMELINE.md)

## Bukti temporal

| Perturbasi atau kontrol | Pemeriksaan |
|---|---|
| Bobot sale diubah | Snapshot, estimasi A/B dan draft sebelum sale identik. |
| Kematian `SYN-A01` dikeluarkan dari ledger uji | Snapshot fisik berubah dan sapi aktif setelah tanggal kematian asli. Snapshot dan estimasi sebelum kematian identik. |
| Pemulihan ditunda | Snapshot dan estimasi sebelum pemulihan identik. Status dan bobot laten kemudian berubah. |
| Observasi klinis pertama terlambat tersedia | Perubahan status belum masuk sebelum cutoff availability, walau waktu efektif sudah lewat. |
| Cold snap diganti skenario panas | Forecast yang dibuat sebelum waktu paparan identik. Bobot laten berubah setelah paparan. |
| Tiket follow-up terlambat dan dikoreksi | Nilai yang diubah belum menggeser anchor sebelum availability. Revisi eksplisit mendapat ID baru. Pembacaan kontemporer lama tetap identik. |
| Mutasi pen dan hospital | Event, lot, ID serta kontinuitas bobot konsisten pada transfer, pulang dan DST. Feeding dibagi menurut durasi akses. |
| Exit dan mutu | Timbang hidup saat atau sesudah kematian ditolak. Growth berhenti di exit. Data hilang dan anchor stale menghasilkan fallback. |

Script cold run juga memeriksa penolakan overwrite direktori build dan referensi dari estimasi ke tiket serta snapshot. Backtest menguji cutoff origin dan perhitungan metrik pada contoh unit dengan sampel yang lolos ambang skenario.

```sh
python -m unittest discover -s simulator_v2/stage1/tests -v
PYTHONPATH=src python -m pytest -q tests
python -m unittest discover -s simulator_v2/stage2/tests -v
```
