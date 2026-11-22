# Simulator V2 · Stage 3.5

`stage3.5-integrated.1` adalah skenario sintetis 12 ekor yang menjadi masukan resmi Stage 4. Stage 3 memakai bobot masuk ditambah 0,9 kg/hari dan galat timbangan sebagai sumber tiket timbang. Stage 3.5 mengambil bobot dari riwayat biologis berbasis nutrien yang sama dengan riwayat konsumsi. Skenario historis dan bukti [Stage 1](../stage1/evidence), [Stage 2](../stage2/evidence), dan [Stage 3](../stage3/evidence) tersedia pada arsip masing-masing.

## Menjalankan fixture

Gunakan Python 3.11+, zona waktu IANA `America/Edmonton` dan PyArrow yang dipatok Stage 1. Direktori keluaran harus baru. Publikasi bersifat atomik.

```sh
python -m venv work/stage35-venv
work/stage35-venv/bin/python -m pip install -r simulator_v2/stage1/requirements.txt
PYTHONHASHSEED=1 work/stage35-venv/bin/python -m simulator_v2.stage3_5 --seed 42 --output work/stage35-a
PYTHONHASHSEED=2 work/stage35-venv/bin/python -m simulator_v2.stage3_5 --seed 42 --output work/stage35-b
diff -r --exclude=run_manifest.json work/stage35-a work/stage35-b
work/stage35-venv/bin/python -m simulator_v2.stage3_5.baseline --scratch work
work/stage35-venv/bin/python -m unittest discover -s simulator_v2/stage3_5/tests -v
```

[Konfigurasi versi](scenario.json) memakai jadwal, formula, dan master gudang Stage 3. Resolver mengeluarkan kurva timbang referensi lama dari konfigurasi aktif. `inputs.json` dalam paket berisi konfigurasi lengkap setelah resolusi. Manifest mencatat commit generator, versi model, hash input dan file kode. Indeks hash mencatat file dan baris kanonik.

## Model biologis dan timbang

- Model `biology.1+chronological-ledger.1` memakai persamaan Stage 2 dan menerapkan gram DM, kJ dan gram protein dari alokasi Stage 3.5. Ukuran badan dan cuaca memengaruhi kebutuhan pemeliharaan. Penalti kesehatan memengaruhi potensi pertumbuhan dan kebutuhan pemeliharaan. Laju pertumbuhan dapat turun ketika pakan kurang atau muncul penyakit.
- Model `latent-scale.1` mengambil bobot laten pada `measured_at`. Timbang di dalam segmen membaca bobot pada akhir segmen sebelumnya dikurangi pemeliharaan yang telah berlalu, dengan batas bobot model. Timbang tepat pada akhir segmen mendapat kredit nutrien dari segmen yang baru selesai. Jadwal timbang bersifat pasif sehingga penambahan pengukuran tidak memecah langkah pertumbuhan.
- Tiket mengandung bias alat tetap dan galat acak uniform simetris. Presisi alat 0,1 kg dengan pembulatan ke terdekat dan titik tengah ke bilangan genap. Fixture memakai shrink 0 kg. Peluang tiket hilang mengikuti jenis timbang, dengan override pada kasus uji. Timbang terima dan timbang pembukaan memakai bobot masuk laten pada waktu efektif. Timbang penjualan dilakukan sesaat sebelum transisi status pada stempel waktu penjualan yang sama. Pengukuran terjadwal setelah keluar dicatat sebagai batal.
- Variasi biologis memakai stream berbasis identitas `biology-individual` dan `biology-lot`. Timbang memakai stream `scale-missing` dan `scale-error` yang ditentukan per ID sumber. Cacah panggilan dan urutan tiket tidak menggeser stream lainnya. Kejadian klinis, jadwal pergerakan, dan operasi pakan fixture memakai skenario deterministik tanpa pengundian.

| Alat | Bias kg | Rentang galat acak kg |
|---|---:|---:|
| Receiving | +0,2 | ±1,4 |
| Yard | −0,5 | ±2,4 |
| Hospital | +0,5 | ±1,8 |
| Shipping | −0,3 | ±1,6 |

## Urutan waktu dan keputusan

1. Pada 08.00 dan 15.00 Edmonton, roster serta estimator membaca fakta dengan `effective_at` atau `observed_at` **lebih awal** daripada awal window dan `available_at` **paling lambat** pada cutoff. Tiket boleh sudah ditimbang dan diposting sambil menunggu waktu tersedia. Estimator hanya menerima replay Stage 1, dokumen timbang, fakta klinis yang terlihat, dan kebijakan model. Bobot laten dan tiket penjualan tidak menjadi masukan.
2. Model B memproyeksikan bobot dari timbang terakhir yang layak berdasarkan fase, musim dan status klinis yang sudah diketahui. Planner membekukan roster dan bobot. Batas bobot per window dapat mengubah target DM sampai batas fase tercapai. Pen dan resep lalu menentukan issue FIFO kontemporer, mixing, delivery, dan pool bunker.
3. Window akses berlangsung 08.00–11.00 dan 15.00–17.00. Pakan dijadwalkan terlepas tiap 30 menit dan dipecah pada batas fisik atau biologis yang relevan. Kuantitas kumulatif hanya bergantung pada waktu yang telah berlalu. Seekor sapi hanya menerima bagian untuk interval saat ia memiliki akses. Mutasi atau pengeluaran sesudah suatu interval tidak membagi ulang pakan interval tersebut. Interval tanpa akses menambah refusal yang diinferensikan.
4. Refusal dan loss sintetis ditetapkan dari skenario operasi pada dispatch. Dokumen bunk efektif saat window tutup, diposting 15 menit kemudian, dan tersedia 30 menit kemudian. Dokumen awal memakai replay Stage 1 pada cutoff tiket. Jika akses fisik berbeda karena koreksi mutasi, settlement revisi menyimpan induk, approval, dan snapshot keputusan semula. Model laten memakai akses fisik efektif dari versi yang direkonsiliasi. Cutoff dokumen operasional tetap berlaku.
5. Pertumbuhan menerima kredit nutrien di akhir tiap segmen. Pengukuran mengikuti bobot pada instannya sendiri, termasuk bila jatuh di antara dua window. Hasil pengukuran baru berpengaruh ketika tiket tersedia pada cutoff berikutnya. Penjualan atau kematian menutup pertumbuhan dan akses fisik. Yardage tetap dihitung dari keberadaan pada tanggal bisnis Stage 1.
6. Koreksi timbang menjaga tiket induk dan membuat dokumen baru dengan persetujuan. Restatement menunjukkan ID snapshot asli, cutoff pengetahuan yang baru, dan alasannya. Keputusan serta estimasi kontemporer asli tetap diterbitkan dengan ID semula.

`effective_at` adalah waktu peristiwa fisik, `observed_at` adalah waktu pengukuran, `posted_at` adalah waktu pencatatan, dan `available_at` adalah waktu dokumen dapat dipakai. Pada tiket timbang kolom `measured_at` menyatakan waktu pengukuran. Tabel diagnostik `scale_samples` menyediakan `effective_at`, `observed_at` dan tanggal bisnis Edmonton. Cutoff pengetahuan dan versi snapshot terpisah dari waktu fisik.

## Bukti dan diagnostik

| Keluaran | Isi |
|---|---|
| `operational/decision_sources` | Referensi fakta, konfigurasi, resep dan bobot beku per keputusan |
| `diagnostic/scale_samples` | Bobot laten, bias, galat, shrink, presisi dan tautan ke tiket |
| `operational/scale_revisions` dan `restated_*` | Tiket induk, approval, snapshot revisi, dan hasil restatement |
| `feed/timed_releases` | Seluruh rilis fisik per interval, termasuk potensi konsumsi tanpa akses |
| `warehouse/dry_matter_bridges` | Rekonsiliasi DM per snapshot dan lapisan FIFO |
| `backtest/` | Pasangan target dan prediksi, snapshot origin dan forecast Model A/B |
| `diagnostic/latent_backtest_targets` | Bobot laten pembanding pada target diagnostik |
| `livestock/daily_soh` dan `monthly_soh` | Persediaan kepala dan animal-days Stage 1 untuk jejak yardage |

Backtest menggunakan tiket non-entry yang sudah tersedia pada cutoff evaluasi. Origin berada 7, 30, atau 60 hari sebelum pengukuran target. Model A membawa bobot terakhir yang layak. Model B memakai proyeksi dari informasi origin dengan parameter Stage 2 yang sudah ditetapkan. Ambang statistik adalah 30 pasangan, 15 sapi, dan 3 lot per horizon. Untuk fixture ini, cakupan 80%, 40%, dan 10% memenuhi syarat pembentukan prediksi, dengan dukungan yang kurang untuk melaporkan MAE atau bias. Hasil ini hanya menunjukkan perilaku estimasi pada data sintetis.

[Bukti Parquet lengkap](evidence/fixture-seed42.zip) · [Manifest](evidence/run_manifest.json) · [Backtest](evidence/backtest.json) · [Perbandingan](evidence/comparison.json) · [Rekonsiliasi](RECONCILIATION.md) · [Kesiapan Stage 4](STAGE4_HANDOFF.md)
