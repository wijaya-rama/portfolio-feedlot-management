# Backtest rolling-origin

Target adalah tiket non-entry yang tersedia sampai 12 Maret 2024 pukul 00.00 Edmonton. Untuk setiap tiket pada waktu `t`, origin adalah `t − h × 24 jam`. Kedua model membuat forecast untuk `t` dari fitur yang tersedia di origin. Origin harus berada dalam horizon evaluasi, hewan aktif pada replay origin, serta mempunyai anchor eligible. Penjadwalan target memakai data evaluasi yang kelak tersedia. Model tidak dilatih pada lot atau hasil timbang. Seluruh lot berperan sebagai evaluasi untuk prior sintetis yang sudah dibekukan.

| Horizon | Kandidat tiket | Prediksi eligible per model | Ekor eligible | Lot eligible | Cakupan |
|---:|---:|---:|---:|---:|---:|
| 7 hari | 19 | 15 | 8 | 3 | 78,95% |
| 30 hari | 19 | 8 | 5 | 2 | 42,11% |
| 60 hari | 19 | 2 | 2 | 1 | 10,53% |

| Horizon | Origin sebelum awal evaluasi | Tidak aktif di origin | Anchor belum tersedia di origin |
|---:|---:|---:|---:|
| 7 | 1 | 2 | 1 |
| 30 | 6 | 5 | 0 |
| 60 | 11 | 6 | 0 |

Cakupan = prediksi eligible dibagi 19 tiket target kandidat pada setiap horizon. Denominator tersebut mengukur cakupan terhadap target yang teramati. Kesempatan timbang hilang tercatat di `weigh_attempts`. Bias seleksi timbang dan ketersediaan antar lot perlu dianalisis di pilot.

Laporan menggunakan ambang skenario per kelompok sebesar 30 pasangan, 15 hewan unik dan 3 lot. Seluruh horizon dan strata fixture berada di bawah ambang. MAE, bias, kuantil galat dan perubahan terhadap baseline belum dilaporkan. Saat ambang terpenuhi, evaluator menghitung galat bertanda sebagai prediksi dikurangi tiket, P10/P50/P90, MAE per model dan `MAE A − MAE B`. Nilai positif berarti perbaikan terhadap A.

Cakupan dipecah menurut breed, sex, frame, stage, musim, status kesehatan origin, lot dan jenis timbang. Diagnostik laten mencatat 25 target pembanding pada pasangan eligible dan menerapkan gate yang sama untuk ringkasan galat. Tahap pilot perlu mengunci holdout per lot dan waktu serta cutoff fit independen sebelum mencoba model berbasis data. [Laporan lengkap](evidence/backtest.json)
