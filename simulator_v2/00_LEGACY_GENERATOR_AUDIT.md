# 00 · Audit generator V1

## Pemulihan dan ruang lingkup

Sumber ditemukan sebagai lampiran tugas `Generate Feedlot Data.py` berukuran **46.074 byte**. Salinan [arsip legacy](legacy/Generate%20Feedlot%20Data.py) identik byte demi byte dengan lampiran. SHA-256 adalah `6cc85041e051bf63ae08fda1c7e90fb5dfa9d16126d73bdad50fa3bc2ddb2fed`. Branch `simulator-v2` dibuat dari tip remote `analysis-rebuild` yang diverifikasi sebagai `07863d44fbd8e98e674e26799fb507c665324efd`, juga head PR #1 yang terlihat dari ref remote. Perbandingan memakai [workbook sumber](../data/Feedlot_Management_StarSchema.xlsx) dan [flat CSV sumber](../data/Feedlot_Management_Flat_15000.csv).

Audit membaca seluruh sumber. Generator memakai Python, NumPy, pandas dan pathlib dari standard library. Sintaks type-hint union memerlukan Python 3.10+ untuk eksekusi normal. Versi runtime historis yang dipakai untuk membuat workbook tidak tercatat. Runtime reproduksi terverifikasi adalah Linux, Python **3.12.14**, NumPy **2.3.5**, pandas **2.2.3**. Pembanding workbook memakai openpyxl **3.1.5**. Generator tidak perlu input data, file cuaca, Excel, atau jaringan. Ia menetapkan RNG NumPy global melalui `np.random.seed(42)` saat proses memuat modul. Urutan pengambilan acak dan urutan tahap menjadi bagian perilakunya.

Contoh menjalankan generator dua kali dari root repositori dengan paket dipasang di lingkungan sementara.

```sh
repo="$(pwd)"
audit_dir="$(mktemp -d)"
python3.12 -m venv "$audit_dir/venv"
"$audit_dir/venv/bin/python" -m pip install numpy==2.3.5 pandas==2.2.3 openpyxl==3.1.5
mkdir "$audit_dir/a" "$audit_dir/b"
for trial in a b; do
  (cd "$audit_dir/$trial" &&
    LC_ALL=C.UTF-8 PYTHONHASHSEED=0 "$audit_dir/venv/bin/python" \
    "$repo/simulator_v2/legacy/Generate Feedlot Data.py" > run.log)
done
diff -rq "$audit_dir/a/output_feedlot_data" "$audit_dir/b/output_feedlot_data"
sha256sum "$audit_dir/a"/output_feedlot_data/*.csv
```

Dua proses segar menghasilkan **122.703 baris** dan tujuh file CSV yang masing-masing identik byte demi byte. File output berada di direktori kerja audit. Workbook dan flat sumber diperiksa read-only. SHA-256 workbook `d2e15c6bda9bdab65612d2ed0a7c808ebb840dd3e8db6f7f134d86d2b92d81c5` dan flat `80e5534d1342343f600b125bd7406864d5ff9636aaaf2a83133c304dbabdc618`.

## Hasil parity

Bandingkan setiap kolom berdasarkan key, urutan baris, urutan kolom dan kesetaraan nilai. Load RFID sebagai teks, tanggal dalam representasi ISO, string dengan NA inference nonaktif, dan CSV numerik memakai float round-trip. Kolom angka ketujuh tabel sama persis setelah parsing, dengan nol delta numerik. Tabel Excel dan CSV tidak memiliki serialisasi file yang sama. Tujuh CSV sumber standalone tidak ada di branch baseline, sehingga uji byte standalone berasal dari dua output replay.

| CSV / sheet | Key | Baris replay dan workbook | Perbedaan nilai mentah | SHA-256 replay |
|---|---|---:|---|---|
| dim_pen / Dim_Pen | pen_id | 40 | 0 | `a781f90ade9a998bc88acb09f49a9416d7dc5f9dfd0202139894db0b024c9345` |
| dim_lot / Dim_Lot | lot_id | 90 | 0 | `c4e1ae61f1c423f46d3d35e72edea896ef14758d3136eedbca990a12bea2620e` |
| dim_cattle / Dim_Cattle | animal_id | 15.000 | 0 | `57c5d7ae50f392f69263b32ea085c96b883b43a02cadab637c45744f54dc40d1` |
| fact_feed_daily / Fact_Feed_Daily | lot_id, pen_id, feed_date | 16.085 | 0 | `79b0a8c09b34ce9b17914fdf74f2836b66fd988b0736d8a6f04d45036bd8189d` |
| fact_scale_weights / Fact_Scale_Weights | weigh_id | 74.268 | 0 | `d259f5707f70d1dfef436794ba72acdd4b2232cdfae703395f6590d41cbe67f7` |
| fact_health_treatments / Fact_Health_Treatments | treatment_id | 2.220 | 0 | `203da9db8b85256d642fdc563ab893bb02bda5762c062d4e9fc48c7ef6ebc328` |
| fact_closeout_sales / Fact_Closeout_Sales | animal_id | 15.000 | 240 grade mortalitas, sentinel `N/A` vs sel kosong | `57b75cd7d2d5266370d45a403ee8f15659994f73bec9415123dbb89e49cf9d9b` |

Urutan, key dan kolom cocok di semua tabel. Penyamaan sentinel grade khusus mortalitas memberi parity nilai seluruh tabel. `Executive_Summary` dan `Data_Dictionary` adalah metadata workbook yang tidak dikeluarkan oleh generator.

### Flat CSV dan sheet Tableau

Source V1 tidak menulis flat. Proyeksi audit memakai relasi many-to-one dan satu baris per sapi. Hasil agregasi treatment lalu pengayaan dimensi menghasilkan 15.000 × 51 dalam urutan sumber. **Rekonstruksi independen menghasilkan byte identik dengan flat CSV Git**. Ini membuktikan resep yang memulihkan isi, dengan provenance proses ekspor historis yang belum tercatat. `Feedlot_Flat_15000` memiliki key, urutan dan nilai bisnis yang sama. Seluruh perbedaan representasi yang ditemukan adalah berikut.

| Cakupan | Sel | Perbedaan |
|---|---:|---|
| Replay closeout terhadap worksheet dan kedua flat | 240 | Grade mortalitas `N/A` menjadi kosong |
| Flat CSV terhadap flat worksheet | 12.900 per kolom | `primary_diagnosis` dan `primary_drug_protocol` untuk sapi tanpa treatment memakai literal `None` di CSV dan kosong di Excel |
| Flat CSV terhadap flat worksheet | 2.100 nilai terisi | `total_vet_cost_cad` terbaca sebagai teks bila inference NA dimatikan pada kolom CSV yang juga punya sel kosong; Excel bertipe numerik. Konversi ke angka dan bandingkan dalam presisi sen |
| Agregasi audit yang dibulatkan ulang vs flat sumber | 26 | Serialisasi `total_vet_cost_cad` berbeda jika jumlah treatment dibulatkan ke sen sebelum menulis. Delta float maksimal 2,85 × 10⁻¹⁴ CAD dan 13 nilai float berbeda setelah parsing. Agregasi tanpa pembulatan mempertahankan byte asli |

Resep proyeksi flat yang diverifikasi dalam lingkungan audit.

1. Baca tujuh CSV replay dengan `keep_default_na=False`, `float_precision="round_trip"` dan `rfid_tag` sebagai string. Mulai dari 25 kolom closeout, join cattle melalui animal_id, lot melalui lot_id, dan pen melalui pen_id. Validasi join one-to-one untuk closeout/cattle dan many-to-one untuk sisanya. Periksa fields bersama kemudian pertahankan satu copy. Pakai urutan kolom [header flat yang diaudit](../data/Feedlot_Management_Flat_15000.csv).
2. Urutkan health dengan treatment_date dan treatment_id. Turunkan jumlah, diagnosis/protokol pertama, flag chronic jika pernah `Chronic / Repeat`, dan label `Treated` atau `Healthy`. Isi diagnosis/protokol tanpa event dengan literal `None`. Gunakan agregat asli `groupby("animal_id").vet_cost_cad.sum()` tanpa membulatkan, dipetakan ke flat dan kosong jika tanpa treatment. Total biaya produksi adalah purchase + allocated feed + yardage + vet closeout yang dibulatkan ke dua desimal.
3. Turunkan tier sesuai batas yang konsisten dengan observasi. ADG memakai ≤1,35 `Low (< 1.35 kg/d)`, ≤1,65 `Target (1.35 - 1.65 kg/d)`, sisanya `High (> 1.65 kg/d)`. FCR memakai `N/A (Mortality)` bagi kematian, ≤6,40 `Superior (< 6.40)`, ≤7,10 `Standard (6.40 - 7.10)`, sisanya `Inefficient (> 7.10)`. Margin memakai <0 `Loss (< $0)`, <250 `Moderate ($0 - $250)`, ≤400 `Strong ($250 - $400)`, sisanya `Superior (> $400)`. Angka tepat 250 tidak muncul di data sehingga pilihan batas itu inferensi. Batas 1,35 dan 6,40 inklusif dalam data walau label mencetak “<”.
4. Ubah grade `N/A` menjadi kosong untuk mortalitas. Pakai `to_csv(index=False)` dengan UTF-8 dan LF untuk serialisasi. Hasil 6.592.909 byte dan SHA-256 sama dengan flat sumber. Untuk perbandingan worksheet gunakan null semantik untuk sentinel grade dan detail tanpa treatment, serta parsing numerik untuk vet.

## Bukti operasional dan finansial

| Area | Hasil audit dan batas interpretasi |
|---|---|
| Identitas, placement dan kapasitas | Nol PK kosong/duplikat, FK orphan dan konflik jalur lot/pen. Seluruh RFID unik 15 digit, urutan sintetis. Ada 15.000 ekor/90 lot/40 pen. Breed individu berbeda dari breed lot pada 1.447 ekor, sex diwarisi dari lot. Arrival 1 Januari 2024–5 Juni 2025. |
| Sale, kematian, kronologi | 14.760 dijual dan 240 mati, dengan satu exit per sapi. Exit 8 Januari 2024–4 Desember 2025. Placed = sold + deaths di semua lot. Satu tanggal jual per lot. Ringkasan workbook dan docstring memberi horizon sampai 31 Desember 2025; operasi replay berakhir 4 Desember. Nol feed pen-day overlapping/overcapacity pada seed audit. |
| Health | 2.220 perawatan pada 2.100 sapi, 120 berulang, 143 record outcome mortalitas. Ada 153 kematian bersamaan/setelah perawatan, termasuk 10 yang treatment terakhir berlabel recovered. Seluruh event masuk dalam umur aktif dan DOF cocok. V1 menggunakan target morbidity 14% dan death 1,6%, memilih kasus tambahan untuk memenuhi kuota. |
| Timbang dan growth | Jumlah per tahap 15.000, 14.882, 14.832, 14.794, 14.760. Tidak ada timbang di luar umur aktif. Timbang masuk dan closeout sale cocok. ADG interval memakai elapsed days, sedangkan cumulative dan lifetime memakai inclusive DOF. Penjualan dijadwalkan berdasarkan DOF lot, meski 11.076 sapi terjual di bawah target finish lot. |
| Feed, ration dan kapasitas | 16.085 lot-pen-days tanpa gap di lifetime lot, 2.650.584 head-days dengan hitungan inklusif. Delivery DM cocok dengan as-fed × fraksi DM dalam 0,005 kg dan tiga komponen DM/biaya menjumlah ke total. Pakan teralokasi minus delivery = −0,40 kg DM dan +CAD 0,57. Masing-masing metrik berselisih >0,01 pada 65 lot, maksimum 0,09 kg dan CAD 0,10, masih dalam rentang pembulatan per sapi. Ini kontrol total cohort, bukan bukti distribusi per hari atau individu. |
| Musim dan harga bahan | Kalender winter 15 November–15 Maret menghasilkan 3.213 baris dari 16.085 delivery. Penalti growth 14–20% ditimbang oleh bagian winter interval, setengah penalti di confinement; aturan DMI menambah 3% confinement dan 6% pen lain pada winter days. Tidak ada input ERA5. Forage CAD 0,14 dan supplement CAD 0,85 per kg DM. Seluruh biaya concentrate cocok dengan CAD 0,36/kg DM, atau CAD 0,414 dari 1 Oktober 2024–31 Maret 2025. Ini kejutan harga yang diprogram untuk komponen concentrate, bukan bukti transaksi gandum/barley. |
| Biaya, carcass dan margin | Purchase cocok dengan kg terima × harga lot. Yardage CAD 0,60 × inclusive DOF. Vet = treatment + CAD 18/head tanpa event dasar bertanggal. Seluruh 14.760 sold bergrade, dengan 1.239 Prime, 10.063 AAA, 3.002 AA dan 456 B/discount. HCW cocok dengan bobot keluar × dressing dalam toleransi rounding, revenue dengan HCW × harga grid. Margin merekonsiliasi revenue dikurangi empat komponen biaya; kematian memakai revenue nol dan seluruh biaya lifetime sebagai kerugian closeout. |

Kontrol domain direrun memakai [audit_sources.py](../analysis_audit/audit_sources.py). Karena tujuh tabel replay cocok setelah perlakuan grade dan flat identik, kontrol key, timeline, formula dan rekonsiliasi yang lolos pada sumber juga mencakup output terkait. Suite baseline **87 tes** lulus. Perbedaan denominator pada dashboard dan jembatan WIP lama didokumentasikan pada fase sebelumnya. [Audit kualitas dan denominator](../analysis_audit/02_DATA_QUALITY_AND_RECONCILIATION.md) · [Fase 2B WIP](../phase2b/04B_MONTHLY_INVENTORY_WIP_FINDINGS.md)

## Temuan prioritas dan tanggapan V2

| Prioritas | Temuan V1 dan bukti | Dampak / rancangan V2 |
|---|---|---|
| P0 · Future leakage | `generate_fact_feed_daily_and_allocate` menghitung bobot harian dari interpolasi entry ke rata-rata bobot keluar sapi yang akhirnya terjual. Alokasi memakai total gain dan midpoint lifetime. Uji terkontrol dengan RNG sama menaikkan 100 kg bobot akhir HW-000002, yang dijual 23 Juni 2024. Itu mengubah 174 baris DMI, mulai 2 Januari 2024. | Delivery dan WIP dini tidak mewakili data as-of. V2 membekukan estimate dan roster saat feeding, lalu mengalokasi pool harian aktual simulasi. |
| P0 · Ledger biaya dan valuasi | Pakan per sapi hanya lifetime. Yardage dan vet dasar dijumlah saat closeout. Tidak ada posting, penerimaan, saldo gudang, invoice atau release per transaksi. Phase 2B menunjukkan redistribusi biaya pakan antara sale dan mortality meski residual agregat CAD 0,57. | Mutasi dan akrual bertanggal, FIFO, WIP, COGS dan write-off per outcome. Pisahkan indikasi pasar dari accumulated cost. |
| P0 · Stok dan pergerakan | Pen/lot statis. Tidak ada receiving, transfer, hospital atau pen return. Lots bergerak sebagai satu unit hingga sell-out. Desain jadwal menjepit arrival akhir dan tidak memeriksa overlap setelah clamp; seed ini lolos, konfigurasi lain berisiko. Semua 15.000 ditutup. | Gunakan replay event dan interval lokasi, uji kapasitas/transfer, partial drafts, opening dan carry-out. |
| P1 · Feed dan warehouse | Komponen forage/concentrate/supplement **menjumlah** secara aritmetis. Tidak ada formula nutrien berbasis batch, PO, receipt, stok, lokasi, mix, refusal atau shrink. DMI dihitung dari bobot, tanpa umpan balik energi ke pertumbuhan. | Pisahkan kebutuhan, delivery, konsumsi, allocation, biaya. Neraca as-fed/DM/sen dari input ke output; lantai/limit nutrisi dan sensitivitas. |
| P1 · Waktu biologis | Penalti kesehatan 15–25% menekan seluruh interval timbang yang memuat treatment, termasuk hari sebelum treatment. Efek health dihitung berbasis event perawatan lengkap dan maksimum per interval, tanpa transit state. Growth selalu positif lewat clamp. Frame direkam tanpa efek growth; penalti winter dihitung dari overlap kalender dan tipe pen. | Simulasi keadaan timesteps dengan onset, pemulihan dan intake/gain berurutan; pisahkan truth, observasi dan estimate. Telaah respons cuaca dan uji backtest. |
| P1 · Mortalitas | Kuota memilih kasus kematian ekstra dan beberapa treatment terakhir tetap recovered. Jika draw fatal melampaui target, daftar status dipotong tetapi tanggal keluar dini tetap dihitung dari semua fatal events; beberapa event fatal dapat bertentangan dengan status sale. Risiko inkonsistensi ini tidak teramati pada seed 42. Estimasi bobot laten kematian memakai ADG tetap 0,85; closeout mengisi bobot/grade dengan sentinel. | Model hazard sintetis bersyarat dan outcome bertanggal. Satu terminal event sah, nullable jika data ukur tidak ada. |
| P1 · Ketahanan dan reproducibility | Seed global dan urutan panggilan mengikat semua domain. Mengubah ukuran cohort, jumlah treatment, atau urutan draw menggeser hasil downstream. ID timbang dan treatment mengikuti urutan setelah sorting. | Gunakan substream RNG, ID stabil, versioning, manifest dan replay. Uji skala/seed variatif untuk constraint. |
| P2 · Penyederhanaan skenario | Harga sintetis halus, flat yardage, phase ration deterministik, breed-driven grade, dan log kalender adalah simplifikasi yang wajar untuk demonstrasi terlabel. Desain V1 menanam korelasi tersebut. Target finish tidak menentukan drafting. | Pertahankan baseline sederhana bila berguna. Gunakan kontrak grid berversi, data rekonsiliasi dan asumsi eksplisit ketika membuat keputusan simulasi. |

Batas audit adalah satu versi sumber yang dilampirkan, satu baseline workbook/CSV, dua replay seed yang sama dan beberapa perturbasi terkontrol. Kesesuaian byte memvalidasi pemulihan data sintetis. Kalibrasi biologis, harga historis, dan aturan yard lapangan memerlukan bukti tambahan. [Aturan bisnis V2](01_V2_BUSINESS_RULES.md) · [Validasi](04_VALIDATION_AND_ACCEPTANCE.md)
