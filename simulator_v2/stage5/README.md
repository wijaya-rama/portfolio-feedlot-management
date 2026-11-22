# Simulator V2 · Stage 5

Stage 5 menjalankan kandidat `stage5-candidate.1` pada 12 sapi sintetis, memakai baseline operasional dan kebijakan biaya yang diterima pada Stage 3.5 dan 4. Dataset lama tetap terkunci. Kandidat menambah model pertumbuhan berbasis persediaan nutrien dan dua jalur cuaca. Skenario ini menguji perangkat lunak dan asumsi model. Angkanya berasal dari simulasi.

| Dokumen | Isi |
|---|---|
| [Telaah dan provenance](REVIEW.md) | Referensi, asumsi biologi, formulasi, kesehatan, karkas dan harga |
| [Cuaca](WEATHER.md) | Sumber, cakupan, offset, ketersediaan dan fallback |
| [Hasil kandidat](RESULTS.md) | Perbandingan versi, sensitivitas, kontrol lintas tahap dan batas bukti |
| [Protokol evaluasi](EVALUATION.md) | Evaluasi tiket timbang yang dibekukan sebelum pilot |
| [Handoff Stage 6](STAGE6_HANDOFF.md) | Kapasitas, rencana pengukuran, checklist dan prasyarat pilot |

## Reproduksi

Dari root repositori dengan Python 3.11+ dan zona IANA Edmonton. Pin PyArrow Stage 1 juga dipakai untuk Stage 5.

```sh
python -m venv work/stage5-venv
work/stage5-venv/bin/python -m pip install -e . -r simulator_v2/stage1/requirements.txt
work/stage5-venv/bin/python -m unittest discover -s simulator_v2/stage5/tests -v
PYTHONHASHSEED=1 work/stage5-venv/bin/python -m simulator_v2.stage5 --output work/stage5-replay-a
PYTHONHASHSEED=2 work/stage5-venv/bin/python -m simulator_v2.stage5 --output work/stage5-replay-b
cmp work/stage5-replay-a/hashes.json work/stage5-replay-b/hashes.json
```

Build bersifat atomik dan memerlukan direktori baru. `run_manifest.json` mencatat timestamp, versi, runtime dan hash sumber. `hashes.json` mencakup baris kanonik Parquet dan file bukti. Konfigurasi [kalibrasi](calibration.json), [pilot](pilot.json) dan [evaluasi](evaluation.json) dipatok di manifest. Versi kode Stage 1–4 menjalankan jalur yang sudah diterima bila opsi kandidat tidak diberikan.

## Data bukti

- `operational_growth.parquet` memuat langkah pertumbuhan yang menghitung tiket timbang sintetis dan keputusan. `retrospective_growth.parquet` me-replay alokasi fisik yang direkonsiliasi dengan sumber cuaca per segmen. Kedua tabel memakai kg, gram DM, MJ ME dan kg CP. Buat agregat per `weather_kind` dan jangan menjumlahkan kedua jalur menjadi satu.
- `operational_nutrient_inputs.parquet` dan `retrospective_nutrient_inputs.parquet` menautkan langkah ke alokasi pada jalur masing-masing. Alokasi fisik memakai versi settlement aktif dalam `reconciled_allocations.parquet`. `feed_deliveries.parquet` memuat pool AF, DM, nutrien dan nilai.
- `scale_observations.parquet` memuat tiket timbang sintetis dan revisinya. Tabel keputusan menautkan estimasi bobot, rencana dan sumber yang terlihat di setiap cutoff. `posted_journal.parquet` memuat satu buku posting kandidat.
- `experiments.json` memuat outcome per sapi, statistik kelompok, arus AF dan DM, serta nilai sen CAD per skenario. Skenario komparatif memiliki basis pembanding dan hash konfigurasi.
- `finance.json` memuat close asli dan restated, invoice routes, refusal recovery dan nilai pasar non-posting. `validation.json` memuat kontrol kandidat dan intervensi. `regression.json` memuat verifikasi baseline dan hasil tes.
- `weather.json`, `backtest_fixture.json`, dan `pilot_capacity.json` mendokumentasikan cakupan, diagnostik resolusi timbang, dan proyeksi aritmetika kapasitas. [Indeks bukti](evidence/hashes.json)
