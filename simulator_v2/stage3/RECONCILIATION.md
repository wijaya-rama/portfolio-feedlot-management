# Rekonsiliasi fixture seed 42

Fixture mengikuti 12 identitas Stage 1, dengan 2 opening, 10 receipt ternak, 5 sale, 2 death, 5 closing dan 338 ekor-hari. Masing-masing window menyimpan rencana untuk empat lokasi. Ada 292 delivery fisik dan 311 settlement termasuk 19 revisi. Ledger biaya memilih satu settlement dan metode per delivery. Hasilnya 674 kandidat konsumsi dan biaya, serta 1.732 langkah biologis.

## Gudang

| Arus horizon | AF (kg) | Sen CAD |
|---|---:|---:|
| Opening | 3.660,000 | 142.400 |
| Penerimaan | +6.705,000 | +164.700 |
| Transfer masuk | +4,000 | +120 |
| Issue ke mixer | −5.400,249 | −161.720 |
| Transfer keluar | −4,000 | −120 |
| Adjustment count | −0,200 | −6 |
| Spoilage | −0,500 | −20 |
| Delta invoice pada saldo tersedia | 0,000 | +13 |
| **Closing** | **4.964,051** | **145.367** |

PO silage 6.700 kg diterima dalam dua tahap. Penerimaan 700 kg bernilai 16.800 sen ditambah 700 sen freight. Penerimaan 6.000 kg bernilai 144.000 sen ditambah 3.000 sen freight. Penerimaan kedua berlaku fisik 10 Januari pukul 07.00 dan tersedia 11 Januari pukul 07.30. Untuk cutoff fisik 11 Januari tengah malam, cutoff pengetahuan awal menghasilkan 3.334,406 kg dan 130.822 sen. Revisi yang disetujui menambah 6.000 kg dan 147.000 sen dengan seluruh kaki issue lama identik.

## Jembatan pakan

| Tahap | AF (kg) | DM (kg) | Sen CAD |
|---|---:|---:|---:|
| Issue | 5.400,249 | 3.234,809 | 161.720 |
| Loss mixer | 53,739 | 32,212 | 1.612 |
| Output mixer dan muat | 5.346,510 | 3.202,597 | 160.108 |
| Loss truck | 26,673 | 15,969 | 773 |
| Sampai pen | 5.319,837 | 3.186,628 | 159.335 |
| Refusal | 427,030 | 255,599 | 12.771 |
| Loss bunk | 0,050 | 0,031 | 2 |
| **Konsumsi model** | **4.892,757** | **2.930,998** | **146.562** |

Massa AF dan DM, energi, protein serta biaya direkonsiliasi per mix dan delivery. Alokasi aktif dan masukan pertumbuhan masing-masing membawa 2.930,998 kg DM. Nilai issue 161.720 sen terbagi menjadi 146.562 sen kandidat WIP dan 15.158 sen loss/refusal setelah issue. Spoilage dan adjustment gudang masuk jembatan stok tersendiri. Retur pada horizon fixture adalah nol.

## Hitungan manual · Kandang A, 31 Desember 2023 pukul 08.00

Bin 1 dibuka dengan 10 kg AF/300 sen dan menerima 5 kg AF/200 sen. Transfer 4 kg AF/120 sen ke bin 2 membawa layer asal. Issue FIFO 8 kg AF mengambil sisa 6 kg/180 sen dari layer lama dan 2 kg/80 sen dari layer baru. Bin 1 tutup 3 kg/120 sen dan bin 2 tutup 4 kg/120 sen pada hari itu. Pada 2 Januari, count bin 2 menunjukkan 3,8 kg dan adjustment mengeluarkan 0,2 kg/6 sen.

Kedua batch untuk contoh ini mengandung 50% DM. Maka 8 kg AF × 50% = 4 kg DM, dengan nilai 260 sen. Mixer dan truck contoh beroperasi tanpa loss. Refusal 2 kg AF mengambil 1 kg DM dan 65 sen. Pool konsumsi 6 kg AF menyisakan 3 kg DM, 30 MJ, 360 g protein, dan 195 sen.

SYN-A01 mendapat 3 jam akses. SYN-A02 mendapat 2 jam sebelum pindah ke hospital pukul 10.00. SYN-A05 mendapat 2 jam dari penempatan pukul 09.00 dan memakai 400 kg fallback karena belum tercakup pada cutoff 08.00. Replay revisi menempatkan SYN-A03 di B. Bobot tetap menggunakan input 08.00, masing-masing 463,716 kg, 437,616 kg dan 400 kg.

| Hewan | Akses | Equal-head (g DM/sen) | BW (g DM/sen) | BW^0,75 (g DM/sen) |
|---|---:|---:|---:|---:|
| SYN-A01 | 3 jam | 1.286 / 83 | 1.361 / 88 | 1.342 / 87 |
| SYN-A02 | 2 jam | 857 / 56 | 856 / 56 | 857 / 56 |
| SYN-A05 | 2 jam | 857 / 56 | 783 / 51 | 801 / 52 |
| **Jumlah** | **7 jam-ekor** | **3.000 / 195** | **3.000 / 195** | **3.000 / 195** |

Equal-head memberi kuota mentah 3.000 × 3/7, 3.000 × 2/7 dan 3.000 × 2/7. Gram residual jatuh ke SYN-A01. Sen dibagi menurut gram DM hasil alokasi. Masing-masing skor BW dan BW^0,75 dikalikan jam akses sebelum dinormalisasi. Untuk dua hewan dengan gram dan akses sama, pembagian 195 sen menghasilkan 98 dan 97 sen menurut urutan ID.

## Bukti penerimaan

| Pemeriksaan | Hasil |
|---|---:|
| Stage 3 | 20/20 |
| Stage 1 | 33/33 |
| Stage 2 | 38/38 |
| Regresi V1 | 87/87 + 60 subtes |
| Hard gate build Stage 3 | 63/63 |

Dua proses dengan `PYTHONHASHSEED` berbeda menghasilkan file isi dan hash kanonik yang identik. Build seed 43 juga melewati kontrol. Indeks hash Stage 1 dan Stage 2 hasil rebuild cocok dengan publikasi masing-masing. Tujuh CSV generator V1 hasil replay cocok dengan SHA-256 audit lama. [Bukti Stage 1](../stage1/evidence/hashes.json) · [Bukti Stage 2](../stage2/evidence/hashes.json) · [Audit V1](../00_LEGACY_GENERATOR_AUDIT.md)

Uji perturbasi mengubah timbang follow-up sebelum tersedia, bobot terminal, outcome mortalitas, pemulihan klinis, dan cuaca. Pada cutoff sebelum fakta yang diubah, rencana, input bobot, delivery selesai dan alokasi historis cocok. Cuaca mengubah bobot laten setelah paparan tanpa mengubah ledger pakan. Mengganti metode alokasi mengubah jalur pertumbuhan dengan delivery, roster, dan total biaya yang sama. Revisi roster ditautkan ke induk dengan input bobot historis tetap beku.

Paket ekspor memuat Parquet bertipe, manifest dan indeks hash, laporan kontrol, serta bridge yang dapat dibaca mesin. [Paket keluaran seed 42](evidence/fixture-seed42.zip)
