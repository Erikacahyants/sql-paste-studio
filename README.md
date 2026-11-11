# BDE Tools ⚡

Aplikasi web **Streamlit** untuk menghasilkan tiga blok SQL **STG / TXF / SRI** sekaligus dari daftar kolom atau schema.

## Fitur

- Pilih pemisah otomatis atau manual: `|`, `|@~`, TAB, koma, baris baru, atau teks kustom seperti `;;`.
- Paste satu baris header seperti `PERIODE|NO REK|SALDO` untuk langsung membuat STG, TXF, dan SRI dengan tipe `STRING`. Pilih **Header saja** bila hasil paste juga memuat baris data; aplikasi mengambil baris headernya.
- Paste deklarasi seperti `PERIODE varchar(100)` dan `SALDO decimal(18,2)`, satu per baris atau dipisahkan koma. Nama tanpa tipe memakai `STRING`.
- Nama kolom dengan spasi seperti `no rek string` dibaca sebagai `no_rek STRING` agar menjadi identifier SQL yang valid.
- Spasi berlebih, baris kosong, dan pemisah di tepi input dirapikan. Pratinjau memperlihatkan nama dan tipe yang benar-benar terbaca sebelum SQL disalin.
- Paste schema `nama|tipe|panjang|scale` atau tabel Markdown. **STG** memakai STRING, **TXF** berisi `CAST(TRIM(KOLOM) AS TIPE) AS KOLOM`, dan **SRI** memakai tipe input.
- Tab **Reverse SQL Hive** membaca `CREATE VIEW ... AS SELECT` berisi `CAST(TRIM(...))` atau `TO_DATE(...)`, `CREATE TABLE`, `SHOW CREATE TABLE`, dan output `DESCRIBE` Hive/Beeline. Pembungkus tabel `createtab_stmt` dan metadata dibersihkan sebelum menghasilkan tiga blok SQL. Nama VIEW/TABLE, tabel sumber `FROM`, dan nama tabel aslinya ditampilkan. Untuk view, SQL asal yang sudah dirapikan juga ditampilkan.
- CHAR(n) dapat diganti dengan VARCHAR(n) pada SRI/TXF bila opsi diaktifkan.
- SQL langsung tampil dan bisa disalin lewat ikon salin bawaan `st.code` (pojok kanan atas blok kode).
- Validasi nama kolom, kolom duplikat, tipe yang belum lengkap, serta sel schema yang salah format.
- Tab **Table Masking** menerima SQL atau teks shell script untuk menyamarkan database, tabel, IPv4/IPv6, serta user/host SSH. Alias konsisten per input, hasil bisa disalin atau di-download sebagai `masked_script.sh`.

## Table Masking

1. Buka tab **Table Masking**, lalu paste script atau klik **Isi contoh**.
2. Database dan tabel dideteksi dari konteks SQL umum (`USE`, `CREATE TABLE/VIEW`, `FROM`, `JOIN`, `INSERT INTO`, `INSERT OVERWRITE TABLE`, dan lainnya), URL JDBC Hive/MySQL/PostgreSQL, serta assignment seperti `DB_NAME`, `DATABASE`, `TABLE_NAME`, atau `SOURCE_TBL`.
3. Opsi IP dan SSH aktif secara default. SSH mencakup `user@host`, host langsung, opsi `-l`, `-J`, `-o HostName` / `User` / `ProxyJump`, serta variabel `SSH_HOST` / `SSH_USER` dan `REMOTE_HOST` / `REMOTE_USER`.
4. Isi **Nama tambahan yang perlu dimasking** untuk pola yang belum terbaca, satu nilai literal per baris. Nilai berulang diganti alias yang sama seperti `DB_001`, `TABLE_001`, `IP_001`, `HOST_001`, dan `USER_001`.
5. Periksa hasil, lalu salin blok kode atau download. Mapping berisi nama asli tersedia di expander terpisah dan tidak dimasukkan ke file hasil.
6. Mapping otomatis disimpan di memori sesi Streamlit, tanpa database atau file. Alias tetap konsisten saat memasking query berikutnya di sesi yang sama. Paste query hasil GPT ke **Pulihkan query hasil GPT** untuk otomatis mengembalikan alias ke nilai asli, lalu salin atau download `restored_query.sql`.

Minta GPT mempertahankan alias seperti `DB_001.TABLE_001`; perubahan huruf besar/kecil masih dikenali, tetapi alias baru seperti `db1.table1` tidak ditebak. Alias yang tidak dikenal dibiarkan apa adanya. Pemulihan juga berlaku di komentar/string dan mencakup seluruh nilai yang dimasking. Tombol **Bersihkan** hanya membersihkan input; **Hapus mapping & input sesi masking** menghapus mapping dan teks masking/pemulihan. Refresh atau sesi baru dapat menghilangkan mapping. Penyimpanan ini berada di memori server untuk sesi masing-masing, bukan penyimpanan permanen atau browser local storage.

Opsi **Masking path folder / file** aktif secara default: `/x/x/bot/s/f_147/tXLON_102` menjadi `PATH_001`. Seluruh path diganti dengan satu alias yang konsisten, termasuk dalam assignment, komentar, dan tujuan SCP. Path Unix absolut, `~/`, `./`, dan `../` didukung; path dengan spasi perlu diapit tanda kutip. Shebang dan URL tidak dianggap path file. Path dinamis yang mengandung variabel shell serta path Windows dapat ditambahkan lewat input manual.

Deteksi ini memakai heuristik, bukan parser SQL/shell lengkap. Nama dinamis, daftar tabel dengan koma, atau sintaks khusus dapat memerlukan input tambahan. Penggantian literal bersifat case-sensitive, mengikuti batas kata, dan berlaku juga dalam komentar/string. Password, private key, dan credential lain tidak otomatis dimasking; tambahkan nilai yang perlu disamarkan secara manual. Script hanya diproses sebagai teks, tidak dijalankan, dan tidak membuka koneksi SSH. Hasil ditujukan untuk dibagikan sebagai contoh, bukan langsung dijalankan.

## Masking Hasil Query Impala

Tab **Masking Hasil Query** menerima hasil data (baris dan kolom), bukan SQL. Copy hasil Impala beserta header dalam format TAB, CSV, atau tabel `|`, lalu pilih **Kolom sensitif yang disamarkan**. Hanya isi kolom pilihan yang diganti alias; header dan kolom lain tetap asli. Nilai berulang dalam satu kolom mendapat alias yang sama, sel kosong tetap kosong, dan angka nol di depan tetap dipertahankan pada kolom yang tidak dipilih. Hasil tersedia untuk disalin atau di-download sebagai TSV.

Kolom sensitif otomatis dipilih berdasarkan nama header seperti `no`, `nomor`, `number`, `key`, `cif`, `name`/`nama`, `address`/`alamat`, rekening, email, telepon, NIK, dan NPWP. Pilihan bisa ditambah atau dilepas manual dan dipertahankan selama header tidak berubah. Header baru memicu deteksi ulang; tombol **Pilih ulang hasil deteksi otomatis** mengembalikan pilihan otomatis. Deteksi ini hanya berdasarkan nama kolom, bukan jaminan semua data sensitif terdeteksi.

Periksa header dan kolom yang tidak dipilih sebelum mengirim hasil ke AI. Fitur ini mengolah data di server aplikasi tanpa menyimpannya ke file/database atau mengirimnya ke AI. Alias berlaku untuk input saat ini dan tidak memakai mapping pemulihan SQL. Gunakan **Hapus input hasil query** untuk membersihkan input sesi.

## Jalankan lokal

Pastikan Python 3.10+ telah terpasang.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Browser akan membuka `http://localhost:8501`.

## Deploy Streamlit Community Cloud

1. Upload semua file/folder (`app.py`, `formatter.py`, `masking.py`, `requirements.txt`, `.streamlit/config.toml`) ke sebuah repository GitHub.
2. Di https://share.streamlit.io buka **Create app** → **Deploy a public app from GitHub**.
3. Pilih repo, branch, dan `app.py` sebagai entry point, lalu tekan **Deploy**.
4. Untuk data internal perusahaan, **jangan deploy publik**; pakai server internal atau penerapan privat sesuai kebijakan keamanan organisasi.

## Contoh input → output

Input:

```text
PERIODE varchar(100)
SALDO decimal(18,2)
TGL date
```

Output STG:

```sql
PERIODE STRING,
SALDO STRING,
TGL STRING
```

Output TXF:

```sql
CAST(TRIM(PERIODE) AS VARCHAR(100)) AS PERIODE,
CAST(TRIM(SALDO) AS DECIMAL(18,2)) AS SALDO,
CAST(TRIM(TGL) AS DATE) AS TGL
```

Output SRI:

```sql
PERIODE VARCHAR(100),
SALDO DECIMAL(18,2),
TGL DATE
```

Untuk reverse SQL, paste misalnya output Hive berikut di tab **Reverse SQL Hive**:

```text
+----------+---------------+---------+
| col_name | data_type     | comment |
+----------+---------------+---------+
| PERIODE  | varchar(100)  | bulan   |
| SALDO    | decimal(18,2) |         |
+----------+---------------+---------+
```

Aplikasi menampilkan ulang STG, TXF, dan SRI yang rapi dan bisa langsung disalin.

Hasil `SHOW CREATE VIEW` yang tercopy sebagai tabel `createtab_stmt` juga bisa dipaste. Kolom sumber dan alias tetap dibedakan saat TXF disusun ulang.

## Keamanan dan keterbatasan

Kode tidak mengirim input ke layanan AI atau database. Namun bila aplikasi di-host di internet, input diproses di server hosting. Jangan paste schema/data perusahaan yang sensitif ke instance cloud publik tanpa izin.

Format SQL ditujukan untuk Hive/Impala dan mungkin perlu penyesuaian untuk dialek lain. Input dari Excel dapat ditempel sebagai teks/tab. Untuk tipe kompleks `ARRAY<...>` dan `STRUCT<...>` perlu format manual.

## Test

```bash
pip install pytest
pytest -q
```
