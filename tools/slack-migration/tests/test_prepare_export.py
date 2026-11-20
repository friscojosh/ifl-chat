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
