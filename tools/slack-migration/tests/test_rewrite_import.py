import json
import zipfile

import pytest

import rewrite_import as ri

NOW = 1795000000000


def user_line(username, email):
    return {'type': 'user', 'user': {
        'username': username, 'email': email, 'auth_service': None, 'nickname': '',
        'first_name': 'X', 'last_name': '', 'position': '', 'roles': 'system_user',
        'teams': [{'name': 'ifl', 'roles': 'team_user', 'channels': [
            {'name': 'town-square', 'roles': 'channel_user'}]}]}}


def lines():
    return [
        {'type': 'version', 'version': 1},
        {'type': 'channel', 'channel': {'team': 'ifl', 'name': 'town-square', 'display_name': 'town-square',
                                        'type': 'O', 'header': '', 'purpose': 'chat'}},
        {'type': 'channel', 'channel': {'team': 'ifl', 'name': 'old_stuff-slack',
                                        'display_name': 'old_stuff-slack', 'type': 'O',
                                        'deleted_at': 1500000200000}},
        user_line('josh_0', 'josh@example.test'),
        user_line('miami.brad', 'brad@example.test'),
        user_line('old.timer', 'slack-u3gone@import.invalid'),
        {'type': 'bot', 'bot': {'username': 'slackbot', 'display_name': 'Slackbot', 'owner': 'josh_0'}},
        {'type': 'post', 'post': {
            'team': 'ifl', 'channel': 'town-square', 'user': 'josh_0', 'message': 'hi', 'create_at': 1,
            'attachments': [{'path': 'bulk-export-attachments/FOK_shot.png'}],
            'reactions': [{'user': 'miami.brad', 'emoji_name': 'partyparrot_ifl', 'create_at': 2},
                          {'user': 'miami.brad', 'emoji_name': 'thumbsup', 'create_at': 3},
                          {'user': 'miami.brad', 'emoji_name': 'nosuchthing', 'create_at': 4}],
            'replies': [{'user': 'slackbot', 'message': 'r', 'create_at': 5}]}},
        {'type': 'post', 'post': {'team': 'ifl', 'channel': 'old_stuff-slack', 'user': 'old.timer',
                                  'message': 'ancient', 'create_at': 6}},
    ]


@pytest.fixture
def setup(tmp_path, identity_csv, chat_snapshot):
    jsonl = tmp_path / 'data.jsonl'
    jsonl.write_text('\n'.join(json.dumps(x) for x in lines()) + '\n')
    att = tmp_path / 'data' / 'bulk-export-attachments'
    att.mkdir(parents=True)
    (att / 'FOK_shot.png').write_bytes(b'\x89PNG')
    cmap = tmp_path / 'channel_map.csv'
    cmap.write_text('slack_id,slack_name,folder,mm_name,mm_display_name,archived,delete_at,messages,reason\n'
                    'C1GEN,general,general,town-square,Town Square,false,,8,\n'
                    'C2OLD,old_stuff,old_stuff,old_stuff-slack,old_stuff,true,1500000200000,2,\n')
    emoji = tmp_path / 'emoji_map.csv'
    emoji.write_text('slack_name,kind,target,mm_name,status,renamed,resized,simplified,sha256,note\n'
                     'partyparrot,custom,,partyparrot_ifl,imported,yes,no,no,x,\n')
    sysemoji = tmp_path / 'emoji_data.go'
    sysemoji.write_text('var SystemEmojis = map[string]string{\n\t"thumbsup": "1f44d",\n}\n')
    users, _ = chat_snapshot
    args = ['--input', str(jsonl), '--attachments-dir', str(tmp_path / 'data'),
            '--identity', str(identity_csv), '--chat-users', str(users), '--channel-map', str(cmap),
            '--emoji-map', str(emoji), '--system-emoji', str(sysemoji),
            '--output-zip', str(tmp_path / 'import.zip'), '--counts', str(tmp_path / 'counts.csv'),
            '--report', str(tmp_path / 'report.md'), '--now-ms', str(NOW)]
    return tmp_path, args


def read_import(path):
    with zipfile.ZipFile(path) as z:
        body = z.read('import.jsonl').decode()
        names = z.namelist()
    return [json.loads(x) for x in body.split('\n') if x.strip()], names


def test_rewrite_and_package(setup):
    tmp, args = setup
    assert ri.main(args) == 0
    out, names = read_import(tmp / 'import.zip')
    assert names == ['import.jsonl', 'data/bulk-export-attachments/FOK_shot.png']
    users = {x['user']['username']: x['user'] for x in out if x['type'] == 'user'}
    josh = users['josh_0']
    assert josh['auth_service'] == 'gitlab' and josh['auth_data'] == '1'
    assert 'roles' not in josh and 'delete_at' not in josh           # keeps system_admin
    assert 'first_name' not in josh and 'position' not in josh
    assert 'roles' not in josh['teams'][0]
    assert 'roles' not in josh['teams'][0]['channels'][0]
    brad = users['miami.brad']
    assert brad['auth_data'] == '7' and brad['email'] == 'brad@example.test'
    assert brad['roles'] == 'system_user' and 'delete_at' not in brad
    old = users['old.timer']
    assert old['auth_service'] is None and old['delete_at'] == NOW
    chans = {x['channel']['name']: x['channel'] for x in out if x['type'] == 'channel'}
    assert chans['town-square']['display_name'] == 'Town Square'
    assert chans['old_stuff-slack']['display_name'] == 'old_stuff'
    assert chans['old_stuff-slack']['deleted_at'] == 1500000200000
    counts = (tmp / 'counts.csv').read_text().splitlines()
    assert counts[1:] == ['old_stuff-slack,1,0,0,0', 'town-square,1,1,3,1']
    report = (tmp / 'report.md').read_text()
    assert '- `nosuchthing`: 1' in report and 'partyparrot_ifl' not in report.split('## Problems')[0].split('most used first')[1]


def test_unknown_author_stops_without_zip(setup):
    tmp, args = setup
    data = lines()
    data[-1]['post']['user'] = 'stranger'
    (tmp / 'data.jsonl').write_text('\n'.join(json.dumps(x) for x in data) + '\n')
    assert ri.main(args) == 1
    assert not (tmp / 'import.zip').exists()
    assert 'author stranger has no user line' in (tmp / 'report.md').read_text()


def test_missing_attachment_stops(setup):
    tmp, args = setup
    (tmp / 'data' / 'bulk-export-attachments' / 'FOK_shot.png').unlink()
    assert ri.main(args) == 1
    assert 'attachment bulk-export-attachments/FOK_shot.png is missing' in (tmp / 'report.md').read_text()


def test_user_not_in_identity_map_stops(setup):
    tmp, args = setup
    data = lines()
    data.insert(4, user_line('someone.else', 'x@example.test'))
    (tmp / 'data.jsonl').write_text('\n'.join(json.dumps(x) for x in data) + '\n')
    assert ri.main(args) == 1
    assert 'user someone.else is not in identity_map.csv' in (tmp / 'report.md').read_text()


def test_expect_existing(setup):
    tmp, args = setup
    assert ri.main(args + ['--expect-existing', 'josh_0']) == 0
    assert ri.main(args + ['--expect-existing', 'ifl-relay']) == 1
    assert 'ifl-relay: no Slack history is linked' in (tmp / 'report.md').read_text()


def test_reaction_not_before_its_post(setup):
    """mmetl can stamp a reaction 1 ms before its post; the import validator rejects that."""
    tmp, args = setup
    data = lines()
    data[-2]['post']['create_at'] = 10
    data[-2]['post']['reactions'][0]['create_at'] = 9
    data[-2]['post']['replies'][0]['reactions'] = [
        {'user': 'miami.brad', 'emoji_name': 'thumbsup', 'create_at': 3}]
    (tmp / 'data.jsonl').write_text('\n'.join(json.dumps(x) for x in data) + '\n')
    assert ri.main(args) == 0
    out, _ = read_import(tmp / 'import.zip')
    post = [x['post'] for x in out if x['type'] == 'post' and x['post']['channel'] == 'town-square'][0]
    assert [r['create_at'] for r in post['reactions']] == [10, 10, 10]
    assert post['replies'][0]['reactions'][0]['create_at'] == 5
    assert '- reactions moved to their post time: 4' in (tmp / 'report.md').read_text()
