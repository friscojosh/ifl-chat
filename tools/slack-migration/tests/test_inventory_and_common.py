import csv
import os
import zipfile

import pytest

import inventory
from common import (MigrationError, load_env_file, member_name, read_csv,
                    resolve_identities)


def test_member_name_undoes_cp437(export_zip):
    with zipfile.ZipFile(export_zip) as z:
        names = {member_name(i) for i in z.infolist()}
    assert 'kylieskoяner/2020-09-13.json' in names


def test_report_counts(export_zip, tmp_path):
    with zipfile.ZipFile(export_zip) as z:
        lines = inventory.write_report(inventory.scan(z), str(tmp_path))
    text = '\n'.join(lines)
    assert "folders not in channels.json: ['FC:F05GEKFA4N9:Canvas']" in text
    assert 'Messages: 12 from 2017-07-14 to 2023-11-14' in text
    assert 'hidden_by_limit 1' in text
    rows = {r['folder']: r for r in read_csv(tmp_path / 'channel_counts.csv')}
    assert rows['general']['messages'] == '8'
    assert rows['general']['replies'] == '2'
    assert rows['kylieskoяner']['in_channels_json'] == 'yes'
    assert rows['FC:F05GEKFA4N9:Canvas']['in_channels_json'] == 'no'


def test_users_file_is_private_and_lists_missing_ids(export_zip, tmp_path):
    out = tmp_path / 'slack_users.csv'
    assert inventory.main(['users', str(export_zip), '--out', str(out)]) == 0
    assert oct(os.stat(out).st_mode & 0o777) == '0o600'
    ids = [r['slack_id'] for r in read_csv(out)]
    assert ids == ['U1JOSH', 'U2GM', 'U3GONE', 'U4BOT']  # USLACKBOT is not a person


def test_compare_flags_lost_history(tmp_path):
    old, new = tmp_path / 'old.csv', tmp_path / 'new.csv'
    fields = inventory.COUNT_FIELDS
    for path, n, first in ((old, 10, '2016-03-05'), (new, 9, '2016-03-05')):
        with open(path, 'w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerow({'folder': 'general', 'messages': n, 'first': first})
    assert inventory.compare(old, new) == ['general: 10 -> 9 messages']
    assert inventory.compare(old, old) == []


def test_env_file_must_be_private(tmp_path):
    p = tmp_path / 'slack.env'
    p.write_text('SLACK_API_TOKEN=xoxp-secret\n')
    os.chmod(p, 0o644)
    with pytest.raises(MigrationError, match='mode 600'):
        load_env_file(p, 'SLACK_API_TOKEN')
    os.chmod(p, 0o600)
    assert load_env_file(p, 'SLACK_API_TOKEN') == 'xoxp-secret'


def test_resolve_identities(identity_csv, chat_snapshot):
    users, _ = chat_snapshot
    from common import load_chat_users
    ids = resolve_identities(read_csv(identity_csv), load_chat_users(users))
    assert ids['U1JOSH'] == {'slack_id': 'U1JOSH', 'username': 'josh_0', 'email': 'josh@example.test',
                             'auth_data': '1', 'active': True, 'existing': True}
    assert ids['U2GM']['username'] == 'miami.brad'
    assert ids['U2GM']['email'] == 'brad@example.test'
    assert ids['U2GM']['existing'] is False and ids['U2GM']['active'] is True
    assert ids['U3GONE']['email'] == 'slack-u3gone@import.invalid'
    assert ids['U3GONE']['auth_data'] is None and ids['U3GONE']['active'] is False
    assert 'U4BOT' not in ids


def test_resolve_refuses_taking_an_existing_chat_username(identity_csv, chat_snapshot):
    from common import load_chat_users
    rows = read_csv(identity_csv)
    rows[2]['mm_username_override'] = 'ifl-relay'
    with pytest.raises(MigrationError, match="already belongs to chat account 'ifl-relay'"):
        resolve_identities(rows, load_chat_users(chat_snapshot[0]))


def test_resolve_refuses_unconfirmed_link_to_existing_name(identity_csv, chat_snapshot):
    from common import load_chat_users
    rows = read_csv(identity_csv)
    rows[0]['confirmed'] = ''           # josh not confirmed: would import as 'josh'
    rows[0]['mm_username_override'] = 'josh_0'
    with pytest.raises(MigrationError, match='josh_0'):
        resolve_identities(rows, load_chat_users(chat_snapshot[0]))


def test_resolve_refuses_two_slack_users_on_one_site_account(identity_csv, chat_snapshot):
    from common import load_chat_users
    rows = read_csv(identity_csv)
    rows[2].update(site_id='7', confirmed='yes', site_email='other@example.test', site_member='yes')
    with pytest.raises(MigrationError, match='site user 7 is also matched'):
        resolve_identities(rows, load_chat_users(chat_snapshot[0]))


def test_mmetl_drop_rule_and_reconcile(tmp_path):
    assert inventory.mmetl_drops({'type': 'message', 'subtype': 'pinned_item', 'user': 'U1'})
    assert inventory.mmetl_drops({'type': 'message', 'text': 'no author'})
    assert not inventory.mmetl_drops({'type': 'message', 'subtype': 'bot_message', 'bot_id': 'B1'})
    assert not inventory.mmetl_drops({'type': 'message', 'subtype': 'channel_join', 'user': 'U1'})
    (tmp_path / 's.csv').write_text('folder,messages,mmetl_drops\ntown-square,10,2\nold,3,0\n')
    (tmp_path / 'i.csv').write_text('mm_name,posts,replies,reactions,attachments\n'
                                    'town-square,6,2,0,0\nold,2,0,0,0\n')
    (tmp_path / 'd.csv').write_text('mm_name,posts\ntown-square,9\nold,2\n')
    rows = {r['mm_name']: r for r in inventory.reconcile(tmp_path / 's.csv', tmp_path / 'i.csv',
                                                         tmp_path / 'd.csv')}
    assert rows['town-square']['import_diff'] == 0 and rows['town-square']['database_diff'] == 1
    assert rows['old']['import_diff'] == -1
    assert inventory.main(['reconcile', '--slack', str(tmp_path / 's.csv'), '--import',
                           str(tmp_path / 'i.csv'), '--out', str(tmp_path / 'o.csv')]) == 1


def test_chat_channel_snapshot(chat_snapshot):
    from common import load_chat_channels
    assert load_chat_channels(chat_snapshot[1]) == {'off-topic', 'town-square', 'old_stuff'}


def test_slack_file_url():
    from common import slack_file_url
    assert slack_file_url('https://files.slack.com/files-pri/T/F/x.png')
    for bad in ('http://files.slack.com/x', 'https://docs.google.com/d/x',
                'https://files.slack.com.evil.example/x', 'https://files.slack.com:8443/x',
                'https://user@evil.example/x', '', None):
        assert not slack_file_url(bad), bad


def test_check_urls_sends_the_token_only_to_files_slack_com(tmp_path):
    import json
    msgs = [{'type': 'message', 'user': 'U1', 'ts': '1.0', 'files': [
        {'id': 'FG', 'name': 'doc', 'url_private': 'https://docs.google.com/document/d/x'},
        {'id': 'FS', 'name': 'b.png', 'url_private_download': 'https://files.slack.com/files-pri/T/F/b.png'}]}]
    z = tmp_path / 'e.zip'
    with zipfile.ZipFile(z, 'w') as w:
        w.writestr('channels.json', '[]')
        w.writestr('general/2020-01-01.json', json.dumps(msgs))

    class S:
        calls = []

        def get(self, url, **kw):
            S.calls.append((url, kw))

            class R:
                status_code = 302
                headers = {'Content-Type': 'text/html'}

                def close(self):
                    pass
            return R()
    with zipfile.ZipFile(z) as zf:
        rows = inventory.check_urls(zf, 'xoxp-secret', tmp_path / 'u.csv', session=S())
    assert [c[0] for c in S.calls] == ['https://files.slack.com/files-pri/T/F/b.png']
    assert S.calls[0][1]['allow_redirects'] is False
    assert {r['file_id']: r['status'] for r in rows} == {'FG': 'skipped', 'FS': 302}


def test_accounts_and_members(tmp_path):
    import json
    before = [{'id': 'a', 'username': 'josh_0', 'roles': 'system_user system_admin',
               'auth_service': 'gitlab', 'auth_data': '1', 'email': 'j@x', 'delete_at': 0}]
    after = [dict(before[0], roles='system_user')]
    (tmp_path / 'b.json').write_text(json.dumps(before))
    (tmp_path / 'a.json').write_text(json.dumps(after))
    assert inventory.accounts(tmp_path / 'b.json', tmp_path / 'a.json') == [
        "josh_0: roles 'system_user system_admin' -> 'system_user'"]
    assert inventory.accounts(tmp_path / 'b.json', tmp_path / 'b.json') == []
    head = 'kind,target_id,user_id,username,name,scheme_admin,explicit_roles\n'
    (tmp_path / 'mb.csv').write_text(head + 'team,t1,a,josh_0,ifl,true,\n'
                                     'channel,c1,a,josh_0,town-square,false,custom_role\n'
                                     'channel,c3,a,josh_0,off-topic,false,\n')
    (tmp_path / 'ma.csv').write_text(head + 'team,t1,a,josh_0,ifl,false,\n'
                                     'channel,c1,a,josh_0,town-square,false,\n'
                                     'channel,c3,a,josh_0,off-topic,false,\n'
                                     'channel,c2,a,josh_0,rando,false,\n')
    restore = inventory.members(tmp_path / 'mb.csv', tmp_path / 'ma.csv')
    assert [(r['kind'], r['target_id'], r['scheme_admin'], r['explicit_roles']) for r in restore] == [
        ('channel', 'c1', 'false', 'custom_role'), ('team', 't1', 'true', '')]


@pytest.mark.parametrize('snapshot_user', [
    {'username': 'josh_0', 'email': 'josh@example.test', 'auth_service': 'gitlab', 'auth_data': '9'},
    {'username': 'josh_0', 'email': 'josh@example.test', 'auth_service': '', 'auth_data': ''},
    {'username': 'josh_0', 'email': 'josh@example.test'},
])
def test_resolve_refuses_existing_account_not_linked_to_that_site_id(identity_csv, snapshot_user):
    """Importing auth_data 2 onto josh_0 would re-link the commissioner and revoke his sessions."""
    rows = read_csv(identity_csv)
    rows[0]['site_id'] = '2'
    chat = [snapshot_user]
    with pytest.raises(MigrationError, match=r"josh_0.*(auth_data|gitlab)"):
        resolve_identities(rows, chat)


def test_resolve_refuses_existing_account_missing_from_snapshot(identity_csv):
    rows = read_csv(identity_csv)
    with pytest.raises(MigrationError, match='josh_0.*not in the chat snapshot'):
        resolve_identities(rows, [])


def test_unverified_email_row_is_treated_as_unmatched(identity_csv, chat_snapshot):
    """slack-match writes site_member=no:unverified_email for a confirmed row
    whose site email is not verified. That email must never reach the import,
    and the account must not be linked to the site user."""
    from common import load_chat_users
    rows = read_csv(identity_csv)
    rows[1]['site_member'] = 'no:unverified_email'
    ident = resolve_identities(rows, load_chat_users(chat_snapshot[0]))['U2GM']
    assert ident['email'] == 'slack-u2gm@import.invalid'
    assert ident['auth_data'] is None and ident['active'] is False
    assert ident['existing'] is False and ident['unverified_email'] is True
    assert 'unverified_email' not in resolve_identities(
        read_csv(identity_csv), load_chat_users(chat_snapshot[0]))['U2GM']


def test_unverified_email_on_an_existing_chat_account_is_refused(identity_csv, chat_snapshot):
    from common import load_chat_users
    rows = read_csv(identity_csv)
    rows[0]['site_member'] = 'no:unverified_email'      # josh_0 already has a chat account
    with pytest.raises(MigrationError, match='U1JOSH.*unverified'):
        resolve_identities(rows, load_chat_users(chat_snapshot[0]))
