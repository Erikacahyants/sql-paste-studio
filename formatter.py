"""Pure parsing and SQL-formatting helpers for SQL Paste Studio.

No Streamlit imports here, so the parsing rules can be unit tested.
"""
from __future__ import annotations

from dataclasses import dataclass
import re


IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TYPE_RE = re.compile(r"^(?P<base>[A-Za-z][A-Za-z0-9_ ]*)(?:\s*\(\s*(?P<length>\d+)\s*(?:,\s*(?P<scale>\d+)\s*)?\))?$", re.I)
DECL_RE = re.compile(
    r"^\s*[`\"']?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[`\"']?\s+"
    r"(?P<type>[A-Za-z][A-Za-z0-9_ ]*(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)"
    r"(?:\s+COMMENT\s+['\"].*?['\"])?\s*,?\s*$", re.I
)
LOOSE_DECL_RE = re.compile(
    r"^\s*(?P<name>.+)\s+(?P<type>[A-Za-z][A-Za-z0-9_]*"
    r"(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)"
    r"(?:\s+COMMENT\s+['\"].*?['\"])?\s*,?\s*$", re.I,
)
IDENT_PART = r"(?:`[A-Za-z_][A-Za-z0-9_]*`|[A-Za-z_][A-Za-z0-9_]*)"
IDENT_PATH = rf"{IDENT_PART}(?:\s*\.\s*{IDENT_PART})*"
CAST_SELECT_RE = re.compile(
    rf"^CAST\s*\(\s*TRIM\s*\(\s*(?P<source>{IDENT_PATH})\s*\)\s+AS\s+"
    rf"(?P<type>[A-Za-z][A-Za-z0-9_ ]*(?:\s*\(\s*\d+\s*(?:,\s*\d+\s*)?\))?)\s*\)"
    rf"\s+AS\s+(?P<alias>{IDENT_PART})$", re.I | re.S,
)
TO_DATE_SELECT_RE = re.compile(
    rf"^TO_DATE\s*\(\s*(?P<source>{IDENT_PATH})\s*\)\s+AS\s+"
    rf"(?P<alias>{IDENT_PART})$", re.I | re.S,
)
VIEW_SELECT_RE = re.compile(
    rf"\bCREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?P<name>{IDENT_PATH})\s+AS\s+SELECT\b",
    re.I | re.S,
)
KNOWN_TYPES = {
    "STRING", "VARCHAR", "CHAR", "TEXT", "INT", "INTEGER", "BIGINT",
    "SMALLINT", "TINYINT", "DECIMAL", "NUMERIC", "NUMBER", "DOUBLE",
    "FLOAT", "REAL", "BOOLEAN", "BOOL", "DATE", "TIMESTAMP", "DATETIME",
    "BINARY", "VARBINARY", "ARRAY", "MAP", "STRUCT",
}
HEADER_NAMES = {"column", "columns", "column_name", "field", "field_name", "kolom", "nama_kolom", "nama kolom", "name", "nama field"}
HEADER_TYPES = {"type", "data_type", "datatype", "tipe", "tipe_data", "data type"}


@dataclass(frozen=True)
class Column:
    name: str
    data_type: str = "STRING"
    source_name: str | None = None
    transform: str | None = None


@dataclass(frozen=True)
class HiveParseResult:
    columns: list[Column]
    source: str
    warnings: list[str]
    clean_sql: str = ""
    object_name: str = ""
    from_table: str = ""


def _clean_text(raw: str) -> list[str]:
    raw = raw.replace("\ufeff", "").replace("\u00a0", " ").replace("\u200b", "").strip()
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("```") or ln.startswith("--"):
            continue
        # Strip SQL INSERT table wrapper when a SQL declaration is pasted.
        if re.match(r"^(?:CREATE|PARTITIONED|ROW FORMAT|STORED|LOCATION|TBLPROPERTIES|WITH SERDEPROPERTIES)\b", ln, re.I):
            continue
        if ln in {"(", ")", ");"}:
            continue
        lines.append(ln)
    return lines


def _is_separator(value: str) -> bool:
    return bool(re.fullmatch(r"\s*:?-{2,}:?\s*", value.strip()))


def _split_commas(line: str) -> list[str]:
    """Split only commas outside SQL type parentheses and quoted text."""
    parts: list[str] = []
    start = depth = 0
    quote = ""
    for i, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            parts.append(line[start:i].strip())
            start = i + 1
    parts.append(line[start:].strip())
    return parts


def _cells(line: str, delimiter: str = "auto") -> list[str]:
    # A typed SQL declaration can contain commas inside DECIMAL(18,2).
    if _sql_decl(line):
        return [line]
    if delimiter == "auto":
        delimiter = next((sep for sep in ("\t", "|@~", "|", ",") if sep in line), "\n")
    if not delimiter:
        raise ValueError("Delimiter tidak boleh kosong.")
    if delimiter == "\n":
        return [line.strip()]
    values = _split_commas(line) if delimiter == "," else line.split(delimiter)
    values = [v.strip() for v in values]
    if delimiter == ",":
        values = [v[1:-1].replace(v[0] * 2, v[0]) if len(v) >= 2 and v[0] in "\"'" and v[-1] == v[0] else v for v in values]
    # Empty fields at the edges commonly come from table borders or a trailing
    # delimiter. Keep empty fields between cells so LENGTH/SCALE stay aligned.
    while len(values) > 1 and not values[0]:
        values.pop(0)
    while len(values) > 1 and not values[-1]:
        values.pop()
    return values


def _remove_quotes(value: str) -> str:
    return value.strip().strip("`\"'").strip()


def _normalize_name(value: str) -> str:
    return re.sub(r"\s+", "_", _remove_quotes(value))


def _sql_decl(line: str) -> Column | None:
    # Parse one declaration, e.g. `PRF_ID` CHAR(2), or SAP_DATE DATE.
    match = DECL_RE.fullmatch(line.strip().rstrip(","))
    if not match:
        return None
    t = match.group("type").strip()
    parts = TYPE_RE.fullmatch(t)
    if not parts or parts.group("base").strip().upper() not in KNOWN_TYPES:
        return None
    return Column(match.group("name"), t)


def _schema_decl(line: str) -> Column | None:
    """Keep even unknown type names so strict validation can report them."""
    match = DECL_RE.fullmatch(line.strip().rstrip(","))
    if match:
        data_type = match.group("type").strip()
        parsed_type = TYPE_RE.fullmatch(data_type)
        if parsed_type and parsed_type.group("base").strip().upper() in KNOWN_TYPES:
            return Column(_normalize_name(match.group("name")), data_type)
    loose = LOOSE_DECL_RE.fullmatch(line)
    if loose:
        data_type = loose.group("type").strip()
        if data_type.split("(", 1)[0].strip().upper() in KNOWN_TYPES:
            return Column(_normalize_name(loose.group("name")), data_type)
    return Column(_normalize_name(match.group("name")), match.group("type").strip()) if match else None


def _parenthesized_block(raw: str, opening: int) -> tuple[str, int] | None:
    """Return the contents and closing position of one SQL parenthesis block."""
    depth = 0
    quote = ""
    for i in range(opening, len(raw)):
        char = raw[i]
        if quote:
            if char == quote:
                quote = ""
        elif char in "\"'`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return raw[opening + 1:i], i
    return None


def _unwrap_createtab_result(raw: str) -> str:
    """Remove the one-column Markdown table wrapped around Hive SHOW CREATE output."""
    lines = raw.splitlines()
    if not any(re.fullmatch(r"\|\s*createtab_stmt\s*\|", line.strip(), re.I) for line in lines[:3]):
        return raw
    content = []
    for line in lines:
        line = line.strip()
        if not line.startswith("|") or not line.endswith("|"):
            continue
        cell = line[1:-1].strip()
        if cell.lower() == "createtab_stmt" or _is_separator(cell):
            continue
        content.append(cell)
    return "\n".join(content)


def _parse_hive_view(text: str) -> HiveParseResult | None:
    sql = _unwrap_createtab_result(text).replace("\\`", "`")
    view = VIEW_SELECT_RE.search(sql)
    if not view:
        return None
    remaining = sql[view.end():]
    from_clause = re.search(r"\bFROM\b", remaining, re.I)
    if not from_clause:
        return HiveParseResult([], "CREATE VIEW", ["Bagian FROM pada CREATE VIEW tidak ditemukan."])
    select_body = remaining[:from_clause.start()]
    tail = re.sub(r"\s+", " ", remaining[from_clause.start():].strip()).rstrip(";")
    columns: list[Column] = []
    formatted: list[str] = []
    warnings: list[str] = []
    for expression in _split_commas(select_body):
        expression = expression.strip()
        if not expression:
            continue
        match = CAST_SELECT_RE.fullmatch(expression)
        date_match = TO_DATE_SELECT_RE.fullmatch(expression) if not match else None
        if date_match:
            source = re.sub(r"\s*\.\s*", ".", date_match.group("source"))
            source_name = _remove_quotes(source.rsplit(".", 1)[-1])
            alias = _remove_quotes(date_match.group("alias"))
            columns.append(Column(alias, "DATE", source_name, "TO_DATE"))
            formatted.append(f"  TO_DATE({source}) AS {date_match.group('alias')}")
            continue
        if not match:
            warnings.append(f"Ekspresi SELECT tidak terbaca: {expression[:90]}")
            continue
        source = re.sub(r"\s*\.\s*", ".", match.group("source"))
        source_name = _remove_quotes(source.rsplit(".", 1)[-1])
        alias = _remove_quotes(match.group("alias"))
        data_type = match.group("type").strip()
        columns.append(Column(alias, data_type, source_name))
        try:
            pretty_type = normalize_type(data_type, char_to_varchar=False)
        except ValueError:
            pretty_type = data_type
        formatted.append(f"  CAST(TRIM({source}) AS {pretty_type}) AS {match.group('alias')}")
    view_name = re.sub(r"\s*\.\s*", ".", view.group("name"))
    clean_sql = f"CREATE VIEW {view_name} AS\nSELECT\n" + ",\n".join(formatted) + f"\n{tail};"
    from_name = re.match(rf"FROM\s+(?P<name>{IDENT_PATH})(?=\s|$)", tail, re.I)
    from_table = re.sub(r"\s*\.\s*", ".", from_name.group("name")) if from_name else ""
    return HiveParseResult(columns, "CREATE VIEW", warnings, clean_sql, view_name, from_table)


def parse_hive(raw: str) -> HiveParseResult:
    """Read common Hive CREATE TABLE and DESCRIBE/Beeline clipboard formats."""
    text = _unwrap_createtab_result(
        raw.replace("\ufeff", "").replace("\u00a0", " ").strip()
    ).replace("\\`", "`")
    if not text:
        return HiveParseResult([], "", [])
    view_result = _parse_hive_view(text)
    if view_result:
        return view_result

    create = re.search(
        rf"\bCREATE\s+(?:EXTERNAL\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        rf"(?P<name>{IDENT_PATH})\s*\(", text, re.I,
    )
    if create:
        table_name = re.sub(r"\s*\.\s*", ".", create.group("name"))
        block = _parenthesized_block(text, create.end() - 1)
        if not block:
            return HiveParseResult([], "CREATE TABLE", ["Kurung daftar kolom CREATE TABLE tidak lengkap."], object_name=table_name)
        body, closing = block
        sections = [body]
        partition = re.search(r"\bPARTITIONED\s+BY\s*\(", text[closing + 1:], re.I)
        if partition:
            partition_opening = closing + 1 + partition.end() - 1
            partition_block = _parenthesized_block(text, partition_opening)
            if partition_block:
                sections.append(partition_block[0])
            else:
                return HiveParseResult([], "CREATE TABLE", ["Kurung PARTITIONED BY tidak lengkap."], object_name=table_name)
        columns: list[Column] = []
        warnings: list[str] = []
        for section in sections:
            section = re.sub(r"(?m)--[^\n]*", "", section)
            for item in _split_commas(section):
                item = item.strip()
                if not item:
                    continue
                declaration = _schema_decl(item)
                if declaration:
                    columns.append(declaration)
                else:
                    warnings.append(f"Tidak terbaca sebagai kolom: {item[:90]}")
        return HiveParseResult(columns, "CREATE TABLE", warnings, object_name=table_name)

    columns = []
    warnings = []
    in_data = False
    for number, original in enumerate(text.splitlines(), 1):
        line = original.strip()
        if not line or line.startswith("```"):
            continue
        if re.match(r"^(?:Time taken:|Fetched:|\d+ rows? selected\b|OK$)", line, re.I):
            continue
        if line.startswith("#"):
            if re.match(r"#\s*(?:Partition Information|Detailed Table Information)", line, re.I):
                break
            continue
        if re.fullmatch(r"[+|\-=: \t]+", line):
            continue
        if line.startswith("|"):
            cells = _cells(line, "|")
        elif "\t" in line:
            cells = _cells(line, "\t")
        else:
            cells = re.split(r"\s{2,}", line, maxsplit=2)
            if len(cells) == 1:
                declaration = _schema_decl(line)
                if declaration:
                    columns.append(declaration)
                    in_data = True
                    continue
        if not cells or not cells[0]:
            continue
        raw_name = _remove_quotes(cells[0]).lstrip("# ")
        if re.match(r"^(?:Partition Information|Detailed Table Information)$", raw_name, re.I):
            break
        name = _normalize_name(raw_name)
        if name.lower() in HEADER_NAMES or name.lower() in {"col_name", "column name"}:
            in_data = True
            continue
        if len(cells) >= 2 and IDENTIFIER_RE.fullmatch(name):
            data_type = _remove_quotes(cells[1])
            columns.append(Column(name, data_type or "STRING"))
            in_data = True
        elif in_data:
            warnings.append(f"Baris {number} tidak terbaca: {line[:90]}")
    return HiveParseResult(columns, "DESCRIBE / tabel Hive", warnings)


def _looks_typed(cells: list[str]) -> bool:
    if len(cells) < 2 or len(cells) > 4:
        return False
    value = TYPE_RE.fullmatch(cells[1].strip())
    return bool(value and value.group("base").strip().upper() in KNOWN_TYPES)


def _from_schema_cells(cells: list[str]) -> Column:
    name = _normalize_name(cells[0])
    t = cells[1].strip() if len(cells) > 1 else "STRING"
    if not t:
        t = "STRING"
    match = TYPE_RE.fullmatch(t)
    # Support rows: COL | varchar | 30, COL | decimal | 18 | 2
    if len(cells) > 4:
        return Column(name, f"{t} [lebih dari 4 sel]")
    length = cells[2].strip() if len(cells) > 2 else ""
    scale = cells[3].strip() if len(cells) > 3 else ""
    if length or scale:
        if match and not match.group("length") and length.isdigit() and (not scale or scale.isdigit()):
            t += f"({int(length)}"
            if scale:
                t += f",{int(scale)}"
            t += ")"
        else:
            t += f" [panjang={length or '-'}, scale={scale or '-'}]"
    return Column(name, t)


def _drop_markdown_separator(lines: list[str], delimiter: str) -> list[str]:
    return [ln for ln in lines if not ("|" in ln and all(_is_separator(c) for c in _cells(ln, delimiter)))]


def parse_quick(raw: str, delimiter: str = "auto", multiline: str = "auto") -> list[Column]:
    """Extract names, supporting pipe headers, Excel headers, MD tables, line lists."""
    if multiline not in {"auto", "all", "first"}:
        raise ValueError("Mode baris tidak dikenali.")
    lines = _clean_text(raw)
    if not lines:
        return []
    is_md = len(lines) > 1 and "|" in lines[0] and all(_is_separator(x) for x in _cells(lines[1], delimiter))
    lines = _drop_markdown_separator(lines, delimiter)
    if not lines:
        return []
    if multiline == "first":
        lines = lines[:1]
    if multiline == "all":
        values = []
        for ln in lines:
            cells = _cells(ln, delimiter)
            decl = _sql_decl(ln)
            if decl:
                values.append(decl.name)
            elif _looks_typed(cells):
                values.append(_remove_quotes(cells[0]))
            else:
                values.extend(_remove_quotes(cell) for cell in cells)
        return [Column(v) for v in values if v]
    if is_md and multiline == "auto":
        head = _cells(lines[0], delimiter)
        if head and head[0].lower() in HEADER_NAMES:
            values = [_remove_quotes(_cells(ln, delimiter)[0]) for ln in lines[1:] if _cells(ln, delimiter)]
        else:
            # Typical markdown data table: take column headings, not row values.
            values = [_remove_quotes(c) for c in head]
    elif len(lines) == 1:
        parsed = _sql_decl(lines[0])
        single_cells = _cells(lines[0], delimiter)
        if parsed:
            values = [parsed.name]
        elif _looks_typed(single_cells):
            values = [_remove_quotes(single_cells[0])]
        else:
            values = [_remove_quotes(x) for x in single_cells]
    else:
        rows = [_cells(ln, delimiter) for ln in lines]
        if rows[0] and rows[0][0].lower() in HEADER_NAMES:
            rows = rows[1:]
        if rows and all(_looks_typed(r) for r in rows):
            values = [_remove_quotes(r[0]) for r in rows]
        elif rows and all(len(r) > 1 for r in rows) and any("\t" in ln for ln in lines):
            # Pasted tabular Excel data: first row is the header row.
            values = [_remove_quotes(c) for c in rows[0]]
        elif rows and all(len(r) > 1 for r in rows):
            # Multiple pipe rows? If the later rows are typed/values treat column 1;
            # otherwise the first row is likely a header list.
            values = [_remove_quotes(c) for c in rows[0]]
        else:
            values = []
            for ln in lines:
                decl = _sql_decl(ln)
                values.append(decl.name if decl else _remove_quotes(ln.rstrip(",")))
    return [Column(v) for v in values if v]


def parse_schema(raw: str, delimiter: str = "auto") -> list[Column]:
    """Extract typed fields from pipe/TSV/Markdown tables, declarations, or names."""
    lines = _clean_text(raw)
    if not lines:
        return []
    is_md = len(lines) > 1 and "|" in lines[0] and all(_is_separator(x) for x in _cells(lines[1], delimiter))
    lines = _drop_markdown_separator(lines, delimiter)
    # DDL-style declarations may be pasted one per line or comma-separated
    # on one line. A comma inside DECIMAL(18,2) belongs to the type.
    if delimiter in {"auto", ",", "\n"} and lines and all("|" not in ln and "\t" not in ln for ln in lines):
        declaration_parts = [_split_commas(ln) for ln in lines]
        flat_parts = [part for parts in declaration_parts for part in parts if part]
        if flat_parts and all(_schema_decl(part) or IDENTIFIER_RE.fullmatch(_remove_quotes(part)) for part in flat_parts):
            return [_schema_decl(part) or Column(_remove_quotes(part)) for part in flat_parts]
    rows = [_cells(ln, delimiter) for ln in lines]
    if rows and rows[0] and rows[0][0].lower() in HEADER_NAMES:
        rows = rows[1:]
    if not rows:
        return []
    if len(rows) == 1 and not _looks_typed(rows[0]):
        decl = _sql_decl(lines[0])
        return [decl] if decl else [Column(_remove_quotes(s)) for s in rows[0] if s.strip()]
    if is_md and rows and all(len(r) >= 2 for r in rows) and not any(_looks_typed(r) for r in rows):
        # Header-only MD table, not typed schema.
        return [Column(_remove_quotes(s)) for s in rows[0] if s.strip()]
    result: list[Column] = []
    for row in rows:
        if not row or not row[0]:
            continue
        if _looks_typed(row):
            result.append(_from_schema_cells(row))
        elif len(row) == 1:
            d = _sql_decl(row[0])
            if d:
                result.append(d)
            else:
                result.append(Column(_remove_quotes(row[0].rstrip(","))))
        else:
            # Preserve malformed type/length cells so validation can flag them.
            result.append(_from_schema_cells(row))
    return result


def normalize_type(value: str, char_to_varchar: bool = True) -> str:
    t = value.strip()
    match = TYPE_RE.fullmatch(t)
    if not match:
        raise ValueError(f"Tipe tidak dikenali: {value!r}")
    base = match.group("base").strip().upper().replace("  ", " ")
    if base not in KNOWN_TYPES:
        raise ValueError(f"Tipe tidak dikenali: {value!r}")
    if char_to_varchar and base == "CHAR":
        base = "VARCHAR"
    if base in {"CHAR", "VARCHAR"} and not match.group("length"):
        raise ValueError(f"{base} wajib punya panjang, mis. VARCHAR(30).")
    length, scale = match.group("length"), match.group("scale")
    if scale and not length:
        raise ValueError(f"Scale tanpa precision pada {value!r}")
    if scale is not None and base not in {"DECIMAL", "NUMERIC", "NUMBER"}:
        raise ValueError(f"Scale hanya dipakai untuk tipe numerik, bukan {base}.")
    if length:
        if int(length) < 1:
            raise ValueError(f"Panjang tipe harus lebih dari nol: {value!r}")
        base += f"({int(length)}"
        if scale is not None:
            if int(scale) > int(length):
                raise ValueError(f"Scale tidak boleh lebih besar daripada precision: {value!r}")
            base += f",{int(scale)}"
        base += ")"
    return base


def validate_columns(columns: list[Column], strict_type: bool = False) -> list[str]:
    messages: list[str] = []
    seen: set[str] = set()
    for i, column in enumerate(columns, 1):
        if not IDENTIFIER_RE.fullmatch(column.name):
            messages.append(f"Baris {i}: nama kolom {column.name!r} tidak valid. Gunakan huruf, angka, atau underscore; jangan diawali angka.")
        if column.source_name and not IDENTIFIER_RE.fullmatch(column.source_name):
            messages.append(f"Baris {i}: nama kolom sumber {column.source_name!r} tidak valid.")
        key = column.name.upper()
        if key in seen:
            messages.append(f"Baris {i}: nama kolom {column.name!r} duplikat.")
        seen.add(key)
        if strict_type:
            try:
                normalize_type(column.data_type)
            except ValueError as error:
                messages.append(f"Baris {i}: {error}")
    return messages


def ident(name: str, backticks: bool = True) -> str:
    if not IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Nama kolom tidak valid: {name!r}")
    return f"`{name}`" if backticks else name


def _lines_with_commas(parts: list[str], trailing_comma: bool) -> str:
    return ",\n".join(parts) + ("," if trailing_comma and parts else "")


def format_string_ddl(
    columns: list[Column],
    *,
    with_comment: bool = True,
    comment: str = "from deserializer",
    backticks: bool = True,
    trailing_comma: bool = False,
    indentation: int = 0,
) -> str:
    if not columns:
        return ""
    safe_comment = comment.replace("'", "''")
    pad = " " * indentation
    suffix = f" COMMENT '{safe_comment}'" if with_comment else ""
    return _lines_with_commas([f"{pad}{ident(c.name, backticks)} string{suffix}" for c in columns], trailing_comma)


def format_schema_sql(
    columns: list[Column], *,
    quote: bool = False,
    char_to_varchar: bool = True,
    stg_comment: bool = False,
) -> dict[str, str]:
    if not columns:
        return {"SRI": "", "STG": "", "TXF": ""}
    sri: list[str] = []
    stg: list[str] = []
    txf: list[str] = []
    for col in columns:
        name = ident(col.name, quote)
        source_name = ident(col.source_name or col.name, quote)
        data_type = normalize_type(col.data_type, char_to_varchar=char_to_varchar)
        sri.append(f"{name} {data_type}")
        stg.append(f"{name} STRING" + (" COMMENT 'from deserializer'" if stg_comment else ""))
        if col.transform == "TO_DATE":
            txf.append(f"TO_DATE({source_name}) AS {name}")
        else:
            txf.append(f"CAST(TRIM({source_name}) AS {data_type}) AS {name}")
    return {
        "SRI": _lines_with_commas(sri, False),
        "STG": _lines_with_commas(stg, False),
        "TXF": _lines_with_commas(txf, False),
    }
