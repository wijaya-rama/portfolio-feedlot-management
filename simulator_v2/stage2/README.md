# Simulator V2 · Tahap 2

Overlay sintetis 12 ekor pada ledger Stage 1. Mesin biologis memakai replay fisik yang sudah direkonsiliasi. Estimator memakai replay per pasangan cutoff dan menerima fakta timbang serta klinis yang tersedia pada origin. Replay fisik dan setiap snapshot estimasi membawa ID berbasis isi.

## Jalankan dari root repositori

```sh
python -m venv work/stage2-venv
work/stage2-venv/bin/python -m pip install -r simulator_v2/stage1/requirements.txt
work/stage2-venv/bin/python -m unittest discover -s simulator_v2/stage2/tests -v
PYTHONHASHSEED=1 work/stage2-venv/bin/python -m simulator_v2.stage2 --seed 42 --output work/stage2-a
PYTHONHASHSEED=2 work/stage2-venv/bin/python -m simulator_v2.stage2 --seed 42 --output work/stage2-b
diff -r --exclude=run_manifest.json work/stage2-a work/stage2-b
```

Python 3.11+ dan zona IANA `America/Edmonton` diperlukan. Tiap build diterbitkan atomik ke direktori baru. `run_manifest.json` memuat commit, runtime dan waktu build. Gunakan indeks hash untuk membandingkan isi build dan hash baris kanonik untuk membandingkan lintas runtime penulis Parquet.

| Modul | Tanggung jawab |
|---|---|
| `timeline.py` | Replay Stage 1, identitas, interval lokasi dan cutoff |
| `biology.py`, `feed.py` | State laten, maintenance, gain dan adapter DM per segmen akses |
| `health.py` | Episode klinis, integrasi hospital dan kematian serta lineage |
| `observations.py` | Jadwal ukur, variasi alat, data hilang dan koreksi |
| `estimation.py` | Estimasi harian dan forecast A/B, revisi eksplisit, asesmen draft |
| `backtest.py` | Rolling-origin, cakupan, strata dan diagnostik laten |
| `fixture.py`, `scenario.json` | Overlay deterministik, parameter sintetis dan sumber versi |
| `validation.py`, `export.py` | Hard gate, publikasi Parquet, provenance dan laporan |

```python
from datetime import date

from simulator_v2.stage1.fixture import local
from simulator_v2.stage2.fixture import build_fixture

fixture = build_fixture(seed=42)
origin = local("2024-01-19 09:00")
original, estimates = fixture.estimator.estimates(origin, animal_id="SYN-A05")
revised, revised_estimates = fixture.estimator.estimates(
    origin, local("2024-01-19 10:00"),
    revision_reason="SYN-SCALE-CORR-05-JAN14", animal_id="SYN-A05",
)
daily = tuple(fixture.estimator.daily(date(2024, 1, 18), date(2024, 1, 20)))
```

## Contoh SYN-A05

Jam memakai Edmonton. Sapi ini masuk sebagai steer Angus-cross, frame sedang, pada umur pembuka sintetis 367 hari. Lotnya `SYN-LOT-2`. Penerimaan dan penempatan di receiving, pen A, lalu pen B memakai event Stage 1. Transfer fisik pen A ke B terjadi 31 Desember pukul 15.00 dan tersedia 2 Januari pukul 08.00, sehingga replay operasional memakai pen A sebelum transfer tersedia.

| Waktu | Fakta dan dampak |
|---|---|
| 31 Des 08.00 | Bobot laten 448,0 kg. Timbang terima **449,3 kg**, tersedia 08.15. |
| 14 Jan 12.00 | Bobot laten **459,492 kg**, tiket follow-up **459,4 kg**. Pengukuran tersedia 17 Jan pukul 12.15. Pada 14 Jan 12.30, A masih **449,3 kg** dan B **466,007 kg**, dengan bobot laten **459,476 kg**. B lebih tinggi karena ADG prior mengasumsikan gain yang lebih besar dari realisasi selama adaptasi dan paparan cold snap. |
| 17 Jan 12.15 | A berpindah ke **459,4 kg** dan B ke **462,945 kg**, berbasis umur tiket sekitar tiga hari. Laten **462,912 kg**. |
| 19 Jan 09.00 hingga 10.00 | Koreksi menjadi **457,8 kg** memenuhi cutoff 10.00. Snapshot 09.00 tetap memakai tiket 459,4 kg. Contoh restatement eksplisit untuk 09.00 menaut ke snapshot asli dan memakai anchor 457,8 kg. |
| 20–24 Jan | Onset, observasi, perawatan sintetis, reassessment dan pemulihan terjadi di pen B. Pada 21 Jan 12.00, B **461,757 kg** dan laten **467,157 kg**. Model B menggunakan status sakit yang tersedia saat origin untuk seluruh proyeksi dari anchor, sedangkan jalur laten membawa gain yang terjadi sebelum onset. |
| 29 Jan 12.30 | Tiket drafting **473,8 kg** telah tersedia. B **473,825 kg** dan melewati ambang draft skenario 470 kg. Laten **474,975 kg**. |
| 31 Jan 11.00 | Stage 1 mencatat penjualan. Timbang akhir **477,3 kg** diukur 10.55 dan tersedia pukul 13.40. Laten pada exit **477,234 kg**. Setelah exit, pertumbuhan serta estimasi aktif berhenti. |

`SYN-A10` masuk hospital 10 Maret pukul 03.05 MDT, menerima perawatan ulang, pulih dan kembali ke pen B pukul 20.00 MDT. Hewan memiliki ID dan lot yang sama sepanjang episode dan masih aktif pada akhir horizon.

Lihat [asumsi dan persamaan](MODEL_ASSUMPTIONS.md), [kamus data dan lineage](DATA_DICTIONARY.md), [backtest](BACKTEST.md), [validasi](VALIDATION.md), dan [handoff Tahap 3](STAGE3_HANDOFF.md).
