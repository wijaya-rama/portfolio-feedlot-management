# Kamus data Stage 4 · stage4.1

Semua Parquet memuat `run_id`. Kode akun dan kunci identitas adalah string. Nilai uang dan massa adalah `int64` dalam sen CAD dan gram. Nilai waktu memakai timestamp UTC mikrodetik. Tanggal layanan dan periode memakai kalender Edmonton. `null` pada dimensi menunjukkan kondisi yang tidak berlaku atau tidak diketahui. Tipe kolom lengkap terdapat di skema Parquet.

| Tabel | Grain dan join | Keterangan nilai |
|---|---|---|
| `control/chart_of_accounts` | `account` | Nama, kategori, saldo normal |
| `control/sources` | `source_id`, unik untuk sistem, dokumen dan baris | Timestamp efektif, posting sumber, ketersediaan, hash payload, vintage sumber dan kind event bila relevan |
| `control/lineage` | `source_id, parent_id` → sources | Edge turunan ke sumber yang sudah tersedia. Ikuti rekursif ke event pergerakan, klinis, FIFO dan bukti feed Stage 3.5. Tabel dan ID sumber tetap dapat dicari dalam arsip sumber |
| `control/approvals` | `approval_id` → journal dan close, `source_id` → sources | Pemberi persetujuan, waktu dan alasan |
| `ledger/journal` | `journal_id` → sumber dan dua akun | Transaksi asli dan delta. `amount_cents` nonnegatif. `reverses_journal_id` menjembatani pembalikan. `outcome_event_id` mengarah ke `source_id` exit. `principal_release` menandai pokok. `pool_id` menunjukkan lot proses bila relevan. `location_id` merupakan lokasi layanan atau bin |
| `ledger/journal_lines` | `journal_id, line_number` | Kaki debit positif dan kredit negatif. Jumlah dua kaki harus nol |
| `ledger/restatement_projection` | `journal_id` pada versi proyeksi | Jurnal untuk penyajian revisi. `period_routing_at` adalah waktu routing untuk periode; `posted_at` dan `available_at` tetap menyatakan kapan dokumen dapat dibukukan. Gunakan satu versi buku pada tiap laporan |
| `ledger/supplier_invoice_routes` | `journal_id` → `invoice_split_id` serta layer/sink | Delta pada akun saat dibukukan, termasuk pembalikan dan re-alokasi. `signed_cents` positif menambah utang invoice |
| `ledger/supplier_invoice_horizon_impact` | Split, sapi opsional, akun akhir | Dampak delta yang telah mengikuti pelepasan pokok dan koreksi sampai cutoff |
| `subledgers/yardage` | `date, animal_id` | Tarif asli, pen layanan yang terpilih satu kali, event aktif dan cents dasar. Koreksi ada di jurnal |
| `subledgers/warehouse_movements` | `entry_id` | Mutasi bertanda per layer/ingredient/bin, g AF, DM pada assay gerakan, nilai dan accounting month |
| `subledgers/warehouse_source_vintages` | `snapshot_id` dari Stage 3.5 | Cutoff efektif/pengetahuan, kait revisi, AF dan sen, termasuk penerimaan terlambat pada penutupan harian uji |
| `subledgers/recoverable_lots` | `lot_id` → ticket dan settlement akhir | g AF/DM, nilai provisional dan invoice delta. Lot recovery memiliki identitas tersendiri |
| `feed/active_settlements` | `delivery_id` → settlement aktif | Metode produksi tunggal dan versi tahap sumber |
| `feed/physical_wip_basis` | `candidate_id` → alokasi, settlement, mix, delivery, sapi | DM konsumsi individual asli, timestamp akses dan nilai provisi. AF tersedia pada grain delivery |
| `feed/settlement_cost_dispositions` | `settlement_id` per delivery | Setiap vintage, jumlah fisik loss dan konsumsi, pembagian nilai provisi. Gunakan `active_settlements` untuk total final |
| `feed/financial_bridge` | `period, policy_version` | Periode layanan dan horizon. Gross issue ke konsumsi dasar, absorpsi, recovery, abnormal dan pending. Warehousing variance terpisah |
| `feed/policy_sensitivity` | `month, policy_version` | Bulan akuntansi dan horizon dibandingkan dengan massa sama. `cumulative_accounted_cost_cents` menjumlah WIP dan recovery tutup, clearing, COGS, mortalitas, serta varians kumulatif. Persediaan bahan tersisa dibandingkan terpisah |
| `monthly/close_versions` | `close_id` | Periode parsial/penuh, cutoff fisik, cutoff pengetahuan, lock, hash jurnal, approval, close asli dan close sebelumnya |
| `monthly/stock_on_hand` | `close_id, scope_type, scope_id` | Ekor buka, receipt, sale, death, transfer, ekor tutup dan ekor-hari |
| `monthly/animal_wip` | `close_id, animal_id` | WIP buka, tambahan per komponen, penyesuaian, dua jenis pelepasan dan WIP tutup. Biaya terlambat ke outcome terpisah. Lot dan pen tutup mengikuti replay efektif pada cutoff |
| `monthly/animal_cost_components` | `close_id, animal_id, component` | Nilai komponen kumulatif di WIP akhir, COGS atau write-off, termasuk perubahan versi |
| `monthly/warehouse` | `close_id, bin_id, layer_id, ingredient_id` | AF dan sen buka/tutup, receipt, issue, transfer, count/adjustment, spoilage, retur dan delta invoice. Outflow bertanda negatif |
| `monthly/warehouse_dm` | `close_id, bin_id, layer_id` | Bridge DM dengan assay, revaluasi dan pembulatan. DM memakai kebijakan fisik Stage 3.5 |
| `monthly/financial_summary` | `close_id` | Rollup WIP, saldo persediaan/kliring, COGS, write-off, revenue, varians, margin |
| `monthly/trial_balance` | `close_id, account` | Saldo awal/tutup bertanda debit minus kredit, debit dan kredit periode. Entri pembukaan resmi masuk saldo awal periode pertama |
| `monthly/exceptions` | `close_id, account, pool_id` | Clearing outstanding yang dapat dijelaskan dan waktu pertama efektif. Tabel kosong pada kebijakan terpilih |
| `monthly/restatement_bridge` | `original_close_id, corrected_close_id, measure` | Nilai asli, revisi dan delta bertanda. Subledger dan trial balance memiliki kedua vintage untuk drill-down |
| `market/quotes` | `quote_id` | Waktu observasi dan tersedia, sumber sintetis, region, kelas seks dan sen/kg live |
| `market/liveweight_view` | `month, animal_id` | Estimasi bobot Model B as-of dan link ke quote eligible. Nilai null untuk data yang kurang atau kedaluwarsa |
| `market/monthly_coverage` | `month` | Ekor aktif, tercakup, celah bobot/harga, nilai subset dan total yard bila cakupan penuh |

Untuk pen, jumlahkan `closing_cents` menurut `closing_location_id` dalam satu `close_id`. Lokasi di jurnal menunjukkan lokasi layanan. Angka awal dan akhir pen dapat berpindah akibat transfer internal tanpa biaya baru pada yard. Untuk bulan atau seri, pilih `as_known` atau `restated` melalui `close_versions`.
