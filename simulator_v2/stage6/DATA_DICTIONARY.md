# Kamus data · stage6a.1

Setiap baris Parquet memiliki `run_id`. Kunci di bawah berscope run. Tanggal penamaan partisi mengikuti bulan bisnis Edmonton berdasarkan jam sumber yang relevan. Baca seluruh partisi satu tabel untuk join lintas bulan. Timestamp adalah UTC berpresisi mikrodetik. Suffix `_g_af` berarti gram as-fed, `_g_dm` gram bahan kering, `_kj` energi, `_cp_g` gram protein kasar, `_kg` kilogram, `_bps` basis points, dan `_cents` sen nominal CAD. Amount nested memakai `g_af`, `g_dm`, `kj`, `cp_g` dan `cents`. Nilai nullable menandai ketidaktersediaan bukti atau hubungan yang tidak berlaku. Tabel fakta tanpa event pada suatu skenario tidak memiliki partisi.

## Ternak, observasi dan keputusan

| Tabel | Grain dan hubungan |
|---|---|
| `lots`, `animals`, `locations` | Lot pembelian, sapi efektif saat masuk, dan versi kapasitas lokasi. `animal_id → lot_id`. RFID sintetis unik disimpan sebagai teks. |
| `placement_requests`, `opening_cattle` | Satu reservasi identitas per permintaan placement, atau satu saldo pembuka per sapi. ID reservasi join ke master setelah realisasi. Saldo pembuka menyimpan dokumen, status, BW, DOF, umur, lokasi dan WIP. |
| `movement_events`, `physical_intervals` | Satu `event_id` atau interval lokasi per sapi × event masuk. Internal transfer memiliki asal dan tujuan, sale/death hanya asal. Interval efektif setengah terbuka. |
| `daily_soh`, `monthly_soh` | Per periode × scope yard, lot atau pen. Termasuk head pembuka/penutup, receipt, sale, death, in/out, dan animal-days unik pada grain tersebut. Animal-days pen dapat menjumlah lebih tinggi karena mutasi dalam hari. |
| `animal_profiles`, `animal_outcomes` | Satu per sapi yang efektif. Profil dan hasil laten bersifat diagnostik. Terminal menyimpan outcome, movement terakhir, DOF, elapsed horizon, BW dan lokasi carry-out bila aktif. |
| `physical_contexts` | Satu snapshot konteks pertumbuhan, klinis, atau sampling. Fingerprint movement tersedia melalui `movement_sha256`. |
| `health_events` | Satu `health_event_id`. `episode_id` mengelompokkan urutan, `previous_health_event_id` menunjuk tahap sebelumnya. `operational_visible` membedakan onset laten dari fakta yang diketahui. |
| `weigh_attempts`, `weight_observations`, `scale_samples_diagnostic` | Satu schedule source, satu versi tiket, satu sampel laten per tiket asli yang berhasil. Tiket menyimpan waktu ukur, posting dan availability. Koreksi menautkan `corrects_observation_id`. |
| `decision_snapshots`, `weight_estimates` | Satu snapshot keputusan atau estimasi per snapshot × sapi × model. Anchor, health fact dan lokasi terakhir diberi FK. |
| `draft_decisions`, `shipment_lines` | Satu penilaian per estimate saat draft atau satu baris shipment per sapi yang keluar. Draft terpilih bisa menunggu kuota. |
| `carcasses`, `packer_settlements` | Satu hasil karkas dan satu dokumen final per sale. Pisahkan kualitas, yield, HCW, bobot aktual bila ada, harga grid, premium, diskon, freight dan adjustment. |
| `weather_forecasts`, `weather_exposure` | Forecast terpilih untuk tanggal target atau interval paparan per jalur. Arsip dan fallback diberi label sumber. |
| `growth_operational`, `growth_retrospective` | Sapi × awal segmen × jalur. Ukuran laten, aliran dan stok cadangan ME/CP. Agregasi antar jalur menggandakan konsumsi. |

## Pakan dan gudang

| Tabel | Grain dan hubungan |
|---|---|
| `warehouse_ingredients`, `warehouse_suppliers`, `warehouse_warehouses`, `warehouse_bins`, `warehouse_prices`, `warehouse_equipment` | Master `record_id` berversi. Memuat harga basis tonne AF, mutu standar, satuan, kapasitas fisik serta equipment. |
| `warehouse_batches`, `warehouse_assays`, `warehouse_orders`, `warehouse_receipts`, `warehouse_po_status` | Batch, tiket hasil assay, PO version, receipt line parsial dan saldo PO akhir. Join lewat batch, PO line version dan source receipt. |
| `warehouse_transactions`, `warehouse_entries`, `warehouse_layers`, `warehouse_balances` | Dokumen FIFO → leg → cost layer, dengan saldo `bin_id × layer_id`. Transfer in menautkan transfer out dan menjaga nilai. |
| `warehouse_af_bridge`, `warehouse_dm_bridge` | Snapshot × periode × bin × batch untuk AF/nilai, atau bin × layer untuk DM. DM memisahkan revaluasi basis dan pembulatan. |
| `ration_versions`, `ration_ingredients`, `feed_plans`, `feeding_weight_inputs` | Formula dan komponennya, rencana per pen/window, serta input skor as-of per snapshot/sapi. |
| `mix_orders`, `mix_issue_links`, `mixes`, `mix_inputs`, `formula_comparisons` | Satu order per load, link issue ke mix, hasil mix, satu input per FIFO issue leg, dan perbandingan komponen. |
| `truck_tickets`, `feed_deliveries`, `bunk_tickets`, `bunk_settlements`, `feed_access_snapshots` | Tiket fisik, delivery, tiket refusal, settlement dan snapshot roster. `delivery_id` mengikat mix, plan, tiket serta pool konsumsinya. |
| `feed_exposures`, `feed_releases`, `feed_allocations` | Akses per sapi/delivery, pool per slice, dan alokasi fisik per akses/slice. Akses hanya untuk interval lokasi yang valid. |
| `accounting_feed_allocations`, `posting_allocation_links`, `feed_cost_bridge` | Satu agregat posting per sapi/delivery, satu crosswalk per release allocation, dan satu bridge biaya per settlement. Gabungkan nilai konsumsi dan normal loss di buku. Gunakan release allocations untuk asupan. |
| `exceptions` | Satu alasan/domain/entity/waktu per konsekuensi yang teramati. Qty memakai unit yang tercantum. |

## Buku dan snapshot

| Tabel | Grain dan hubungan |
|---|---|
| `yardage`, `warehouse_finance` | Satu charge per hari bisnis/sapi dan satu leg inventory untuk subledger finance. Sumber menautkan movement dan warehouse entry yang berlaku. |
| `financial_sources`, `financial_source_links`, `financial_approvals` | Satu dokumen sumber, edge sumber × parent, atau persetujuan controller berversi. Simpan clock efektif, posting, availability dan hash payload. |
| `journals_as_known`, `journals_restated`, `journal_lines` | Satu jurnal per aksi dan buku, ditambah dua kaki debit/kredit per jurnal as-known. Release memakai `outcome_event_id` pada registry sumber finance. |
| `finance_snapshots`, `finance_monthly`, `trial_balance` | Close per versi/bulan, ringkasan close, dan per akun × close. `replaces_close_id` menunjuk tutup asli, `prior_month_close_id` menunjuk vintase bulan sebelumnya. |
| `wip`, `wip_components`, `finance_soh`, `warehouse_close`, `finance_exceptions`, `close_deltas` | Closing WIP per sapi, rincian cost component, head check, stok per bin/layer, clearing terbuka dengan bukti, dan perbedaan close akibat restatement. Join lewat `close_id` dan scope. |

## Artefak JSON

`validation.json` memuat gate independen dan hasil mesin baseline. `diagnostics.json` memuat distribusi dan konvensi pengukuran. `monthly_summary.json` memuat ringkasan asli dan restated. `weather.json` menyimpan metadata arsip dan detik per sumber. `performance.json` merekam satu eksekusi. `hashes.json` memetakan partisi ke baris, ukuran dan SHA-256. `config.json` dan `run_manifest.json` membekukan input, cakupan, runtime dan versi.
