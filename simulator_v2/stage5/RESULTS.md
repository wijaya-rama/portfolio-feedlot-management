# Hasil kandidat · fixture sintetis seed 42

Kandidat menggunakan satu ledger ternak 12 ekor, 10 placement dan dua sapi carry-in. Lima keluar lewat sale, dua lewat kematian, dan lima merupakan carry-out. Salah satu kematian terjadi tanpa terapi. Ada empat first treatment, satu repeat dan dua admisi hospital. Durasi dari entry yang diketahui sekitar 0,3–72,1 hari. Dua sale terjadi dalam satu hari sejak masuk dan menguji kronologi atau posting. Jangkauan bobot hidup semua outcome retrospektif 365–572 kg. HCW skenario pada lima sale 274,8–350,0 kg, rerata 313,3 kg. Grade tidak tersedia pada seluruh sale. Hasil ini membuktikan jalur peristiwa dan kontrol kondisi tepi pada fixture. [Outcome individu](evidence/experiments.json)

## Dari baseline ke kandidat

| Ukuran | Baseline diterima | Kandidat |
|---|---:|---:|
| ADG laten operasional (kg/hari elapsed) | 0,907 | 0,901 |
| ADG retrospektif seluruh paparan (kg/hari elapsed) | — | 0,886 |
| DM ledger fisik (kg) | 2.924,400 | 2.900,386 |
| Rerata bobot laten akhir operasional (kg) | 466,21 | 466,05 |
| WIP akhir (CAD) | 8.137,01 | 8.130,79 |
| Inventori pakan akhir (CAD) | 1.454,41 | 1.467,49 |
| COGS penjualan (CAD) | 7.756,97 | 7.754,09 |
| Rugi mortalitas (CAD) | 2.732,05 | 2.728,40 |
| Margin kotor penjualan (CAD) | 1.600,53 | 1.603,41 |
| Kontribusi yard dalam lingkup buku (CAD) | −1.182,96 | −1.176,10 |

Retrospektif terdiri dari **328,58 hari-sapi arsip** dengan ADG 0,900 kg dan DMI 8,761 kg/hari serta **3,83 hari-sapi fallback** dengan ADG −0,325 kg dan DMI 5,643 kg/hari. Fallback pada fixture terutama terjadi sebelum pembukaan cakupan tahun 2024 dan mengandung banyak segmen parsial. Perbedaan antar kelompok tersebut menggabungkan komposisi hewan, akses pakan dan timing. Pengaruh suhu diuji dengan input konsumsi yang sama pada eksperimen di bawah.

Stage 5 menempatkan pemeliharaan, pertumbuhan dan catatan timbang pada langkah kronologis yang sama. Perubahan movement retroaktif berlaku prospektif pada jalur pembuatan tiket timbang. Dokumen pakan/gerak yang diketahui kemudian masih dapat menghasilkan settlement fisik revisi dengan lineage dan approval yang telah tersedia pada Stage 3.5 serta Stage 4. Uji menggeser ketersediaan koreksi, waktu sale intrawindow dan isi arsip masa depan, lalu memeriksa bobot atau hash keputusan awal. Validator feed-release juga kini memakai kunci pembagian yang sama dengan settlement untuk ties sisa integer. Ketidaksamaan kunci sebelumnya bisa membuat residual semu pada intervensi loss tinggi.

## Eksperimen terkontrol

Baris dengan feed tetap memakai delivery, metode dan seed yang sama kecuali ketika metode itu sendiri diuji. Percobaan ME, penawaran dan loss fisik membangun kembali operasi dengan satu parameter yang diubah sehingga feedback melalui tiket dan rencana tetap dapat terjadi. Penghilangan burden mempertahankan kasus, waktu terapi, biaya, perpindahan dan alokasi. Semua hasil bersifat sensitivitas model.

| Skenario | ADG kg/hari | DMI kg/hari | Gain:DM | Bobot akhir rerata kg | HCW rerata sale kg |
|---|---:|---:|---:|---:|---:|
| 10 °C · feed tetap | 0,919 | 8,725 | 0,1054 | 466,55 | 313,94 |
| −25 °C · feed tetap | 0,836 | 8,725 | 0,0958 | 464,24 | 312,68 |
| 10 °C · burden klinis menjadi nol | 0,931 | 8,725 | 0,1068 | 466,89 | 314,06 |
| 10 °C · alokasi equal-head | 0,921 | 8,725 | 0,1055 | 466,59 | 313,70 |
| 10 °C · alokasi BW | 0,917 | 8,725 | 0,1051 | 466,48 | 314,02 |
| Musiman · feed fisik basis | 0,902 | 8,725 | 0,1034 | 466,08 | 313,60 |
| Musiman · ME bahan utama −10% | 0,800 | 8,714 | 0,0918 | 463,24 | 312,00 |
| Musiman · target DM −20% | 0,632 | 7,066 | 0,0895 | 458,60 | 309,10 |
| Musiman · mixing loss 300 bps | 0,889 | 8,548 | 0,1040 | 465,71 | 313,40 |
| Musiman · distribusi loss 150 bps | 0,896 | 8,637 | 0,1037 | 465,90 | 313,50 |

Pada percobaan dingin, maintenance ME naik sekitar 20% dengan net loss/gain bergantung pada kondisi segmen. Sensitivitas efisiensi ME maintenance 0,59–0,69 memberi ADG 0,894–0,930 kg/hari pada 10 °C. Efisiensi ME gain 0,35–0,45 memberi 0,886–0,930 kg/hari. Slope pemeliharaan dingin 0,004–0,012 per °C memberi ADG 0,888–0,759 kg/hari pada −25 °C. Angka ini memperlihatkan range skenario. Kalibrasi empiris efisiensi, thermal stress dan MP masih terbuka.

DMI per sapi-hari bisnis retrospektif, termasuk hari parsial, memiliki median 2,01% bobot langkah pertama hari tersebut. Maksimum 2,92%, dan beberapa hari tanpa konsumsi. Fixture menghasilkan sekitar 9,85 kg DM per kg net gain retrospektif. Partial exit, penerimaan, penyakit dan pembatasan penawaran memberi beberapa kasus bobot turun. Neraca tidak mengubah g DM atau energi untuk menargetkan margin.

## Biaya dan kontrol

Kuantitas ditawarkan 5.275,251 kg AF dan 3.159,072 kg DM. Ledger memodelkan konsumsi 4.843,235 kg AF dan 2.900,386 kg DM. Fisik mixing loss 53,287 kg AF, distribusi loss 26,439 kg AF, refusal 431,966 kg AF, dan bunk loss 0,050 kg AF. Biaya issue CAD 1.603,38 terbagi menjadi konsumsi dasar CAD 1.450,50, loss normal terserap CAD 101,90, loss proses abnormal CAD 50,82 dan recovery CAD 0,16. Biaya feed efektif yang diposting ke basis WIP serta outcome adalah CAD 1.552,40. Penyesuaian invoice, sisa di inventori, dan warehouse variance ditelusuri terpisah. Buku berisi 5.294 jurnal, saldo debit-kredit nol, dan 62 bridge DM penutupan dibukukan/direstatement serta diperiksa terhadap ledger gudang.

| Skenario | Biaya feed efektif CAD | WIP akhir CAD | COGS CAD | Margin kotor CAD | Varians feed CAD |
|---|---:|---:|---:|---:|---:|
| Kebijakan selected · operasi dasar | 1.552,40 | 8.130,79 | 7.754,09 | 1.603,41 | 51,11 |
| Toleransi tighter | 1.497,74 | 8.103,44 | 7.732,78 | 1.624,72 | 105,78 |
| Consumption-only | 1.450,50 | 8.078,88 | 7.714,95 | 1.642,55 | 153,02 |
| Target DM −20% | 1.260,23 | 7.982,91 | 7.641,79 | 1.715,71 | 41,51 |
| Mixing loss 300 bps | 1.505,35 | 8.106,29 | 7.736,48 | 1.621,02 | 97,77 |
| Distribusi loss 150 bps | 1.528,67 | 8.118,35 | 7.745,41 | 1.612,09 | 74,67 |
| Packer 85% harga baseline | 1.552,40 | 8.130,79 | 7.754,09 | 199,79 | 51,11 |
| Packer 115% harga baseline | 1.552,40 | 8.130,79 | 7.754,09 | 3.007,03 | 51,11 |

Margin kotor dapat terlihat naik ketika pakan dibebankan sebagai varians atau berkurang, sementara pendapatan settlement sintetis dipertahankan tetap. Kontribusi yard juga membebankan mortalitas dan varians. Gunakan outcome feed dan laporan kontribusi bersama margin untuk membaca perbedaan. Harga live non-posting dan grid HCW ilustratif tidak mengalir ke akun WIP. [Close, invoice dan recovery](evidence/finance.json)

## Penerimaan

- 22 skenario, 377 hasil pemeriksaan operasional/biologis dan 86 kontrol finansial untuk setiap buku pembanding. Baseline Stage 1–4 direbuild dengan indeks hash yang sama. Dua build kandidat mempunyai indeks dan isi artefak yang sama, termasuk hash baris Parquet. [Kontrol kandidat](evidence/validation.json) · [Bukti regresi](evidence/regression.json)
- Backtest fixture memuat 16/8/2 prediksi eligible pada 7/30/60 hari, dengan 20 target pada tiap horizon. Data kurang untuk menerbitkan MAE, bias, coverage interval atau klaim akurasi. [Bukti backtest](evidence/backtest_fixture.json)
- Proyeksi kapasitas menghasilkan 375–425 ekor peak concurrent, 300–375 carry-out dan 243.650–290.375 animal-days. Prediksi volume sekitar 0,49–0,58 juta baris animal-window maksimum dan 2,44–2,90 juta alokasi per metode jika setiap slice disimpan. Puncak rencana feed 8,5 t AF/hari sebelum loss, dengan sekitar 119 t kebutuhan awal dan buffer menurut cadence yang dipilih. [Proyeksi kapasitas](evidence/pilot_capacity.json)
- Kandidat lulus pada fixture. Implementasi runner 24 bulan, validasi skala, seri cuaca vintage, serta bukti intake, health, carcass dan harga untuk kalibrasi komersial masih terbuka. [Gerbang Stage 6](STAGE6_HANDOFF.md)
