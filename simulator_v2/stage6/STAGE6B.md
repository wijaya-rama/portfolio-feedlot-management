# Stage 6B · Performance hardening dan preflight 24 bulan

Bukti Stage 6A tetap berada pada [commit awal](https://github.com/wijaya-rama/portfolio-feedlot-management/commit/8dfbaa3160dc88a9b673cd0772a2d7813866e5ee) dan [direktori diagnostik terbit](evidence/diagnostic/). Run acuan Stage 6B membangun ulang commit awal pada mesin pengujian dan menghasilkan `hashes.json` yang identik dengan bukti tersebut.

## Kontrak stok

| Ukuran diagnostik Stage 6A | Nilai |
|---|---:|
| Carry-in | 8 |
| Placement | 100 |
| Sale | 64 |
| Mortalitas | 4 |
| Animal-days sekaligus jasa yardage | 4.698 |
| SOH akhir periode 31 Desember 2025 | 52 |
| SOH akhir simulasi 28 Februari 2026 | 40 |

`diagnostics.json` kandidat menulis `stock_reporting.periods[].period_end_soh`, `final_simulation_date` dan `final_simulation_soh`. Gate membandingkan grain yard yang dibaca ulang dari Parquet dengan replay, menguji persamaan stok dan kontinuitas periode, serta mengikat SOH terakhir ke roster aktif pada catatan outcome dan event. Tes menggunakan bukti Stage 6A sebagai fixture untuk angka 52 dan 40.

## Perubahan jalur accounting

- Buku Stage 4 tetap memproses sumber, approval, costing dan route biaya outcome. Setiap jurnal masuk ke bulan pertama tempat periode buku dan availability sama-sama memenuhi cutoff. Ringkasan incremental membawa saldo GL, WIP per sapi dan komponen, release, normal-loss absorption dan clearing. Aktivitas bulan berjalan menghasilkan trial balance dan WIP opening/closing dengan aturan Stage 4. Stage 4 tetap menerima jurnal mentah pada entry point sebelumnya.
- Fingerprint memakai urutan dan byte JSON kanonik semula. Satu encoding per jurnal memasok state SHA-256 bersama selama prefix antarpenutupan identik. Bila fakta yang memenuhi cutoff menyela urutan, state terpecah pada batas visibility dan setiap rangkaian mempertahankan urutannya. Saat dibekukan, masing-masing state memperoleh penutup array yang sama dengan encoding semula. Dua view punya state sendiri dan tidak berbagi jurnal antarversi.
- Snapshot close lama dan revisi tetap terpisah, mengikat prior close, periode, cutoff, fingerprint, dan approval. Koreksi masuk ke bucket periode yang terkena dan saldo berikutnya berasal dari roll-forward. Build lengkap masih memproses kedua buku agar semua jurnal dan identitas versi diterbitkan lengkap.
- SQLite menyimpan input, sumber, parent dan action. Scan urut sumber membaca blob dalam satu cursor dan spool jurnal kumulatif dihapus. Setelah replay FIFO independen selesai, close memakai checkpoint kuantitas dan nilai per layer untuk transaksi dengan availability langsung. Transaksi terlambat tetap memilih replay warehouse Stage 3 ber-cutoff. Parquet mempertahankan ZSTD, partisi bulanan, ukuran row group hingga 8.192, dan publish atomik. Buffer global dibatasi 65.536 baris dan writer mendeteksi append ke partisi yang sudah ditutup.
- Audit disk memproyeksikan kolom yang dipakai pada fakta pertumbuhan dan pakan, membaca batch 8.192, merekonstruksi hash kedua view, serta memeriksa lock, approval, lineage dan pemilihan forecast yang tersedia saat hari bisnis dibuka.

## Konfigurasi dan asumsi

[Konfigurasi 25](configs/preflight-25.json) · [100](configs/preflight-100.json) · [250](configs/preflight-250.json) · [500](configs/preflight-500.json) · [Rencana Stage 5](../stage5/pilot.json)

Konfigurasi berasal dari 60 slot lot berjarak 12 hari, dengan distribusi pembulatan integer proporsional. Kalender memakai America/Edmonton dan mencakup 731 hari bisnis sejak 1 Januari 2024. Skala rencana 1.500 placement, 350 carry-in, dan target akhir 15.000 placement. Jumlah pen dipertahankan pada dua receiving, enam produksi, dan dua hospital. Kapasitas fisik per pen dibulatkan ke atas sesuai skala. Batas perencanaan Stage 5 dan ruang overflow masih memerlukan penerimaan operasional untuk pilot.

- Batas minimum DOF per lot bergilir di 155, 175, dan 195 hari. Eligibility shipment juga memerlukan status produksi, bobot as-of minimal 490 kg dan keputusan draft mingguan. Batas 65% lot dan kapasitas shipment sintetis yang diskalakan memungkinkan pengiriman sebagian. DOF realisasi bisa melewati minimum dengan kelipatan jadwal, kesehatan atau bobot.
- Cohort carry-in menggunakan DOF sebelum 1 Januari, bobot pembukaan sebesar 363 kg + 0,96 kg per DOF, dan WIP CAD 1.580 + CAD 4,10 per DOF dengan dokumen asal sintetis. Carry-out menyimpan lokasi aktif dan WIP.
- Dua window Edmonton 08.00–11.00 dan 15.00–17.00 menghasilkan 10 slot rilis untuk satu hari penuh. Receiving memilih 2–4 hari. Pengadaan berjalan setiap tujuh hari, receipt pertama pada hari ke-5 dan kedua pada hari ke-7. Stok sasaran tiga bahan setara sekitar 119,4 ton AF pada kapasitas desain pilot Stage 5. Kapasitas bin per bahan 105 kg AF per ekor desain dan kapasitas mixer/truck 5 ton AF.
- Jalur operasional memakai fallback musiman dan jalur retrospektif memakai arsip yang tersedia serta fallback berlabel. Bobot, kesehatan, harga, grid, kesalahan timbangan, pembukaan dan kebijakan pengadaan adalah asumsi sintetis untuk latihan throughput dan kontrol.

## Reproduksi

```sh
python -m venv work/stage6b-venv
work/stage6b-venv/bin/python -m pip install -e . -r simulator_v2/stage1/requirements.txt pytest
work/stage6b-venv/bin/python -m simulator_v2.stage6.benchmark_profile \
  --config simulator_v2/stage6/configs/preflight-25.json --seed 171 \
  --output work/preflight-25-171 --metrics work/preflight-25-171-profile.json
work/stage6b-venv/bin/python -m simulator_v2.stage6.benchmarks.collect \
  --work work --output work/preflight-report.json preflight-25-171
work/stage6b-venv/bin/python -m pytest -q tests simulator_v2/stage{1,2,3,3_5,4,5,6}/tests
```

`benchmarks/profile_views.py` mengukur posting dan close per view. Untuk mengukur commit awal, jalankan skrip tersebut dengan path absolut dari checkout commit awal dan `PYTHONPATH` menunjuk ke checkout itu. Untuk perbandingan, gunakan `--comparison-manifest` hanya pada build kandidat dengan konfigurasi dan seed yang sama, lalu jalankan `benchmarks.equivalence`. Opsi itu menahan namespace run sehingga ID turunan lineage dapat dibandingkan langsung. Build normal mengikat `run_id` ke konfigurasi dan hash input kode. Gunakan `benchmarks.lot_month` dengan DuckDB opsional untuk query 12 bulan.

`performance.json` dan profil mencatat peak RSS proses Linux, waktu dinding sebelum rename dan waktu termasuk publish. Timer tahap bersarang memisahkan durasi inclusive dan exclusive. RSS pada akhir tahap adalah high-water mark proses yang sudah dicapai. Tidak ada worker simulator terpisah. Data lengkap disimpan di direktori kerja lokal. Bukti yang ditelusuri Git memuat hitungan, profil, gate dan hash build.

## Profil diagnostik yang sebanding

Mesin Linux x86-64 memakai AMD EPYC 9V74, tiga CPU logis yang terlihat, kuota cgroup 2 vCPU, limit memori 8 GiB, Python 3.12.14 dan PyArrow 19.0.1. Timer memakai satu build per konfigurasi. Beberapa pekerjaan independen berjalan bersamaan dalam kuota yang sama. Profil ini mengukur mesin tersebut. Anggaran pilot Stage 5 menyebut 4 vCPU dan 16 GiB.

| Diagnostik 100 placement dan 99 hari | Stage 6A sebelum | Stage 6B sesudah |
|---|---:|---:|
| Wall, termasuk publish atomik | 51,25 dtk | 34,67 dtk |
| Peak RSS | 502,7 MiB | 261,7 MiB |
| Scheduler, replay dan operasi | 9,25 dtk | 9,17 dtk |
| Kesehatan | 0,048 dtk | 0,046 dtk |
| Pertumbuhan operasional dan retrospektif | 5,01 dtk | 4,93 dtk |
| Feeding | 3,38 dtk | 3,40 dtk |
| Seleksi DM dan aplikasi transaksi FIFO | 0,153 dtk | 0,142 dtk |
| Replay gudang independen setelah simulasi | 0,192 dtk | 0,194 dtk |
| Ekspansi sumber ke action | 7,16 dtk | 7,71 dtk |
| Posting jurnal kedua view | 2,32 dtk | 2,75 dtk |
| Accounting dan seluruh close | 28,73 dtk | 14,02 dtk |
| Posting dan close khusus restatement | 10,58 dtk | 2,85 dtk |
| Delapan panggilan close | 13,92 dtk | 0,069 dtk |
| Serialisasi historis sebelum hashing atau fingerprint incremental | 8,33 dtk | 1,35 dtk |
| Serialisasi Parquet | 3,22 dtk | 3,21 dtk |
| Hash berkas input, artefak, Parquet | 0,044 dtk | 0,084 dtk |
| Audit lintas domain | 10,89 dtk | 10,07 dtk |
| Sumber keuangan | 63.393 | 63.393 |
| Baris jurnal dua sisi as-known | 78.458 | 78.458 |
| Parquet | 33.126.955 byte | 33.237.594 byte |

Wall turun 32%, peak RSS turun 48%, accounting dan close turun 51%, dan posting plus close restated turun 73%. Fungsi close lama mendeserialisasi sejarah berulang, mengelompokkan ulang jurnal untuk WIP, clearing dan trial balance, serta mengenkode array jurnal kumulatif. Waktu close kandidat berasal dari checkpoint yang sudah dibangun selama posting. Indeks periode dan fingerprint kandidat sendiri memakan 1,56 detik secara gabungan. Waktu fase dalam tabel dapat tumpang tindih.

## Ekuivalensi dan perbaikan kontrol

Dengan namespace run ditahan untuk pengujian, 78 tabel diagnostik sama secara semantik. Dari 263 partisi, 243 identik byte. Buffer mengubah batas sebagian row group. Satu jurnal koreksi bergeser dari Desember ke November di `journals_restated` karena partition clock mengikuti `period_routing_at` pada view revisi. Setiap field jurnal itu identik. `journals_as_known` dan `journal_lines` tetap memakai clock posting. Seluruh snapshot finance dan hash jurnal di kedua view sama. Perbandingan mencakup pergerakan, outcome, alokasi terpilih, nilai FIFO, WIP serta release per sapi, settlement, lineage, trial balance dan close. [Perbandingan diagnostik](evidence/stage6b/diagnostic-equivalence.json)

Fixture shortage memberi hasil semantik yang sama termasuk backlog dan koreksi WIP 25 sen. Dua rebuild terkendali pada `PYTHONHASHSEED=107` dan `218` menghasilkan indeks deterministik yang identik. Tes checkpoint membandingkan digest dengan SHA-256 langsung atas array jurnal, termasuk ketersediaan di luar cutoff, partisi nonmonotonik, dan periode interim. Stage 4 menjalankan fixture invoice, reversal dan kontrol loss. Stage 6B menjalankan settlement packer, koreksi yardage dan stok di horizon penuh. [Perbandingan shortage](evidence/stage6b/shortage-equivalence.json) · [Verifikasi regresi](evidence/stage6b/verification.json)

Stage 6A hanya merekonstruksi fingerprint original dari Parquet. Stage 6B merekonstruksi kedua view dan memeriksa lock, approval, relasi ke snapshot original, dan data snapshot terbit. Gate stok kini memisahkan akhir periode dan akhir simulasi. Audit cuaca memverifikasi vintage operasional terhadap cutoff hari bisnis. Writer mendeteksi risiko penimpaan bila fakta datang setelah partisi final ditutup.

## Hasil kalender penuh

Setiap run mencakup 731 hari dan 1.462 window tingkat yard. Setiap view menerbitkan 24 close. Peak inventory berasal dari roster setelah event. Jurnal pada tabel adalah pasangan debit/kredit per view, sedangkan `journal_lines` as-known memiliki dua baris per pasangan.

| Placement | Seed | Carry-in | Sale | Mati | Carry-out | Peak inventory | Animal-days | WIP akhir CAD |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 25 | 42 | 6 | 25 | 1 | 5 | 7 | 4.578 | 10.696,38 |
| 25 | 171 | 6 | 23 | 3 | 5 | 7 | 4.170 | 11.352,25 |
| 100 | 42 | 23 | 82 | 19 | 22 | 27 | 17.127 | 48.566,06 |
| 250 | 42 | 58 | 212 | 44 | 52 | 66 | 43.346 | 114.370,77 |

| Placement / seed | Event ternak | Transaksi gudang | Load berhasil | Alokasi rilis / posting | Sumber finance | Jurnal per view | Parquet MiB |
|---|---:|---:|---:|---:|---:|---:|---:|
| 25 / 42 | 87 | 18.655 | 5.801 | 45.670 / 9.129 | 137.201 | 73.276 | 65,18 |
| 25 / 171 | 87 | 16.936 | 5.228 | 41.578 / 8.311 | 124.661 | 66.644 | 60,42 |
| 100 / 42 | 412 | 29.437 | 9.395 | 170.752 / 34.134 | 333.546 | 194.255 | 171,69 |
| 250 / 42 | 1.087 | 30.430 | 9.726 | 432.120 / 86.379 | 639.486 | 393.124 | 365,46 |

| Placement / seed | Wall dtk | Peak RSS MiB | Accounting dan close dtk | Audit lintas domain dtk | Fingerprint close / hash file dtk |
|---|---:|---:|---:|---:|---:|
| 25 / 42 | 77,18 | 330,41 | 30,88 | 19,31 | 2,57 / 0,14 |
| 25 / 171 | 69,50 | 321,00 | 26,23 | 17,99 | 2,28 / 0,12 |
| 100 / 42 | 200,04 | 425,94 | 76,99 | 56,73 | 6,81 / 0,46 |
| 250 / 42 | 399,47 | 509,19 | 145,67 | 120,42 | 13,47 / 0,86 |

Median DOF sale 178–181 hari. Semua placement terealisasi dan semua carry-out tertaut ke WIP akhir. Empat run mencatat 59 kategori hard gate per run, 20.771.456 assertion, 40 kontrol replay/pergerakan, dan 1.728 kontrol Stage 4. WIP akhir as-known dan restated sama pada tiap run. Delta pada periode awal tetap bisa ditelusuri. [Pengukuran dan validasi per run](evidence/stage6b/preflight-measurements.json)

Pada 250 placement, dua load dibatalkan karena silase kurang pada window sore 31 Januari dan 28 November 2025. Jumlah target silase yang terpengaruh 32,014 kg DM. Audit mengonfirmasi bahwa load tersebut mengikuti jalur shortage dan seluruh persamaan fisik dan ledger lulus. Ini menandai keterbatasan asumsi buffer yang seragam antar bahan. Konfigurasi 500 placement tersedia. Gate audit pada 250 placement sendiri mencapai 120,42 detik, dan proyeksi wall 500 sekitar 688–806 detik pada mesin ini. 250 menjadi ukuran terbesar yang divalidasi. Perluasan ke 500 tidak diperlukan untuk membedakan hasil dari anggaran pilot.

### Query lot-month

DuckDB 2.0.1, satu thread, mengagregasi DM dan sen FIFO untuk satu lot di 12 bulan partisi `accounting_feed_allocations` pada run 250. Pruning membaca 12 dari 24 berkas. Ukuran terkompresi 12 berkas kandidat 3.497.816 byte. Cold memakai lima koneksi baru dan advisory eviction per berkas di Linux. Warm memakai sepuluh pengukuran pada koneksi yang sama setelah warm-up. Cache filesystem cold bersifat best effort.

| Query | Median | P95 |
|---|---:|---:|
| Cold | 3,93 ms | 12,72 ms |
| Warm | 3,21 ms | 3,84 ms |

[Result set, sampel dan query plan](evidence/stage6b/lot-month-250.json)

## Proyeksi pilot 1.500 placement

Proyeksi berasal dari selisih aktual run 100 dan 250 pada 24 periode sama. Skenario Stage 5 memberi 243.650–290.375 animal-days. Volume yang dihasilkan oleh kenaikan workload ialah 2,43–2,89 juta alokasi rilis, 0,49–0,58 juta alokasi posting, 2,98–3,52 juta sumber finance, dan 3,82–4,53 juta jurnal gabungan. Masa pengamatan dan window tetap konstan. Model mengaitkan operasi dengan animal-days, accounting dengan volume sumber, validasi dan Parquet dengan volume fakta, dan fingerprint dengan jumlah jurnal. Hasilnya adalah perkiraan pada mesin terukur untuk menilai anggaran, dengan ketidakpastian paling besar pada memori dan kompresi di luar kisaran observasi.

| Anggaran Stage 5 | Terukur pada 250 | Proyeksi 1.500 pada mesin ini | Anggaran pilot |
|---|---:|---:|---:|
| Wall | 399,47 dtk | 1.923–2.279 dtk | 600 dtk |
| Peak RSS | 0,50 GiB | 1,12–1,26 GiB | 6 GiB |
| Parquet | 0,36 GiB | 1,80–2,14 GiB | 2 GiB |
| Audit lintas domain | 120,42 dtk | 607–720 dtk | 120 dtk untuk rekonsiliasi |
| Accounting dan audit digabung | 266,09 dtk | 1.277–1.513 dtk | 120 dtk untuk rekonsiliasi |
| Fingerprint dan hash berkas | 14,33 dtk | 68,71–81,39 dtk | 45 dtk |

[Proyeksi per skenario dan driver workload](evidence/stage6b/scaling.json) · [Profil sebelum dan sesudah](evidence/stage6b/diagnostic-profiles.json)

Biaya tersisa pada 250 placement berasal dari pembuatan dan pendaftaran sumber finance, dua posting berurutan yang menjaga urutan informasi dan state outcome, serta audit per allocation slice, langkah pertumbuhan, dan baris jurnal. Hash file relatif kecil. Pada ukuran pilot, fingerprint jurnal mendominasi anggaran hashing. Biaya perubahan inkremental atas partisi terbit dan keuntungan paralelisme pada mesin acuan belum terukur. Kecukupan silase dan headroom pada skala pilot masih perlu verifikasi. Kalibrasi penyakit, mortalitas, pertumbuhan, konsumsi, grid karkas dan harga tetap sintetis. Mortalitas 19 dari 123 sapi pada run 100 dan 44 dari 308 pada run 250 memperjelas kebutuhan validasi model.

**Keputusan Stage 6B adalah HOLD untuk 1.500 placement.** Hasil kalender dan accounting lulus pada ukuran yang diuji. Wall clock, audit, dan hashing proyeksi melewati anggaran. Parquet berada di dekat batas. 1.500 placement dan skala rilis 15.000 tetap di luar eksekusi Stage 6B. [Assessment pilot](PILOT_READINESS.md)
