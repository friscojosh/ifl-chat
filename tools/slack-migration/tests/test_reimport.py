"""Re-import: a second Slack export on top of the first import (README "Second import").
All data here is synthetic."""
import json
import os
import shutil
import zipfile

import pytest

import import_emoji as ie
import inventory as inv
import prepare_export as pe
import rewrite_import as ri
from common import (IDENTITY_FIELDS, MigrationError, PriorImport, member_name, post_key, read_csv,
                    resolve_identities, write_csv)
from conftest import identity_row

NOW = 1795000000000
MAP_HEAD = 'slack_id,slack_name,folder,mm_name,mm_display_name,archived,delete_at,messages,reason\n'


# ---------------------------------------------------------------- identities

def chat_after_first_import():
    """Chat accounts once the first import ran: the linked members, the
    deactivated unmatched person and the imported bots."""
    return [
        {'username': 'josh_0', 'email': 'josh@example.test', 'auth_service': 'gitlab', 'auth_data': '1'},
        {'username': 'miami.brad', 'email': 'brad@example.test', 'auth_service': 'gitlab', 'auth_data': '7'},
        {'username': 'old.timer', 'email': 'slack-u3gone@import.invalid', 'auth_service': '',
         'delete_at': 1},
        {'username': 'slackbot', 'email': '', 'is_bot': True},
        {'username': 'ifl-relay', 'email': 'ifl-relay@iflgm.invalid'},
    ]


PRIOR_PEOPLE = {'U1JOSH': {'username': 'josh_0', 'email': 'josh@example.test'},
                'U2GM': {'username': 'miami.brad', 'email': 'brad@example.test'},
                'U3GONE': {'username': 'old.timer', 'email': 'slack-u3gone@import.invalid'}}


def rows(identity_csv):
    return read_csv(identity_csv)


def test_without_prior_every_imported_account_is_refused(identity_csv):
    with pytest.raises(MigrationError) as e:
        resolve_identities(rows(identity_csv), chat_after_first_import())
    assert 'old.timer' in str(e.value) and 'miami.brad' in str(e.value)


def test_people_from_the_first_import_are_existing(identity_csv):
    ids = resolve_identities(rows(identity_csv), chat_after_first_import(), PRIOR_PEOPLE)
    assert ids['U3GONE'] == {'username': 'old.timer', 'email': 'slack-u3gone@import.invalid',
                             'auth_data': None, 'active': False, 'existing': True, 'prior': True,
                             'slack_id': 'U3GONE'}
    assert ids['U2GM']['username'] == 'miami.brad' and ids['U2GM']['auth_data'] == '7'
    assert ids['U1JOSH']['username'] == 'josh_0' and ids['U1JOSH']['prior']


def test_first_run_username_wins_over_a_changed_slack_username(identity_csv, tmp_path):
    r = rows(identity_csv)
    next(x for x in r if x['slack_id'] == 'U3GONE')['slack_username'] = 'renamed.in.slack'
    ids = resolve_identities(r, chat_after_first_import(), PRIOR_PEOPLE)
    assert ids['U3GONE']['username'] == 'old.timer'


def test_new_slack_people_still_go_through_the_normal_checks(identity_csv):
    r = rows(identity_csv) + [identity_row(slack_id='U5NEW', slack_username='new.person', is_bot='false'),
                              identity_row(slack_id='U6CLASH', slack_username='old.timer', is_bot='false')]
    with pytest.raises(MigrationError) as e:
        resolve_identities(r, chat_after_first_import(), PRIOR_PEOPLE)
    assert 'U6CLASH' in str(e.value) and 'U5NEW' not in str(e.value)
    ids = resolve_identities(r[:-1], chat_after_first_import(), PRIOR_PEOPLE)
    assert ids['U5NEW']['existing'] is False and ids['U5NEW']['username'] == 'new.person'


def test_imported_account_missing_from_chat_stops(identity_csv):
    chat = [u for u in chat_after_first_import() if u['username'] != 'old.timer']
    with pytest.raises(MigrationError, match='U3GONE.*not in the chat snapshot'):
        resolve_identities(rows(identity_csv), chat, PRIOR_PEOPLE)


def test_newly_confirmed_person_must_be_linked_in_chat_first(identity_csv):
    r = rows(identity_csv)
    row = next(x for x in r if x['slack_id'] == 'U3GONE')
    row.update(confirmed='yes', site_id='9', site_member='yes', site_email='old@example.test')
    with pytest.raises(MigrationError, match='link-slack-user'):
        resolve_identities(r, chat_after_first_import(), PRIOR_PEOPLE)
    chat = chat_after_first_import()
    chat[2].update(auth_service='gitlab', auth_data='9', email='old@example.test')
    ids = resolve_identities(r, chat, PRIOR_PEOPLE)
    assert ids['U3GONE']['username'] == 'old.timer' and ids['U3GONE']['auth_data'] == '9'


# ---------------------------------------------------------------- prepare_export

@pytest.fixture
def first_run(export_zip, identity_csv, chat_snapshot, tmp_path):
    """Run prepare_export the first time, then build the chat snapshot the
    first import leaves behind."""
    users, channels = chat_snapshot
    emoji = tmp_path / 'emoji_map.csv'
    emoji.write_text('slack_name,kind,target,mm_name,status,renamed,resized,simplified,sha256,note\n'
                     'partyparrot,custom,,partyparrot_ifl,imported,yes,no,no,x,\n')
    prior = tmp_path / 'prod'
    prior.mkdir()
    assert pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                    '--chat-users', str(users), '--chat-channels', str(channels),
                    '--emoji-map', str(emoji), '--output', str(prior / 'prepared.zip'),
                    '--channel-map', str(prior / 'channel_map.csv'), '--report', str(tmp_path / 'r1.md')]) == 0
    (prior / 'import.zip').write_bytes(b'')   # prepare_export only needs it to exist
    cmap = read_csv(prior / 'channel_map.csv')
    with zipfile.ZipFile(prior / 'prepared.zip') as z:
        first_users = json.loads(z.read('users.json'))
    after_users = json.loads(users.read_text())
    after_users += [{'username': u['name'], 'email': (u.get('profile') or {}).get('email', ''),
                     'is_bot': bool(u.get('is_bot'))}
                    for u in first_users if u['name'] != 'josh_0']
    after_users[[u['username'] for u in after_users].index('miami.brad')].update(
        auth_service='gitlab', auth_data='7')
    now_users = tmp_path / 'chat_users_now.json'
    now_users.write_text(json.dumps(after_users))
    now_channels = tmp_path / 'chat_channels_now.txt'
    now_channels.write_text(channels.read_text() + ''.join(r['mm_name'] + '\n' for r in cmap))
    return prior, emoji, now_users, now_channels


def run_second(export_zip, identity_csv, first_run, tmp_path, out='second'):
    prior, emoji, now_users, now_channels = first_run
    d = tmp_path / out
    d.mkdir()
    rc = pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                  '--chat-users', str(now_users), '--chat-channels', str(now_channels),
                  '--emoji-map', str(emoji), '--output', str(d / 'prepared.zip'),
                  '--channel-map', str(d / 'channel_map.csv'), '--report', str(d / 'r.md'),
                  '--reimport-from', str(prior), '--prior-emoji-map', str(emoji)])
    return rc, d


def test_without_reimport_a_second_run_refuses_imported_people(export_zip, identity_csv, first_run, tmp_path):
    prior, emoji, now_users, now_channels = first_run
    with pytest.raises(MigrationError):    # every imported person is refused
        pe.prepare(str(export_zip), [], read_csv(identity_csv), json.loads(now_users.read_text()),
                   {'x'}, {}, str(tmp_path / 'p.zip'), str(tmp_path / 'm.csv'))


def test_second_run_reproduces_the_first(export_zip, identity_csv, first_run, tmp_path):
    prior = first_run[0]
    rc, d = run_second(export_zip, identity_csv, first_run, tmp_path)
    assert rc == 0
    first = {r['slack_id']: r for r in read_csv(prior / 'channel_map.csv')}
    second = {r['slack_id']: r for r in read_csv(d / 'channel_map.csv')}
    assert {k: (v['mm_name'], v['mm_display_name']) for k, v in second.items()} == \
           {k: (v['mm_name'], v['mm_display_name']) for k, v in first.items()}
    assert not any(r['mm_name'].endswith('-slack-slack') for r in second.values())
    assert all(r['reason'] == 'imported by the first run' for r in second.values())
    with zipfile.ZipFile(prior / 'prepared.zip') as a, zipfile.ZipFile(d / 'prepared.zip') as b:
        assert sorted(a.namelist()) == sorted(b.namelist())
        for name in a.namelist():
            if name.endswith('.json') and name != 'users.json':
                assert a.read(name) == b.read(name), name   # same text, mentions, emoji
        ua = {u['id']: u['name'] for u in json.loads(a.read('users.json'))}
        ub = {u['id']: u['name'] for u in json.loads(b.read('users.json'))}
        assert ua == ub
    report = (d / 'r.md').read_text()
    assert '- re-import: new channels: 0' in report
    assert '- re-import: new people: 0' in report and '- re-import: new bots: 0' in report


def test_new_channel_and_new_person_get_the_usual_handling(export_zip, identity_csv, first_run, tmp_path):
    with zipfile.ZipFile(export_zip) as z:
        members = {member_name(i): z.read(i) for i in z.infolist()}
    chans = json.loads(members['channels.json'])
    chans.append({'id': 'C9NEW', 'name': 'old_stuff-slack', 'created': 1700000000, 'creator': 'U1JOSH',
                  'is_archived': False, 'members': ['U5NEW'], 'purpose': {'value': ''},
                  'topic': {'value': ''}})
    users = json.loads(members['users.json'])
    users.append({'id': 'U5NEW', 'name': 'new.person', 'deleted': False, 'is_bot': False,
                  'profile': {'real_name': 'New', 'email': ''}})
    members['channels.json'] = json.dumps(chans).encode()
    members['users.json'] = json.dumps(users).encode()
    members['old_stuff-slack/2026-11-25.json'] = json.dumps(
        [{'type': 'message', 'user': 'U5NEW', 'text': 'hello', 'ts': '1795000000.000100'}]).encode()
    new_zip = tmp_path / 'export2.zip'
    with zipfile.ZipFile(new_zip, 'w') as z:
        for n, b in members.items():
            z.writestr(n, b)
    ident = tmp_path / 'identity2.csv'
    r = read_csv(identity_csv) + [identity_row(slack_id='U5NEW', slack_username='new.person', is_bot='false')]
    write_csv(ident, r, IDENTITY_FIELDS)
    rc, d = run_second(new_zip, ident, first_run, tmp_path)
    assert rc == 0
    cmap = {r['slack_id']: r for r in read_csv(d / 'channel_map.csv')}
    # The Slack name equals a chat channel (one the first import made): `-slack` as usual,
    # and never one of the first run's names.
    assert cmap['C9NEW']['mm_name'] == 'old_stuff-slack-slack'
    assert cmap['C2OLD']['mm_name'] == 'old_stuff-slack'
    with zipfile.ZipFile(d / 'prepared.zip') as z:
        names = {u['id']: u['name'] for u in json.loads(z.read('users.json'))}
    assert names['U5NEW'] == 'new.person'


def test_channel_from_the_first_import_missing_in_chat_stops(export_zip, identity_csv, first_run, tmp_path):
    first_run[3].write_text('town-square\noff-topic\n')
    rc, _ = run_second(export_zip, identity_csv, first_run, tmp_path)
    assert rc == 2


def test_prior_emoji_names_win(export_zip, identity_csv, first_run, tmp_path):
    prior, emoji, now_users, now_channels = first_run
    newer = tmp_path / 'emoji_new.csv'
    newer.write_text('slack_name,kind,target,mm_name,status,renamed,resized,simplified,sha256,note\n'
                     'partyparrot,custom,,partyparrot_2,imported,yes,no,no,x,\n')
    d = tmp_path / 'e'
    d.mkdir()
    assert pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                    '--chat-users', str(now_users), '--chat-channels', str(now_channels),
                    '--emoji-map', str(newer), '--output', str(d / 'prepared.zip'),
                    '--channel-map', str(d / 'channel_map.csv'), '--report', str(d / 'r.md'),
                    '--reimport-from', str(prior), '--prior-emoji-map', str(emoji)]) == 0
    with zipfile.ZipFile(d / 'prepared.zip') as z:
        day = json.loads(z.read('town-square/2020-09-13.json'))
    assert day[0]['text'] == 'hi <@U2GM> :partyparrot_ifl:'


def test_prior_emoji_map_pins_unrenamed_and_failed_names(tmp_path):
    m = tmp_path / 'm.csv'
    m.write_text('slack_name,kind,target,mm_name,status,renamed,resized,simplified,sha256,note\n'
                 'same,custom,,same,imported,no,no,no,x,\n'
                 'broke,custom,,broke,failed,no,no,no,x,\n'
                 'moved,custom,,moved_2,unchanged,yes,no,no,x,\n')
    assert pe.load_prior_emoji_map(m) == {'same': 'same', 'broke': 'broke', 'moved': 'moved_2'}


def test_reimport_flags_go_together(export_zip, identity_csv, first_run, tmp_path):
    prior, emoji, now_users, now_channels = first_run
    assert pe.main(['--input', str(export_zip), '--identity', str(identity_csv),
                    '--chat-users', str(now_users), '--chat-channels', str(now_channels),
                    '--output', str(tmp_path / 'x.zip'), '--channel-map', str(tmp_path / 'x.csv'),
                    '--report', str(tmp_path / 'x.md'), '--reimport-from', str(prior)]) == 2


# ---------------------------------------------------------------- rewrite_import

def user_line(username, email):
    return {'type': 'user', 'user': {
        'username': username, 'email': email, 'auth_service': None, 'roles': 'system_user',
        'teams': [{'name': 'ifl', 'roles': 'team_user', 'channels': [
            {'name': 'town-square', 'roles': 'channel_user'}]}]}}


def chan(name, **kw):
    return {'type': 'channel', 'channel': {'team': 'ifl', 'name': name, 'display_name': name,
                                           'type': 'O', **kw}}


ATT = 'bulk-export-attachments/FOK_shot.png'
HI = {'team': 'ifl', 'channel': 'town-square', 'user': 'josh_0', 'message': 'hi', 'create_at': 1000,
      'attachments': [{'path': ATT}],
      'reactions': [{'user': 'miami.brad', 'emoji_name': 'thumbsup', 'create_at': 1001}],
      'replies': [{'user': 'miami.brad', 'message': 'r', 'create_at': 1005}]}


def prior_lines():
    return [
        {'type': 'version', 'version': 1},
        chan('town-square'), chan('old_stuff-slack', deleted_at=200),
        {'type': 'post', 'post': HI},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'town-square', 'user': 'old.timer',
                                  'message': 'typo', 'create_at': 1010}},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'old_stuff-slack', 'user': 'old.timer',
                                  'message': 'ancient', 'create_at': 6}},
    ]


def second_lines():
    hi = json.loads(json.dumps(HI))
    hi['message'] = 'hi (edited in Slack)'          # the root changed since the first export
    hi['reactions'].append({'user': 'josh_0', 'emoji_name': 'thumbsup', 'create_at': 1500})
    hi['replies'].append({'user': 'miami.brad', 'message': 'later reply', 'create_at': 2000,
                          'reactions': [{'user': 'new.person', 'emoji_name': 'thumbsup', 'create_at': 2001}]})
    return [
        {'type': 'version', 'version': 1},
        chan('town-square'), chan('old_stuff-slack', deleted_at=999), chan('new-chan'),
        user_line('josh_0', 'josh@example.test'), user_line('miami.brad', 'brad@example.test'),
        user_line('old.timer', 'slack-u3gone@import.invalid'),
        user_line('new.person', 'slack-u5new@import.invalid'),
        {'type': 'bot', 'bot': {'username': 'slackbot', 'display_name': 'Slackbot', 'owner': 'josh_0'}},
        {'type': 'post', 'post': hi},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'town-square', 'user': 'old.timer',
                                  'message': 'typo fixed', 'create_at': 1010}},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'town-square', 'user': 'new.person',
                                  'message': 'fresh', 'create_at': 3000,
                                  'attachments': [{'path': 'bulk-export-attachments/FNEW_n.png'}],
                                  'reactions': [{'user': 'josh_0', 'emoji_name': 'thumbsup',
                                                 'create_at': 3001}]}},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'old_stuff-slack', 'user': 'old.timer',
                                  'message': 'ancient', 'create_at': 6}},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'new-chan', 'user': 'josh_0',
                                  'message': 'first', 'create_at': 50}},
    ]


def write_import_zip(path, lines, files):
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('import.jsonl', '\n'.join(json.dumps(x) for x in lines) + '\n')
        for name, data in files.items():
            z.writestr('data/' + name, data)


@pytest.fixture
def reimport_setup(tmp_path, identity_csv):
    prior = tmp_path / 'prod'
    prior.mkdir()
    (prior / 'channel_map.csv').write_text(MAP_HEAD + 'C1GEN,general,general,town-square,Town Square,false,,3,\n'
                                           'C2OLD,old_stuff,old_stuff,old_stuff-slack,old_stuff,true,200,1,\n')
    with zipfile.ZipFile(prior / 'prepared.zip', 'w') as z:
        z.writestr('users.json', json.dumps([
            {'id': 'U1JOSH', 'name': 'josh_0', 'is_bot': False, 'profile': {'email': 'josh@example.test'}},
            {'id': 'U2GM', 'name': 'miami.brad', 'is_bot': False, 'profile': {'email': 'brad@example.test'}},
            {'id': 'U3GONE', 'name': 'old.timer', 'is_bot': False,
             'profile': {'email': 'slack-u3gone@import.invalid'}},
            {'id': 'USLACKBOT', 'name': 'slackbot', 'is_bot': True, 'profile': {'bot_id': 'BSLACKBOT'}}]))
    write_import_zip(prior / 'import.zip', prior_lines(), {ATT: b'\x89PNG-first'})
    ident = tmp_path / 'identity2.csv'
    write_csv(ident, read_csv(identity_csv) + [
        identity_row(slack_id='U5NEW', slack_username='new.person', is_bot='false')], IDENTITY_FIELDS)
    chat = tmp_path / 'chat_now.json'
    chat.write_text(json.dumps(chat_after_first_import()))
    w = tmp_path / 'second'
    (w / 'data' / 'bulk-export-attachments').mkdir(parents=True)
    (w / 'data' / ATT).write_bytes(b'\x89PNG-again')
    (w / 'data' / 'bulk-export-attachments' / 'FNEW_n.png').write_bytes(b'\x89PNG-new')
    (w / 'data.jsonl').write_text('\n'.join(json.dumps(x) for x in second_lines()) + '\n')
    (w / 'channel_map.csv').write_text(
        MAP_HEAD + 'C1GEN,general,general,town-square,Town Square,false,,3,imported by the first run\n'
        'C2OLD,old_stuff,old_stuff,old_stuff-slack,old_stuff,true,200,1,imported by the first run\n'
        'C9,new-chan,new-chan,new-chan,new-chan,false,,1,\n')
    sysemoji = tmp_path / 'emoji_data.go'
    sysemoji.write_text('var SystemEmojis = map[string]string{\n\t"thumbsup": "1f44d",\n}\n')
    args = ['--input', str(w / 'data.jsonl'), '--attachments-dir', str(w / 'data'),
            '--identity', str(ident), '--chat-users', str(chat), '--channel-map', str(w / 'channel_map.csv'),
            '--system-emoji', str(sysemoji), '--output-zip', str(w / 'import.zip'),
            '--counts', str(w / 'counts.csv'), '--report', str(w / 'rewrite.md'),
            '--plan', str(w / 'plan.csv'), '--now-ms', str(NOW), '--reimport-from', str(prior)]
    return prior, w, args


def read_out(path):
    with zipfile.ZipFile(path) as z:
        lines = [json.loads(x) for x in z.read('import.jsonl').decode().split('\n') if x.strip()]
        files = {n: z.read(n) for n in z.namelist() if n.startswith('data/')}
    return lines, files


def test_since_first_import_emits_only_new_posts(reimport_setup):
    prior, w, args = reimport_setup
    assert ri.main(args) == 0
    out, files = read_out(w / 'import.zip')
    assert [x['channel']['name'] for x in out if x['type'] == 'channel'] == ['new-chan']
    assert [x['user']['username'] for x in out if x['type'] == 'user'] == ['new.person']
    assert not [x for x in out if x['type'] == 'bot']
    posts = {(x['post']['channel'], x['post']['create_at']): x['post'] for x in out if x['type'] == 'post'}
    assert set(posts) == {('town-square', 1000), ('town-square', 3000), ('new-chan', 50)}
    carrier = posts[('town-square', 1000)]
    # The first import's root: its text (not Slack's edit), its file, no reactions,
    # and only the reply that is new.
    assert carrier['message'] == 'hi' and carrier['attachments'] == [{'path': ATT}]
    assert 'reactions' not in carrier
    assert [r['message'] for r in carrier['replies']] == ['later reply']
    assert files['data/' + ATT] == b'\x89PNG-first'
    assert files['data/bulk-export-attachments/FNEW_n.png'] == b'\x89PNG-new'
    plan = {r['mm_name']: r for r in read_csv(w / 'plan.csv')}
    ts = plan['town-square']
    assert (ts['new_posts'], ts['new_replies'], ts['carrier_roots'], ts['carrier_roots_edited']) == \
           ('1', '1', '1', '1')
    assert (ts['new_reactions'], ts['new_attachments']) == ('2', '1')
    assert (ts['unchanged'], ts['skipped_changed'], ts['skipped_reactions']) == ('1', '2', '0')
    assert plan['new-chan']['new_channel'] == 'true' and plan['new-chan']['new_posts'] == '1'
    assert plan['old_stuff-slack']['unchanged'] == '1' and plan['old_stuff-slack']['new_posts'] == '0'
    report = (w / 'rewrite.md').read_text()
    assert '- new channels: 1' in report and '- problems: 0' in report


def test_unchanged_root_with_new_reply_and_new_reaction_on_old_post(reimport_setup):
    prior, w, args = reimport_setup
    lines = second_lines()
    lines[9]['post']['message'] = 'hi'                 # root not edited this time
    (w / 'data.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
    assert ri.main(args) == 0
    plan = {r['mm_name']: r for r in read_csv(w / 'plan.csv')}['town-square']
    assert plan['carrier_roots'] == '1' and plan['carrier_roots_edited'] == '0'
    assert plan['unchanged'] == '2' and plan['skipped_reactions'] == '1'


def test_thread_whose_root_is_not_in_chat_is_skipped(reimport_setup):
    prior, w, args = reimport_setup
    write_import_zip(prior / 'import.zip', [x for x in prior_lines()
                                            if x.get('post', {}).get('create_at') != 1000],
                     {ATT: b'\x89PNG-first'})
    # keep the cutoff past the thread: the 1010 post is still there
    assert ri.main(args) == 0
    out, _ = read_out(w / 'import.zip')
    assert ('town-square', 1000) not in {(x['post']['channel'], x['post']['create_at'])
                                         for x in out if x['type'] == 'post'}
    plan = {r['mm_name']: r for r in read_csv(w / 'plan.csv')}['town-square']
    assert plan['skipped_threads'] == '1' and plan['skipped_thread_replies'] == '1'


def test_full_emits_everything_and_counts_duplicates(reimport_setup, capsys):
    prior, w, args = reimport_setup
    assert ri.main(args + ['--full']) == 0
    assert 'DUPLICATE' in capsys.readouterr().err
    out, _ = read_out(w / 'import.zip')
    assert len([x for x in out if x['type'] == 'post']) == 5
    assert [x['channel']['name'] for x in out if x['type'] == 'channel'] == ['new-chan']
    plan = {r['mm_name']: r for r in read_csv(w / 'plan.csv')}
    ts = plan['town-square']
    # The edited root, its old reply (now under a new root) and the edited post duplicate.
    assert (ts['matched'], ts['duplicates'], ts['new_posts'], ts['new_replies']) == ('0', '3', '1', '1')
    assert plan['old_stuff-slack']['matched'] == '1'
    assert '--full' in (w / 'rewrite.md').read_text()


def test_since_and_full_are_exclusive_and_need_reimport(reimport_setup):
    prior, w, args = reimport_setup
    with pytest.raises(SystemExit):
        ri.main(args + ['--full', '--since-first-import'])
    i = args.index('--reimport-from')
    assert ri.main(args[:i] + ['--full']) == 2


def test_outputs_never_overwrite_the_first_run(reimport_setup):
    prior, w, args = reimport_setup
    i = args.index('--output-zip')
    bad = args[:i + 1] + [str(prior / 'import.zip')] + args[i + 2:]
    before = (prior / 'import.zip').read_bytes()
    assert ri.main(bad) == 2
    assert (prior / 'import.zip').read_bytes() == before


def test_prior_bot_missing_from_chat_is_a_problem(reimport_setup, tmp_path):
    prior, w, args = reimport_setup
    chat = [u for u in chat_after_first_import() if u['username'] != 'slackbot']
    (tmp_path / 'chat_now.json').write_text(json.dumps(chat))
    assert ri.main(args) == 1
    assert 'slackbot from the first import is not in chat' in (w / 'rewrite.md').read_text()


# ---------------------------------------------------------------- reconcile (inventory)

def test_reimport_check_predicts_the_since_run(reimport_setup, tmp_path, capsys):
    prior, w, args = reimport_setup
    assert ri.main(args) == 0
    out = tmp_path / 'check.csv'
    assert inv.main(['reimport-check', '--prior', str(prior / 'import.zip'),
                     '--new', str(w / 'import.zip'), '--out', str(out)]) == 0
    text = capsys.readouterr().out
    assert 'new channels: 1' in text and 'new posts: 2' in text and 'new replies: 1' in text
    assert 'possible duplicates: 0' in text and 'HAZARD' not in text
    rows = {r['mm_name']: r for r in read_csv(out)}
    assert rows['town-square']['matched'] == '1' and rows['town-square']['reactions_readded'] == '0'


def test_reimport_check_flags_duplicates_and_existing_channels(reimport_setup, tmp_path, capsys):
    prior, w, args = reimport_setup
    assert ri.main(args + ['--full']) == 0
    out = tmp_path / 'check.csv'
    assert inv.main(['reimport-check', '--prior', str(prior / 'import.zip'),
                     '--new', str(w / 'import.zip'), '--out', str(out)]) == 1
    assert 'HAZARD: 3 post(s)' in capsys.readouterr().out
    assert inv.main(['reimport-check', '--prior', str(prior / 'import.zip'), '--allow-duplicates',
                     '--new', str(w / 'import.zip'), '--out', str(out)]) == 0
    # A channel line for a channel already in chat, and a matched post whose files differ.
    bad = tmp_path / 'bad.zip'
    hi = json.loads(json.dumps(HI))
    hi['attachments'] = []
    hi['replies'] = []
    write_import_zip(bad, [chan('town-square'), {'type': 'post', 'post': hi}], {})
    rows, users, bots, hazards = inv.reimport_check(prior / 'import.zip', bad)
    assert any('town-square' in h for h in hazards)
    assert any('different attachments' in h for h in hazards)


def test_reimport_verify(tmp_path):
    check = tmp_path / 'check.csv'
    write_csv(check, [{'mm_name': 'a', 'new_posts': 2, 'new_replies': 1, 'possible_duplicates': 0},
                      {'mm_name': 'b', 'new_posts': 0, 'new_replies': 0, 'possible_duplicates': 0}],
              inv.CHECK_FIELDS)
    (tmp_path / 'before.csv').write_text('mm_name,posts\na,10\nb,5\n')
    (tmp_path / 'after.csv').write_text('mm_name,posts\na,13\nb,6\n')
    rows = inv.reimport_verify(tmp_path / 'before.csv', tmp_path / 'after.csv', check)
    assert {r['mm_name']: r['diff'] for r in rows} == {'a': 0, 'b': 1}


def test_prior_import_index(tmp_path):
    p = tmp_path / 'i.jsonl'
    p.write_text('\n'.join(json.dumps(x) for x in prior_lines()) + '\n')
    idx = PriorImport.load(str(p))
    assert idx.channels == {'town-square', 'old_stuff-slack'}
    assert idx.cutoff == {'town-square': 1010, 'old_stuff-slack': 6}
    k = post_key('town-square', 1000, 'hi')
    assert idx.has(k) and idx.attachments(k) == ('FOK_shot.png',)
    assert idx.reactions(k) == {('miami.brad', 'thumbsup')}
    assert not idx.has(post_key('town-square', 1000, 'hi '))


# ---------------------------------------------------------------- emoji

def test_emoji_names_from_the_first_run_are_kept():
    system = {'smile'}
    entries = [{'slack_name': n, 'kind': 'custom', 'target': '', 'url': 'u', 'note': ''}
               for n in ['Party', 'party', 'party_']]
    # first run: Party -> party, party -> party_2 ; now a new emoji `party_` sorts after them
    # and Slack deleted `Party`.
    prior = {'Party': 'party', 'party': 'party_2'}
    got = {e['slack_name']: e['mm_name'] for e in ie.assign_names(entries[1:], system, prior)}
    assert got == {'party': 'party_2', 'party_': 'party_'}
    entries2 = [{'slack_name': 'pArty', 'kind': 'custom', 'target': '', 'url': 'u', 'note': ''}]
    assert ie.assign_names(entries2, system, prior)[0]['mm_name'] == 'party_3'
