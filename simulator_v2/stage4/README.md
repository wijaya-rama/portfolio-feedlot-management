# Simulator V2 · Stage 4

Kontrol keuangan fixture sintetis 12 sapi menggunakan `stage3.5-integrated.1`, seed 42. Stage 4 memverifikasi arsip operasional dan kunci hash, mereproduksi tabel input akuntansi, lalu menerbitkan jurnal, buku pembantu, penutupan bulanan, dan analisis pasar. Rentang layanan 31 Desember 2023 sampai 11 Maret 2024 menurut kalender America/Edmonton. Periode Desember dan Maret parsial.

## Reproduksi

Jalankan dari root repositori dengan Python 3.11+ dan PyArrow Stage 1. Pilih direktori keluaran baru untuk tiap build.

```sh
python -m venv work/stage4-venv
work/stage4-venv/bin/pip install -r simulator_v2/stage1/requirements.txt -e . pytest
PYTHONHASHSEED=1 work/stage4-venv/bin/python -m simulator_v2.stage4 --seed 42 --output work/stage4-a
PYTHONHASHSEED=2 work/stage4-venv/bin/python -m simulator_v2.stage4 --seed 42 --output work/stage4-b
diff -r --exclude=run_manifest.json work/stage4-a work/stage4-b
work/stage4-venv/bin/python -m simulator_v2.stage4.package work/stage4-a work/stage4-seed42.zip
work/stage4-venv/bin/python -m simulator_v2.stage3_5.baseline --scratch work
PYTHONPATH=src:. work/stage4-venv/bin/python -m pytest -q tests simulator_v2/stage1/tests simulator_v2/stage2/tests simulator_v2/stage3/tests simulator_v2/stage3_5/tests simulator_v2/stage4/tests
```

`run_manifest.json` mencatat waktu build, commit saat build, hash generator, konfigurasi, PyArrow, dan basis zona waktu. Run ID, hash baris kanonik dan file selain manifest bersifat deterministik pada runtime yang sama. Direktori diterbitkan secara atomik setelah gate berhasil. Penerbitan kedua ke target yang sama ditolak.

| Dokumen | Cakupan |
|---|---|
| [Kebijakan](POLICY.md) dan [konfigurasi](policy.json) | Akun, toleransi sintetis, pencatatan, cutoff, dan pembalikan |
| [Kamus data](DATA_DICTIONARY.md) | Grain, kunci, join, unit dan semantik vintage |
| [Rekonsiliasi](RECONCILIATION.md) | Perhitungan manual, dampak invoice, perbandingan penutupan dan sensitivitas |
| [Validasi](VALIDATION.md) | Gate, pengujian negatif dan perlindungan baseline |
| [Handoff Stage 5](STAGE5_HANDOFF.md) | Prasyarat penggunaan dan batas cakupan |

[Paket bukti Parquet](evidence/fixture-seed42.zip) · [Manifest](evidence/run_manifest.json) · [Indeks hash](evidence/hashes.json) · [Rekonsiliasi mesin](evidence/reconciliation.json) · [Sensitivitas](evidence/policy_sensitivity.json) · [Hasil validasi](evidence/validation.json)
