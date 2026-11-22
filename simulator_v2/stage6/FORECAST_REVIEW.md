# Telaah forecast Stage 7

Telaah ini memakai laporan pilot 1.500 yang diserahkan pengguna, seed 42, `SYN-STAGE6-RUN-c10780f1f054de8422edc83c`, evaluator `stage5-saved-holdout.1`. Arsip sumber memiliki awalan SHA-256 `5221f92c9596`. Tabel di bawah merangkum laporan lama. Angka revisi memerlukan pembacaan arsip Parquet di Colab.

| Horizon | MAE temporal A / B, kg | Bias B 60 hari, kg | Coverage interval B holdout lot | Pasangan berinterval / seluruh pasangan eligible holdout lot |
|---|---:|---:|---:|---:|
| 7 hari | 18,4954 / 5,7618 | — | 84,32% | 555 / 3.034 |
| 30 hari | 36,1454 / 10,4304 | — | 82,87% | 397 / 2.702 |
| 60 hari | 68,3230 / 26,1129 | −25,9961 | 76,86% | 229 / 2.224 |

Bias B 60 hari juga melewati toleransi ±16 kg pada holdout lot (−26,2566 kg) dan irisan lot–waktu (−30,3267 kg). Temporal 60 hari mencatat coverage 92,45% walau point forecast bias. Coverage interval mengukur proporsi outcome yang masuk rentang setelah kalibrasi residual, sehingga rentang dapat mencakup offset dari point forecast.

## Batas proyeksi

Stage 2 memakai `min(hari_dari_tiket_ke_target, 35)`. Batas 35 hari menjaga nowcast saat data timbang menua. Evaluator lama menerapkan rumus yang sama saat target berada 7/30/60 hari di depan. Umur tiket di origin ikut menghabiskan 35 hari. Pada horizon 60, target aktual paling awal dalam laporan masih lebih dari 57 hari sesudah origin, sehingga semua pasangan eligible sudah mencapai batas bahkan dengan tiket baru. Laporan mencatat 1.152/1.152 pada holdout temporal dan 2.224/2.224 pada holdout lot. Dengan ADG positif, prediksi lama berhenti bertambah setelah batas. Ini menjelaskan mekanisme yang mendorong bias negatif. Besar kontribusinya dibanding kesalahan ADG atau perubahan fase dan kondisi klinis memerlukan data per pasangan.

Evaluator revisi 2 mempertahankan nowcast dengan batas yang sama sampai origin, lalu menambahkan ADG yang tersedia di origin dikali lead aktual. Model A dan kedua versi B memakai pasangan yang sama. `observed_errors.legacy_B` dan `legacy_capped_model_b_pairs` memberi pembanding langsung. Laju fase, faktor musim, faktor klinis dan ambang anchor stale berasal dari kode dan konfigurasi yang sudah ada. Tidak ada parameter point forecast yang di-fit ke hasil holdout. ADG tetap konstan dari origin sampai target, sehingga perubahan fase, musim, atau kesehatan di sepanjang forecast masih dapat menimbulkan bias. Hasil revisi juga bisa memperburuk bias positif pada horizon yang lebih pendek.

## Kalibrasi dan cutoff

- Fitur tetap berasal dari snapshot dengan `effective_at < origin` dan `available_at <= origin`. Tiket target dipilih dalam jendela ±3 hari. Evaluasi memakai waktu timbang aktual untuk menghitung lead, dan nilai timbang hanya untuk residual. Koreksi yang baru tersedia setelah origin dapat mengubah label final, tetapi tidak masuk snapshot fitur pada origin tersebut.
- Revisi 1 memakai pool development yang dibekukan 1 Juli 2025 dan hanya memberi interval pada origin mulai tanggal itu. Coverage lot yang dilaporkan berlaku pada subset dalam tabel. Rumus coverage dengan residual bertanda benar. Angka di bawah 85% menunjukkan coverage rendah pada subset tersebut, dengan kemungkinan pergeseran residual antar lot atau waktu.
- Revisi 2 mengalibrasi per horizon dari tiket development yang diukur sebelum 1 Juli dan tersedia pada `min(origin, 1 Juli)`. Revisi tiket dipilih ulang per cutoff. Lot holdout dan carry-in dikeluarkan sebelum membangun pool. Setiap lot mendapat bobot total sama dan setiap fold memerlukan 100 pasangan. Kuantil residual prediksi dikurangi observasi 5% dan 95% memberi interval `[prediksi − q95, prediksi − q05]`. Laporan menunjukkan jumlah pasangan berinterval, pasangan tanpa kalibrasi yang cukup, median lebar, dan coverage. Cakupan lot lintas versi dapat memiliki denominator berbeda.

## Dukungan sampel dan penggunaan hasil

| Horizon | Irisan pasangan / sapi / lot | Cakupan prediksi | Ambang strata | Ambang primer |
|---|---:|---:|---|---|
| 7 hari | 235 / 96 / 6 | 97,92% | Memenuhi | Gagal jumlah lot |
| 30 hari | 167 / 78 / 5 | 98,24% | Memenuhi | Gagal jumlah lot |
| 60 hari | 104 / 54 / 4 | 100% | Memenuhi | Gagal jumlah sapi dan lot |

Revisi 1 memakai ambang primer untuk semua kelompok utama yang ditampilkan, termasuk irisan. Revisi 2 melaporkan hasil primer dan strata berdampingan. Holdout lot dan waktu memakai ambang primer untuk `meets_sample_support`. Irisan, carry-in, dan jenis tiket ditampilkan sebagai strata. Ambang 100/60/8 untuk primer, 30/20/3 untuk strata, dan cakupan prediksi 70% tetap dipertahankan.

Arsip historis mempertahankan hasil fisik, finansial, dan audit dari run asal. Evaluator revisi 2 membaca ulang arsip yang sama, memverifikasi hash dan status audit, lalu menyimpan laporan terpisah. Simulasi baru diperlukan bila kebijakan estimator operasional diubah dan dampaknya pada pakan, yard, penjualan atau ledger akan dinilai. Bukti satu seed yang telah dibuka cocok untuk diagnosis berpasangan. Promosi masih memerlukan evaluasi independen dengan bukti yang belum dipakai untuk diagnosis, lima seed sesuai protokol, dan gerbang operasional serta sumber daya. [Protokol Stage 5](../stage5/EVALUATION.md) · [Langkah di Colab](colab/README.md)
