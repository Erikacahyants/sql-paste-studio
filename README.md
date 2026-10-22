# SQL Paste Studio ⚡

Aplikasi web **Streamlit** untuk menghasilkan tiga blok SQL **STG / TXF / SRI** sekaligus dari daftar kolom atau schema.

## Fitur

- Pilih pemisah otomatis atau manual: `|`, `|@~`, TAB, koma, baris baru, atau teks kustom seperti `;;`.
- Paste deklarasi seperti `PERIODE varchar(100)` dan `SALDO decimal(18,2)`, satu per baris atau dipisahkan koma. Nama tanpa tipe memakai `STRING`.
- Spasi berlebih, baris kosong, dan pemisah di tepi input dirapikan. Pratinjau memperlihatkan nama dan tipe yang benar-benar terbaca sebelum SQL disalin.
- Paste schema `nama|tipe|panjang|scale` atau tabel Markdown. **STG** memakai STRING, **TXF** berisi `CAST(TRIM(KOLOM) AS TIPE) AS KOLOM`, dan **SRI** memakai tipe input.
- Tab **Reverse SQL Hive** membaca `CREATE VIEW ... AS SELECT` berisi `CAST(TRIM(...))` atau `TO_DATE(...)`, `CREATE TABLE`, `SHOW CREATE TABLE`, dan output `DESCRIBE` Hive/Beeline. Pembungkus tabel `createtab_stmt` dan metadata dibersihkan sebelum menghasilkan tiga blok SQL. Untuk view, SQL asal yang sudah dirapikan juga ditampilkan.
- CHAR(n) dapat diganti dengan VARCHAR(n) pada SRI/TXF bila opsi diaktifkan.
- SQL langsung tampil dan bisa disalin lewat ikon salin bawaan `st.code` (pojok kanan atas blok kode).
- Validasi nama kolom, kolom duplikat, tipe yang belum lengkap, serta sel schema yang salah format.

## Jalankan lokal

Pastikan Python 3.10+ telah terpasang.

```bash
pip install -r requirements.txt
streamlit run app.py
```

Browser akan membuka `http://localhost:8501`.

## Deploy Streamlit Community Cloud

1. Upload semua file/folder (`app.py`, `formatter.py`, `requirements.txt`, `.streamlit/config.toml`) ke sebuah repository GitHub.
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
