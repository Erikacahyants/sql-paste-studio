"""BDE Tools — paste text, inspect columns, and copy SQL."""
from __future__ import annotations

import streamlit as st
from masking import mask_text, restore_text
from result_masking import parse_result, mask_result, detect_sensitive_columns

from formatter import (
    format_schema_sql,
    parse_hive,
    parse_schema,
    validate_columns,
)


st.set_page_config(page_title="BDE Tools", page_icon="⚡", layout="wide")

st.markdown(
    """
    <style>
      :root {color-scheme: dark;}
      .block-container {max-width: 1320px; padding-top: 2rem; padding-bottom: 3rem;}
      h1, h2, h3 {letter-spacing: -.035em;}
      [data-testid="stHeader"] {background: transparent;}
      [data-testid="stVerticalBlockBorderWrapper"] {border-color: #30415b; border-radius: 16px;}
      [data-baseweb="tab-list"] {gap: .6rem;}
      [data-baseweb="tab"] {border-radius: 10px 10px 0 0; padding: .8rem 1.2rem;}
      .stTextArea textarea, .stCodeBlock code {font-family: Consolas, 'Courier New', monospace !important;}
      .stTextArea textarea {font-size: .92rem; line-height: 1.55;}
      .hero {padding: 1.2rem 0 1.4rem;}
      .hero .eyebrow {color: #70e3cb; font-size: .75rem; font-weight: 800; letter-spacing: .16em;}
      .hero h1 {font-size: clamp(2.3rem, 4vw, 3.6rem); margin: .3rem 0 .45rem; line-height: 1.07;}
      .hero p {max-width: 740px; color: #adbed3; font-size: 1.02rem; line-height: 1.6; margin: 0;}
      .step {color: #70e3cb; font-size: .8rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase;}
      .section-note {color: #a9bad0; margin: -.1rem 0 1rem; font-size: .91rem;}
      footer {visibility: hidden;}
    </style>
    <div class="hero">
      <div class="eyebrow">DATA ENGINEERING / SQL UTILITY</div>
      <h1>BDE Tools <span style="color:#70e3cb">⚡</span></h1>
      <p>Sekali paste daftar kolom atau schema, langsung dapat STG, TXF, dan SRI. Periksa hasilnya, lalu salin blok yang dibutuhkan.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

SCHEMA_SAMPLE = """PERIODE varchar(100)
KODE_CABANG varchar(20)
SALDO decimal(18,2)
TGL date"""
HEADER_SAMPLE = "PERIODE|KODE_CABANG|NO REK|SALDO"
HIVE_SAMPLE = """| createtab_stmt |
| -------------- |
| CREATE VIEW `prd_txf_datalake`.`contoh` AS SELECT |
| CAST(TRIM(`sumber`.`periode`) AS VARCHAR(100)) AS `PERIODE`, |
| CAST(TRIM(`sumber`.`saldo`) AS DECIMAL(18,2)) AS `SALDO`, |
| TO_DATE(`sumber`.`as_of_date`) AS `AS_OF_DATE` |
| FROM `prd_db_pms_stg`.`sumber` |"""

st.session_state.setdefault("schema_text", SCHEMA_SAMPLE)
st.session_state.setdefault("hive_text", HIVE_SAMPLE)

MASKING_SAMPLE = '''#!/bin/bash
SCRIPT_PATH="/x/x/bot/s/f_147/tXLON_102"
DB_NAME="prd_finance"
TABLE_NAME="daily_balance"
SSH_USER="etl_user"
SSH_HOST="warehouse.internal"
ssh -p 22 "${SSH_USER}@${SSH_HOST}" <<'REMOTE'
beeline -u 'jdbc:hive2://10.20.30.40:10000/prd_finance' -e "
INSERT OVERWRITE TABLE prd_finance.daily_balance
SELECT * FROM raw_finance.transactions;
"
REMOTE
'''
st.session_state.setdefault("masking_text", "")
st.session_state.setdefault("masking_mappings", [])
st.session_state.setdefault("restore_text", "")

DELIMITER_CHOICES = ["Otomatis", "|", "|@~", "TAB", "Koma", "Baris baru", "Kustom"]


def delimiter_picker(key: str) -> str | None:
    choice = st.selectbox(
        "Pemisah kolom", DELIMITER_CHOICES, key=f"{key}_delimiter",
        help="Otomatis mendeteksi TAB, |@~, |, atau koma di setiap baris. Pilih Kustom untuk pemisah lain.",
    )
    if choice == "Kustom":
        custom = st.text_input("Isi pemisah", key=f"{key}_custom", placeholder="Contoh: ; atau ||")
        if not custom:
            st.warning("Isi pemisah kustom terlebih dahulu.")
            return None
        return custom
    return {"Otomatis": "auto", "TAB": "\t", "Koma": ",", "Baris baru": "\n"}.get(choice, choice)


def input_actions(key: str, sample: str, header_sample: str | None = None) -> None:
    buttons = st.columns(3 if header_sample else 2)
    example, clear = buttons[0], buttons[-1]
    with example:
        if st.button("Contoh bertipe" if header_sample else "Isi contoh", key=f"{key}_example", use_container_width=True):
            st.session_state[f"{key}_text"] = sample
            st.rerun()
    if header_sample:
        with buttons[1]:
            if st.button("Contoh header", key=f"{key}_header_example", use_container_width=True):
                st.session_state[f"{key}_text"] = header_sample
                st.rerun()
    with clear:
        if st.button("Bersihkan", key=f"{key}_clear", use_container_width=True):
            st.session_state[f"{key}_text"] = ""
            st.rerun()


def show_errors(errors: list[str]) -> None:
    for error in errors[:8]:
        st.error(error)
    if len(errors) > 8:
        st.error(f"Ada {len(errors) - 8} masalah lain. Periksa input dan pratinjau kolom.")


tab_schema, tab_hive, tab_masking, tab_results, tab_help = st.tabs(["Generator STG / TXF / SRI", "Reverse SQL Hive", "Table Masking", "Masking Hasil Query", "Panduan"])

with tab_schema:
    left, right = st.columns([1, 1], gap="large")
    with left, st.container(border=True):
        st.markdown('<div class="step">01 / Input</div>', unsafe_allow_html=True)
        st.subheader("Daftar kolom dan tipe")
        st.markdown('<div class="section-note">Paste header dengan delimiter, atau daftar nama dan tipe. Header tanpa tipe otomatis menjadi STRING.</div>', unsafe_allow_html=True)
        schema_input_mode = st.selectbox(
            "Bentuk input", ["Deteksi otomatis", "Header saja"],
            help="Pilih Header saja bila teks yang dipaste adalah baris nama kolom dari Excel atau file data.",
        )
        schema_delimiter = delimiter_picker("schema")
        input_actions("schema", SCHEMA_SAMPLE, HEADER_SAMPLE)
        schema_raw = st.text_area(
            "Teks schema", key="schema_text", height=290,
            placeholder="PERIODE varchar(100)\nSALDO decimal(18,2)\nTGL date",
        )
        st.caption("Contoh header: A|B|C, A|@~B|@~C, atau dari Excel (TAB). Nama ber-spasi jadi underscore.")
        with st.expander("Pengaturan SQL"):
            convert_char = st.toggle("Ubah CHAR menjadi VARCHAR", value=False)
            quote_schema = st.toggle("Gunakan backtick", value=False)
            stg_comment = st.toggle("Tambahkan COMMENT di STG", value=False)
    with right, st.container(border=True):
        st.markdown('<div class="step">02 / Periksa & salin</div>', unsafe_allow_html=True)
        st.subheader("Hasil otomatis")
        schema_cols = parse_schema(
            schema_raw, delimiter=schema_delimiter,
            input_mode="header" if schema_input_mode == "Header saja" else "auto",
        ) if schema_delimiter else []
        schema_errors = validate_columns(schema_cols, strict_type=True)
        missing = sum(col.data_type.upper() == "STRING" for col in schema_cols)
        st.caption(f"{len(schema_cols)} kolom terbaca · {missing} tanpa tipe eksplisit → STRING")
        if schema_cols:
            with st.expander("Pratinjau kolom dan tipe", expanded=bool(schema_errors)):
                st.dataframe(
                    [{"No": i, "Nama kolom": col.name, "Tipe": col.data_type}
                     for i, col in enumerate(schema_cols, 1)],
                    hide_index=True, use_container_width=True,
                )
        show_errors(schema_errors)
        if schema_cols and not schema_errors:
            outputs = format_schema_sql(
                schema_cols, quote=quote_schema,
                char_to_varchar=convert_char, stg_comment=stg_comment,
            )
            for title, description in [
                ("STG", "Semua STRING"), ("TXF", "CAST + TRIM"), ("SRI", "Tipe asli"),
            ]:
                row_count = len(outputs[title].splitlines())
                st.markdown(f"**{title}** · {description} · **{row_count} baris SQL**")
                st.code(outputs[title], language="sql", wrap_lines=True)
            st.caption("Salin tiap blok lewat ikon di kanan atasnya.")
        elif schema_errors:
            st.warning("Perbaiki schema atau pemisah sebelum menyalin SQL.")
        elif schema_delimiter:
            st.info("Paste daftar kolom atau schema di sebelah kiri untuk melihat ketiga hasil.")

with tab_hive:
    left, right = st.columns([1, 1], gap="large")
    with left, st.container(border=True):
        st.markdown('<div class="step">01 / Paste dari Hive</div>', unsafe_allow_html=True)
        st.subheader("SQL atau hasil DESCRIBE")
        st.markdown('<div class="section-note">Paste CREATE VIEW, SHOW CREATE TABLE, CREATE TABLE, atau DESCRIBE dari Hive/Beeline.</div>', unsafe_allow_html=True)
        input_actions("hive", HIVE_SAMPLE)
        hive_raw = st.text_area(
            "Teks dari Hive", key="hive_text", height=340,
            placeholder="CREATE TABLE db.nama_tabel (\n  PERIODE varchar(100),\n  SALDO decimal(18,2)\n);",
        )
        st.caption("Bisa paste tabel createtab_stmt seperti hasil copy Hive. Garis tabel dan header akan dibersihkan otomatis.")
        with st.expander("Pengaturan SQL Hive"):
            hive_convert_char = st.toggle("Ubah CHAR menjadi VARCHAR", value=False, key="hive_convert_char")
            hive_quote = st.toggle("Gunakan backtick", value=False, key="hive_quote")
            hive_stg_comment = st.toggle("Tambahkan COMMENT di STG", value=False, key="hive_stg_comment")
    with right, st.container(border=True):
        st.markdown('<div class="step">02 / Periksa & salin</div>', unsafe_allow_html=True)
        st.subheader("SQL yang sudah dirapikan")
        hive_result = parse_hive(hive_raw)
        hive_errors = validate_columns(hive_result.columns, strict_type=True)
        st.caption(f"{len(hive_result.columns)} kolom terbaca · format: {hive_result.source or 'belum ada'}")
        if hive_result.object_name or hive_result.from_table:
            object_box, source_box = st.columns(2)
            with object_box:
                st.caption("Nama VIEW / TABLE")
                st.code(hive_result.object_name or "—", language=None)
            with source_box:
                st.caption("Tabel sumber (FROM)")
                st.code(hive_result.from_table or "—", language=None)
            if hive_result.from_table:
                original_name = hive_result.from_table.rsplit(".", 1)[-1].strip("`")
                st.caption(f"Nama tabel asli: `{original_name}`")
        if hive_result.columns:
            with st.expander("Pratinjau kolom dan tipe", expanded=bool(hive_errors or hive_result.warnings)):
                st.dataframe(
                    [{"No": i, "Nama kolom": col.name, "Kolom sumber": col.source_name or col.name, "Tipe": col.data_type}
                     for i, col in enumerate(hive_result.columns, 1)],
                    hide_index=True, use_container_width=True,
                )
        show_errors(hive_result.warnings + hive_errors)
        if hive_result.columns and not hive_errors and not hive_result.warnings:
            if hive_result.clean_sql:
                row_count = len(hive_result.clean_sql.splitlines())
                st.markdown(f"**SQL VIEW rapi** · hasil reverse dari Hive · **{row_count} baris SQL**")
                st.code(hive_result.clean_sql, language="sql", wrap_lines=True)
            hive_outputs = format_schema_sql(
                hive_result.columns, quote=hive_quote,
                char_to_varchar=hive_convert_char, stg_comment=hive_stg_comment,
            )
            for title, description in [
                ("STG", "Semua STRING"), ("TXF", "CAST + TRIM"), ("SRI", "Kolom bertipe rapi"),
            ]:
                row_count = len(hive_outputs[title].splitlines())
                st.markdown(f"**{title}** · {description} · **{row_count} baris SQL**")
                st.code(hive_outputs[title], language="sql", wrap_lines=True)
            st.caption("Salin tiap blok lewat ikon di kanan atasnya.")
        elif hive_errors or hive_result.warnings:
            st.warning("Ada bagian input yang belum terbaca. Periksa teks Hive sebelum menyalin SQL.")
        else:
            st.info("Paste SQL atau hasil DESCRIBE dari Hive di sebelah kiri.")

with tab_masking:
    st.caption("Mapping tersimpan sementara di memori sesi ini, tanpa file atau database. Refresh / sesi baru dapat menghilangkan mapping. Pertahankan alias persis seperti hasil masking saat meminta query.")
    if st.button("Hapus mapping & input sesi masking", key="reset_masking_session"):
        st.session_state["masking_mappings"] = []
        for key in ("masking_text", "masking_dbs", "masking_tables", "masking_extra", "restore_text"):
            st.session_state[key] = ""
        st.rerun()
    left, right = st.columns([1, 1], gap="large")
    with left, st.container(border=True):
        st.markdown('<div class="step">01 / Paste script</div>', unsafe_allow_html=True)
        st.subheader("Table Masking")
        st.caption("Paste SQL atau teks shell script untuk menyamarkan nama database, tabel, IP, user/host SSH, dan path folder/file.")
        input_actions("masking", MASKING_SAMPLE)
        masking_raw = st.text_area("SQL / shell script", key="masking_text", height=360)
        masking_ip = st.toggle("Masking alamat IP", value=True)
        masking_ssh = st.toggle("Masking user dan host SSH", value=True)
        masking_paths = st.toggle("Masking path folder / file", value=True)
        st.caption("Contoh path: /x/x/bot/s/f_147/tXLON_102 menjadi PATH_001. Path yang sama memakai alias yang sama.")
        with st.expander("Nama tambahan yang perlu dimasking"):
            st.caption("Satu nilai asli per baris. Gunakan ini untuk nama dinamis atau pola yang belum terdeteksi otomatis.")
            masking_dbs = st.text_area("Nama database tambahan", key="masking_dbs")
            masking_tables = st.text_area("Nama tabel tambahan", key="masking_tables")
            masking_extra = st.text_area("Teks lainnya (misalnya path atau credential)", key="masking_extra")
        st.caption("Hanya mengolah teks; script tidak dijalankan dan koneksi SSH tidak dibuka.")
    with right, st.container(border=True):
        st.markdown('<div class="step">02 / Periksa & salin</div>', unsafe_allow_html=True)
        st.subheader("Script hasil masking")
        if masking_raw.strip():
            masked = mask_text(
                masking_raw, tables=masking_tables, databases=masking_dbs,
                extra=masking_extra, mask_ip=masking_ip, mask_ssh=masking_ssh,
                mask_paths=masking_paths,
                mappings=st.session_state["masking_mappings"],
            )
            saved = {row["Asli"]: row for row in st.session_state["masking_mappings"]}
            saved.update({row["Asli"]: row for row in masked.mappings})
            st.session_state["masking_mappings"] = list(saved.values())
            st.caption(f"{len(masked.mappings)} nilai unik dimasking. Nilai yang sama memakai alias yang sama.")
            st.code(masked.text, language="bash", wrap_lines=True)
            st.download_button("Download hasil masking", data=masked.text,
                               file_name="masked_script.sh", mime="text/plain")
            if masked.mappings:
                with st.expander("Lihat mapping (berisi nama asli)"):
                    st.dataframe(masked.mappings, hide_index=True, use_container_width=True)
            else:
                st.info("Belum ada nilai yang terdeteksi. Isi nama tambahan bila perlu.")
            st.warning("Deteksi otomatis bersifat best-effort. Periksa hasil sebelum dibagikan; password, key, nama dinamis, dan pola SQL/SSH lain bisa belum tersamarkan. Tambahkan nilai yang masih terlihat lewat nama tambahan.")
        else:
            st.info("Paste script di sebelah kiri atau klik Isi contoh.")

    st.divider()
    st.subheader("Masukkan Query")
    st.caption(f'{len(st.session_state["masking_mappings"])} mapping tersimpan di sesi. Bersihkan input masking tidak menghapus mapping; gunakan tombol Hapus mapping untuk memulai pekerjaan baru.')
    restore_left, restore_right = st.columns(2, gap="large")
    with restore_left:
        restore_raw = st.text_area(
            "Paste query disini", key="restore_text", height=260,
            placeholder="SELECT * FROM DB_001.TABLE_001;",
        )
        st.caption("Gunakan alias dari hasil masking (misalnya DB_001.TABLE_001). Alias yang diganti GPT menjadi db1.table1 tidak dapat dicocokkan otomatis. Pemulihan berlaku juga di komentar/string.")
    with restore_right:
        if restore_raw.strip() and st.session_state["masking_mappings"]:
            restored = restore_text(restore_raw, st.session_state["masking_mappings"])
            st.caption(f"{len(restored.mappings)} alias unik dipulihkan ke nilai asli.")
            st.code(restored.text, language="sql", wrap_lines=True)
            st.download_button("Download query asli", data=restored.text,
                               file_name="restored_query.sql", mime="text/plain")
            st.caption("Hasil ini berisi nilai asli. Alias yang tidak ada dalam mapping tetap dibiarkan; periksa sebelum digunakan.")
        elif restore_raw.strip():
            st.info("Mapping sesi belum tersedia. Masking script asli terlebih dahulu.")
        else:
            st.info("Paste query disini untuk otomatis mengembalikan nama database, tabel, dan nilai lain yang dimasking.")

with tab_results:
    st.subheader("Masking Hasil Query Impala")
    st.caption("Paste hasil data beserta header. Kolom sensitif otomatis dipilih berdasarkan namanya; tambahkan atau lepas pilihan sesuai kebutuhan. Mendukung copy TAB, CSV, dan tabel dengan pemisah |.")
    if st.button("Hapus input hasil query", key="clear_query_results"):
        st.session_state["query_results_text"] = ""
        st.session_state["query_results_columns"] = []
        st.session_state.pop("query_results_headers", None)
        st.rerun()
    result_raw = st.text_area("Hasil query dari Impala", key="query_results_text", height=240,
                              placeholder="nama\tno_rekening\tsaldo\nBudi\t0012345678\t150000")
    result_separator = st.selectbox("Pemisah hasil query", ["Otomatis", "TAB", "Koma", "|"], key="query_results_separator")
    try:
        result_headers, result_rows = parse_result(result_raw, {"Otomatis": "auto", "TAB": "\t", "Koma": ",", "|": "|"}[result_separator])
    except ValueError as exc:
        st.error(str(exc))
    else:
        if result_headers:
            # Include position so duplicate column names can be selected independently.
            result_options = [f"{i + 1}. {name}" for i, name in enumerate(result_headers)]
            detected_columns = detect_sensitive_columns(result_headers)
            detect_again = st.button("Pilih ulang hasil deteksi otomatis", key="query_results_detect")
            if st.session_state.get("query_results_headers") != result_headers or detect_again:
                st.session_state["query_results_columns"] = [result_options[i] for i in detected_columns]
                st.session_state["query_results_headers"] = list(result_headers)
            st.caption(f"{len(detected_columns)} kolom terdeteksi dari nama seperti no, nomor, number, key, CIF, name/nama, address/alamat, rekening, email, dan telepon. Deteksi berdasarkan header saja; periksa pilihan sebelum menyalin. Pilihan manual tetap dipakai selama header tidak berubah.")
            chosen_columns = st.multiselect("Kolom sensitif yang disamarkan", result_options, key="query_results_columns")
            st.caption(f"{len(result_rows)} baris data · {len(result_headers)} kolom. Header dan kolom yang tidak dipilih tetap asli. Nilai berulang dalam satu kolom memakai alias yang sama; sel kosong tetap kosong.")
            if chosen_columns and result_rows:
                masked_result = mask_result(result_headers, result_rows, [result_options.index(value) for value in chosen_columns])
                st.markdown("**Hasil untuk disalin ke AI**")
                st.code(masked_result, language=None, wrap_lines=False)
                st.download_button("Download hasil data masking", data=masked_result,
                                   file_name="masked_results.tsv", mime="text/tab-separated-values")
                st.caption("Periksa header dan kolom yang tidak dipilih sebelum dibagikan. Data diproses di server aplikasi; fitur ini tidak menyimpan data ke file/database atau mengirimnya ke AI. Alias data hanya berlaku untuk input ini.")
            elif not result_rows:
                st.info("Header sudah terbaca. Paste juga baris hasil query.")
            else:
                st.info("Pilih minimal satu kolom sensitif untuk menampilkan hasil masking.")

with tab_help:
    st.subheader("Panduan singkat")
    st.markdown(
        """
1. **Paste header atau nama dan tipe.** Header seperti `PERIODE|NO REK|SALDO` otomatis menjadi tiga kolom STRING. Untuk tipe khusus, tulis `PERIODE varchar(100)` dan `SALDO decimal(18,2)`.
2. **Pilih pemisah bila perlu.** Otomatis mengenali TAB, `|@~`, `|`, dan koma. Pilih **Kustom** untuk pemisah lain. Format tabel seperti `PERIODE|@~varchar|@~100` juga didukung.
3. **Periksa pratinjau.** Nama tanpa tipe memakai `STRING`. Nama seperti `no rek string` dibaca sebagai `no_rek STRING`. Spasi berlebih, baris kosong, dan pemisah di tepi input dirapikan.
4. **Salin hasil.** STG berisi `STRING`, TXF berisi `CAST(TRIM(...))`, dan SRI memakai tipe input. Jumlah baris tampil di atas setiap blok; angka itu tidak ikut tersalin.

**Reverse SQL Hive:** paste `CREATE VIEW ... AS SELECT`, `CREATE TABLE` / `SHOW CREATE TABLE`, atau hasil `DESCRIBE` dari Hive/Beeline. Tabel `createtab_stmt` hasil copy Hive akan dibuka. Nama VIEW/TABLE dan tabel sumber pada `FROM` ditampilkan. Ekspresi `CAST(TRIM(...))` dan `TO_DATE(...)` dibaca, lalu SQL view, STG, TXF, dan SRI ditampilkan.

**Table Masking:** paste SQL atau shell script. Database/tabel pada konteks SQL umum dan variabel seperti `DB_NAME` / `TABLE_NAME` diganti alias `DB_001` / `TABLE_001`. Opsi IP dan SSH menyamarkan alamat IP serta user/host SSH. Tambahkan nilai yang belum terdeteksi, satu per baris. Penggantian literal bersifat case-sensitive dan juga berlaku di komentar/string. Salin blok hasil atau download script; mapping nama asli hanya ditampilkan di expander terpisah. Periksa hasil sebelum membagikan script.

SQL mengikuti gaya Hive/Impala. Periksa kembali hasil sebelum menjalankannya. Input diproses di server tempat aplikasi berjalan, jadi ikuti kebijakan perusahaan untuk data sensitif.
        """
    )

st.divider()
st.caption("BDE Tools · Hanya menghasilkan teks SQL; tidak terhubung ke database.")
