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


def FILE(i, **kw):
    f = {'id': f'F{i}', 'name': f'{i}.png', 'mode': 'hosted',
         'url_private_download': f'https://files.slack.com/x/{i}.png'}
    f.update(kw)
    return f


def test_attachment_overflow_replies_rule():
    """mmetl v0.6.0 keeps 5 files on a post and moves the rest into replies of
    up to 5 each (services/intermediate/export.go createRepliesForAttachments).
    Only files it can attach count: named and present in __uploads."""
    up = {f'F{i}' for i in range(12)}

    def msg(n, **kw):
        m = {'type': 'message', 'user': 'U1', 'ts': '1.1',
             'files': [FILE(i) for i in range(n)]}
        m.update(kw)
        return m
    rule = inventory.mmetl_attachment_replies
    assert [rule(msg(n), up) for n in (0, 5, 6, 9, 10, 11, 12)] == [0, 0, 1, 1, 1, 2, 2]
    m = msg(7)
    m['files'][0]['name'] = ''                       # access denied: mmetl skips it
    m['files'][1]['id'] = 'FMISSING'                 # not downloaded: not attached
    assert rule(m, up) == 0
    assert rule(msg(9, file={'id': 'F0', 'name': 'a'}), up) == 0  # 'file' wins over 'files'
    assert rule(msg(9, subtype='pinned_item'), up) == 0           # dropped message


def test_scan_and_reconcile_count_attachment_overflow_replies(tmp_path):
    import json
    files = [{'id': f'F{i}', 'name': f'{i}.png', 'mode': 'hosted',
              'url_private_download': f'https://files.slack.com/x/{i}.png'} for i in range(9)]
    path = tmp_path / 'e.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('channels.json', json.dumps([{'id': 'C1', 'name': 'pics', 'members': []}]))
        z.writestr('users.json', '[]')
        z.writestr('pics/2020-01-01.json', json.dumps(
            [{'type': 'message', 'user': 'U1', 'ts': '1.000100', 'files': files}]))
        for i in range(9):
            z.writestr(f'__uploads/F{i}/{i}.png', b'x')
    with zipfile.ZipFile(path) as z:
        inventory.write_report(inventory.scan(z), str(tmp_path))
    row = read_csv(tmp_path / 'channel_counts.csv')[0]
    assert (row['messages'], row['mmetl_drops'], row['mmetl_extra']) == ('1', '0', '1')
    # mmetl's output: 1 post with 5 files and 1 empty reply with the other 4.
    (tmp_path / 'i.csv').write_text('mm_name,posts,replies,reactions,attachments\npics,1,1,0,9\n')
    rows = inventory.reconcile(tmp_path / 'channel_counts.csv', tmp_path / 'i.csv')
    assert rows[0]['expected'] == 2 and rows[0]['import_diff'] == 0
    assert rows[0]['mmetl_extra'] == '1'


def _counts(tmp_path, extra, files_import, **imp):
    (tmp_path / 's.csv').write_text(
        'folder,messages,mmetl_drops,mmetl_extra,files_import\n'
        f'pics,1,0,{extra},{files_import}\n')
    cols = {'mm_name': 'pics', 'posts': 1, 'replies': extra, 'attachments': files_import, 'overflow_replies': extra}
    cols.update(imp)
    (tmp_path / 'i.csv').write_text(','.join(cols) + '\n' + ','.join(map(str, cols.values())) + '\n')
    return inventory.reconcile(tmp_path / 's.csv', tmp_path / 'i.csv')[0]


def test_duplicate_file_ids_count_once():
    up = {f'F{i}' for i in range(12)}
    m = {'type': 'message', 'user': 'U1', 'ts': '1.1',
         'files': [FILE(i % 5) for i in range(10)] + [FILE(5)]}   # 6 distinct ids
    assert len(inventory.importable_files(m, up)) == 6
    assert inventory.mmetl_attachment_replies(m, up) == 1
    m['files'] = [FILE(0)] * 10
    assert inventory.mmetl_attachment_replies(m, up) == 0


def test_hidden_tombstone_and_external_files_do_not_count():
    up = {f'F{i}' for i in range(12)}
    files = [FILE(i) for i in range(5)] + [
        FILE(5, mode='hidden_by_limit'), FILE(6, mode='tombstone'),
        {'id': 'F7', 'name': 'x', 'mode': 'external'}]
    m = {'type': 'message', 'user': 'U1', 'ts': '1.1', 'files': files}
    assert len(inventory.importable_files(m, up)) == 5
    assert inventory.mmetl_attachment_replies(m, up) == 0


def test_reconcile_accepts_9_and_10_file_messages(tmp_path):
    for n in (9, 10):
        r = _counts(tmp_path, 1, n)
        assert (r['import_diff'], r['overflow_diff'], r['files_diff']) == (0, 0, 0)
        assert r['mmetl_extra'] == '1'


def test_reconcile_fails_when_claimed_overflow_has_no_import_replies(tmp_path):
    # claims 1 overflow reply, but the import has none and the totals still balance
    r = _counts(tmp_path, 1, 9, overflow_replies=0)
    assert r['overflow_diff'] == -1
    # no overflow column: the attachment totals are the cross-check
    r = _counts(tmp_path, 1, 9, attachments=5, overflow_replies='')
    assert r['files_diff'] == -4
    # nothing to cross-check against at all: fail closed
    (tmp_path / 's.csv').write_text('folder,messages,mmetl_drops,mmetl_extra\npics,1,0,1\n')
    (tmp_path / 'i.csv').write_text('mm_name,posts,replies\npics,1,1\n')
    assert inventory.reconcile(tmp_path / 's.csv', tmp_path / 'i.csv')[0]['files_diff'] == 'unverifiable'


def test_reconcile_cli_exits_nonzero_on_overflow_mismatch(tmp_path):
    _counts(tmp_path, 1, 9, overflow_replies=0)
    argv = ['reconcile', '--slack', str(tmp_path / 's.csv'), '--import', str(tmp_path / 'i.csv'),
            '--out', str(tmp_path / 'o.csv')]
    assert inventory.main(argv) == 1
    assert 'mmetl_extra' in read_csv(tmp_path / 'o.csv')[0]


def test_import_overflow_replies_are_detected():
    from rewrite_import import count_overflow_replies
    post = {'user': 'a', 'create_at': 100, 'message': 'hi', 'attachments': [1] * 5}
    over = {'user': 'a', 'create_at': 101, 'message': '', 'attachments': [1] * 4}
    plain = {'user': 'a', 'create_at': 101, 'message': 'text', 'attachments': [1]}
    other = {'user': 'b', 'create_at': 101, 'message': '', 'attachments': [1]}
    assert count_overflow_replies([post, over]) == 1
    assert count_overflow_replies([post, plain]) == 0
    assert count_overflow_replies([post, other]) == 0
    assert count_overflow_replies([{**post, 'attachments': [1] * 3}, over]) == 0
