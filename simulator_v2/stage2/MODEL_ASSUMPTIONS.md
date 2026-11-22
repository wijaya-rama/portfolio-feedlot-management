# Asumsi dan persamaan sintetis

Parameter versi `stage2-synthetic.1` memuat koefisien, rentang, label dan peluang skenario internal. Breed, sex, frame, umur, bobot pembuka, jadwal klinis dan timbang ditetapkan per ekor di fixture. Kalibrasi biologis dan klinis memerlukan data lapangan. Label respons `low` dan `moderate` menyatakan perubahan beban skenario tanpa identitas obat, dosis atau estimasi efektivitas komparatif. [Parameter](scenario.json) · [Fixture](fixture.py)

## State biologis dan konsumsi

- Bobot awal diterapkan sekali di event opening atau receipt. Umur saat ini = umur masuk + waktu berlalu UTC. Umur dan bobot awal ditetapkan independen dari sale/death. Lot dan ID bersumber dari ledger.
- Stage = receiving atau hospital sesuai tipe lokasi. Di kandang produksi, 14 hari pertama sejak masuk adalah adaptasi, lalu finishing. Stage dan ransum default memakai versi konfigurasi yang sama.
- Potensi gain per hari = 1,9 kg × `clamp(1 − umur_hari/820, 0,45, 1)` × faktor breed, sex, frame, individu, lot dan stage × `(1 − 0,70 × beban klinis)`. Faktor individu dan lot menggunakan uniform simetris ±12% dan ±8% dari stream berbeda, dengan kunci ID masing-masing. Potensi dibatasi 2,4 kg/hari.
- Dua feeding window lokal berlaku pukul 08.00–10.00 dan 15.00–17.00. Pangsa segmen `s` = durasi segmen / durasi window / jumlah window. Pindah, masuk, keluar, perubahan stage, kesehatan dan skenario cuaca dapat memecah akses. Interval lokasi Stage 1 dan detik UTC menentukan akses saat perubahan DST.
- Demand DM segmen = target harian ransum × `s`. DM termakan = `min(demand, 0,029 × bobot laten awal segmen × s) × (1 − 0,58 × beban) × faktor intake cuaca`. Demand dan konsumsi disimpan dalam gram DM bulat. Energi `E` = kg DM termakan × MJ/kg DM ransum. Protein kasar `P` = kg DM termakan × fraksi CP ransum. Ini asumsi konsumsi individu sementara, tanpa delivery pen atau saldo persediaan.
- Maintenance energi harian `M` = `50 × (BW/400)^0,75 × faktor cuaca × (1 + 0,16 × beban)`. Maintenance protein harian `C` = `0,40 × (BW/400)^0,75` kg CP. Proksi susut harian `L` = `min(0,8, 0,013 × M)`. Maintenance mengurangi bobot selama waktu berlalu, termasuk di luar feeding window, dengan nilai `L` dibekukan per segmen.
- Saat segmen feeding selesai, bobot menerima kredit maintenance `L × min(s, E/M)` dan gain `max(0, min(potensi × s, (E − M × s)/29, (P − C × s)/0,40))`. Gain dibatasi oleh potensi, energi dan protein. Bobot terjepit pada 180–900 kg. Batas ini adalah guardrail fixture. Perubahan bobot pada penutupan segmen adalah diskret sesuai resolusi model. Bobot pada instan exit merupakan checkpoint terminal sebelum mutasi.
- Kalender dingin berlaku 15 November–15 Maret inklusif. Baris cuaca sintetis mengganti skenario kalender mulai `observed_at` hingga tengah malam lokal. Biology memakai paparan fisik mulai saat itu. Ketersediaan sistem bisa lebih lambat. Estimator hanya memakai kalender dan versi prior skenario.

## Health dan penimbangan

Onset mengaktifkan beban sintetis sesuai severity. Observasi pertama dapat disusul perawatan di pen atau admission yang sudah dicatat Stage 1. Perawatan pertama atau ulang mengurangi beban dengan relief konfigurasi. Reassessment dapat berujung perawatan ulang, pemulihan atau status kronis. Pemulihan menurunkan beban ke nol. Kronis menggunakan beban tetap konfigurasi dan dapat dinilai ulang. Transfer keluar hospital mengacu pada movement Stage 1. Kematian berasal dari ledger dan bisa menutup kasus, atau membuka catatan terminal tanpa episode yang diketahui. Fixture mencakup kematian dengan dan tanpa perawatan, pemulihan dan kasus kronis. Onset laten tetap di kanal diagnostik.

Tiket timbang memakai bobot laten pada saat ukur ditambah bias alat dan galat uniform simetris, kemudian dibulatkan ke 0,1 kg. Kehilangan tiket memakai draw terpisah dari variasi alat, dengan peluang menurut jenis timbang dan override fixture untuk menguji data hilang. Pengukuran terminal dilakukan lima menit sebelum penjualan dan tiketnya tersedia pada atau setelah dispatch. Shrink pengiriman, HCW dan grade berada di luar model Tahap 2.

## Estimasi operasional

- **A** membawa bobot tiket eligible terakhir. ADG proyeksi 0.
- **B** memakai `kg_tiket + prior_ADG × min(umur_tiket_pada_target, 35)`. Prior dalam kg/hari ditentukan stage origin, kalender origin dan status klinis teramati di origin. Faktor dingin 0,92. Faktor sakit 0,48 dan kronis 0,71. Untuk forecast, prior dan fitur dibekukan pada origin. `estimated_adg_kg` menyatakan pertambahan rata-rata per hari dari timbang ke target setelah pembatasan. `adg_prior_kg` menyimpan laju sebelum pembatasan.
- Tiap origin menyimpan dua cutoff. Tiket telat dipakai mulai saat tersedia. Mutasi dirunut sesuai replay Stage 1. Tiket final sale dipakai sebagai target diagnostik. Model A/B dapat memakai tiket drafting yang telah tersedia di origin.
- Bila tidak ada anchor eligible, bobot dan ADG kosong dengan flag `missing_anchor`. Bobot tersedia sampai usia 14 hari diberi `high_recent`, di atas 14 sampai kurang dari 35 hari `moderate_aged`, dan mulai 35 hari `low_stale`. Confidence bersifat ordinal menurut usia data. B membatasi hari proyeksi untuk anchor tua. Asesmen draft menunda bila bobot tidak cukup, anchor tua atau ada sakit yang teramati.
- Prior B tetap sesuai skenario. Model B menggunakan satu laju untuk seluruh selisih sejak timbang. Cakupan fixture membatasi penilaian, sehingga Model C dan rekonstruksi ADG per periode kesehatan, fase atau paparan menunggu pilot.
