import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from formatter import (
    parse_hive, parse_quick, parse_schema, format_string_ddl,
    format_schema_sql, validate_columns, normalize_type,
)


def test_pipe_line_and_exact_sql():
    cols = parse_quick("PERIODE|KODE_CABANG|DEBET|KREDIT")
    assert [c.name for c in cols] == ["PERIODE", "KODE_CABANG", "DEBET", "KREDIT"]
    assert format_string_ddl(cols) == (
        "`PERIODE` string COMMENT 'from deserializer',\n"
        "`KODE_CABANG` string COMMENT 'from deserializer',\n"
        "`DEBET` string COMMENT 'from deserializer',\n"
        "`KREDIT` string COMMENT 'from deserializer'"
    )


def test_excel_tab_header():
    cols = parse_quick("A\tB\tC\n10\t11\t12")
    assert [c.name for c in cols] == ["A", "B", "C"]


def test_one_per_line_and_sql_declarations():
    assert [c.name for c in parse_quick("COL_A\nCOL_B\nCOL_C")] == ["COL_A", "COL_B", "COL_C"]
    assert [c.name for c in parse_quick("A varchar(20),\nB INT,\nC DATE")] == ["A", "B", "C"]


def test_markdown_header():
    t = "| PERIODE | CABANG |\n| ---- | ----- |\n| 2026 | 001 |"
    assert [c.name for c in parse_quick(t)] == ["PERIODE", "CABANG"]


def test_schema_rows_and_conversion():
    cols = parse_schema("PRF_ID|char|2\nNRF_ID|varchar|5\nSALDO|decimal|18|2\nTGL|date")
    assert [c.data_type for c in cols] == ["char(2)", "varchar(5)", "decimal(18,2)", "date"]
    outputs = format_schema_sql(cols)
    assert outputs["SRI"] == "PRF_ID VARCHAR(2),\nNRF_ID VARCHAR(5),\nSALDO DECIMAL(18,2),\nTGL DATE"
    assert outputs["STG"] == "PRF_ID STRING,\nNRF_ID STRING,\nSALDO STRING,\nTGL STRING"
    assert "CAST(TRIM(PRF_ID) AS VARCHAR(2)) AS PRF_ID" in outputs["TXF"]


def test_schema_markdown():
    raw = """| COLUMN | TYPE | LENGTH | SCALE |
| --- | --- | --- | --- |
| A | char | 5 | |
| B | decimal | 10 | 3 |"""
    cols = parse_schema(raw)
    assert [c.name for c in cols] == ["A", "B"]
    assert [c.data_type for c in cols] == ["char(5)", "decimal(10,3)"]


def test_schema_name_only():
    cols = parse_schema("A|B|C")
    assert [c.name for c in cols] == ["A", "B", "C"]
    assert all(c.data_type == "STRING" for c in cols)


def test_duplicate_and_bad_name():
    assert len(validate_columns(parse_quick("A|a|bad name"))) == 2


def test_comment_escaped_and_comma():
    sql = format_string_ddl(parse_quick("A|B"), comment="owner's", trailing_comma=True)
    assert "owner''s" in sql
    assert sql.endswith(",")


def test_invalid_char_length():
    assert "wajib" in str(pytest.raises(ValueError, normalize_type, "CHAR").value)


def test_decimal_scale():
    with pytest.raises(ValueError):
        normalize_type("DECIMAL(2,5)")


def test_schema_sql_ddl_decimal_and_varchar():
    cols = parse_schema("SALDO DECIMAL(18,2),\nNAMA VARCHAR(50),\nTGL DATE")
    assert [(c.name, c.data_type) for c in cols] == [
        ("SALDO", "DECIMAL(18,2)"), ("NAMA", "VARCHAR(50)"), ("TGL", "DATE")
    ]
    assert not validate_columns(cols, strict_type=True)

def test_real_18_column_example():
    raw = "PERIODE|KODE_CABANG|SANDI_ANTASENA|NAMA_POS|SL|CCY|DEBET|KREDIT|KETERANGAN|NO_REK|JENIS_RECLASS|SEGMENT_DIV_OWNER|CHANNEL_OWNER_L1|OUTPUT_L1|OUTPUT_L2|OUTPUT_L3|CHANNEL_OWNER_L3|AMOUNT_FTP_SCMR_YTD"
    out = format_string_ddl(parse_quick(raw))
    assert out.count(" COMMENT 'from deserializer'") == 18
    assert out.splitlines()[-1] == "`AMOUNT_FTP_SCMR_YTD` string COMMENT 'from deserializer'"


def test_single_typed_row_in_quick_mode():
    assert [c.name for c in parse_quick("PRF_ID|char|2")] == ["PRF_ID"]


def test_multi_character_delimiter_auto_and_manual_with_messy_spacing():
    raw = "\ufeff  A |@~ B |@~ C |@~  \n\n"
    assert [c.name for c in parse_quick(raw)] == ["A", "B", "C"]
    assert [c.name for c in parse_quick(raw, delimiter="|@~")] == ["A", "B", "C"]
    assert [c.name for c in parse_quick("A ;; B ;; C", delimiter=";;")] == ["A", "B", "C"]


def test_wrapped_quick_header_can_be_combined():
    raw = "A|@~ B |@~\n  C |@~ D  "
    assert [c.name for c in parse_quick(raw, multiline="all")] == ["A", "B", "C", "D"]
    assert [c.name for c in parse_quick(raw, multiline="first")] == ["A", "B"]


def test_schema_multi_character_delimiter_keeps_empty_length_cell():
    raw = "A |@~ char |@~ 2 |@~\n\n B |@~ decimal |@~ 18 |@~ 3 |@~"
    cols = parse_schema(raw)
    assert [(c.name, c.data_type) for c in cols] == [("A", "char(2)"), ("B", "decimal(18,3)")]


def test_schema_malformed_cells_are_reported_instead_of_becoming_string():
    for raw in ("A|@~varcharr|@~20", "A|@~decimal|@~oops|@~2", "A|@~decimal|@~18|@~2|@~extra"):
        assert validate_columns(parse_schema(raw), strict_type=True)


def test_typed_declarations_generate_all_three_outputs():
    raw = "PERIODE varchar(100), SALDO decimal(18,2), TGL date"
    cols = parse_schema(raw)
    assert [(c.name, c.data_type) for c in cols] == [
        ("PERIODE", "varchar(100)"), ("SALDO", "decimal(18,2)"), ("TGL", "date")
    ]
    outputs = format_schema_sql(cols, char_to_varchar=False)
    assert outputs["STG"] == "PERIODE STRING,\nSALDO STRING,\nTGL STRING"
    assert outputs["TXF"] == (
        "CAST(TRIM(PERIODE) AS VARCHAR(100)) AS PERIODE,\n"
        "CAST(TRIM(SALDO) AS DECIMAL(18,2)) AS SALDO,\n"
        "CAST(TRIM(TGL) AS DATE) AS TGL"
    )
    assert outputs["SRI"] == "PERIODE VARCHAR(100),\nSALDO DECIMAL(18,2),\nTGL DATE"


def test_mixed_typed_and_name_only_declarations():
    cols = parse_schema("PERIODE varchar(100),\nKODE_CABANG\nSALDO decimal(18,2)")
    assert [(c.name, c.data_type) for c in cols] == [
        ("PERIODE", "varchar(100)"), ("KODE_CABANG", "STRING"), ("SALDO", "decimal(18,2)")
    ]


def test_char_type_is_preserved_when_conversion_is_off():
    outputs = format_schema_sql(parse_schema("KODE char(2)"), char_to_varchar=False)
    assert outputs["SRI"] == "KODE CHAR(2)"
    assert "AS CHAR(2)" in outputs["TXF"]


def test_reverse_hive_create_table_ignores_table_options_and_comments():
    raw = """CREATE EXTERNAL TABLE IF NOT EXISTS db.contoh (
      `PERIODE` varchar(100) COMMENT 'bulan',
      `SALDO` decimal(18,2),
      `TGL` date
    ) STORED AS PARQUET
    TBLPROPERTIES ('owner'='unit');"""
    result = parse_hive(raw)
    assert result.source == "CREATE TABLE"
    assert result.object_name == "db.contoh"
    assert result.from_table == ""
    assert not result.warnings
    assert [(c.name, c.data_type) for c in result.columns] == [
        ("PERIODE", "varchar(100)"), ("SALDO", "decimal(18,2)"), ("TGL", "date")
    ]
    outputs = format_schema_sql(result.columns, char_to_varchar=False)
    assert outputs["STG"].startswith("PERIODE STRING")
    assert "CAST(TRIM(SALDO) AS DECIMAL(18,2)) AS SALDO" in outputs["TXF"]
    assert "PERIODE VARCHAR(100)" in outputs["SRI"]


def test_reverse_hive_describe_from_beeline_table():
    raw = """+------------+---------------+---------+
| col_name   | data_type     | comment |
+------------+---------------+---------+
| PERIODE    | varchar(100)  | bulan   |
| SALDO      | decimal(18,2) |         |
+------------+---------------+---------+
# Partition Information
| PERIODE    | varchar(100)  |         |"""
    result = parse_hive(raw)
    assert [(c.name, c.data_type) for c in result.columns] == [
        ("PERIODE", "varchar(100)"), ("SALDO", "decimal(18,2)")
    ]
    assert not result.warnings


def test_reverse_hive_describe_tab_and_padded_text():
    raw = """# col_name             data_type          comment
PERIODE                varchar(100)       bulan
SALDO\tdecimal(18,2)\tjumlah saldo"""
    result = parse_hive(raw)
    assert [(c.name, c.data_type) for c in result.columns] == [
        ("PERIODE", "varchar(100)"), ("SALDO", "decimal(18,2)")
    ]


def test_reverse_hive_ignores_beeline_footer_and_partition_section():
    raw = """| col_name | data_type    | comment |
| PERIODE  | varchar(100) |         |
| # Partition Information | | |
| PERIODE  | varchar(100) |         |
2 rows selected (0.2 seconds)"""
    result = parse_hive(raw)
    assert [(c.name, c.data_type) for c in result.columns] == [("PERIODE", "varchar(100)")]
    assert not result.warnings


def test_reverse_hive_create_table_includes_partition_columns():
    raw = """CREATE TABLE db.saldo (
      SALDO decimal(18,2)
    ) PARTITIONED BY (PERIODE varchar(6))
    STORED AS PARQUET"""
    result = parse_hive(raw)
    assert result.object_name == "db.saldo"
    assert [(c.name, c.data_type) for c in result.columns] == [
        ("SALDO", "decimal(18,2)"), ("PERIODE", "varchar(6)")
    ]


def test_reverse_hive_create_view_from_copied_markdown_table():
    raw = r"""| createtab_stmt |
| ------------------------- |
| CREATE VIEW \`prd_txf_datalake\`.\`contoh\` AS SELECT |
| CAST(TRIM(\`sumber\`.\`kode_cabang\`) AS VARCHAR(100)) AS \`KODE_CABANG\`, |
| CAST(TRIM(\`sumber\`.\`nilai_asli\`) AS DECIMAL(18,2)) AS \`SALDO\` |
| FROM \`PRD_DB_PMS_STG\`.\`sumber\` |"""
    result = parse_hive(raw)
    assert result.source == "CREATE VIEW"
    assert result.object_name == "`prd_txf_datalake`.`contoh`"
    assert result.from_table == "`PRD_DB_PMS_STG`.`sumber`"
    assert not result.warnings
    assert [(c.name, c.data_type, c.source_name) for c in result.columns] == [
        ("KODE_CABANG", "VARCHAR(100)", "kode_cabang"),
        ("SALDO", "DECIMAL(18,2)", "nilai_asli"),
    ]
    assert result.clean_sql.startswith("CREATE VIEW `prd_txf_datalake`.`contoh` AS\nSELECT\n")
    assert "\nFROM `PRD_DB_PMS_STG`.`sumber`;" in result.clean_sql
    outputs = format_schema_sql(result.columns, char_to_varchar=False)
    assert outputs["STG"] == "KODE_CABANG STRING,\nSALDO STRING"
    assert "CAST(TRIM(nilai_asli) AS DECIMAL(18,2)) AS SALDO" in outputs["TXF"]
    assert outputs["SRI"] == "KODE_CABANG VARCHAR(100),\nSALDO DECIMAL(18,2)"


def test_reverse_hive_view_mixes_cast_and_to_date():
    raw = r"""| createtab_stmt |
| -------------------------- |
| CREATE VIEW \`db_txf\`.\`contoh\` AS SELECT |
| CAST(TRIM(\`sumber\`.\`rownum\`) AS INTEGER) AS \`ROWNUM\`, |
| CAST(TRIM(\`sumber\`.\`kode\`) AS VARCHAR(100)) AS \`KODE\`, |
| CAST(TRIM(\`sumber\`.\`l1\`) AS VARCHAR(100)) AS \`l1\`, |
| TO_DATE(\`sumber\`.\`as_of_date\`) AS \`AS_OF_DATE\` |
| FROM \`db_stg\`.\`sumber\` |"""
    result = parse_hive(raw)
    assert not result.warnings
    assert not validate_columns(result.columns, strict_type=True)
    assert [c.name for c in result.columns] == ["ROWNUM", "KODE", "l1", "AS_OF_DATE"]
    assert result.columns[-1].data_type == "DATE"
    assert "TO_DATE(`sumber`.`as_of_date`) AS `AS_OF_DATE`" in result.clean_sql
    outputs = format_schema_sql(result.columns, char_to_varchar=False)
    assert outputs["STG"].endswith("AS_OF_DATE STRING")
    assert outputs["TXF"].endswith("TO_DATE(as_of_date) AS AS_OF_DATE")
    assert outputs["SRI"].endswith("AS_OF_DATE DATE")
