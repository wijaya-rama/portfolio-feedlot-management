# Kamus data Stage 1

Skema `stage1.1`, kebijakan `livestock.1`. Setiap record membawa `synthetic=true`. PK di bawah berscope `run_id`, dan tabel snapshot juga berscope `snapshot_id`. ID, RFID, kode dan status disimpan sebagai UTF-8. Timestamp Parquet beresolusi mikrodetik UTC, tanggal lokal bertipe date32, dan hitungan/urutan bilangan bulat int64. Kolom bertanda `?` boleh null. Semua timestamp master dan event memenuhi `posted_at <= available_at`.

## Sumber

| Tabel dan grain | Kolom | Aturan |
|---|---|---|
| `lots`, satu lot pembelian (`lot_id`) | `supplier_id`, `compatibility_group`, `effective_at`, `posted_at`, `available_at` | ID pemasok sintetis. Kebijakan fixture mengizinkan dua lot satu grup dalam kandang produksi |
| `animals`, satu identitas (`animal_id`) | `lot_id`, `rfid`, `effective_at`, `posted_at`, `available_at` | FK lot tetap; RFID unik, 15 digit teks berawalan `000`; ketiga jam merekam registrasi |
| `locations`, satu versi (`location_version_id`) | `location_id`, `kind`, `capacity_head`, `effective_at`, `posted_at`, `available_at` | Jenis `production`, `receiving`, atau `hospital`. Kapasitas dalam ekor, termasuk 0. Pada cutoff pengetahuan tertentu, versi berlaku pada `[effective_at, effective_at berikutnya)` untuk ID lokasi yang sama. Versi yang belum tersedia tak mengakhiri versi aktif |
| `animal_events`, satu baris event (`event_id`) | `animal_id`, `kind`, `from_location_id?`, `to_location_id?`, `effective_at`, `business_date`, `posted_at`, `available_at`, `sequence`, `source`, `supersedes_event_id?`, `reason?` | `business_date` berasal dari waktu efektif dalam Edmonton. `source` adalah struktur `(system, document_id, line_id, revision, synthetic)`. Empat field pertama mengidentifikasi versi baris sumber. `supersedes_event_id` adalah FK ke record sebelumnya untuk sapi yang sama |

| `kind` | Asal | Tujuan | Efek |
|---|---|---|---|
| `opening` | null | Lokasi aktif | Satu ekor saldo awal sebelum horizon |
| `receipt` | null | Receiving | Satu ekor penerimaan dari luar |
| `transfer` | Lokasi saat ini | Lokasi lain yang sah | Satu ekor keluar lokasi asal dan masuk lokasi tujuan, yard tetap |
| `sale` | Lokasi saat ini | null | Satu ekor keluar, status `sold` |
| `death` | Lokasi saat ini | null | Satu ekor keluar, status `dead` |
| `reversal` | null | null | Menonaktifkan event yang dirujuk saat tersedia. Alasan wajib dan waktu efektif mengikuti target |

Penggantian memakai jenis mutasi yang dikoreksi dengan `supersedes_event_id` dan `reason`. Untuk sebuah target, ketersediaan koreksi harus lebih akhir dan posting harus setidaknya setara. Hanya satu penerus setiap record. Reversal menutup rantai tersebut. Input berulang dengan isi identik bersifat idempoten. ID yang sama dengan isi berbeda atau ID berbeda dengan kunci sumber sama ditolak.

## Hasil per snapshot

| Tabel dan grain | Kolom dan interpretasi |
|---|---|
| `lots`, `animals`, `locations` | Salinan master yang efektif sebelum cutoff dan sudah tersedia. Setiap baris membawa `snapshot_id` |
| `effective_events`, per `event_id` yang berlaku | Kontrak sama dengan ledger mentah, dengan `snapshot_id`. Memuat event sah yang dipakai untuk replay |
| `animal_state`, per `animal_id` terdaftar pada cutoff | `lot_id`, `status` (`pending`, `active`, `sold`, `dead`), `location_id?`, `last_event_id?`. Lokasi hanya terisi untuk `active` |
| `animal_location_intervals`, per `animal_id + start_at + start_sequence + start_event_id` | `lot_id`, `location_id`, `start_at`, `start_sequence`, `start_event_id`, `end_at?`, `end_event_id?`. Interval `[start_at,end_at)`. Jika dua mutasi pada instan sama, interval di antaranya bisa berdurasi nol. Null berakhir berarti terbuka pada cutoff |
| `daily_soh`, `monthly_soh`, per `scope_type + scope_id + period_end` | `scope_type` adalah `yard`, `location` atau `lot`. `period_start`, `period_end` inklusif menurut kalender lokal. Bulan parsial memakai tanggal awal/akhir yang tercakup |

Kolom SOH adalah `opening_head`, `receipts`, `sales`, `deaths`, `transfers_in`, `transfers_out`, `closing_head` dan `animal_days`. Buka, tutup, dan arus dalam ekor. Transfer dicatat per lokasi saja. `animal_days` menghitung kehadiran per scope dan hari. Nilai itu aditif lintas hari untuk scope yang sama. Jembatan bulan membawa buka hari pertama, menjumlah arus dan ekor-hari, serta memakai tutup dari hari terakhir. SOH tutup hanya aditif untuk scope yang tidak tumpang tindih pada tanggal sama.

## Manifest dan laporan

| File | Jejak |
|---|---|
| `run_manifest.json` | `run_id`, konfigurasi/horizon/seed, hash config, commit Git saat build bila tersedia, hash file generator, batch, stream seed, `built_at`, runtime dan hash TZif, cutoff akhir, status, hash indeks |
| `snapshot.json` | `snapshot_id`, config versi/kalender, rentang, dua cutoff, hash input dan hasil, indeks tabel, hash validasi, `revises_snapshot_id?` dan `approval?` dengan ID, aktor, waktu dan alasan |
| `hashes.json` | SHA-256 file dan baris kanonik per tabel, jumlah baris, ID/path tiap snapshot. `animal_events.jsonl` memakai UTC berakhiran `Z`, kunci objek terurut, UTF-8 dan LF |
| `validation.json` | Pemeriksaan dengan `check_id`, `scope`, `version`, `severity`, `expected`, `actual`, `failed_count` dan `sample_ids`. Publikasi diblokir bila ada error |

`available_at <= knowledge_cutoff` menentukan record yang diketahui. `effective_at < effective_before` menentukan mutasi yang sudah berlaku. Rantai koreksi diselesaikan setelah seleksi pengetahuan dan sebelum seleksi waktu efektif. Cache atau keputusan Tahap 2 perlu menyimpan kedua cutoff beserta `snapshot_id`.
