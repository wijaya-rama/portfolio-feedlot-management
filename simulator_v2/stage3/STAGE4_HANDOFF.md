# Handoff Stage 4 · WIP dan akuntansi keuangan

Mulai dari satu versi run dan cutoff yang ditetapkan. `feed/active_settlements.parquet` memberi settlement dan metode terpilih per delivery. `feed/wip_candidates.parquet` memberi tanggal layanan Edmonton, waktu akhir akses, ketersediaan, hewan, lot, pen, mix, delivery, gram DM dan nilai provisional dalam sen CAD. Gunakan `candidate_id` sebagai identitas sumber idempoten dan simpan FK ke alokasi, settlement serta layer. Metode alternatif tetap tersedia untuk analisis skenario.

## Pekerjaan dan kontrol yang dibutuhkan

1. Sepakati bagan akun, akrual barang diterima, waktu kapitalisasi, aturan tanggal layanan/posting, dan kebijakan period lock serta restatement. Jembatani persediaan pakan → issue/mix/pen → WIP/varians. Rekonsiliasi akun kliring dan persediaan ke `inventory_movements`, `stock_bridges` dan `feed_bridges`.
2. Post hanya nilai konsumsi terpilih ke buku pembantu WIP sapi. Pisahkan spoilage, shrink, mixing loss, delivery loss, bunk loss dan refusal sebagai varians. Gunakan event layanan yardage Stage 1 dengan tarif efektif dan gabungkan sumber biaya pembelian dan perawatan yang disetujui.
3. Tangani invoice final menggunakan `invoice_splits`. Bagian stok tersedia sudah mengubah layer warehouse dan mengalir melalui biaya issue berikutnya. Bagian historis menunjuk entry yang telah mengeluarkan bahan. Teruskan selisih itu melalui sumber mix dan kategorinya ke stok kliring, WIP, COGS, write-off atau varians. Contoh `SYN-HAND-I1` membagi +25 sen menjadi 13 pada stok, 10 pada issue sebelumnya dan 2 pada spoilage. Harga provisional pada tiket historis tetap dapat diaudit.
4. Bandingkan settlement revisi dengan induknya dan post delta yang disetujui. Dua versi penuh dapat dibaca untuk audit. Rekonsiliasi per hewan, lot, yard, periode dan mata akun sampai satu sen. Bedakan tanggal efektif, ketersediaan dan periode yang terbuka untuk post.
5. Tangani tepat satu pelepasan WIP pokok pada sale atau death dari Stage 1. Atur akrual dan koreksi biaya yang tersedia setelah exit, termasuk akses pakan pada hari keluar. Arahkan biaya terlambat ke COGS atau write-off sesuai outcome dan pastikan WIP hewan tertutup nol.
6. Tambahkan jurnal berpasangan, tie-out total debit/kredit, lock dan jembatan bulanan WIP/COGS/write-off. Tetapkan kebijakan settlement revenue serta rekonsiliasi antarversi sebelum menilai margin.

Kelayakan biaya pada Stage 3 adalah estimasi manajemen yang berasal dari konsumsi termodelkan. Parameter nutrisi, tarif, akun, aturan akrual dan persetujuan revisi produksi memerlukan keputusan terpisah.
