# Rekonsiliasi fixture seed 42

## Persediaan dan nutrien

Semua angka di bawah adalah untuk satu horizon dan satu versi aktif. AF adalah massa as-fed, DM adalah bahan kering, dan CP adalah protein kasar. Sen adalah sen CAD.

| Arus gudang | g AF | g DM | Sen CAD |
|---|---:|---:|---:|
| Buka | 3.660.000 | 3.083.500 | 142.400 |
| Penerimaan | +6.705.000 | +3.063.500 | +164.700 |
| Transfer neto | 0 | 0 | 0 |
| Issue FIFO | −5.397.876 | −3.233.344 | −161.646 |
| Penyesuaian hitung | −200 | −100 | −6 |
| Spoilage | −500 | −250 | −20 |
| Revaluasi assay DM | 0 | −29.642 | 0 |
| Pembulatan gram DM | 0 | −19 | 0 |
| Delta invoice pada persediaan | 0 | 0 | +13 |
| Tutup | **4.966.424** | **2.883.645** | **145.441** |

Kaki transfer AF masing-masing 4.000 g, DM 2.000 g, dan nilai 120 sen. Delta invoice total 25 sen terdiri dari 13 sen pada layer tersisa dan 12 sen pada sink historis. Penurunan kadar bahan kering pada assay silage menyesuaikan basis DM sisa stok. Basis fisik AF, nilai FIFO, dan DM issue yang sudah tercatat tetap mengikuti versi dokumen asalnya. Receipt terlambat yang disetujui menambah 6.000.000 g AF dan 147.000 sen pada snapshot gudang revisi untuk Januari 11. Layer serta entri historis dapat ditelusuri ke snapshot awal dan revisi.

| Arus pakan | g AF | g DM | kJ | g CP | Sen CAD |
|---|---:|---:|---:|---:|---:|
| Issue | 5.397.876 | 3.233.344 | 34.726.885 | 397.217 | 161.646 |
| Loss mixing | 53.716 | 32.196 | 345.883 | 3.972 | 1.605 |
| Mixed dan loaded | 5.344.160 | 3.201.148 | 34.381.002 | 393.245 | 160.041 |
| Loss distribusi | 26.661 | 15.962 | 171.418 | 1.960 | 771 |
| Delivered | 5.317.499 | 3.185.186 | 34.209.584 | 391.285 | 159.270 |
| Refusal | 435.350 | 260.755 | 2.800.380 | 32.054 | 13.028 |
| Loss bunk | 50 | 31 | 336 | 4 | 2 |
| Konsumsi | **4.882.099** | **2.924.400** | **31.408.868** | **359.227** | **146.240** |

Masing-masing dari tiga metode membagi persis pool konsumsi yang sama untuk delivery yang sama. Metode aktif BW^0,75 menghasilkan 3.336 kandidat WIP. Total gram DM, kJ dan gram CP kandidat terpakai sama dengan total kredit pertumbuhan. Terdapat 292 delivery dan 311 versi settlement, termasuk 19 revisi. Seleksi settlement aktif menghindari penghitungan ganda antarversi dan antarmetode.

## Pemeriksaan independen

- Pengiriman 31 Desember pukul 08.00 Edmonton ke Pen A menarik 6.000 g AF dari layer lama senilai 180 sen dan 2.000 g AF dari layer baru senilai 80 sen. Pool 8.000 g AF berisi 4.000 g DM. Refusal 2.000 g AF membawa 1.000 g DM dan 65 sen sehingga konsumsi 3.000 g DM dan 195 sen.
- Enam rilis masing-masing 500 g DM. Pada 08.00–09.00 A01 dan A02 berbagi. Pada 09.00–10.00 A05 ikut. Pada 10.00–11.00 A01 dan A05 berbagi. Equal-head menghasilkan 1.334, 834 dan 832 g DM, serta 88, 54 dan 53 sen untuk A01, A02 dan A05. Posisi A03 yang sudah direvisi berada di Pen B.
- Skenario uji satu ekor mengawali window dengan bobot 400 kg, tanpa galat atau shrink. Pukul 08.15 tetap 400 kg. Pukul 08.30, pelepasan 2.000 g DM, 16 MJ, dan 0,2 kg CP memberi kredit 0,25 kg. Separuh pakan menurunkan kredit menjadi 0. Beban penyakit 0,5 dengan penalti 0,5 dan pakan tetap memberi kredit 0,1875 kg.
- Pada 1 Januari, yard memulai dengan 4 ekor, menerima 3, mencatat 1 kematian, dan menutup dengan 6 ekor. Hari itu tetap memiliki 7 animal-days dan tidak ada porsi pakan A08 setelah waktu kematiannya. Horizon memuat 338 animal-days.

[Laporan mesin](evidence/reconciliation.json) · [Hasil validasi](evidence/validation.json) · [Verifikasi baseline](evidence/baseline_hash_checks.json)
