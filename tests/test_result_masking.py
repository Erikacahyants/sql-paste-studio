import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from result_masking import mask_result, parse_result, detect_sensitive_columns
from formatter import parse_schema


@pytest.mark.parametrize('separator', ['\t', ',', ';', '|', '||', '|@~'])
def test_auto_delimiters_without_ui_settings(separator):
    header = separator.join(['nama', 'rekening', 'saldo'])
    data = separator.join(['Budi', '00123', '100'])
    assert [column.name for column in parse_schema(header)] == ['nama', 'rekening', 'saldo']
    assert parse_result(header + '\n' + data) == (
        ['nama', 'rekening', 'saldo'], [['Budi', '00123', '100']])


def test_detect_sensitive_headers_in_common_naming_styles():
    headers = ['NO', 'no_rek', 'nomor_kartu', 'accountNumber', 'customer_key',
               'CIF', 'cifname', 'fullName', 'nama_nasabah', 'ADDRESS',
               'alamat_rumah', 'email', 'noHP', 'NIK', 'NPWP', 'customer_id',
               'norekening', 'telp', 'tanggal_lahir']
    assert detect_sensitive_columns(headers) == list(range(len(headers)))


def test_detection_leaves_ordinary_measure_columns_unselected():
    assert detect_sensitive_columns(['saldo', 'nominal', 'amount', 'periode',
                                     'note', 'quantity', 'status']) == []


def test_selected_columns_repeated_values_and_leading_zeroes():
    headers, rows = parse_result('name\taccount\tamount\nBudi\t00123\t100\nBudi\t00456\t200')
    output = mask_result(headers, rows, [0])
    assert output == ('name\taccount\tamount\nCOL_001_VALUE_001\t00123\t100\n'
                      'COL_001_VALUE_001\t00456\t200\n')
    assert 'Budi' not in output


def test_impala_ascii_and_markdown_tables():
    for raw in ('+------+-----+\n| name | id |\n+------+-----+\n| Budi | 01 |\n+------+-----+',
                '| name | id |\n| --- | --- |\n| Budi | 01 |'):
        assert parse_result(raw) == (['name', 'id'], [['Budi', '01']])


def test_csv_quoted_newlines_and_empty_cells():
    headers, rows = parse_result('name,note,amount\nBudi,"a,b\nc",\nSari,,001')
    assert rows == [['Budi', 'a,b\nc', ''], ['Sari', '', '001']]
    output = mask_result(headers, rows, [0, 1])
    assert parse_result(output)[1] == [
        ['COL_001_VALUE_001', 'COL_002_VALUE_001', ''], ['COL_001_VALUE_002', '', '001']]


def test_reject_misaligned_rows_and_missing_headers():
    with pytest.raises(ValueError):
        parse_result('name\tid\nBudi\t01\textra')
    with pytest.raises(ValueError):
        parse_result('name\t\nBudi\t01')


def test_duplicate_headers_and_alias_collision():
    headers, rows = parse_result('name\tname\nBudi\tCOL_001_VALUE_001')
    assert mask_result(headers, rows, [0]) == 'name\tname\nCOL_001_VALUE_002\tCOL_001_VALUE_001\n'
