# Kamus data Stage 3

Semua record dalam build bersifat sintetis dan membawa `run_id`. `*_at` memakai UTC dengan resolusi mikrodetik. Tanggal layanan, invoice dan periode mengikuti `America/Edmonton`. Bilangan massa, nilai dan nutrien memakai bilangan bulat 64-bit. `g_af` berarti gram as-fed, `g_dm` gram dry matter, `kj` kilojoule, `cp_g` gram crude protein, dan `cents` sen CAD. `bps` adalah bagian per 10.000. Estimasi bobot operasional tetap memakai kg sebagai float sesuai kontrak Stage 2. Struct jumlah pakan menyimpan kelima komponen AF, DM, energi, protein dan nilai dalam basis aditif yang sama.

## Sumber dan gudang

| Tabel | Grain dan kunci |
|---|---|
| `livestock/animals`, `lots`, `location_versions`, `movement_events` | Salinan fakta Stage 1, dengan kunci dan lineage asal. |
| `warehouse/ingredients`, `suppliers`, `locations`, `bins`, `batches`, `batch_assays`, `prices`, `purchase_orders`, `equipment` | Satu record per versi efektif, kunci `record_id`. ID bisnis dan ID dokumen tetap tersimpan. Batch mengikat bahan, pemasok dan label lot supplier. Bin mengikat lokasi warehouse. Assay mengikat batch dan persentase DM. Harga mengikat pemasok, bahan, CAD dan unit tarif. |
| `warehouse/transactions` | Satu dokumen sumber dengan kunci `record_id`, urutan efektif `effective_at, sequence, record_id`. Opening, receipt, transfer, issue, count, adjustment, spoilage, retur dan invoice delta. Massa sumber fixture adalah gram AF. Referensi count, receipt dan tanggal invoice tersedia sesuai jenis dokumen. |
| `warehouse/warehouse_snapshots`, `snapshot_documents` | Versi as-of dengan cutoff efektif eksklusif dan ketersediaan inklusif, serta satu baris per pasangan snapshot/transaksi. Induk dan approval menautkan revisi. |
| `warehouse/<snapshot_id>/receipt_lines`, `purchase_status` | Satu baris penerimaan per tiket dengan versi PO, harga, supplier batch, tanggal fisik, posting, ketersediaan, unit tarif dan nilai landed. Status PO menunjukkan sisa gram dari penerimaan parsial. |
| `warehouse/<snapshot_id>/inventory_cost_layers` | Satu layer per kejadian kredit `layer_id`. Simpan nilai awal, AF awal, batch, transaksi asal dan urutan FIFO. |
| `warehouse/<snapshot_id>/inventory_movements` | Satu kaki transaksi per layer/bin, kunci `entry_id`. Tanda positif menambah stok. Transfer masuk mengacu langsung ke kaki keluar. DM menerangkan assay/spec pada saat kejadian. Jembatan stok menggunakan AF karena moisture dapat berubah. |
| `warehouse/<snapshot_id>/inventory_balances`, `stock_counts`, `invoice_splits` | Saldo kontribusi per bin/layer. Count menyimpan buku, fisik dan selisih. Invoice split mengaitkan masing-masing delta ke entry stok saat ini atau entry penggunaan historis. |
| `warehouse/stock_bridges` | Satu baris per snapshot, rentang, bahan, batch dan bin. Flow bertanda merekonsiliasi opening ke closing. |

## Keputusan, campuran, dan konsumsi

| Tabel | Grain dan kunci |
|---|---|
| `operational/weigh_attempts`, `weight_observations` | Jadwal dan record timbang sintetis dari input referensi independen, termasuk tiket hilang dan koreksi. |
| `operational/estimate_snapshots`, `weight_estimates`, `feeding_weight_inputs` | Satu snapshot per cutoff, estimasi B per hewan, dan input beku per cutoff/hewan, termasuk fallback bagi hewan yang baru diketahui kemudian. `estimate_id` kosong bila tidak ada estimasi pada cutoff. |
| `feed/ration_versions`, `ration_ingredients` | Header formula berversi dan satu komponen per bahan per versi. Berisi proporsi DM, DM asumsi, target energi/protein, fase eligible dan batas substitusi. |
| `feed/mix_orders`, `mix_issue_links`, `mix_batches`, `mix_inputs`, `formula_comparisons` | Order/tiket satu batch, tautan issue ke komponen, hasil input/output/loss, detail sumber per layer, serta perbandingan target DM/AF dan realisasi per komponen. `mix_inputs.layer_entry_id` menunjuk issue di snapshot warehouse horizon. |
| `feed/delivery_plans`, `truck_tickets`, `deliveries` | Rencana per pen/window, tiket angkut per mix/tujuan, kemudian muat, sampai dan truck loss. Rencana menyimpan cutoff, snapshot bobot dan jumlah roster yang diketahui. Rencana nol dicatat untuk pen tanpa roster. |
| `feed/bunk_tickets`, `bunk_settlements`, `access_snapshots` | Observasi pasca-window dan satu versi penyelesaian per delivery dengan basis replay Stage 1. Refusal dari tiket dan tambahan inferensi pen kosong tersedia sebagai kolom berbeda. Baris revisi menunjuk induk dan approval. |
| `feed/exposures`, `allocations` | Satu interval per hewan/pen/versi settlement serta satu estimasi alokasi per interval/metode. Referensi event keluar bisa kosong untuk interval tetap terbuka. `score` memakai unit internal yang hanya berlaku dalam metode yang sama. |
| `feed/active_settlements`, `wip_candidates`, `feed_bridges` | Satu settlement dan metode aktif per delivery, satu kandidat biaya provisional per alokasi terpilih yang punya konsumsi atau nilai, dan bridge per periode. |
| `feed/revision_approvals` | Record persetujuan fixture per revisi warehouse atau settlement. |

## Pertumbuhan dan kontrol

`diagnostic/animal_profiles`, `weather` dan `health_events` adalah input simulasi. `growth_steps` menyimpan langkah pertumbuhan laten per hewan dengan tipe Stage 2. Kolom `demand_g_dm` pada langkah Stage 3 memuat gram yang tersedia dari ledger. Target permintaan ada di `delivery_plans`. `growth_inputs` menautkan langkah ke alokasi yang menyuplai gram dan nutrien, beserta ketersediaan settlement.

`inputs.json` memuat konfigurasi dan hash input. `run_manifest.json` mencatat versi, commit, runtime, cutoff dan hash indeks. `hashes.json` memetakan setiap Parquet/JSON isi ke SHA-256, dan setiap tabel ke jumlah baris serta hash kanonik. `validation.json` memakai skema kontrol Stage 1. `reconciliation.json` berisi jembatan pakan bulanan dan horizon dalam angka mentah.
