# Phase 2B-4.5 · Inventaris bulanan, WIP, dan pelepasan biaya

Cakupan laporan adalah 15.000 sapi dalam kohor simulasi Highwood Feeders. Rekonstruksi menghasilkan 24 saldo akhir bulan dari Januari 2024 hingga Desember 2025, dengan rincian 90 lot dan 40 pen tercatat. Harga perolehan dan tindakan veteriner bertanggal dapat ditelusuri dari data asal. Estimasi WIP dan pelepasan biaya juga memakai pengiriman pakan bertanggal dan akrual yardage. WIP dan COGS aktual lengkap, valuasi pasar, serta nilai persediaan gudang pakan belum tersedia. [Notebook](../notebooks/04b_monthly_inventory_wip.ipynb)

## Audit sumber dan kelayakan

| Metrik | Klasifikasi | Bukti dan batas penggunaan |
|---|---|---|
| Identitas individu, breed, jenis kelamin, lot, pen, tanggal masuk dan harga perolehan | Tercatat langsung dalam simulasi | `Dim_Cattle`. `Dim_Lot` memuat tanggal tiba, harga live/kg dan jumlah penempatan. `Dim_Pen` memberi atribut pen. Breed individu dipakai untuk analisis sapi. |
| Tanggal dan jenis keluar | Tercatat langsung dalam simulasi | `Fact_Closeout_Sales` merekam `Finished Sale` dan `Mortality`. CSV dan `Feedlot_Flat_15000` mengulang data closeout. Tanggal jual operasional memakai tanggal keluar. Tanggal pembayaran, posting, dan penyelesaian faktur tidak tersedia. |
| Stok awal dan akhir, penempatan, penjualan, mortalitas | Direkonstruksi | Gabungan kalender dan tanggal masuk/keluar individu. Tanggal masuk dari 1 Januari 2024 sampai 5 Juni 2025. Tanggal keluar dari 8 Januari 2024 sampai 4 Desember 2025. |
| Mutasi fisik antarpen, transfer kepemilikan lain, dan stok fisik | Tidak didukung | `pen_id` konsisten sepanjang data. Riwayat pindah pen serta sensus fisik tidak tersedia. |
| Pembelian WIP | Direkonstruksi dari harga perolehan tercatat | Harga perolehan disematkan ke tanggal masuk sebagai kebijakan model. Invoice, biaya tunai dan tanggal posting tidak tersedia. |
| Veteriner langsung | Tercatat langsung dan dapat dijumlah menurut bulan | 2.220 tindakan pada `Fact_Health_Treatments`, 5 Januari 2024–29 Agustus 2025. Gunakan tanggal tindakan dan nominal per `treatment_id`. |
| Veteriner dasar | Nominal direkonsiliasi, waktu tidak didukung | Selisih biaya veteriner closeout dan tindakan langsung sebesar CAD 18 per sapi. Sumber tidak memberi tanggal beban atau kebijakan pengakuannya. |
| Pakan yang dikirim dan biaya pengiriman pakan | Tercatat langsung dan dapat dijumlah menurut bulan | 16.085 baris `Fact_Feed_Daily` pada grain lot–pen–tanggal, 1 Januari 2024–4 Desember 2025. Ada jumlah as-fed, bahan kering, komponen, head-days dan nilai pakan. Nilai tersebut berasal dari model pengiriman. |
| Pakan individu dan yardage per bulan | Estimasi | Bagi biaya pengiriman harian dengan sapi yang memenuhi syarat hari itu. Gunakan CAD 0,60 per hari produksi inklusif untuk yardage sesuai pola tarif yang direkonsiliasi pada snapshot. Tarif historis independen dan konsumsi individual tidak tersedia. |
| WIP serta pelepasan penjualan dan mortalitas | Direkonstruksi sebagian dan diestimasi | Harga perolehan dan tindakan bertanggal menghasilkan jembatan parsial. Jembatan estimasi menambahkan pakan dan yardage. Buku besar WIP bulanan, COGS aktual, koreksi, biaya disposal atau recovery, dan biaya produksi lain tidak tersedia. |
| Biaya dan pendapatan lifetime | Tercatat langsung dalam simulasi | `Fact_Closeout_Sales` memuat purchase, allocated feed, yardage, vet, dan pendapatan lifetime. Angka tersebut digunakan untuk audit retrospektif. Harga grid karkas dinyatakan per kg HCW. |
| Bobot hidup | Tercatat langsung pada hari timbang, estimasi di antaranya | `Fact_Scale_Weights` memiliki 74.268 catatan timbang dari 1 Januari 2024 sampai 4 Desember 2025. Gunakan bobot terakhir yang tersedia pada waktu tutup. |
| Harga pasar liveweight dan biaya penjualan | Tidak didukung dalam snapshot | Sumber internal hanya memberi harga perolehan dan harga realisasi karkas. Harga pasar dan biaya penjualan membutuhkan sumber bertanggal terpisah. |
| Persediaan gudang pakan dan valuasinya | Tidak didukung | Data memberi pengiriman pakan ke lot dan pen. Rekaman mutasi gudang yang diperlukan dijabarkan di bawah. |

`Executive_Summary` dan `Data_Dictionary` memberi konteks cakupan dan definisi. Label akhir Desember dalam ringkasan tidak menambah transaksi setelah 4 Desember. Snapshot cuaca ERA5 merupakan sumber terpisah untuk paparan cuaca dan diverifikasi saat build. Tanggal internal adalah tanggal efektif simulasi. Waktu ketika data masuk atau direvisi tidak tercatat, sehingga rekonstruksi historis tidak menguji tanggal posting atau keterlambatan pencatatan. [Audit tabel dan kolom](../analysis_audit/01_SOURCE_INVENTORY.md) · [Model data](../phase2a/DATA_MODEL.md)

## Stok dan pergerakan sapi

Pada tanggal tutup `t`, sapi berada dalam stok akhir jika `entry_date ≤ t < exit_date`. Cutoff memakai akhir hari kalender feedlot. Sumber hanya merekam tanggal tanpa jam atau zona waktu. Stok awal adalah saldo akhir hari sebelum tanggal pertama bulan. Penempatan, penjualan dan mortalitas dihitung pada tanggal efektif, termasuk tanggal terakhir bulan. Sapi yang masuk dan keluar pada hari yang sama menghasilkan penempatan dan satu jenis keluar, dengan satu hari produksi dan tanpa stok akhir. Penggunaan hari masuk dan keluar secara inklusif untuk biaya produksi menjelaskan mengapa head-days pengiriman bisa mencakup sapi yang sudah keluar dari stok pada akhir hari.

| Periode | Stok awal | Penempatan | Penjualan | Mortalitas | Stok akhir |
|---|---:|---:|---:|---:|---:|
| 2024 | 0 | 9.569 | 6.554 | 128 | 2.887 |
| 2025 | 2.887 | 5.431 | 8.206 | 112 | 0 |
| Seluruh kohor | 0 | 15.000 | 14.760 | 240 | 0 |

Saldo bulanan tertinggi adalah 5.988 ekor pada 31 Mei 2025. Pada tanggal akhir bulan, 473 penjualan dan 9 mortalitas langsung mengurangi stok, dan 1.184 penempatan masuk dalam arus bulan tersebut. Setelah 297 penjualan terakhir pada Desember 2025, saldo akhir kohor adalah nol. Saldo nol berlaku untuk kohor tercatat. Hitung fisik yard tidak tersedia. Identitas rekonsiliasi adalah **stok awal + penempatan − penjualan − mortalitas = stok akhir**, diuji pada individu, bulan, lot dan pen tercatat.

## WIP dan pelepasan biaya

1. **Basis pembelian dan veteriner bertanggal.** Ambil nilai perolehan tepat satu kali pada tanggal masuk. Tambahkan tindakan veteriner teramati pada tanggal tindakan. Hasilnya adalah bagian WIP dan pelepasan biaya yang didukung tanggal sumber.
2. **Estimasi biaya produksi.** Alokasikan total biaya pengiriman lot–pen pada setiap tanggal kepada sapi aktif pada tanggal itu dengan porsi per ekor yang sama. Pembagian memakai sen CAD. Sisa sen diberikan satu per satu berdasarkan urutan ID sapi aktif sehingga biaya harian kembali tepat ke total pengiriman. Tambahkan yardage CAD 0,60 per hari produksi inklusif, sesuai parameter yang cocok dengan closeout. Model tidak memakai bobot akhir, DMI lifetime atau biaya lifetime untuk menentukan alokasi harian.
3. **Pelepasan dan penyesuaian.** Pada bulan keluar, seluruh akumulasi sampai dengan hari keluar dilepas satu kali menurut jenis keluar. `estimated_sold_cogs_cents` dan `estimated_mortality_loss_cents` adalah dua arus terpisah. `adjustments_applied_cents` bernilai nol karena model tidak menerapkan penyesuaian. Kolom `actual_*` kosong ketika ada sapi yang memenuhi syarat dan data aktual lengkap belum tersedia. Nol struktural berlaku bila jumlah sapi yang memenuhi syarat adalah nol.
4. **Komponen tanpa tanggal.** CAD 270.000,00 biaya dasar veteriner ditahan di `lifetime_closeout_audit`, di luar pengeluaran bulanan, WIP, dan pelepasan biaya. Selisih biaya pakan lifetime terhadap estimasi distribusi pengiriman hanya dapat dihitung setelah closeout. Tidak ada penyesuaian bulanan untuk selisih ini. Overhead di luar yardage, depresiasi, freight, pembiayaan, serta biaya dan pemulihan atas kematian tidak teridentifikasi sebagai komponen bertanggal.

Persamaan berlaku untuk basis parsial dan estimasi **WIP awal + pembelian + biaya produksi + penyesuaian yang diterapkan − biaya penjualan yang dilepas − biaya mortalitas yang dilepas = WIP akhir**. Basis parsial sudah termasuk di dalam estimasi, sehingga kedua basis disajikan sebagai alternatif ukuran. Rekonsiliasi memakai integer sen CAD.

| Jembatan estimasi (CAD) | 2024 | 2025 |
|---|---:|---:|
| WIP awal | 0,00 | 6.213.604,75 |
| Pembelian | 18.173.857,29 | 10.931.249,30 |
| Veteriner bertanggal | 80.713,51 | 62.481,33 |
| Alokasi pakan harian | 5.250.743,21 | 4.968.799,71 |
| Akrual yardage | 831.747,00 | 758.603,40 |
| Penyesuaian yang diterapkan | 0,00 | 0,00 |
| Dikurangi estimasi COGS terjual | 17.847.695,29 | 22.684.110,91 |
| Dikurangi estimasi pelepasan mortalitas | 275.760,97 | 250.627,58 |
| **WIP akhir estimasi** | **6.213.604,75** | **0,00** |
| WIP akhir pada basis parsial | 5.366.705,41 | 0,00 |
| Harga perolehan pada stok akhir | 5.348.959,27 | 0,00 |

Untuk seluruh kohor, estimasi pelepasan berjumlah CAD 40.531.806,20 untuk penjualan dan CAD 526.388,55 untuk mortalitas. Keduanya berjumlah CAD 41.058.194,75. Tambahkan CAD 270.000,00 biaya veteriner dasar yang tidak diberi tanggal dan CAD 0,57 selisih pakan lifetime untuk merekonsiliasi ke total closeout CAD 41.328.195,32. Total closeout per outcome adalah CAD 40.816.000,68 untuk penjualan dan CAD 512.194,64 untuk mortalitas. Selisih pakan bersih CAD 0,57 menutupi redistribusi yang lebih besar. Dalam kelompok penjualan, biaya pakan lifetime melebihi estimasi alokasi pengiriman sebesar CAD 18.514,48, sedangkan untuk mortalitas biaya pakan lifetime lebih rendah CAD 18.513,91. Dengan demikian, kecocokan total kohor tidak memvalidasi alokasi individu, COGS, atau write-off aktual. Notebook menyajikan perbandingan retrospektif per tahun keluar dan outcome untuk audit.

## Valuasi pasar sapi

Harga perolehan pada stok akhir, WIP akumulasi, nilai pasar estimasi, dan indikasi nilai pasar dikurangi biaya penjualan tersedia sebagai ukuran terpisah. Estimasi liveweight memakai penimbangan pada hari tutup jika ada, atau membawa bobot terakhir sebelum tutup sampai usia 45 hari secara default. Bobot setelah cut-off dan bobot terlalu lama tidak dipakai. Dari 86.388 sapi-bulan dengan stok akhir, 2.128 memiliki penimbangan pada tanggal tutup, 69.651 memakai bobot sebelumnya, dan 14.609 tidak memenuhi ambang usia bobot. Pada November 2025, seluruh 297 sapi dalam stok akhir memiliki timbangan lebih lama dari 45 hari. Cakupan bobot perlu dibaca bersama cakupan harga.

| Kandidat sumber 2024–2025 | Kesesuaian dan keputusan |
|---|---|
| Alberta Weekly Livestock Market Review | Arsip 2024 dan 2025 tersedia. Contoh PDF memiliki minggu observasi dan terbit, harga Canfax per cwt, serta rentang harga lelang menurut jenis kelamin dan kelas bobot. Pilih transaksi live dan pasar relevan, cek kesenjangan seri, hak atas komponen Canfax dan izin redistribusi sebelum impor. [Arsip resmi](https://www.alberta.ca/weekly-livestock-and-crop-market-reviews) · [Contoh 2024](https://open.alberta.ca/dataset/38b723e8-db70-4532-8d85-d5feae64e950/resource/3c25431a-e4ca-4657-b327-6ab24c7c0403/download/agi-itrb-weekly-livestock-market-review-2024-06-28.pdf) · [Contoh 2025](https://open.alberta.ca/dataset/ddd55b15-02b0-475b-affc-e38e8c690bbc/resource/7d47d892-5f39-41ce-a92d-ad03b0a6a6f3/download/agi-tedab-weekly-livestock-market-review-2025-07-11.pdf) |
| Perlich Bros., Lethbridge | Contoh laporan bertanggal di Southern Alberta mencantumkan yearling steer dan heifer, kelompok bobot lb, harga per cwt, rentang dan jumlah ekor. Cocok sebagai kandidat pembanding feeder lokal. Kelengkapan arsip dan hak pakai ulang untuk laporan 2024–2025 belum terverifikasi. [Contoh laporan 6 Maret 2025](https://api.clix.auction/uploads/document/1oqcFIB11741373298HyI7FePm.pdf) |
| Canfax | Kandidat live fed dan feeder setelah verifikasi basis transaksi, geografi, kelas, tanggal publikasi, dan hak publikasi. Ketentuan Canfax membatasi penyimpanan dan redistribusi informasi pasar dari layanan anggota. [Metode](https://canfax.ca/media/attachments/2022/08/25/fed-and-feeder-prices.pdf) · [Ketentuan](https://canfax.ca/terms-of-service.html) |
| Statistics Canada 32-10-0077-01 | Seri bulanan provinsi dengan lisensi pemerintah terbuka. Dapat dipertimbangkan untuk pembanding regional, tetapi grain provinsi dan kategori agregat belum mendukung penilaian Southern Alberta per jenis kelamin dan kelompok bobot. Tanggal rilis dan revisi juga perlu ditelusuri sebelum penggunaan as-of. [Tabel](https://www150.statcan.gc.ca/t1/tbl1/en/tv.action?pid=3210007701) · [Lisensi dan metadata](https://open.canada.ca/data/en/dataset/d5614095-e77a-4cb4-a5e6-9f8bff067c9f) |

Belum ada seri yang memenuhi kecocokan data dan hak penggunaan untuk valuasi penuh kohor. Tidak ada harga pasar yang diimpor. Isi `QUOTE_ROWS` di notebook, atau berikan `quote_rows` ke `build_monthly_inventory`, setelah meninjau sumber dan lisensi. Satu baris adalah satu asumsi harga untuk tanggal akhir bulan `month_end`, `sex`, dan pita `[min_live_kg, max_live_kg)` yang tidak tumpang tindih. Lengkapi `quote_id, animal_class, geography, price, unit, reference, usage_rights, observed_on, published_on` serta `costs_to_sell_cad_per_head` jika tersedia. Kelas adalah label referensi yang dipilih untuk pita bobot dan jenis kelamin. Sumber belum memiliki kelas pemasaran feeder/fed berwaktu per sapi, sehingga kesesuaian kelas dan geografi perlu diputuskan saat menyusun asumsi. Harga dari observasi dan rilis setelah tanggal tutup ditolak. `CAD/cwt live` dibagi 45,359237 untuk memperoleh `CAD/kg live`. Harga karkas `CAD/kg HCW` tidak memenuhi basis harga liveweight.

Nilai indikatif adalah bobot estimasi dikali harga liveweight yang cocok. Kurangi biaya penjualan per ekor hanya jika tersedia. Jika satu atau lebih sapi dalam stok tidak memiliki estimasi, total kelompok tetap kosong dan jumlah sapi yang dinilai tersedia. Hanya periode dengan stok nol memiliki nilai nol tanpa harga. WIP pada biaya produksi digunakan untuk manajemen. Jika IFRS berlaku, IAS 41 umumnya memakai nilai wajar dikurangi biaya untuk menjual untuk aset biologis yang relevan. Jika ASPE Kanada berlaku, Section 3041 membedakan persediaan agrikultur dari aset biologis produktif, dan opsi model biaya atau nilai realisasi neto untuk persediaan mengikuti kondisi yang berlaku. Indikasi pasar dalam paket belum mendukung pengukuran formal ataupun pemilihan kebijakan akuntansi. [IAS 41](https://www.ifrs.org/issued-standards/list-of-standards/ias-41-agriculture/) · [CPA Canada Section 3041](https://www.cpacanada.ca/-/media/site/operational/rg-research-guidance-and-support/docs/02452-rg-aspe-briefing-section-3041-agriculture-june-2020.pdf)

## Persediaan pakan gudang

| Input gudang | Ketersediaan |
|---|---|
| Saldo awal fisik dan nilai awal | Tidak ada per bahan, batch, gudang atau bin. |
| Penerimaan, pembelian pemasok dan landed cost | Tidak ada dokumen penerimaan, purchase order, invoice, retur, freight atau landed cost per batch. |
| Pengeluaran gudang | Ada pengiriman pakan ke lot dan pen. ID dokumen issue, asal bin, bahan spesifik/batch dan proses pencampuran gudang tidak tersedia. |
| Penyesuaian fisik dan saldo akhir | Tidak ada stock count, waste, shrink, retur, transfer lokasi, atau saldo akhir. |
| Unit cost dan kebijakan valuasi | Tersedia nominal pengiriman dan komponen ransum. Harga barang masuk, biaya per batch dan metode FIFO atau weighted average gudang tidak tersedia. |

Yang dapat dilaporkan dari sumber adalah **38.833.509,03 kg as-fed**, **28.544.013,42 kg bahan kering**, dan **CAD 10.219.542,92** nilai pengiriman, dengan 2.650.584 head-days pada pengiriman tercatat. Pengiriman ke pen tidak membuktikan issue dari gudang, konsumsi, atau saldo fisik. Saldo gudang dan nilai gudang dibiarkan tidak tersedia.

Usulan grain ledger adalah satu baris per pergerakan, bahan, batch, dan lokasi stok. Setiap transfer memiliki dua kaki yang saling mereferensikan.

| Kelompok | Kolom yang diusulkan |
|---|---|
| Identitas dan waktu | `movement_id`, `effective_date`, `posted_at`, `warehouse_id`, `bin_id`, `ingredient_id`, `inventory_batch_id`, `movement_type` |
| Kuantitas | `quantity_signed_as_fed_kg`, `dry_matter_fraction`, `quantity_signed_dm_kg`, `original_quantity`, `original_unit` |
| Nilai | `unit_cost_cad_per_as_fed_kg`, `landed_cost_cad`, `inventory_value_signed_cad`, `valuation_method` |
| Jejak audit | `source_document_id`, `source_line_id`, `supplier_id`, `transfer_id`, `reversal_for_movement_id`, `adjustment_reason`, `lot_id`, `pen_id`, `feed_delivery_reference` |

Jenis pergerakan mencakup opening, receipt, issue, supplier return, transfer in/out, dan count adjustment atau write-off. Hubungkan pengiriman ke dokumen issue atau batch pencampuran sebelum menggabungkan fakta. Rekonsiliasi kuantitas dan nilai awal, pergerakan, dan stok akhir untuk tiap bahan dan lokasi. Bandingkan saldo buku dengan stock count dan GL, serta dokumentasikan kebijakan cutoff dan konversi DM.

## Ekspor dan verifikasi

`build_monthly_inventory` menghasilkan satu sumber Pandas tervalidasi untuk notebook dan ekspor. `write_build` menulis tabel berikut sebagai CSV beserta manifest skema, hash dan rekonsiliasi. Tabel baseline 2A tetap menggunakan perintah build yang sudah ada.

| Tabel | Grain dan penggunaan |
|---|---|
| `animal_month` | ID sapi × akhir bulan apabila ada aktivitas produksi pada bulan tersebut. Gunakan penanda `closing_head=1` untuk snapshot stok. Kolom `exit_date` dan `exit_type` baru tampil pada bulan keluar. |
| `monthly_yard`, `monthly_lot`, `monthly_recorded_pen` | Saldo dan arus bulanan di tingkat yard, lot, dan pen yang tercatat. Pilih grain sesuai laporan. |
| `annual_yard` | Stok awal pertama, penjumlahan arus, serta saldo akhir bulan terakhir per tahun kalender. |
| `monthly_feed_delivery` | Bulan × lot × pen dengan pengiriman tercatat. |
| `lifetime_closeout_audit` | Satu baris per sapi keluar, untuk perbandingan lifetime retrospektif dan komponen tanpa tanggal. |
| `market_quote_assumptions` | Satu baris per ID asumsi harga, dengan sumber dan hak penggunaan yang diisikan. Kosong secara default. |

Impor ID sebagai teks, tanggal sebagai tanggal ISO, dan nominal `*_cents` sebagai sen CAD. Pertahankan sel kosong. Jumlahkan arus pada rentang bulan, ambil saldo pembuka dari bulan pertama dan saldo penutup dari bulan terakhir. Untuk filter yang menghitung ulang dari `animal_month`, publikasikan total pasar hanya jika jumlah sapi yang berhasil dinilai sama dengan stok akhir pada filter yang sama. Hindari penjumlahan lintas grain atau memasukkan tabel audit lifetime kembali ke arus WIP.

```sh
python -m pip install -e '.[notebook]'
python -W error -m feedlot_analytics.cli build \
  --weather-snapshot phase2a/weather/era5-20261121T143547299379Z-fd9571517552 \
  --output work/phase2b45-baseline
python -W error -m unittest discover -s tests -v
python -m nbconvert --to notebook --execute notebooks/04b_monthly_inventory_wip.ipynb \
  --output-dir work --output 04b_monthly_inventory_wip.executed.ipynb --ExecutePreprocessor.timeout=240
```

Sebanyak **661 kontrol baseline** dan **704 tanggal cuaca** lolos. **49 kontrol inventaris** memverifikasi cakupan individu, head-days dan biaya pengiriman, kesinambungan saldo, transaksi bulanan, rekonsiliasi saldo tahunan, dan perbandingan pelepasan dengan biaya closeout. Pelepasan setiap sapi hanya muncul pada bulan keluarnya, sesuai outcome. Saldo akhir Desember 2024 sama dengan saldo awal 2025.

Pada Python 3.12.14, **87 tes lulus**, termasuk 13 tes baru, tanpa kegagalan, error, atau skip. Build dasar menghasilkan 11 CSV dan tiga JSON yang identik byte demi byte dengan build commit awal `353bfeb`. Notebook baru menjalankan lima sel kode dan menghasilkan satu grafik. Notebook skenario sebelumnya menjalankan sembilan sel kode dan menghasilkan empat grafik. Dua replay skenario menghasilkan 18 output tampilan identik. Dua build inventaris juga menghasilkan berkas ekspor yang identik.

## Sebelum Phase 2B-5

1. Dapatkan ledger WIP dan GL bertanggal, sistem subledger invoice pembelian dan settlement, tarif yardage efektif, tanggal biaya veteriner dasar, serta jurnal penjualan, kematian, dan penyesuaian. Cocokkan dengan saldo fisik sapi dan mutasi pen.
2. Dapatkan seri harga live bertanggal dan berizin untuk kelas feeder/fed yang sesuai, biaya jual, serta data timbang yang lebih rapat atau metode estimasi yang divalidasi. Tentukan kerangka akuntansi sebelum menerbitkan ukuran formal.
3. Mulai ledger gudang dengan opening count per lokasi dan batch. Hubungkan receipt, issue, retur dan transfer ke dokumen, lalu rekonsiliasi ke stock count dan GL.
4. Uji parity filter dan tipe data pada Excel, Power BI, Tableau dan HTML dengan memisahkan saldo, arus, nilai estimasi dan ketersediaan pada tanggal laporan.
