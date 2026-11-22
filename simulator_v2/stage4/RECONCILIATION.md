# Rekonsiliasi Stage 4 · seed 42

Seluruh nilai pada tabel adalah CAD. Jembatan feed di bawah memakai biaya FIFO provisional pada versi settlement aktif. DMI tetap mengikuti akses fisik Stage 3.5 sebesar 4.882.099 g AF dan 2.924.400 g DM.

| Arus biaya | Dasar konsumsi | Kebijakan terpilih |
|---|---:|---:|
| Issue FIFO bruto | 1.616,46 | 1.616,46 |
| Biaya konsumsi dasar | 1.462,40 | 1.462,40 |
| Mixing loss diserap | 0,00 | 16,05 |
| Distribution loss diserap | 0,00 | 7,68 |
| Refusal normal nonrecoverable diserap | 0,00 | 79,02 |
| Pakan dibebankan ke ternak | **1.462,40** | **1.565,15** |
| Refusal recoverable | 0,16 | 0,16 |
| Varians proses | 153,90 | 51,15 |
| Pending | 0,00 | 0,00 |

Loss bruto terdiri dari mixing 16,05, distribusi 7,71, refusal 130,28, dan bunk 0,02. Tiga sen distribusi pada delivery hospital tanggal 6 Januari masuk varians karena window itu tidak menghasilkan konsumsi. Selisih count 0,06 dan spoilage provisional 0,20 berasal dari gudang di luar issue FIFO. Dengan tambahan 0,03 dari invoice, varians feed yang diakui menjadi 51,44.

## Penutupan dan hasil

| Periode Edmonton | Ekor buka + masuk − sale − mati = tutup | Ekor-hari | WIP buka | WIP tutup asli | WIP tutup revisi |
|---|---|---:|---:|---:|---:|
| 31 Des 2023 | 2 + 3 − 1 − 0 = 4 | 5 | 2.100,00 | 4.660,34 | 4.661,68 |
| Jan 2024 | 4 + 3 − 2 − 2 = 3 | 187 | 4.660,34 | 4.296,17 | 4.293,81 |
| Feb 2024 | 3 + 3 − 1 − 0 = 5 | 90 | 4.296,17 | 7.717,84 | 7.715,75 |
| 1–11 Mar 2024 | 5 + 1 − 1 − 0 = 5 | 56 | 7.717,84 | 8.137,01 | 8.137,01 |

| Periode buku asli | Penjualan bersih | COGS | Gross margin | Mortalitas | Varians feed | Kontribusi yard |
|---|---:|---:|---:|---:|---:|---:|
| Desember | 1.760,00 | 1.253,40 | 506,60 | 0,00 | 0,69 | 505,91 |
| Januari | 3.647,50 | 3.077,97 | 569,53 | 2.725,09 | 28,61 | −2.184,17 |
| Februari | 1.930,00 | 1.773,08 | 156,92 | 0,10 | 15,63 | 141,19 |
| Maret | 2.020,00 | 1.652,52 | 367,48 | 6,86 | 6,51 | 354,11 |
| **Horizon** | **9.357,50** | **7.756,97** | **1.600,53** | **2.732,05** | **51,44** | **−1.182,96** |

WIP akhir per sapi aktif adalah A02 1.573,29, A03 1.611,46, A09 1.565,02, A10 1.721,87, dan A11 1.665,37. WIP akhir ketujuh sapi keluar nol. Persediaan gudang tutup dengan 4.966.424 g AF dan CAD 1.454,41. Recoverable menunjukkan 500 g AF, 250 g DM dan CAD 0,17 setelah invoice. Saldo kliring nol. Trial balance saldo akhir debit dan kredit masing-masing CAD 29.492,05.

## Invoice dan revisi

Invoice pemasok +25 sen tersedia 4 Januari, setelah periode issue Desember terkunci. Split FIFO membagi 13 sen ke persediaan tersisa, 10 sen ke issue historis, dan 2 sen ke spoilage historis. Sepuluh sen issue menjadi 8 sen biaya ternak, 1 sen recovery dan 1 sen varians. Setelah pelepasan dan koreksi, biaya ternak ini tersisa 2 sen di WIP A02, 2 sen di COGS A05 dan 4 sen di write-off A01. Jurnal Januari awal dan jurnal koreksi Maret tetap dapat ditelusuri. Koreksi packer 250 sen mengurangi piutang dan revenue pada Januari. Penerimaan gudang terlambat pada 11 Januari memperbarui vintage harian dengan +6.000.000 g AF dan +147.000 sen.

Restatement berizin mengubah alokasi feed dan lokasi setelah koreksi pergerakan, serta membawa koreksi yardage 31 Januari ke Januari untuk analisis. Dibandingkan penutupan asli, WIP revisi berubah +134 sen pada Desember, −236 sen pada Januari, −209 sen pada Februari, dan nol pada Maret. Pada cutoff revisi, A03 berada di pen B untuk Desember. COGS dan write-off bergeser antarbuku bulanan dengan total horizon sama. Hash snapshot asli tetap sama saat direkonstruksi hanya dari data yang diketahui saat lock.

## Contoh hitungan manual

- **FIFO dan refusal 31 Desember.** Issue 6.000 g AF × 180/6.000 sen dan 2.000 g AF × 80/2.000 sen memberi 8.000 g AF dan 260 sen. Refusal 2.000 g AF membawa 65 sen. Dari 2.000 g tersebut, 500 g bertag recovery, 400 g mengikuti allowance 5% × 8.000 g, dan 1.100 g berlebih. Pembagian 65 sen dengan sisa terbesar memberi 16 sen recovery, 13 sen normal dan 36 sen varians. Konsumsi 3.000 g DM membawa 195 sen. Biaya ternak menjadi 208 sen.
- **Mix dan distribusi hospital 31 Desember.** Issue 190 sen memuat mixing loss 2 sen dan distribution loss 1 sen. Refusal 15 sen terbagi 9 sen normal dan 6 sen varians. Konsumsi dasar 172 sen, total biaya ternak 184 sen, dan 6 sen tersisa sebagai varians.
- **Pelepasan.** Contoh unit membuka WIP 10.000 sen, lalu menambah feed 180, yardage 120 dan vet 80. Pelepasan pokok sebesar 10.380 sen. Invoice terlambat 25 sen membuat COGS atau write-off menjadi 10.405 sen sesuai exit, dengan WIP nol.
- **Yardage dan akses.** Pada 1 Januari, 4 ekor buka + 3 receipt − 1 mati menghasilkan 6 ekor tutup. Tujuh ekor-hari menghasilkan 840 sen. A08 tidak mempunyai alokasi PM. A01 menerima porsi sampai waktu kematian di tengah window 31 Januari. Jurnal tiket yang tersedia setelah kematiannya masuk write-off.
- **Recovery dan pelepasan parsial.** Sebagai uji unit, lot 500 g AF bernilai 17 sen melepas 200 g ke delivery berikutnya senilai 7 sen. Disposal 300 g sisanya melepaskan 10 sen ke varians. Shipment Januari menjual A05 dan A06, sementara A07 tetap dalam lot pembelian sampai Februari.

## Sensitivitas dan pasar

| Kebijakan | Absorpsi | COGS | Mortalitas | Varians feed | Kontribusi yard | WIP akhir | Absorpsi tertahan di WIP |
|---|---:|---:|---:|---:|---:|---:|---:|
| Konsumsi dasar | 0,00 | 7.717,61 | 2.720,87 | 154,20 | −1.235,18 | 8.084,79 | 0,00 |
| Ambang lebih ketat | 47,52 | 7.735,50 | 2.725,85 | 106,68 | −1.210,53 | 8.109,44 | 24,65 |
| Terpilih | 102,75 | 7.756,97 | 2.732,05 | 51,44 | −1.182,96 | 8.137,01 | 52,22 |

Total biaya yang ditelusuri pada ketiga kebijakan adalah CAD 18.677,64 dalam cakupan COGS, write-off, varians, WIP, recovery dan clearing. Selisih kontribusi antara konsumsi dasar dan kebijakan terpilih sebesar CAD 52,22 tetap masuk WIP sapi aktif. Cakupan nilai pasar sintetis per bulan 4/4, 2/3, 0/5 dan 3/5 ekor. Bulan dengan cakupan parsial memiliki nilai total yard null.
