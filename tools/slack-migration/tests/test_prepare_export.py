import json
import zipfile

import pytest

import prepare_export as pe
from common import MigrationError, read_csv


@pytest.fixture
def prepared(export_zip, identity_csv, chat_snapshot, tmp_path):
    users, channels = chat_snapshot
    emoji = tmp_path / 'emoji_map.csv'
    emoji.write_text('slack_name,kind,target,mm_name,status,renamed,resized,simplified,sha256,note\n'
                     'partyparrot,custom,,partyparrot_ifl,imported,yes,no,no,x,\n')
    out = tmp_path / 'prepared.zip'
    cmap = tmp_path / 'channel_map.csv'
    rc = pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                  '--chat-users', str(users), '--chat-channels', str(channels),
                  '--emoji-map', str(emoji), '--output', str(out),
                  '--channel-map', str(cmap), '--report', str(tmp_path / 'r.md')])
    assert rc == 0
    z = zipfile.ZipFile(out)
    yield z, {r['slack_id']: r for r in read_csv(cmap)}
    z.close()


def msgs(z, name):
    return json.loads(z.read(name))


def test_channel_map(prepared):
    z, cmap = prepared
    assert cmap['C1GEN']['mm_name'] == 'town-square'
    assert cmap['C1GEN']['mm_display_name'] == 'Town Square'
    assert cmap['C2OLD']['mm_name'] == 'old_stuff-slack'      # name already used in chat
    assert cmap['C2OLD']['delete_at'] == '1500000200000'      # the channel_archive message
    assert cmap['C3ODD']['mm_name'] == 'kyliesko-ner'
    assert cmap['C3ODD']['mm_display_name'] == 'kylieskoяner'
    orphan = next(r for r in cmap.values() if r['folder'] == 'FC:F05GEKFA4N9:Canvas')
    assert orphan['mm_name'] == 'fc-f05gekfa4n9-canvas' and orphan['archived'] == 'true'
    names = set(z.namelist())
    assert 'town-square/2020-09-13.json' in names
    assert 'fc-f05gekfa4n9-canvas/2023-11-14.json' in names
    chans = {c['id']: c for c in msgs(z, 'channels.json')}
    assert chans['C2OLD']['updated'] == 1500000200000
    assert 'U4BOT' not in chans['C1GEN']['members']


def test_people_and_bots(prepared):
    z, _ = prepared
    users = {u['id']: u for u in msgs(z, 'users.json')}
    assert users['U1JOSH']['name'] == 'josh_0'
    assert users['U2GM']['profile']['email'] == 'brad@example.test'
    assert users['U3GONE']['profile']['email'] == 'slack-u3gone@import.invalid'
    assert users['USLACKBOT']['name'] == 'slackbot'
    assert users['USLACKBOT']['profile']['bot_id'] == 'BSLACKBOT'
    assert users['B9POLL']['name'] == 'simple-poll' and users['B9POLL']['is_bot']
    assert users['U4BOT']['name'] == 'ifl_calendar'


def test_messages(prepared):
    z, _ = prepared
    day = {m['ts']: m for m in msgs(z, 'town-square/2020-09-13.json')}
    first = day['1600000000.000100']
    assert first['text'] == 'hi <@U2GM> :partyparrot_ifl:'
    assert first['reactions'] == [{'name': 'partyparrot_ifl', 'users': ['U2GM'], 'count': 1}]
    assert day['1600000001.000100']['text'] == "pic\n" + pe.NOTE_HIDDEN
    assert 'files' not in day['1600000001.000100']
    two = day['1600000002.000100']
    assert [f['id'] for f in two['files']] == ['FOK']
    assert two['text'] == pe.note_missing('gone.png')          # the download was an HTML page
    bot = day['1600000003.000100']
    assert bot['subtype'] == 'bot_message' and bot['bot_id'] == 'BSLACKBOT'
    assert day['1600000006.000100']['bot_id'] == 'B4CAL'
    assert day['1600000007.000100']['subtype'] == 'thread_broadcast'
    assert 'subtype' not in msgs(z, 'fc-f05gekfa4n9-canvas/2023-11-14.json')[0]
    assert set(n for n in z.namelist() if n.startswith('__uploads/')) == {'__uploads/FOK/shot.png'}


def test_input_is_untouched(export_zip, identity_csv, chat_snapshot, tmp_path):
    before = export_zip.read_bytes()
    users, channels = chat_snapshot
    pe.main(['--input', str(export_zip), '--identity', str(identity_csv), '--chat-users', str(users),
             '--chat-channels', str(channels), '--output', str(tmp_path / 'o.zip'),
             '--channel-map', str(tmp_path / 'm.csv'), '--report', str(tmp_path / 'r.md')])
    assert export_zip.read_bytes() == before
    assert pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                    '--chat-users', str(users), '--chat-channels', str(channels),
                    '--output', str(export_zip), '--channel-map', str(tmp_path / 'm.csv'),
                    '--report', str(tmp_path / 'r.md')]) == 2


def test_person_missing_from_identity_map_stops(export_zip, identity_csv, chat_snapshot, tmp_path):
    rows = [ln for ln in identity_csv.read_text().splitlines() if not ln.startswith('U2GM,')]
    identity_csv.write_text('\n'.join(rows) + '\n')
    users, channels = chat_snapshot
    with pytest.raises(MigrationError, match='U2GM'):
        pe.prepare(str(export_zip), [], read_csv(identity_csv), json.loads(users.read_text()),
                   {'town-square'}, {}, str(tmp_path / 'o.zip'), str(tmp_path / 'm.csv'))


def test_archive_state_from_before_the_freeze(export_zip, identity_csv, chat_snapshot, tmp_path):
    """Channels archived only to freeze Slack come over open."""
    state = tmp_path / 'prefreeze_counts.csv'
    state.write_text('folder,archived\ngeneral,false\nold_stuff,false\n')
    users, channels = chat_snapshot
    cmap = tmp_path / 'm.csv'
    assert pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                    '--chat-users', str(users), '--chat-channels', str(channels),
                    '--output', str(tmp_path / 'o.zip'), '--channel-map', str(cmap),
                    '--report', str(tmp_path / 'r.md'), '--archive-state', str(state)]) == 0
    rows = {r['slack_id']: r for r in read_csv(cmap)}
    assert rows['C2OLD']['archived'] == 'false' and rows['C2OLD']['delete_at'] == ''


# ---------------------------------------------------------------- review fixes

import os  # noqa: E402

JOSH = {'id': 'U1JOSH', 'name': 'josh', 'deleted': False, 'is_bot': False,
        'profile': {'real_name': 'Josh H', 'email': 'josh@example.test'}}
JOSH_CHAT = {'username': 'josh_0', 'email': 'josh@example.test', 'auth_service': 'gitlab', 'auth_data': '1'}
IDENT = [{'slack_id': 'U1JOSH', 'slack_username': 'josh', 'is_bot': 'false', 'slack_deleted': '',
          'match': 'email', 'site_id': '1', 'site_username': 'josh', 'site_email': 'josh@example.test',
          'site_member': 'yes', 'chat_username': 'josh_0', 'chat_email': 'josh@example.test',
          'chat_active': 'yes', 'confirmed': 'yes', 'mm_username_override': ''}]


def chan(cid, name, archived=False):
    return {'id': cid, 'name': name, 'created': 1500000000, 'creator': 'U1JOSH',
            'is_archived': archived, 'is_general': False, 'members': ['U1JOSH'],
            'purpose': {'value': ''}, 'topic': {'value': ''}}


def msg(ts, text='x', **kw):
    d = {'type': 'message', 'user': 'U1JOSH', 'text': text, 'ts': ts}
    d.update(kw)
    return d


def build(tmp_path, channels, days, uploads=None, name='in.zip'):
    """days: {folder: [messages]}; uploads: {'FID/name': bytes}."""
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('channels.json', json.dumps(channels))
        z.writestr('users.json', json.dumps([JOSH]))
        for folder, ms in days.items():
            z.writestr(f'{folder}/2020-01-01.json', json.dumps(ms))
        for member, data in (uploads or {}).items():
            z.writestr(f'__uploads/{member}', data)
    return path


def zip_of(tmp_path, uploads, name='extra.zip'):
    path = tmp_path / name
    with zipfile.ZipFile(path, 'w') as z:
        for member, data in uploads.items():
            z.writestr(f'__uploads/{member}', data)
    return path


def run(tmp_path, src, chat_users=(JOSH_CHAT,), chat_channels=('town-square',), extra=(),
        archive_state=None):
    out, cmap = tmp_path / 'out.zip', tmp_path / 'cmap.csv'
    stats = pe.prepare(str(src), [str(p) for p in extra], IDENT, list(chat_users),
                       set(chat_channels), {}, str(out), str(cmap), archive_state)
    return zipfile.ZipFile(out), {r['slack_id']: r for r in read_csv(cmap)}, stats


def folder_msgs(z, folder):
    return json.loads(z.read(f'{folder}/2020-01-01.json'))


def test_tombstone_becomes_a_slackbot_post_in_its_thread(tmp_path):
    src = build(tmp_path, [chan('C1', 'general')], {'general': [
        msg('1.1', 'This message was deleted.', subtype='tombstone', user='USLACKBOT',
            thread_ts='1.1', reply_count=1),
        msg('1.2', 'reply', thread_ts='1.1')]})
    z, _, stats = run(tmp_path, src)
    first, reply = folder_msgs(z, 'town-square')
    assert first['text'] == pe.TOMBSTONE_TEXT
    assert first['subtype'] == 'bot_message' and first['bot_id'] == 'BSLACKBOT'
    assert first['thread_ts'] == '1.1' and reply['thread_ts'] == '1.1'
    assert stats['converted tombstone to a slackbot post'] == 1
    assert any(u['id'] == 'USLACKBOT' and u['name'] == 'slackbot' for u in json.loads(z.read('users.json')))


def test_slackbot_reply_keeps_its_thread_link(prepared):
    z, _ = prepared
    day = {m['ts']: m for m in msgs(z, 'town-square/2020-09-13.json')}
    assert day['1600000003.000100']['thread_ts'] == '1600000003.000100'
    assert day['1600000004.000100']['thread_ts'] == '1600000003.000100'
    assert day['1600000007.000100']['thread_ts'] == '1600000003.000100'


def test_file_notes(tmp_path):
    src = build(tmp_path, [chan('C1', 'general')], {'general': [
        msg('1.1', 'gone', files=[{'id': 'FD', 'mode': 'tombstone'}]),
        msg('1.2', '', files=[{'id': 'FE', 'is_external': True, 'title': 'a [b] c',
                               'url_private': 'https://example.test/doc'}]),
        msg('1.3', '', files=[{'id': 'FH', 'mode': 'hidden_by_limit'},
                              {'id': 'FN', 'name': 'x.png', 'size': 1}])]})
    z, _, stats = run(tmp_path, src)
    a, b, c = folder_msgs(z, 'town-square')
    assert a['text'] == 'gone\n' + pe.NOTE_DELETED and 'files' not in a
    assert b['text'] == r'[a \[b\] c](https://example.test/doc)'
    assert c['text'] == pe.NOTE_HIDDEN + '\n' + pe.note_missing('x.png')
    assert stats['files deleted in Slack'] == 1 and stats['external files kept as links'] == 1


def test_channel_name_collisions_among_slack_channels(tmp_path):
    src = build(tmp_path, [chan('C1', 'dev-ops'), chan('C2', 'dev.ops'), chan('C3', 'dev ops')],
                {'dev-ops': [msg('1.1')], 'dev.ops': [msg('1.1')], 'dev ops': [msg('1.1')]})
    z, rows, _ = run(tmp_path, src)
    names = [rows[i]['mm_name'] for i in ('C1', 'C2', 'C3')]
    assert names == ['dev-ops', 'dev-ops-2', 'dev-ops-3']
    assert all(f'{n}/2020-01-01.json' in z.namelist() for n in names)


def test_slack_suffix_and_numbering_check_each_other_against_chat(tmp_path):
    src = build(tmp_path, [chan('C1', 'foo'), chan('C2', 'baz'), chan('C3', 'baz.')],
                {'foo': [msg('1.1')], 'baz': [msg('1.1')], 'baz.': [msg('1.1')]})
    _, rows, _ = run(tmp_path, src, chat_channels=('town-square', 'foo', 'foo-slack', 'baz-2'))
    assert rows['C1']['mm_name'] == 'foo-slack-2'
    assert rows['C2']['mm_name'] == 'baz' and rows['C3']['mm_name'] == 'baz-3'


def test_bot_names_avoid_existing_chat_accounts(tmp_path):
    src = build(tmp_path, [chan('C1', 'general')], {'general': [
        msg('1.1', 'a', user=None, subtype='bot_message', bot_id='B1', username='IFL Relay'),
        msg('1.2', 'b', user=None, subtype='bot_message', bot_id='B2', username='IFL Bot')]})
    chat = [JOSH_CHAT, {'username': 'ifl-relay'}, {'username': 'ifl-bot'}]
    z, _, _ = run(tmp_path, src, chat_users=chat)
    names = [u['name'] for u in json.loads(z.read('users.json')) if u.get('is_bot')]
    assert len(names) == len(set(names)) == 2
    assert not {'ifl-relay', 'ifl-bot'} & set(names)


def test_unlabelled_bots_are_named_from_their_id(tmp_path):
    src = build(tmp_path, [chan('C1', 'general')], {'general': [
        msg('1.1', 'a', user=None, subtype='bot_message', bot_id='B0AAA'),
        msg('1.2', 'b', user=None, bot_id='B0BBB'),
        msg('1.3', 'c', user=None, subtype='bot_message', bot_id='B0CCC', username='Poller'),
        msg('1.4', 'd', user=None, subtype='bot_message', bot_id='B0DDD', username='жж')]})
    z, _, _ = run(tmp_path, src)
    users = {u['id']: u['name'] for u in json.loads(z.read('users.json'))}
    assert users['B0AAA'] == 'integration-b0aaa' and users['B0BBB'] == 'integration-b0bbb'
    assert users['B0CCC'] == 'poller'
    assert users['B0DDD'] == 'integration-b0ddd'
    again, _, _ = run(tmp_path, src)
    assert again.read('users.json') == z.read('users.json')


def test_username_only_bot_message_gets_a_bot_id(tmp_path):
    src = build(tmp_path, [chan('C1', 'general')], {'general': [
        msg('1.1', 'a', user=None, subtype='bot_message', username='Hook X'),
        msg('1.2', 'b', user=None, subtype='bot_message', username='Hook X'),
        msg('1.3', 'c', user=None, subtype='bot_message', username='Known', bot_id='B0K'),
        msg('1.4', 'd', user=None, subtype='bot_message', username='Known')]})
    z, _, _ = run(tmp_path, src)
    a, b, c, d = folder_msgs(z, 'town-square')
    assert a['bot_id'] and a['bot_id'] == b['bot_id'] and a['bot_id'] != 'Hook X'
    assert d['bot_id'] == c['bot_id'] == 'B0K'
    bots = {u['id']: u['name'] for u in json.loads(z.read('users.json')) if u.get('is_bot')}
    assert bots[a['bot_id']] == 'hook-x' and bots['B0K'] == 'known'


def test_archive_state_can_force_a_channel_archived(export_zip, identity_csv, chat_snapshot, tmp_path):
    state = tmp_path / 's.csv'
    state.write_text('folder,archived\nkylieskoяner,true\nFC:F05GEKFA4N9:Canvas,false\n', encoding='utf-8')
    users, channels = chat_snapshot
    cmap = tmp_path / 'm.csv'
    assert pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                    '--chat-users', str(users), '--chat-channels', str(channels),
                    '--output', str(tmp_path / 'o.zip'), '--channel-map', str(cmap),
                    '--report', str(tmp_path / 'r.md'), '--archive-state', str(state)]) == 0
    rows = {r['slack_id']: r for r in read_csv(cmap)}
    assert rows['C3ODD']['archived'] == 'true' and rows['C3ODD']['delete_at'] != ''
    assert rows['C1GEN']['archived'] == 'false'
    orphan = next(r for r in rows.values() if r['folder'].startswith('FC:'))
    assert orphan['archived'] == 'true'


def upload_case(tmp_path):
    files = [{'id': 'FBAD', 'name': 'gone.png', 'size': 10}, {'id': 'FMIS', 'name': 'a.png', 'size': 3},
             {'id': 'FOK', 'name': 'shot.png', 'size': 4}, {'id': 'FX', 'name': 'x.png', 'size': 5}]
    src = build(tmp_path, [chan('C1', 'general')],
                {'general': [msg(f'1.{i}', '', files=[f]) for i, f in enumerate(files)]},
                {'FBAD/gone.png': b'<!DOCTYPE html><html>no</html>', 'FOK/shot.png': b'\x89PNG'})
    extra1 = zip_of(tmp_path, {'FBAD/gone.png': b'0123456789', 'FOK/shot.png': b'EVIL',
                               'FMIS/b.png': b'abc', 'FX/x.png': b'toolong!'}, 'e1.zip')
    extra2 = zip_of(tmp_path, {'FX/x.png': b'12345'}, 'e2.zip')
    return src, [extra1, extra2]


def test_extra_uploads_replace_rejected_copies(tmp_path):
    src, extra = upload_case(tmp_path)
    z, _, stats = run(tmp_path, src, extra=extra)
    got = {n: z.read(n) for n in z.namelist() if n.startswith('__uploads/')}
    assert got == {'__uploads/FBAD/gone.png': b'0123456789', '__uploads/FOK/shot.png': b'\x89PNG',
                   '__uploads/FX/x.png': b'12345'}
    ms = {m['ts']: m for m in folder_msgs(z, 'town-square')}
    assert pe.note_missing('a.png') == ms['1.1']['text'] and 'files' not in ms['1.1']
    assert ms['1.0']['files'][0]['id'] == 'FBAD'
    assert stats['downloads rejected (wrong size or an HTML error page)'] == 2   # the HTML page and the long copy
    assert stats['downloads rejected (file name differs from the message)'] == 1


def test_uploads_are_not_read_into_memory(tmp_path, monkeypatch):
    src, extra = upload_case(tmp_path)
    real, seen = zipfile.ZipFile.read, []
    monkeypatch.setattr(zipfile.ZipFile, 'read',
                        lambda self, n, *a, **k: (seen.append(getattr(n, 'filename', n)),
                                                  real(self, n, *a, **k))[1])
    run(tmp_path, src, extra=extra)
    assert not [n for n in seen if '__uploads' in n]


def test_failure_removes_partial_and_closes_every_archive(tmp_path, monkeypatch):
    src, extra = upload_case(tmp_path)
    opened = []

    class Spy(zipfile.ZipFile):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)
    monkeypatch.setattr(pe.zipfile, 'ZipFile', Spy)
    monkeypatch.setattr(pe, 'fix_message', lambda *a, **k: (_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(RuntimeError):
        pe.prepare(str(src), [str(p) for p in extra], IDENT, [JOSH_CHAT], {'town-square'}, {},
                   str(tmp_path / 'out.zip'), str(tmp_path / 'm.csv'))
    assert not (tmp_path / 'out.zip.partial').exists() and not (tmp_path / 'out.zip').exists()
    assert len(opened) >= 3 and all(z.fp is None for z in opened)


def test_a_corrupt_extra_archive_closes_the_ones_before_it(tmp_path, monkeypatch):
    src, extra = upload_case(tmp_path)
    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'not a zip')
    opened = []

    class Spy(zipfile.ZipFile):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            opened.append(self)
    monkeypatch.setattr(pe.zipfile, 'ZipFile', Spy)
    with pytest.raises(zipfile.BadZipFile):
        pe.prepare(str(src), [str(extra[0]), str(bad)], IDENT, [JOSH_CHAT], {'town-square'}, {},
                   str(tmp_path / 'out.zip'), str(tmp_path / 'm.csv'))
    assert opened and all(z.fp is None for z in opened)


def test_outputs_holding_emails_are_private(tmp_path):
    src, extra = upload_case(tmp_path)
    run(tmp_path, src, extra=extra)
    assert (tmp_path / 'out.zip').stat().st_mode & 0o777 == 0o600


def test_no_output_may_be_an_input_even_through_a_link(export_zip, identity_csv, chat_snapshot, tmp_path):
    users, channels = chat_snapshot
    link = tmp_path / 'link.zip'
    link.symlink_to(export_zip)
    hard = tmp_path / 'hard.csv'
    os.link(identity_csv, hard)
    base = ['--input', str(export_zip), '--identity', str(identity_csv), '--chat-users', str(users),
            '--chat-channels', str(channels)]
    ok = ['--output', str(tmp_path / 'o.zip'), '--channel-map', str(tmp_path / 'm.csv'),
          '--report', str(tmp_path / 'r.md')]

    def with_(flag, value):
        args = list(ok)
        args[args.index(flag) + 1] = str(value)
        return base + args
    before = export_zip.read_bytes()
    assert pe.main(with_('--output', link)) == 2
    assert pe.main(with_('--channel-map', export_zip)) == 2
    assert pe.main(with_('--report', link)) == 2
    assert pe.main(with_('--channel-map', hard)) == 2
    assert pe.main(base + ok[:4] + ['--report', str(tmp_path / 'm.csv')]) == 2   # two outputs, one file
    assert export_zip.read_bytes() == before
