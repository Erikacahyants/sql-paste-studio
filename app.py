"""SQL Paste Studio — paste text, inspect columns, and copy SQL."""
from __future__ import annotations

import streamlit as st

from formatter import (
    format_schema_sql,
    parse_hive,
    parse_schema,
    validate_columns,
)


st.set_page_config(page_title="SQL Paste Studio", page_icon="⚡", layout="wide")

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
      <h1>SQL Paste Studio <span style="color:#70e3cb">⚡</span></h1>
      <p>Sekali paste daftar kolom atau schema, langsung dapat STG, TXF, dan SRI. Periksa hasilnya, lalu salin blok yang dibutuhkan.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

SCHEMA_SAMPLE = """PERIODE varchar(100)
KODE_CABANG varchar(20)
SALDO decimal(18,2)
TGL date"""
HIVE_SAMPLE = """| createtab_stmt |
| -------------- |
| CREATE VIEW `prd_txf_datalake`.`contoh` AS SELECT |
| CAST(TRIM(`sumber`.`periode`) AS VARCHAR(100)) AS `PERIODE`, |
| CAST(TRIM(`sumber`.`saldo`) AS DECIMAL(18,2)) AS `SALDO`, |
| TO_DATE(`sumber`.`as_of_date`) AS `AS_OF_DATE` |
| FROM `prd_db_pms_stg`.`sumber` |"""

st.session_state.setdefault("schema_text", SCHEMA_SAMPLE)
st.session_state.setdefault("hive_text", HIVE_SAMPLE)

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


def input_actions(key: str, sample: str) -> None:
    example, clear = st.columns(2)
    with example:
        if st.button("Isi contoh", key=f"{key}_example", use_container_width=True):
            st.session_state[f"{key}_text"] = sample
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


tab_schema, tab_hive, tab_help = st.tabs(["Generator STG / TXF / SRI", "Reverse SQL Hive", "Panduan"])

with tab_schema:
    left, right = st.columns([1, 1], gap="large")
    with left, st.container(border=True):
        st.markdown('<div class="step">01 / Input</div>', unsafe_allow_html=True)
        st.subheader("Daftar kolom dan tipe")
        st.markdown('<div class="section-note">Contoh: PERIODE varchar(100), satu kolom per baris. Nama tanpa tipe dianggap STRING.</div>', unsafe_allow_html=True)
        schema_delimiter = delimiter_picker("schema")
        input_actions("schema", SCHEMA_SAMPLE)
        schema_raw = st.text_area(
            "Teks schema", key="schema_text", height=290,
            placeholder="PERIODE varchar(100)\nSALDO decimal(18,2)\nTGL date",
        )
        st.caption("Bisa juga: PERIODE|@~varchar|@~100, daftar A|B|C, atau beberapa deklarasi dipisahkan koma.")
        with st.expander("Pengaturan SQL"):
            convert_char = st.toggle("Ubah CHAR menjadi VARCHAR", value=False)
            quote_schema = st.toggle("Gunakan backtick", value=False)
            stg_comment = st.toggle("Tambahkan COMMENT di STG", value=False)
    with right, st.container(border=True):
        st.markdown('<div class="step">02 / Periksa & salin</div>', unsafe_allow_html=True)
        st.subheader("Hasil otomatis")
        schema_cols = parse_schema(schema_raw, delimiter=schema_delimiter) if schema_delimiter else []
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
                st.markdown(f"**{title}** · {description}")
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
        st.caption(f"{len(hive_result.columns)} kolom terbaca · sumber: {hive_result.source or 'belum ada'}")
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
                st.markdown("**SQL VIEW rapi** · hasil reverse dari Hive")
                st.code(hive_result.clean_sql, language="sql", wrap_lines=True)
            hive_outputs = format_schema_sql(
                hive_result.columns, quote=hive_quote,
                char_to_varchar=hive_convert_char, stg_comment=hive_stg_comment,
            )
            for title, description in [
                ("STG", "Semua STRING"), ("TXF", "CAST + TRIM"), ("SRI", "Kolom bertipe rapi"),
            ]:
                st.markdown(f"**{title}** · {description}")
                st.code(hive_outputs[title], language="sql", wrap_lines=True)
            st.caption("Salin tiap blok lewat ikon di kanan atasnya.")
        elif hive_errors or hive_result.warnings:
            st.warning("Ada bagian input yang belum terbaca. Periksa teks Hive sebelum menyalin SQL.")
        else:
            st.info("Paste SQL atau hasil DESCRIBE dari Hive di sebelah kiri.")

with tab_help:
    st.subheader("Panduan singkat")
    st.markdown(
        """
1. **Paste nama dan tipe.** Contoh: `PERIODE varchar(100)` dan `SALDO decimal(18,2)`, satu per baris. Boleh juga dipisahkan koma dalam satu baris.
2. **Pilih pemisah bila perlu.** Otomatis mengenali TAB, `|@~`, `|`, dan koma. Pilih **Kustom** untuk pemisah lain. Format tabel seperti `PERIODE|@~varchar|@~100` juga didukung.
3. **Periksa pratinjau.** Nama tanpa tipe memakai `STRING`. Spasi berlebih, baris kosong, dan pemisah di tepi input dirapikan.
4. **Salin hasil.** STG berisi `STRING`, TXF berisi `CAST(TRIM(...))`, dan SRI memakai tipe input. Ketiganya langsung tampil.

**Reverse SQL Hive:** paste `CREATE VIEW ... AS SELECT`, `CREATE TABLE` / `SHOW CREATE TABLE`, atau hasil `DESCRIBE` dari Hive/Beeline. Tabel `createtab_stmt` hasil copy Hive akan dibuka. Ekspresi `CAST(TRIM(...))` dan `TO_DATE(...)` dibaca, lalu SQL view, STG, TXF, dan SRI ditampilkan.

SQL mengikuti gaya Hive/Impala. Periksa kembali hasil sebelum menjalankannya. Input diproses di server tempat aplikasi berjalan, jadi ikuti kebijakan perusahaan untuk data sensitif.
        """
    )

st.divider()
st.caption("SQL Paste Studio · Hanya menghasilkan teks SQL; tidak terhubung ke database.")
