import json
import os
import sys
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from common import IDENTITY_FIELDS, write_csv  # noqa: E402

USERS = [
    {'id': 'U1JOSH', 'name': 'josh', 'deleted': False, 'is_bot': False,
     'profile': {'real_name': 'Josh H', 'email': 'josh@example.test'}},
    {'id': 'U2GM', 'name': 'miami.brad', 'deleted': False, 'is_bot': False,
     'profile': {'real_name': 'Brad M', 'email': 'brad@example.test'}},
    {'id': 'U3GONE', 'name': 'old.timer', 'deleted': True, 'is_bot': False,
     'profile': {'real_name': 'Old Timer', 'email': ''}},
    {'id': 'U4BOT', 'name': 'ifl_calendar', 'deleted': False, 'is_bot': True,
     'profile': {'real_name': 'IFL Calendar', 'bot_id': 'B4CAL'}},
]
CHANNELS = [
    {'id': 'C1GEN', 'name': 'general', 'created': 1500000000, 'creator': 'U1JOSH',
     'is_archived': False, 'is_general': False, 'members': ['U1JOSH', 'U2GM', 'U4BOT'],
     'purpose': {'value': 'chat'}, 'topic': {'value': ''}},
    {'id': 'C2OLD', 'name': 'old_stuff', 'created': 1500000000, 'creator': 'U1JOSH',
     'is_archived': True, 'is_general': False, 'members': ['U1JOSH', 'U3GONE'],
     'purpose': {'value': ''}, 'topic': {'value': ''}},
    {'id': 'C3ODD', 'name': 'kylieskoяner', 'created': 1500000000, 'creator': 'U1JOSH',
     'is_archived': False, 'is_general': False, 'members': ['U1JOSH'],
     'purpose': {'value': ''}, 'topic': {'value': ''}},
]
GENERAL_DAY = [
    {'type': 'message', 'user': 'U1JOSH', 'text': 'hi <@U2GM> :partyparrot:', 'ts': '1600000000.000100',
     'reactions': [{'name': 'partyparrot', 'users': ['U2GM', 'U4BOT'], 'count': 2}]},
    {'type': 'message', 'user': 'U2GM', 'text': 'pic', 'ts': '1600000001.000100',
     'files': [{'id': 'FHID', 'mode': 'hidden_by_limit'}]},
    {'type': 'message', 'user': 'U2GM', 'text': '', 'ts': '1600000002.000100',
     'files': [{'id': 'FOK', 'name': 'shot.png', 'size': 4, 'mode': 'hosted',
                'url_private_download': 'https://files.slack.com/x/shot.png'},
               {'id': 'FBAD', 'name': 'gone.png', 'size': 10, 'mode': 'hosted',
                'url_private_download': 'https://files.slack.com/x/gone.png'}]},
    {'type': 'message', 'subtype': 'slackbot_response', 'user': 'USLACKBOT', 'text': 'beep',
     'ts': '1600000003.000100', 'thread_ts': '1600000003.000100'},
    {'type': 'message', 'user': 'U2GM', 'text': 'reply to slackbot', 'ts': '1600000004.000100',
     'thread_ts': '1600000003.000100'},
    {'type': 'message', 'subtype': 'bot_message', 'bot_id': 'B9POLL', 'username': 'Simple Poll',
     'text': 'vote', 'ts': '1600000005.000100', 'bot_profile': {'name': 'Simple Poll'}},
    {'type': 'message', 'user': 'U4BOT', 'text': 'calendar via user id', 'ts': '1600000006.000100'},
    {'type': 'message', 'subtype': 'reply_broadcast', 'user': 'U2GM', 'text': 'also',
     'ts': '1600000007.000100', 'thread_ts': '1600000003.000100'},
]
OLD_DAY = [
    {'type': 'message', 'user': 'U3GONE', 'text': 'ancient', 'ts': '1500000100.000100'},
    {'type': 'message', 'subtype': 'channel_archive', 'user': 'U1JOSH', 'text': 'archived',
     'ts': '1500000200.000100'},
]
ORPHAN_DAY = [
    {'type': 'message', 'subtype': 'document_unfurl', 'user': 'U1JOSH', 'text': 'canvas link',
     'ts': '1700000000.000100'},
]


def _zinfo(name):
    info = zipfile.ZipInfo(name, date_time=(2026, 11, 19, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


@pytest.fixture
def export_zip(tmp_path):
    """A small Slack export shaped like the real one, including a UTF-8 folder
    name written without the UTF-8 flag and a folder with no channel record."""
    path = tmp_path / 'export.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(_zinfo('channels.json'), json.dumps(CHANNELS))
        z.writestr(_zinfo('users.json'), json.dumps(USERS))
        z.writestr(_zinfo('canvases.json'), '[]')
        z.writestr(_zinfo('general/2020-09-13.json'), json.dumps(GENERAL_DAY))
        z.writestr(_zinfo('old_stuff/2017-07-14.json'), json.dumps(OLD_DAY))
        z.writestr(_zinfo('FC:F05GEKFA4N9:Canvas/2023-11-14.json'), json.dumps(ORPHAN_DAY))
        z.writestr(_zinfo('kylieskoяner/2020-09-13.json'),
                   json.dumps([{'type': 'message', 'user': 'U1JOSH', 'text': 'x', 'ts': '1600000000.5'}]))
        z.writestr(_zinfo('__uploads/FOK/shot.png'), b'\x89PNG')
        z.writestr(_zinfo('__uploads/FBAD/gone.png'), b'<!DOCTYPE html><html>no</html>')
    # Rewrite the non-ASCII name the way Slack does: UTF-8 bytes, flag clear.
    data = bytearray(path.read_bytes())
    utf8 = 'kylieskoяner/2020-09-13.json'.encode('utf-8')
    for i in range(len(data) - 4):
        if data[i:i + 4] in (b'PK\x03\x04', b'PK\x01\x02'):
            flag_at = i + (6 if data[i + 2] == 3 else 8)
            name_len_at = i + (26 if data[i + 2] == 3 else 28)
            n = int.from_bytes(data[name_len_at:name_len_at + 2], 'little')
            name_at = i + (30 if data[i + 2] == 3 else 46)
            if bytes(data[name_at:name_at + n]) == utf8:
                flags = int.from_bytes(data[flag_at:flag_at + 2], 'little') & ~0x800
                data[flag_at:flag_at + 2] = flags.to_bytes(2, 'little')
    path.write_bytes(bytes(data))
    return path


def identity_row(**kw):
    row = {k: '' for k in IDENTITY_FIELDS}
    row.update(kw)
    return row


@pytest.fixture
def identity_csv(tmp_path):
    rows = [
        identity_row(slack_id='U1JOSH', slack_username='josh', is_bot='false', match='email',
                     site_id='1', site_username='josh', site_email='josh@example.test',
                     site_member='yes', chat_username='josh_0', chat_email='josh@example.test',
                     chat_active='yes', confirmed='yes'),
        identity_row(slack_id='U2GM', slack_username='miami.brad', is_bot='false', match='email',
                     site_id='7', site_username='brad', site_email='Brad@Example.test',
                     site_member='yes', confirmed='yes'),
        identity_row(slack_id='U3GONE', slack_username='old.timer', is_bot='false', slack_deleted='true'),
        identity_row(slack_id='U4BOT', slack_username='ifl_calendar', is_bot='true'),
    ]
    path = tmp_path / 'identity_map.csv'
    write_csv(path, rows, IDENTITY_FIELDS)
    return path


@pytest.fixture
def chat_snapshot(tmp_path):
    users = tmp_path / 'chat_users.json'
    users.write_text(json.dumps([
        {'username': 'josh_0', 'email': 'josh@example.test', 'auth_service': 'gitlab', 'auth_data': '1'},
        {'username': 'ifl-relay', 'email': 'ifl-relay@iflgm.invalid'},
        {'username': 'calls', 'email': 'calls@localhost', 'is_bot': True},
    ]))
    channels = tmp_path / 'chat_channels.txt'
    channels.write_text('off-topic\ntown-square\nold_stuff (archived)\nThere are 3 channels on local instance\n')
    return users, channels
