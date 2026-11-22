# Simulator V2 · Tahap 1

Ledger sintetis ini merekonstruksi status setiap sapi dan posisi yard pada dua cutoff. Ekspor bertipe Parquet berisi master, ledger mentah, event efektif, interval lokasi, status per sapi, serta SOH yard, lokasi dan lot. Contoh hitungan tangan dan rincian kolom tersedia di [timeline fixture](FIXTURE_TIMELINE.md) dan [kamus data](DATA_DICTIONARY.md).

## Modul

| Modul | Tanggung jawab |
|---|---|
| `model.py`, `provenance.py` | Konfigurasi, zona bisnis, kontrak bertipe, ID stabil dan encoding kanonik |
| `ledger.py`, `validation.py` | Ingest batch atomik per proses, identitas dan FK, idempotensi, rantai koreksi dan laporan pengecualian |
| `replay.py` | As-of dua cutoff, versi kapasitas, status per sapi dan interval okupansi |
| `soh.py` | Jembatan harian dan bulanan, tie-out yard/lokasi/lot, animal-days |
| `snapshots.py`, `export.py` | Publikasi immutable, revisi dengan persetujuan eksplisit, Parquet dan baca ulang ledger terverifikasi |
| `fixture.py`, `expected.py`, `__main__.py` | Skenario 12 ekor, ekspektasi manual, CLI dan manifest |
| `tests/` | Uji integritas, temporal, restatement, replay ekspor dan cold run |

## Menjalankan dan memeriksa

Jalankan dari root repositori dengan Python 3.11+, basis data zona IANA `America/Edmonton` dan PyArrow sesuai versi di bawah. Instalasi PyArrow dapat memakai wheel lokal. Build, replay, dan tes berjalan lokal. Dua output harus memakai direktori baru.

```sh
python -m venv work/stage1-venv
work/stage1-venv/bin/python -m pip install -r simulator_v2/stage1/requirements.txt
work/stage1-venv/bin/python -m unittest discover -s simulator_v2/stage1/tests -v
PYTHONHASHSEED=1 work/stage1-venv/bin/python -m simulator_v2.stage1 --seed 42 --output work/stage1-a
PYTHONHASHSEED=2 work/stage1-venv/bin/python -m simulator_v2.stage1 --seed 42 --output work/stage1-b
diff -r --exclude=run_manifest.json work/stage1-a work/stage1-b
```

Manifest memuat waktu build, commit, hash kode/config dan runtime Python, Arrow dan TZif. `hashes.json` memuat SHA-256 baris kanonik dan file, serta path dan ID snapshot. Timestamp build berada di manifest. Parquet byte identik pada runtime yang sama. Bandingkan hash kanonik bila mengganti versi penulis Parquet. Contoh keluaran seed 42 tersimpan di [validation.json](evidence/validation.json) dan [hashes.json](evidence/hashes.json). Jika validasi gagal, CLI mengembalikan status 1 dan laporan JSON ke stderr. Simpan stderr ke file untuk audit kegagalan.

```python
from datetime import date, datetime, timezone
from simulator_v2.stage1.export import load_ledger
from simulator_v2.stage1.replay import replay
from simulator_v2.stage1.soh import calculate_soh

ledger = load_ledger("work/stage1-a")
closing = datetime(2024, 1, 1, 7, tzinfo=timezone.utc)
state = replay(ledger, effective_before=closing, knowledge_cutoff=closing)
_, daily, monthly, checks = calculate_soh(ledger, date(2023, 12, 31), date(2023, 12, 31), closing)
```

`replay` melaporkan transisi yang ditolak dan melewatinya saat diagnosis. Periksa `checks` sebelum memakai hasil. `SnapshotStore.publish` menghalangi publikasi jika ada error. Lokasi master diterapkan sebelum event pada instan UTC yang sama. Urutan event memakai `(effective_at, sequence, event_id)`.

## Asumsi fixture

- Saldo awal dua ekor berasal dari dua event opening eksplisit pada 30 Desember 2023. Keduanya sudah ada di kandang A saat horizon dibuka. Identitas, pemasok dan seluruh record berlabel sintetis. Seed mengubah RFID sintetis. Jadwal, penempatan dan jumlah ekor tetap.
- Satu yard terdiri dari kandang A berkapasitas 5, B berkapasitas 4 (turun ke 3 mulai 29 Februari), receiving 3, dan hospital 1. Semua masuk dalam yard SOH. Receipt masuk ke receiving. Rute transfer fixture adalah receiving ke kandang produksi atau hospital, produksi ke kandang produksi lain atau hospital, serta hospital ke produksi. Dua lot dapat berbagi kandang produksi jika `compatibility_group` sama. Kapasitas dicek setelah tiap mutasi dan ketika versi kapasitas mulai berlaku.
- Efektif memakai batas eksklusif dan ketersediaan memakai batas inklusif. Penutupan EOD memakai status sebelum tengah malam Edmonton berikutnya. Mulai periode diberlakukan dari sisi kiri batas itu. Koreksi yang sudah diketahui menyupersesi catatan lama, lalu replay menerapkan cutoff efektif. Pemindahan tanggal efektif dapat mengeluarkan event dari jendela lama. Reversal meniadakan event yang ditaut tanpa menciptakan mutasi fisik baru.
- Publikasi asli dikunci per run dan rentang laporan. Revisi wajib merujuk snapshot periode yang sama dan menyertakan ID, aktor, waktu dan alasan persetujuan. Satu versi mempunyai paling banyak satu penerus. Persetujuan dalam fixture bersifat sintetis. Snapshot awal dan revisi disimpan berdampingan.
- Animal-days menghitung satu ekor per hari di yard atau lot jika aktif kapan pun hari itu, termasuk hari masuk dan keluar. Pada scope lokasi, sapi dapat dihitung di dua lokasi pada hari transfer. Gunakan interval lokasi dan cutoff keputusan untuk menentukan roster pada suatu window.

## Batas Tahap 1 dan handoff

Replay penuh berlangsung di memori dan publikasi memakai direktori lokal. Tahap ini belum menguji throughput pilot atau skala 15.000 ekor, menyediakan layanan otorisasi produksi, atau melakukan pemulihan dari checkpoint. Master lot dan hewan hanya memodelkan registrasi. Hospital hanya memodelkan lokasi. Supplier, receipt, shipment dan alasan kematian dibawa sebagai ID atau metadata sintetis. Bagian bulan di tepi horizon dihitung untuk hari yang tercakup.

Untuk Tahap 2, tetapkan kontrak bobot carry-in dan timbang terima, unit kg, jenis observasi, alat timbang, serta timestamp ukur, posting dan ketersediaan. Ambil roster, lokasi dan exit dari replay atau interval bertaut `snapshot_id`. Pisahkan bobot laten, observasi dan estimasi operasional, dan simpan cutoff pengetahuan pada prediksi serta keputusan. Siapkan baseline timbang terakhir, split rolling-origin, dan uji perubahan input masa depan untuk mencegah kebocoran data. Parameter biologis, kesehatan dan cuaca perlu versi dan sumber yang terpisah.

## Hasil penerimaan

Seed 42 menghasilkan 37 record ledger mentah, 34 mutasi efektif, 576 baris SOH harian dan 32 baris bulanan. Seluruh 49 pemeriksaan fixture lulus, termasuk replay pada 25 batas ketersediaan. Yard merekonsiliasi 2 + 10 − 5 − 2 = 5 ekor dengan 15 transfer internal neto nol dan 338 ekor-hari. Uji Tahap 1 lulus 33/33 dan regresi repositori lulus 87/87. Dua eksekusi generator V1 menghasilkan tujuh CSV yang masing-masing cocok dengan SHA-256 [audit baseline](../00_LEGACY_GENERATOR_AUDIT.md).
