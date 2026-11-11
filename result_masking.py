"""Parse pasted result tables and mask selected cells without storing data."""
import csv
import io
import re


def parse_result(raw: str, delimiter: str = 'auto') -> tuple[list[str], list[list[str]]]:
    if not raw.strip():
        return [], []
    text = raw.strip('\r\n')
    first = text.splitlines()[0]
    if delimiter == 'auto':
        delimiter = next((sep for sep in ('\t', '|', ',') if sep in first), ',')
        if re.fullmatch(r'\s*\+(?:[-+]+)\s*', first):
            delimiter = '|'
    if delimiter == '|':
        lines = []
        for line in text.splitlines():
            if re.fullmatch(r'\s*\+(?:[-+]+)\s*', line):
                continue
            cells = line.strip().removeprefix('|').removesuffix('|').split('|')
            if all(re.fullmatch(r'\s*:?-+:?\s*', cell) for cell in cells):
                continue
            lines.append([cell.strip() for cell in cells])
        records = lines
    else:
        try:
            records = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=True))
        except csv.Error as exc:
            raise ValueError('Format tabel tidak valid. Periksa tanda kutip dan pemisah.') from exc
    if not records:
        return [], []
    headers, *rows = records
    if not headers or any(not name.strip() for name in headers):
        raise ValueError('Baris pertama harus berisi nama setiap kolom.')
    for index, row in enumerate(rows, 2):
        if len(row) != len(headers):
            raise ValueError(f'Baris {index}: ditemukan {len(row)} kolom, seharusnya {len(headers)}. Periksa pemisah atau copy ulang tabel beserta header.')
    return headers, rows


def mask_result(headers: list[str], rows: list[list[str]], selected: list[int]) -> str:
    """Return TSV; equal values within a column share an alias. Empty cells stay empty."""
    reserved = set(headers) | {cell for row in rows for cell in row}
    mappings: dict[tuple[int, str], str] = {}
    counts: dict[int, int] = {}
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter='\t', lineterminator='\n')
    writer.writerow(headers)
    for row in rows:
        masked = list(row)
        for column in selected:
            value = row[column]
            if value == '':
                continue
            key = (column, value)
            if key not in mappings:
                count = counts.get(column, 0) + 1
                alias = f'COL_{column + 1:03d}_VALUE_{count:03d}'
                while alias in reserved:
                    count += 1
                    alias = f'COL_{column + 1:03d}_VALUE_{count:03d}'
                counts[column] = count
                mappings[key] = alias
                reserved.add(alias)
            masked[column] = mappings[key]
        writer.writerow(masked)
    return output.getvalue()
