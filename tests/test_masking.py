import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from masking import mask_text, restore_text


def test_shell_script_masks_sql_variables_ssh_and_jdbc_consistently():
    raw = '''#!/bin/bash
DB_NAME="prod_finance"
TABLE_NAME="balances"
SSH_USER="etl_user"
SSH_HOST="warehouse.internal"
ssh -i ~/.ssh/id_rsa -p 2222 "${SSH_USER}@${SSH_HOST}" <<'SQL'
beeline -u 'jdbc:hive2://10.20.30.40:10000/prod_finance' -e "
INSERT OVERWRITE TABLE prod_finance.balances
SELECT t.amount FROM raw_db.transactions t JOIN raw_db.customers c ON t.id=c.id;
"
SQL
'''
    result = mask_text(raw)
    for original in ('prod_finance', 'balances', 'etl_user', 'warehouse.internal',
                     '10.20.30.40', 'raw_db', 'transactions', 'customers'):
        assert original not in result.text
    assert '${SSH_USER}@${SSH_HOST}' in result.text
    assert 't.amount' in result.text and 't.id=c.id' in result.text
    assert result.text.count('DB_001') == 3
    assert result.text.count('\n') == raw.count('\n')
    assert '-i PATH_001 -p 2222' in result.text


def test_quoted_sql_ddl_and_repeated_names():
    result = mask_text('USE `prod`; CREATE TABLE IF NOT EXISTS `prod`.`orders` (id INT); '
                       'INSERT INTO prod.orders SELECT * FROM prod.orders;')
    assert result.text == ('USE `DB_001`; CREATE TABLE IF NOT EXISTS `DB_001`.`TABLE_001` (id INT); '
                           'INSERT INTO DB_001.TABLE_001 SELECT * FROM DB_001.TABLE_001;')


def test_ssh_options_and_plain_host():
    result = mask_text('ssh -l deploy -J jumpuser@bastion.internal -p 2222 worker.internal "date"')
    for value in ('deploy', 'jumpuser', 'bastion.internal', 'worker.internal'):
        assert value not in result.text
    assert '2222' in result.text and '"date"' in result.text


def test_ips_ipv6_validation_and_disabled_options():
    raw = '10.0.0.1 10.0.0.1 [2001:db8::1]:22 ::1 999.0.0.1 ssh admin@server.internal'
    result = mask_text(raw)
    assert result.text.count('IP_001') == 2
    assert '[IP_002]:22' in result.text
    assert 'IP_003' in result.text
    assert '999.0.0.1' in result.text
    assert mask_text(raw, mask_ip=False, mask_ssh=False).text == raw


def test_manual_literals_boundaries_and_no_alias_collisions():
    result = mask_text('orders orders_archive TABLE_001 prod.a prodXa secret.*',
                       tables='orders', databases='prod.a', extra='secret.*')
    assert result.text == 'TABLE_002 orders_archive TABLE_001 DB_001 prodXa MASK_001'


def test_empty_unknown_dynamic_and_incomplete_scripts_do_not_crash():
    for raw in ('', 'echo hello', 'ssh "', 'SELECT * FROM ${DB}.${TABLE};'):
        assert mask_text(raw).text == raw


def test_ssh_config_options_and_scp():
    result = mask_text('ssh -o HostName=private.internal -o User=operator alias "date"\n'
                       'scp ./dump.csv operator@private.internal:/tmp/dump.csv')
    for value in ('private.internal', 'operator', 'alias'):
        assert value not in result.text
    assert '/tmp/dump.csv' not in result.text
    assert 'scp PATH_001 USER_001@HOST_001:PATH_002' in result.text


def test_jdbc_database_detected_without_sql():
    result = mask_text("beeline -u 'jdbc:hive2://10.0.0.1:10000/warehouse;principal=hive'")
    assert '/DB_001;principal=hive' in result.text


def test_ip_toggle_also_applies_to_ssh_host_variable():
    raw = 'SSH_HOST=10.0.0.1\nssh admin@10.0.0.1 "date"'
    result = mask_text(raw, mask_ip=False)
    assert result.text.count('10.0.0.1') == 2
    assert 'admin' not in result.text


def test_paths_in_assignments_commands_and_comments_are_consistent():
    path = '/x/x/bot/s/f_147/tXLON_102'
    raw = f'JOB="{path}"\nbash {path}\n# {path}\ncat {path}/output.log'
    result = mask_text(raw)
    assert result.text == 'JOB="PATH_001"\nbash PATH_001\n# PATH_001\ncat PATH_002'
    assert mask_text(raw, mask_paths=False).text == raw


def test_quoted_paths_spaces_and_shell_operators():
    result = mask_text('cat "/srv/private files/input.csv" > /tmp/output.log; cd ../jobs')
    assert result.text == 'cat "PATH_001" > PATH_002; cd PATH_003'


def test_path_masking_preserves_shebang_urls_and_sql_division():
    raw = '#!/bin/bash\ncurl https://example.org/srv/data\ncat /srv/data\nSELECT total / count;'
    result = mask_text(raw)
    assert result.text == '#!/bin/bash\ncurl https://example.org/srv/data\ncat PATH_001\nSELECT total / count;'


def test_whole_path_wins_over_table_name_inside_it():
    result = mask_text('SELECT * FROM orders; cat /srv/orders/data.csv')
    assert result.text == 'SELECT * FROM TABLE_001; cat PATH_001'


def test_session_aliases_stay_stable_across_different_queries():
    first = mask_text('SELECT * FROM prod.orders')
    second = mask_text('SELECT * FROM raw.customers JOIN prod.orders ON 1=1',
                       mappings=first.mappings)
    assert second.text == 'SELECT * FROM DB_002.TABLE_002 JOIN DB_001.TABLE_001 ON 1=1'
    saved = {row['Asli']: row for row in first.mappings + second.mappings}
    assert restore_text(second.text, list(saved.values())).text == (
        'SELECT * FROM raw.customers JOIN prod.orders ON 1=1')
    assert mask_text('SELECT * FROM prod.orders').text == first.text


def test_restore_gpt_query_quotes_case_and_unknown_aliases():
    masked = mask_text('SELECT * FROM prod.orders')
    query = 'SELECT t.id FROM `db_001`.`table_001` t JOIN DB_999.TABLE_999 x ON 1=1'
    assert restore_text(query, masked.mappings).text == (
        'SELECT t.id FROM `prod`.`orders` t JOIN DB_999.TABLE_999 x ON 1=1')
    assert restore_text('TABLE_001_backup xTABLE_001 $TABLE_001', masked.mappings).text == (
        'TABLE_001_backup xTABLE_001 $TABLE_001')
    assert restore_text(query, []).text == query


def test_restore_round_trip_and_no_cascading_aliases():
    raw = 'SELECT * FROM prod.orders; ssh operator@private.host "cat /srv/input.csv"'
    masked = mask_text(raw)
    assert restore_text(masked.text, masked.mappings).text == raw
    mappings = [
        {'Jenis': 'TABLE', 'Asli': 'TABLE_002', 'Masking': 'TABLE_001'},
        {'Jenis': 'TABLE', 'Asli': 'orders', 'Masking': 'TABLE_002'},
    ]
    assert restore_text('TABLE_001 TABLE_002', mappings).text == 'TABLE_002 orders'
