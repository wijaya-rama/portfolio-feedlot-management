# Simulator V2 · Stage 3

Stage 3 menambahkan ledger bahan pakan, FIFO per bahan dan bin, pencampuran, pengiriman ke pen, penyelesaian bunk, alokasi individu, dan skenario pertumbuhan berbasis ledger untuk fixture sintetis 12 ekor. Stage 1 memasok identitas dan interval lokasi. Estimator dan persamaan pertumbuhan Stage 2 dipakai kembali melalui adapter baru. Skenario ini memakai versi `biology.1+feed-ledger.1`.

## Menjalankan build

Jalankan dari root repositori. Gunakan Python 3.11+, zona IANA `America/Edmonton`, dan versi PyArrow pada requirements Stage 1. CLI memvalidasi build dan menerbitkannya secara atomik ke direktori baru.

```sh
python -m venv work/stage3-venv
work/stage3-venv/bin/python -m pip install -r simulator_v2/stage1/requirements.txt
work/stage3-venv/bin/python -m unittest discover -s simulator_v2/stage3/tests -v
PYTHONHASHSEED=1 work/stage3-venv/bin/python -m simulator_v2.stage3 --seed 42 --output work/stage3-a
PYTHONHASHSEED=2 work/stage3-venv/bin/python -m simulator_v2.stage3 --seed 42 --output work/stage3-b
diff -r --exclude=run_manifest.json work/stage3-a work/stage3-b
```

Manifest mencatat versi kebijakan, skema, Stage 1, model, commit, hash input dan kode, runtime, serta waktu build. Indeks hash memuat hash file dan baris kanonik. JSON rekonsiliasi dan kontrol publikasi dapat dibaca tanpa PyArrow. [Paket keluaran seed 42](evidence/fixture-seed42.zip)

| Modul | Tanggung jawab |
|---|---|
| `warehouse.py` | Versi master, PO, penerimaan, stock count, transaksi, lapisan FIFO, invoice delta, dan snapshot dua cutoff |
| `ration.py` | Resep dan substitusi, AF/DM dan nutrien dari issue, kehilangan mixer, serta distribusi lot campuran |
| `allocation.py` | Rencana as-of, input bobot beku, penyelesaian bunk, akses dan alokasi tiga metode |
| `biology.py` | Adapter tanpa umpan balik keputusan dan jejak penggunaan nutrien pada tiap langkah biologis |
| `fixture.py`, `scenario.json` | Jadwal, parameter dan dokumen sintetis fixture 12 ekor |
| `reconciliation.py`, `validation.py`, `export.py` | Jembatan massa dan nilai, basis biaya Stage 4, hard gate dan publikasi Parquet |

## Urutan waktu dan ketersediaan

1. Pada pukul 08.00 dan 15.00 Edmonton, replay Stage 1 memilih event dengan `effective_at < start` dan `available_at <= start`. Estimator B memakai aturan cutoff yang sama untuk timbang, fakta klinis, dan lokasi. Roster awal dan bobot dibekukan di seluruh yard. Kebutuhan DM per pen adalah jumlah target fase per ekor yang dibatasi 1,2% bobot estimasi per window. Dispatch yang diskenariokan eksplisit membawa status `scripted_dispatch`.
2. Formula yang tersedia pada cutoff menentukan gram DM sasaran per bahan dan AF yang direncanakan menggunakan asumsi DM formula. FIFO memilih layer yang tersedia saat issue. Assay batch yang tersedia saat issue menentukan DM aktual. Pada waktu yang sama, urutan logisnya adalah issue → mixing → muat → delivery. Window akses adalah 08.00–11.00 dan 15.00–17.00.
3. Pada akhir window, tiket bunk mencatat refusal dan loss. Fixture memposting tiket 15 menit kemudian dan membuatnya tersedia 30 menit setelah tutup. Replay pada cutoff ketersediaan tiket memberi interval akses awal, termasuk mutasi yang terjadi di dalam window. Bila koreksi Stage 1 mengubah akses, revisi eksplisit menyimpan ID induk, approval dan akses baru dengan snapshot keputusan awal yang sama.
4. Settlement mengurangi refusal dan bunk loss dari pakan yang tiba. Untuk pen tanpa akses, seluruh sisa yang dapat dimakan masuk refusal, dengan selisih dari tiket ditandai sebagai inferensi. Seluruh bunk ditutup setiap window. Hari tanpa akses tetap mengikuti aturan yardage Stage 1 yang menghitung status aktif kapan pun dalam hari.
5. Bagi pool menggunakan skor dikali detik akses. Bobot menggunakan estimasi B dengan jangkar timbang yang masih berlaku, termasuk timbang terima. Jangkar berusia 35 hari atau lebih, jangkar hilang, dan hewan yang belum diketahui pada cutoff memakai 400 kg dan flag yang berbeda. Jika hewan dikenal di pen lain pada cutoff, skor beku tetap ikut hewan. Sisa gram, kJ, gram protein dan sen dibagi deterministik dengan metode sisa terbesar. Semua metode memakai pool yang sama. Metode produksi fixture adalah BW^0,75. Equal-head tetap berbobot durasi.
6. Secara retrospektif, adapter skenario biologis memakai alokasi aktif yang sudah diselesaikan dan dibuktikan. Setiap porsi dikreditkan pada akhir segmen layanan terkait. Waktu tersedia untuk keputusan operasional tetap berasal dari tiket atau approval. Timbang sintetis bersifat independen dari model pertumbuhan. Tiket timbang mengikuti kurva referensi dari bobot masuk dan gain tetap 0,9 kg/hari ditambah galat alat yang tersedia as-of, sedangkan bobot laten mengikuti respons nutrien, health dan cuaca. Hasil biologis dapat berubah tanpa mengubah rencana awal atau tiket timbang skenario.

## Kebijakan provisional

- Massa disimpan sebagai gram AF dan DM. DM dihitung dengan pembulatan ke gram terdekat, dengan setengah dibulatkan naik. Harga PO adalah sen CAD per kg atau ton AF. Layer menggabungkan nilai komoditas dan freight inbound. Issue parsial mengikuti nilai yang tersisa pada layer dan meninggalkan pecahan sen bersama sisa stok. Transfer mempertahankan umur asal, batch, gram, sen dan kaki sumber.
- Dokumen penerimaan fisik terpisah dari delta invoice. Koreksi kuantitas positif dapat berlaku surut dengan dokumen dan nilai eksplisit. Debit diproses pada waktu tersedia. Koreksi negatif dicatat sebagai adjustment yang dibuktikan pada waktu tersedia. Snapshot stok lama tetap dapat dibaca pada cutoff lama. Loss gudang, disposal, refusal dan loss distribusi dicatat dengan biaya sumbernya.
- Resep berversi untuk semua fase fixture. Contoh formula yard berubah dari 60/40 menjadi 45/55 silage/barley berdasarkan DM sasaran. Tiket 16 Januari mengganti sebagian barley dengan oats di bawah batas 25% AF per komponen. Nilai energi dan protein berasal dari spesifikasi sintetis bahan, lalu dijumlahkan dari DM aktual. Mixer, truck dan bunk memakai komposisi homogen untuk output serta kerugian. Kadar komponen refusal di lapangan dapat berbeda.
- Pengiriman mengikuti rencana dan parameter loss/refusal sintetis. Tidak ada model intake terukur, probing bunk, refeed, carryover antarwindow, atau kalibrasi nutrisi. Metabolik adalah proxy pembagian, sementara equal-head dan BW adalah skenario pembanding. Replay dan validasi ditujukan untuk fixture dalam memori.

[Kamus data](DATA_DICTIONARY.md) · [Laporan rekonsiliasi dan contoh hitungan](RECONCILIATION.md) · [Handoff Stage 4](STAGE4_HANDOFF.md)
