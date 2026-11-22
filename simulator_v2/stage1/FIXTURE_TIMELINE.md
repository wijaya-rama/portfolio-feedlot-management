# Timeline fixture 12 sapi dan ekspektasi manual

Semua ID dan peristiwa di halaman ini sintetis. Jam di tabel adalah jam bisnis `America/Edmonton`. Nomor 01–12 merujuk ke `SYN-A01`–`SYN-A12`. Lot 1 berisi 01–04. Lot 2 berisi 05–07 dan 11. Lot 3 berisi 08–10 dan 12. A dan B adalah kandang produksi, R receiving, dan H hospital.

| Waktu efektif lokal | Mutasi yang terlihat pada replay terbaru |
|---|---|
| 30 Des 2023 21.00 | Opening 01 dan 02 di A |
| 31 Des 08.00 | 03, 04 dan 05 masuk ke R, kapasitas 3 terisi |
| 31 Des 09.00 | 04 dan 03 dari R ke B, 05 dari R ke A. Versi awal mencatat 03 ke A |
| 31 Des 10.00, 15.00, 18.00 | 02 dari A ke H, 05 dari A ke B (terlambat tersedia), 04 dijual dari B |
| 1 Jan 2024 07.00, 08.00, 09.00 | 02 pulang ke A, 06–08 masuk ke R, lalu 06 ke A dan 07–08 ke B |
| 1 Jan 15.00, 16.00 | 08 mati di B. Transfer 01 dari A ke B tercatat pukul 16.00, lalu dibatalkan. 01 tetap di A pada replay terbaru |
| 31 Jan 11.00, 16.00 | 05 dijual dari B dan 06 dari A. 01 mati di A |
| 29 Feb 00.00, 09.00, 10.00, 16.00 | Kapasitas B turun dari 4 ke 3. 09–11 masuk ke R, lalu 09 dan 11 ke A serta 10 ke B. 07 dijual dari B |
| 10 Mar 00.00, 01.55, 03.05 | 12 masuk ke R tepat tengah malam, lalu pindah ke B. 10 dari B ke H. Jarak 01.55–03.05 hanya 10 menit karena DST |
| 10 Mar 20.00, 22.00 | 10 kembali ke B. 12 dijual dari B pada hari kedatangannya |
| 11 Mar | Lima ekor aktif pada akhir horizon. A berisi 02, 09, 11 dan B berisi 03, 10 |

## Jam event dan versi 31 Desember

| Catatan | `effective_at` UTC | `posted_at` UTC | `available_at` UTC |
|---|---|---|---|
| 05 pindah A → B | 31 Des 22.00 | 1 Jan 15.00 | 2 Jan 15.00 |
| 03 pindah R → B, menggantikan R → A | 31 Des 16.00 | 3 Jan 17.00 | 4 Jan 17.00 |
| Pembatalan transfer 01 | 1 Jan 23.00 | 4 Jan 19.00 | 5 Jan 15.00 |

`effective_at` menentukan hari mutasi fisik. `posted_at` mencatat kapan sistem menerima catatan. `available_at` menentukan kapan replay dapat menggunakannya. Misalnya transfer 05 masuk sistem 1 Januari pukul 08.00 lokal dan baru bisa dipakai 2 Januari pukul 08.00. Karena mutasinya efektif 31 Desember, replay dengan pengetahuan 2 Januari mengubah distribusi kandang pada 31 Desember. Seluruh varian menggunakan cutoff efektif **1 Januari 07.00 UTC**.

| Cutoff pengetahuan UTC | Kandang A | Kandang B | R | H | Yard | Status |
|---|---:|---:|---:|---:|---:|---|
| 1 Jan 07.00 | 3 | 0 | 0 | 1 | 4 | Publikasi awal |
| 2 Jan 15.00 | 2 | 1 | 0 | 1 | 4 | Replay diagnostik setelah transfer 05 tersedia |
| 4 Jan 17.00 | 1 | 2 | 0 | 1 | 4 | Revisi dengan persetujuan sintetis pada 4 Jan 18.00 UTC |

Setelah pembatalan 01 tersedia pada 5 Januari, tutup 1 Januari berubah dari A 2/B 4 ke A 3/B 3, dengan total enam. Catatan mentah asli dan dua catatan koreksi tetap dapat ditelusuri di ledger.

## Hitungan manual harian

Tabel memakai versi terbaru. Pada hari tanpa mutasi, buka sama dengan tutup dan seluruh arus nol.

| Tanggal | Yard buka | Terima | Jual | Mati | Yard tutup | A buka→tutup | B buka→tutup | R buka→tutup | H buka→tutup | Ekor-hari yard |
|---|---:|---:|---:|---:|---:|---|---|---|---|---:|
| 31 Des | 2 | 3 | 1 | 0 | 4 | 2→1 | 0→2 | 0→0 | 0→1 | 5 |
| 1 Jan | 4 | 3 | 0 | 1 | 6 | 1→3 | 2→3 | 0→0 | 1→0 | 7 |
| 2–30 Jan, per hari | 6 | 0 | 0 | 0 | 6 | 3→3 | 3→3 | 0→0 | 0→0 | 6 |
| 31 Jan | 6 | 0 | 2 | 1 | 3 | 3→1 | 3→2 | 0→0 | 0→0 | 6 |
| 1–28 Feb, per hari | 3 | 0 | 0 | 0 | 3 | 1→1 | 2→2 | 0→0 | 0→0 | 3 |
| 29 Feb | 3 | 3 | 1 | 0 | 5 | 1→3 | 2→2 | 0→0 | 0→0 | 6 |
| 1–9 Mar, per hari | 5 | 0 | 0 | 0 | 5 | 3→3 | 2→2 | 0→0 | 0→0 | 5 |
| 10 Mar | 5 | 1 | 1 | 0 | 5 | 3→3 | 2→2 | 0→0 | 0→0 | 6 |
| 11 Mar | 5 | 0 | 0 | 0 | 5 | 3→3 | 2→2 | 0→0 | 0→0 | 5 |

Contoh 31 Desember revisi. A tutup dengan 2 buka + 1 masuk − 2 pindah keluar = 1. B tutup dengan 0 buka + 3 transfer masuk − 1 jual = 2. R tutup dengan 3 receipt − 3 transfer keluar = 0. H tutup dengan 1 transfer masuk. Lima transfer internal memberi lima kaki masuk dan lima kaki keluar, dengan efek nol di yard. Contoh 10 Maret. 12 terhitung pada enam ekor-hari yard setelah masuk dan keluar pada hari yang sama. Yard tutup lima.

## Hitungan manual bulanan

| Periode | Buka | Terima | Jual | Mati | Tutup | Ekor-hari | Tutup lot 1/2/3 |
|---|---:|---:|---:|---:|---:|---:|---|
| 31 Des 2023 | 2 | 3 | 1 | 0 | 4 | 5 | 3/1/0 |
| Januari 2024 | 4 | 3 | 2 | 2 | 3 | 187 | 2/1/0 |
| Februari 2024 | 3 | 3 | 1 | 0 | 5 | 90 | 2/1/2 |
| 1–11 Maret 2024 | 5 | 1 | 1 | 0 | 5 | 56 | 2/1/2 |
| Horizon | 2 | 10 | 5 | 2 | 5 | 338 | 2/1/2 |

Ekor-hari Januari adalah 7 + 29 × 6 + 6 = 187. Februari adalah 28 × 3 + 6 = 90. Maret adalah 9 × 5 + 6 + 5 = 56. Dua saldo awal dan sepuluh penerimaan menghasilkan 12 identitas. Setelah lima penjualan dan dua mortalitas tersisa lima aktif.
