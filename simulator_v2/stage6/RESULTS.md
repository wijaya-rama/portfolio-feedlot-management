# Hasil diagnostik Stage 6A

Konfigurasi `stage6a-diagnostic.1`, seed 42, mencakup 22 November 2025 sampai 28 Februari 2026 dalam kalender Edmonton. Satu build memberi 100 placement di lima lot dan delapan carry-in. Run ini berakhir dengan 40 carry-out, 64 sale dan empat mortalitas. [Konfigurasi](configs/diagnostic.json) · [Diagnostik terstruktur](evidence/diagnostic/diagnostics.json)

## Ternak dan kapasitas

| Periode bisnis | SOH awal | Masuk | Jual | Mati | SOH akhir | Animal-days |
|---|---:|---:|---:|---:|---:|---:|
| 2025-11, sejak tanggal 22 | 8 | 18 | 4 | 0 | 22 | 214 |
| 2025-12 | 22 | 42 | 11 | 1 | 52 | 1.463 |
| 2026-01 | 52 | 21 | 28 | 3 | 42 | 1.825 |
| 2026-02 | 42 | 19 | 21 | 0 | 40 | 1.196 |

Placement berturut-turut sebesar 18, 22, 20, 21, dan 19 ekor pada 22 November, 4 dan 18 Desember, 5 Januari, serta 11 Februari. Puncak SOH akhir hari 73. Ada 134 transfer internal, terdiri dari 98 receiving-to-production, 28 regrouping, dan delapan hospital masuk/keluar. Seluruh transfer bernilai nol pada arus yard. Animal-days direkonsiliasi ke 4.698 charge yardage. Median receiving 2,98 hari elapsed, dengan rentang 1,98–3,98 hari.

| Bulan | Receiving R01 / 26 | Produksi P01 / 37 | Produksi P02 / 37 | Produksi P03 / 37 | Hospital H01 / 4 |
|---|---:|---:|---:|---:|---:|
| 2025-11 | 18 | 22 | 2 | 0 | 0 |
| 2025-12 | 22 | 37 | 17 | 6 | 1 |
| 2026-01 | 21 | 37 | 24 | 10 | 1 |
| 2026-02 | 19 | 33 | 20 | 6 | 0 |

Tabel menunjukkan puncak sesudah event per bulan, termasuk head pembuka. P01 mencapai 37 ekor dua bulan. Strategi pengisian pen terkonsentrasi pada P01 dan masih menyisakan kapasitas di P02/P03. Model satu kelompok kompatibilitas serta kebijakan isi pen ini perlu diuji dengan lot dan headroom pilot.

## Pertumbuhan, kesehatan, dan penimbangan

| Metrik | n | Min | P05 | Median | P95 | Maks |
|---|---:|---:|---:|---:|---:|---:|
| ADG laten, kg/hari elapsed | 108 | 0,30 | 0,77 | 0,99 | 1,22 | 1,29 |
| DMI, kg/hari elapsed | 108 | 6,14 | 7,79 | 8,79 | 9,70 | 9,82 |
| DMI, % BW pada hari dengan paparan ≥95% | 4.530 | 1,35 | 1,86 | 2,26 | 2,34 | 2,41 |
| FCR, kg DM/kg kenaikan laten | 104 | 6,86 | 7,07 | 8,83 | 10,98 | 20,22 |

DMI menurut fase 7,04 kg/hari receiving, 8,28 adaptasi, 9,06 finishing, dan 5,64 hospital. Empat sapi dikeluarkan dari penyebut FCR karena waktu belum tujuh hari atau gain tidak positif. Outlier FCR 20,22 (`SYN-LOT-0002-A00022`) punya ADG 0,30 kg/hari, DMI 6,14 kg/hari, episode severe yang berlanjut ke kronis dan mati pada sekitar 14 hari. Rendahnya gain membuat rasio sensitif pada horizon pendek dan kasus ini memiliki jejak biologis serta alokasi yang direkonsiliasi.

Sebanyak 28 dari 108 sapi memiliki onset, dengan 36 episode dan 32 kejadian deteksi awal. Tujuh sapi mengalami episode berulang. Ada lima transisi kronis, empat admisi hospital, 22 treatment awal, 25 repeat treatment pada 13 episode, dan empat mortalitas. Satu mortalitas memiliki treatment di episode yang sama. Hitungan hospital dan mortalitas mudah berubah dengan satu kejadian pada sampel ini. Mortalitas, rekurensi, dan perbedaan treatment belum terkalibrasi ke populasi lapangan.

Receiving menghasilkan 100 tiket dari 100 percobaan. Follow-up menghasilkan 196 dari 234, hospital 3 dari 4, drafting 66 dari 78, dan timbang sale 47 dari 64. Satu koreksi terlambat menjadi anchor pada satu keputusan berikutnya. Galat tiket follow-up terhadap laten memiliki median −0,58 kg dan P05–P95 sekitar −2,57 hingga 1,70 kg. Hasil ini mengukur sampler sintetis. Protokol evaluasi estimator pada horizon 7/30/60 hari tetap menjadi gerbang sampel yang memadai. [Protokol Stage 5](../stage5/EVALUATION.md)

Operasi memakai 2.376 jam seasonal fallback dan konfigurasi ini tidak memasukkan forecast. Replay retrospektif memakai 311 jam arsip dan 2.065 jam fallback. Interval arsip memakai offset tetap dari sumber yang diterima. Cakupan Desember setelah akhir arsip memakai label musiman. [Metadata dan cakupan](evidence/diagnostic/weather.json)

## Pakan dan gudang

Ada 672 load yang dijalankan. Issue sebesar 68.050,515 kg AF dan 42.717,703 kg DM mengalir ke 64.500,130 kg AF dan 40.490,694 kg DM konsumsi. Selisih AF terdiri dari 450,281 kg mix loss, 258,889 kg distribution loss, 2.790,845 kg refusal, dan 50,370 kg bunk loss. Median per delivery 0,66% mix, 0,37% distribusi dan 4,06% refusal. P95 masing-masing 1,28%, 0,71% dan 6,51%.

Gudang membuka dengan 52.875 kg AF, menerima 67.520,204 kg pada 84 receipt parsial, memindahkan setiap receipt dari dock, meng-issue 68.050,515 kg, dan mencatat 17,500 kg spoilage. Saldo akhir 52.327,189 kg AF, 38.883,669 kg DM, dan CAD 19.648,68. Jembatan DM memasukkan 0,291 kg pembulatan. Saldo awal DM 38.715,076 kg dengan receipt 42.893,875 kg DM dan spoilage 7,870 kg DM. Kapasitas 50.760 kg per bin utama dipakai hingga 36,2% silase, 37,0% barley, dan 37,3% oats sepanjang run. Penutupan menyimpan persediaan relatif besar terhadap kebutuhan 100 placement, mencerminkan stok sasaran berdasarkan kapasitas rancangan dan bukan pola pengadaan lapangan yang sudah dikalibrasi.

Nilai issue CAD 21.593,78 terdiri dari CAD 20.467,56 konsumsi, CAD 966,21 penyerapan normal loss dan CAD 160,01 varians proses. Warehouse spoilage menambah CAD 4,28 varians. Diagnosis utama tidak mengalami shortage atau penundaan karena kapasitas. Kasus terkontrol mencatat keduanya dan menguji hasil buku secara eksak. [Konfigurasi shortage](configs/adversarial-shortage.json)

## Sale, karkas dan settlement

Terdapat 13 shipment, dengan lima lot dikirim melalui beberapa shipment. Median DOF penjualan 48,77 hari, P05–P95 38,27–68,27. Median bobot sale terukur 428,50 kg, P05–P95 418,43–462,92 kg. Untuk 64 sale, median HCW 257,75 kg dan dressing 59,78%, dengan P05–P95 246,60–278,73 kg dan 58,15–61,87%. Grade tercatat pada 57/64 sale. Quality grade sintetis menghasilkan 5 Prime, 26 AAA, 24 AA, 2 A, dan 7 tanpa grade. Yield class terpisah, dengan 5 Y1, 17 Y2, 24 Y3, 6 Y4, 5 Y5 dan 7 tanpa grade. Harga grid sebelum freight bervariasi dari CAD 7,58 hingga CAD 8,30/kg HCW, dengan median CAD 8,00.

DOF dan bobot jual terkonsentrasi oleh horizon diagnostik yang pendek dan threshold yang dipilih untuk menguji draft serta shipment dalam run. Distribusi ini tidak memenuhi tujuan kalibrasi finishing komersial atau frekuensi grade Kanada. Settlement sintetis memungkinkan penjurnalan semua sale walau tiket grade atau tiket timbang akhir kosong.

## Buku, WIP, COGS dan margin

| Tutup as-known | WIP akhir CAD | Pendapatan bersih CAD | COGS CAD | Mortalitas CAD |
|---|---:|---:|---:|---:|
| November 2025 | 38.243,24 | 8.527,66 | 7.791,25 | 0,00 |
| Desember 2025 | 92.147,83 | 22.823,10 | 21.613,02 | 1.777,72 |
| Januari 2026 | 75.677,59 | 55.527,11 | 54.829,30 | 5.747,68 |
| Februari 2026 | 70.498,25 | 42.068,61 | 41.469,70 | 0,00 |

Opening WIP CAD 15.400,00 memiliki sumber eksplisit. Semua 68 exit menjalani release dan memiliki WIP akhir nol. Pada horizon, pendapatan bersih CAD 128.946,48 terhadap COGS CAD 125.703,27 memberi gross margin CAD 3.243,21. Setelah mortality write-off CAD 7.525,40 dan varians CAD 164,29, kontribusi yard model sebesar −CAD 4.446,48. Nilai final seluruh settlement CAD 128.959,02 mencakup CAD 12,54 yang diposting setelah horizon. Delta yardage CAD 0,25 masuk Desember pada buku as-known dan menambah November pada restatement. Trial balance, WIP, warehouse control, receivable, clearing dan continuity lulus di keempat bulan pada kedua pandangan.

## Validasi dan performa

Run final menjalankan 50 kategori gate dengan 923.987 pemeriksaan, di samping 10 kontrol SOH/replay dan 72 pemeriksaan tutup Stage 4. Pemeriksaan input as-of, fingerprint tutup asli, partisi Parquet, FIFO, biaya, nutrien dan outcome menggunakan data yang dibaca ulang dari disk. Uji Stage 6A memberi enam tes terkontrol. Regresi V1 dan Stage 1–5 memberi 229 tes dan 62 subtes lulus. Rebuild arsip Stage 1–3 cocok dengan 120 file terindeks. [Gate](evidence/diagnostic/validation.json)

Dataset Parquet 33.126.955 byte dalam 263 partisi. Partisi terbesar 3.193.100 byte. Empat tabel snapshot lineage berjumlah 184.366 byte. Volume utama terdiri dari 310 movement, 268 health events, 2.188 transaksi gudang, 421 versi tiket timbang, 64 settlement packer, 63.393 sumber finance, 23.342 alokasi fisik individual, 9.324 alokasi posting dan 78.458 baris jurnal as-known. Performa lingkungan memiliki kuota dua CPU dan 8 GiB. Eksekusi utama membutuhkan sekitar 53 detik, termasuk 30,75 detik untuk akuntansi dan close, serta 11,18 detik untuk audit lintas domain. Peak RSS proses 510.388 KiB. [Pengukuran mesin](evidence/diagnostic/performance.json)

Diagnosis ini memakai 4.698 animal-days. Close kumulatif, input lineage, file dan audit akan bertambah dengan animal-days dan jumlah periode. Proyeksi berbasis angka kecil memberi risiko melampaui anggaran 600 detik dalam handoff, sehingga skala pilot mendapat status **HOLD**. [Keputusan pilot](PILOT_READINESS.md)

Dua cold run dengan `PYTHONHASHSEED` 107 dan 218 menghasilkan indeks byte-identik dengan SHA-256 `c48e4dbd11da590633da49a00fb3edf1a7dcff5e9fa2857c548210b5a47be606`. Wall clock proses 53,54 dan 58,64 detik. Peak RSS keduanya sekitar 498–501 MiB. [Cold run](evidence/cold_runs.json) · [Regresi](evidence/regression.json)
