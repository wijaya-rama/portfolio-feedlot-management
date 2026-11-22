# Kamus data dan lineage

Skema `stage2.1`. Grain berscope `run_id`. Parquet memakai teks UTF-8 untuk ID/enum, timestamp UTC mikrodetik, tanggal bisnis Edmonton bertipe date32, dan int64 untuk gram DM. Bobot skala berpresisi 0,1 kg, estimasi 0,001 kg, dan langkah biologis floating-point. Field bertanda `?` dapat berisi null. Semua baris berlabel sintetis.

| Tabel | Grain dan field |
|---|---|
| `operational/weigh_attempts` | Satu kesempatan ukur per `source_event_id`. Animal, lot, lokasi, event kedatangan di lokasi, jenis, `scheduled_at`, `status`, `observation_id?`, `movement_event_id?`, dan `physical_snapshot_id`. Status `missing` memiliki ID observasi kosong. |
| `operational/weight_observations` | Satu versi tiket per `observation_id`. Animal, lot, lokasi per `location_event_id`, tautan movement? untuk opening/receiving/sale, jenis, kg, `measured_at`, `posted_at`, `available_at`, `scale_id`, `quality_flag`, `corrects_observation_id?`, sumber, versi sumber/model dan snapshot fisik. |
| `operational/estimate_snapshots` | Satu `snapshot_id` per input, policy dan cutoff. Stage 1 run ID, batas efektif/pengetahuan, SHA-256 movement replay, fakta klinis, tiket eligible dan policy, versi estimator, `revises_snapshot_id?` dan `revision_reason?`. |
| `operational/weight_estimates` | Satu `estimate_id` per snapshot, animal, target dan model. Identitas, lokasi/lot saat origin, stage, status/ID kesehatan?, `estimate_date`, `estimate_for`, dua cutoff, model/versi, ID/waktu ukur/ketersediaan jangkar?, umur timbang pada origin?, kg/ADG/prior?, status confidence, flag mutu dan fallback. |
| `operational/draft_assessments` | Satu keputusan per `draft_id`, dengan FK `estimate_id` dan `snapshot_id`, animal, waktu keputusan, target kg, status `selected` atau `deferred`, dan alasan. Asesmen fixture bersifat independen dari shipment Stage 1. |
| `diagnostic/animal_profiles` | Satu `animal_id` per profil. Lot, breed, sex, frame, bobot/umur masuk, faktor gain individu/lot, FK event opening/receipt dan versi model. |
| `diagnostic/synthetic_weather` | Satu `source_id` per tanggal override. Tanggal bisnis, skenario, waktu paparan mulai dan tersedia. Default kalender ada di konfigurasi. |
| `diagnostic/health_events` | Satu `health_event_id` per tindakan. `episode_id`, predecessor?, animal/lot, lokasi, action, waktu efektif/post/available, source event, movement event?, severity?, respons?, beban, status, flag visibilitas operasional serta versi model dan snapshot fisik. |
| `diagnostic/biology_steps` | Satu animal per awal segmen. Lot, lokasi/event interval, waktu awal/akhir, stage, umur, potensi gain, referensi kesehatan?, cuaca, bobot awal/sebelum kredit/akhir, dan maintenance. Feeding window?, pangsa akses, gram DM demand/consumed, MJ, kg CP, versi adapter/biologi dan snapshot fisik. |
| `diagnostic/observed_backtest_pairs` | Satu horizon per tiket target. Origin dan target UTC, animal/lot/breed/sex/frame, jenis tiket, musim, stage/health snapshot origin?, alasan kelayakan, referensi prediksi A/B?, kg tiket dan prediksi A/B?. |
| `diagnostic/latent_backtest_targets` | Satu horizon per tiket target eligible. Animal, waktu target, bobot simulasi dan snapshot fisik. |

## Lineage dan cutoff

`inputs.json` membekukan konfigurasi, seed stream, profil skenario, event klinis masukan, jadwal timbang, provenance koreksi dan hash input Stage 1. `run_manifest.json` menaut ke `hashes.json` untuk hash file dan baris kanonik. Run Stage 2 dan Stage 1 punya ID masing-masing. PK/FK event fisik dapat dicocokkan dengan `effective_events` Stage 1 menggunakan `stage1_run_id` dan `event_id`. Snapshot fisik Stage 2 berasal dari replay Stage 1 pada dua cutoff di `inputs.json`. Keduanya 12 Maret 2024 pukul 00.00 Edmonton pada fixture.

Timbang memakai interval aktif `[start_at,end_at)`. Final sale harus merujuk movement sale dan diukur sebelum exit. Koreksi mempertahankan identitas, jenis, waktu ukur, alat, lokasi dan referensi movement. `available_at` penerus harus lebih akhir, tanpa percabangan. Mutu `accepted` atau `corrected` dapat menjadi anchor. Seleksi menyelesaikan rantai koreksi yang diketahui, membuang tiket `suspect` dan `rejected`, lalu memilih waktu ukur terbaru dengan tie-break ketersediaan dan ID.

Untuk origin operasional, batas efektif eksklusif dan ketersediaan inklusif. Estimasi harian adalah posisi sebelum tengah malam berikutnya. Retrospektif memakai cutoff pengetahuan setelah origin dengan alasan eksplisit, ID baru dan pointer ke snapshot awal. Estimasi harian memakai cutoff kontemporer meski build dilakukan sesudah periode berakhir. Hash snapshot operasional mencakup fakta eligible pada origin dan replay Stage 1 yang terlihat. Tiket skala mencatat lokasi fisik saat ukur. Lokasi operasional di estimasi mengikuti replay sesuai cutoff, termasuk saat mutasi fisik terlambat tersedia.

`operational_health()` memproyeksikan ID, waktu efektif, ketersediaan dan status yang terlihat dari ledger klinis. Estimator menerima proyeksi ini melalui API. Beban klinis, onset laten dan bobot simulator berada di jalur diagnostik. ID kesehatan pada estimasi dapat di-join ke `health_events` untuk audit as-of.
