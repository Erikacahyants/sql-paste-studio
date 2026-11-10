import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from masking import mask_text


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
    assert '-i ~/.ssh/id_rsa -p 2222' in result.text


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
    assert '/tmp/dump.csv' in result.text


def test_jdbc_database_detected_without_sql():
    result = mask_text("beeline -u 'jdbc:hive2://10.0.0.1:10000/warehouse;principal=hive'")
    assert '/DB_001;principal=hive' in result.text


def test_ip_toggle_also_applies_to_ssh_host_variable():
    raw = 'SSH_HOST=10.0.0.1\nssh admin@10.0.0.1 "date"'
    result = mask_text(raw, mask_ip=False)
    assert result.text.count('10.0.0.1') == 2
    assert 'admin' not in result.text
