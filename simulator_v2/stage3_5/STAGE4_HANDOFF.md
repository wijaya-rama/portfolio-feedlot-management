# Kesiapan Stage 4

Pakai paket seed 42 Stage 3.5 untuk pengembangan dan uji costing/WIP sintetis. Kunci versi melalui `run_manifest.json`, `hashes.json`, `scenario_version`, snapshot Stage 1 dan cutoff gudang. Skenario Stage 3 tetap merupakan pembanding historis.

- Basis pakan yang layak adalah `feed/active_settlements` bersama `feed/wip_candidates`. Join melalui ID alokasi, settlement, delivery, mix dan layer issue. Pilih satu metode aktif. Pertahankan `service_date`, `access_end` dan `available_at` saat membentuk vintage biaya.
- Nilai kandidat WIP adalah biaya provisional FIFO. Tabel invoice split membedakan delta yang masih berada pada stok dari delta sink historis. Refusal, spoilage, loss mixing, loss distribusi dan loss bunk memiliki jejak biaya sendiri. Yardage berasal dari `livestock/daily_soh` atau `monthly_soh`.
- Versi historis dan revisi settlement merupakan fakta bitemporal. ID induk, approval dan timestamp membuat keduanya dapat ditelusuri tanpa mengubah cutoff asli. Gunakan `operational/weight_observations` untuk tiket timbang yang tersedia dan tabel diagnostik hanya untuk audit simulasi.

Tidak ada cacat perangkat lunak terbuka yang teridentifikasi pada fixture yang akan membatalkan basis Stage 4. Validasi ini mencakup fixture 12 ekor. Kalibrasi pertumbuhan, intake, weather response dan galat alat terhadap data lapangan masih diperlukan untuk penggunaan empiris. Tidak ada pengukuran intake individu, refeeding, atau carryover antarwindow pada skenario ini. Pelepasan seragam 30 menit, campuran homogen, refusal terprogram, shrink nol, dan skor alokasi adalah asumsi sintetis. Dukungan backtest belum memadai untuk menilai akurasi di tiga horizon. Stage 4 accounting dan simulasi 1.500 maupun 15.000 ekor tetap di luar build ini.
