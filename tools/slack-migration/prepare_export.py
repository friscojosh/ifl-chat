"""Prepare an enriched Slack export for mmetl (league chat spec §5, Plan 5 Task 6).

Writes a NEW zip; the input is never changed. Makes no network requests and
never reads a token: downloaded files come only from `__uploads/` in the
input and in --uploads archives. Doing the renames here, before
`mmetl transform slack`, lets mmetl's own mention conversion carry them into
message text (`<@U123>` becomes `@<final username>`, `<#C123>` becomes
`~<final channel>`).

  * Channels: Slack #general becomes town-square; names chat would reject
    are made valid; names already used in chat get `-slack`; folders with no
    channels.json record become archived channels; archived channels get
    their archive time. Writes channel_map.csv.
  * People: usernames and emails come from identity_map.csv
    (common.resolve_identities); IDs referenced but missing from users.json
    are added as deleted users.
  * Bots: every bot_id that posts gets a named bot account; Slackbot
    responses and deleted-message tombstones become posts by `slackbot`, so
    their threads survive.
  * Files: a file that cannot be imported (hidden by the free-plan limit,
    deleted, external, or not downloaded) is removed from the message and a
    short note is added to the text instead.
  * Emoji: custom emoji names are rewritten per emoji_map.csv in text and
    reactions.
  * Archive state: with --archive-state (the channel_counts.csv of an export
    taken before the cutover freeze), each listed channel keeps the archived
    flag it had then, so channels archived only to freeze Slack import open.
"""
import argparse
import collections
import hashlib
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run with python -I
from common import (DISPLAY_NAME_MAX, SLACK_GENERAL, TOWN_SQUARE,  # noqa: E402
                    MigrationError, load_chat_channels, load_chat_users,
                    member_name, read_csv, resolve_identities, slug,
                    truncate, valid_channel_name, valid_username, write_csv)

SLACKBOT_USER = 'USLACKBOT'
SLACKBOT_BOT = 'BSLACKBOT'
SLACKBOT_NAME = 'slackbot'
CHANNEL_MAP_FIELDS = ['slack_id', 'slack_name', 'folder', 'mm_name', 'mm_display_name',
                      'archived', 'delete_at', 'messages', 'reason']
EMOJI_TOKEN = re.compile(r':([A-Za-z0-9_+\'\-]+):')
HTML_PREFIXES = (b'<!doctype', b'<html')

NOTE_HIDDEN = "_[File not available: hidden by Slack's free-plan limit]_"
NOTE_DELETED = '_[File deleted in Slack]_'
TOMBSTONE_TEXT = '_[This message was deleted in Slack]_'


def note_missing(name):
    return f'_[File not available: {name}]_'


# ---------------------------------------------------------------- channels

def plan_channels(channels, folders, chat_channels, folder_messages, bot_users=(),
                  archive_state=None):
    """Return (channel records to write, channel_map rows, folder -> mm name)."""
    by_name = {c['name']: c for c in channels}
    records, rows, used, folder_to_mm = [], [], set(), {}

    def unique(name):
        base, n = name, 2
        while name in used:
            suffix = f'-{n}'
            name = base[:64 - len(suffix)] + suffix
            n += 1
        used.add(name)
        return name

    def mm_name_for(slack_name, slack_id):
        if slack_name == SLACK_GENERAL:
            return TOWN_SQUARE, 'Slack #general is the team town-square'
        name, reason = slack_name.lower().strip('_-'), ''
        if not (len(name) > 1 and valid_channel_name(name)):
            name = slug(slack_name)[:64].strip('_-')
            reason = 'invalid characters removed'
            if not (len(name) > 1 and valid_channel_name(name)):
                name, reason = f'slack-{slack_id.lower()}', 'no usable name; Slack id used'
        if name in chat_channels or name == TOWN_SQUARE:
            name, reason = truncate(name, 58) + '-slack', 'name already used in chat'
        return name, reason

    orphans = sorted(f for f in folders if f not in by_name)
    for c in sorted(channels, key=lambda c: c['id']):
        c = dict(c)
        # Bots are not channel members in chat; leaving their user ids here
        # makes mmetl invent a deleted person for each one.
        c['members'] = [u for u in c.get('members') or [] if u not in bot_users]
        if archive_state and c['name'] in archive_state:
            c['is_archived'] = archive_state[c['name']]
        records.append(c)
    for folder in orphans:
        msgs = folder_messages.get(folder, [])
        cid = 'CORPHAN' + hashlib.sha1(folder.encode()).hexdigest()[:10].upper()
        records.append({
            'id': cid, 'name': folder, 'created': int(min((float(m['ts']) for m in msgs), default=0)),
            'creator': '', 'is_archived': True, 'is_general': False,
            'members': sorted({m['user'] for m in msgs
                               if m.get('user') and m['user'] not in bot_users}),
            'purpose': {'value': f'Slack export folder "{folder}" had no channel record.'},
            'topic': {'value': ''}, '_orphan': True,
        })
    for rec in records:
        folder = rec['name']
        mm, reason = mm_name_for(rec['name'], rec['id'])
        if rec.get('_orphan'):
            reason = 'folder not in channels.json; imported as archived'
        mm = unique(mm)
        msgs = folder_messages.get(folder, [])
        delete_at = ''
        if rec.get('is_archived'):
            archive_ts = [float(m['ts']) for m in msgs if m.get('subtype') == 'channel_archive']
            last_ts = max(archive_ts or [float(m['ts']) for m in msgs] or [float(rec.get('created') or 0)])
            delete_at = int(last_ts * 1000) or 1
            rec['updated'] = delete_at  # mmetl uses `updated` (ms) as the archive time
        display = 'Town Square' if mm == TOWN_SQUARE else truncate(rec['name'].strip('_-') or mm, DISPLAY_NAME_MAX)
        rows.append({'slack_id': rec['id'], 'slack_name': rec['name'], 'folder': folder,
                     'mm_name': mm, 'mm_display_name': display,
                     'archived': str(bool(rec.get('is_archived'))).lower(),
                     'delete_at': delete_at, 'messages': len(msgs), 'reason': reason})
        folder_to_mm[folder] = mm
        rec['name'] = mm
        rec.pop('_orphan', None)
    return records, rows, folder_to_mm


# ---------------------------------------------------------------- people and bots

def plan_users(users, identities, missing_rows, bot_names_seen, taken_names):
    """users.json with final usernames and emails, plus synthetic users/bots."""
    out = []
    used = set(taken_names) | {i['username'] for i in identities.values()}
    for u in users:
        u = json.loads(json.dumps(u))
        if u.get('is_bot'):
            out.append(u)
            continue
        ident = identities.get(u['id'])
        if ident is None:
            raise MigrationError(f'{u["id"]} ({u["name"]}) is not in identity_map.csv')
        u['name'] = ident['username']
        u.setdefault('profile', {})['email'] = ident['email']
        out.append(u)
    for row in missing_rows:
        ident = identities.get(row['slack_id'])
        if ident is None:
            raise MigrationError(f'{row["slack_id"]} is not in identity_map.csv')
        out.append({'id': row['slack_id'], 'name': ident['username'], 'deleted': True,
                    'is_bot': False, 'real_name': 'Deleted User',
                    'profile': {'real_name': 'Deleted User', 'email': ident['email']}})
    # Bots that exist in users.json keep their names when they are free.
    # A bot_id that is really a person's user id stays that person's post.
    bot_ids = ({(u.get('profile') or {}).get('bot_id') for u in out if u.get('is_bot')}
               | {u['id'] for u in out})
    for u in out:
        if u.get('is_bot'):
            name = u['name'].lower()
            if name in used or not valid_username(name):
                name = unique_bot_name(slug(name, r'a-z0-9._-') or 'bot', used)
            used.add(name)
            u['name'] = name
    # Every other bot that posted gets an account named after how it posted.
    for bot_id, label in sorted(bot_names_seen.items()):
        if bot_id in bot_ids:
            continue
        if bot_id == SLACKBOT_BOT:
            name = SLACKBOT_NAME if SLACKBOT_NAME not in used else unique_bot_name(SLACKBOT_NAME, used)
            uid, real = SLACKBOT_USER, 'Slackbot'
        else:
            name = unique_bot_name(slug(re.sub(r'\s+', '-', label), r'a-z0-9._-') or 'bot', used)
            uid, real = bot_id, label or bot_id
        used.add(name)
        out.append({'id': uid, 'name': name, 'deleted': False, 'is_bot': True,
                    'real_name': real, 'profile': {'bot_id': bot_id, 'real_name': real}})
    return out


def unique_bot_name(base, used):
    base = truncate(base, 60) or 'bot'
    if base not in used and valid_username(base):
        return base
    if valid_username(base + '-bot') and base + '-bot' not in used:
        return base + '-bot'
    n = 2
    while f'{base}-{n}' in used:
        n += 1
    return f'{base}-{n}'


# ---------------------------------------------------------------- messages

def rename_emoji(text, emoji):
    if not text or not emoji:
        return text
    return EMOJI_TOKEN.sub(lambda m: f':{emoji.get(m.group(1), m.group(1))}:', text)


def fix_message(m, available, emoji, stats, bot_users=None):
    """Rewrite one Slack message in place. `available` maps file id -> True
    when its bytes will be in the prepared zip; `bot_users` maps a bot's
    user id to its bot id."""
    bot_users = bot_users or {}
    if m.get('user') in bot_users and not m.get('bot_id'):
        m['bot_id'] = bot_users[m['user']]  # mmetl then files it under the bot
        stats['posts by a bot user id attributed to the bot'] += 1
    for r in m.get('reactions') or []:
        bots = [u for u in r.get('users') or [] if u in bot_users]
        if bots:
            r['users'] = [u for u in r['users'] if u not in bot_users]
            r['count'] = len(r['users'])
            stats['bot reactions dropped'] += len(bots)
    if m.get('reactions'):
        m['reactions'] = [r for r in m['reactions'] if r.get('users')]
    sub = m.get('subtype')
    if sub == 'slackbot_response' or (sub == 'tombstone'):
        if sub == 'tombstone':
            m['text'] = TOMBSTONE_TEXT
        m['subtype'] = 'bot_message'
        m['bot_id'] = SLACKBOT_BOT
        m['username'] = 'Slackbot'
        stats[f'converted {sub} to a slackbot post'] += 1
    elif sub == 'reply_broadcast':
        m['subtype'] = 'thread_broadcast'
        stats['converted reply_broadcast to thread_broadcast'] += 1
    elif sub == 'document_unfurl':
        m.pop('subtype')
        stats['converted document_unfurl to a plain message'] += 1
    elif sub in ('pinned_item', 'channel_archive', 'channel_unarchive', 'bot_add', 'bot_remove',
                 'bot_disable', 'bot_enable', 'reminder_add', 'welcome_party', 'huddle_thread'):
        stats[f'left for mmetl to drop or convert: {sub}'] += 1

    notes, keep = [], []
    files = list(m.get('files') or [])
    legacy = m.pop('file', None)
    if legacy:
        files.append(legacy)
    for f in files:
        if f.get('mode') == 'hidden_by_limit':
            notes.append(NOTE_HIDDEN); stats['files hidden by the free-plan limit'] += 1
        elif f.get('mode') == 'tombstone':
            notes.append(NOTE_DELETED); stats['files deleted in Slack'] += 1
        elif f.get('is_external') and (f.get('url_private') or f.get('permalink')):
            url = f.get('url_private') or f.get('permalink')
            notes.append(f'[{f.get("title") or f.get("name") or url}]({url})')
            stats['external files kept as links'] += 1
        elif f.get('id') and f.get('name') and available.get(f['id']):
            keep.append(f); stats['files imported'] += 1
        else:
            notes.append(note_missing(f.get('name') or f.get('title') or f.get('id', 'unknown')))
            stats['files not downloaded'] += 1
    if files:
        if keep:
            m['files'] = keep
        else:
            m.pop('files', None)
            if m.get('subtype') == 'file_share':
                m.pop('subtype')
    if notes:
        m['text'] = ((m.get('text') or '') + ('\n' if m.get('text') else '') + '\n'.join(notes))
    m['text'] = rename_emoji(m.get('text'), emoji)
    for r in m.get('reactions') or []:
        if r.get('name') in emoji:
            r['name'] = emoji[r['name']]
            stats['reactions renamed'] += 1
    return m


def good_upload(data, size):
    head = data[:64].lstrip().lower()
    if any(head.startswith(p) for p in HTML_PREFIXES):
        return False
    return size in (None, 0) or len(data) == size


# ---------------------------------------------------------------- driver

def load_emoji_map(path):
    if not path:
        return {}
    out = {}
    for row in read_csv(path):
        if row['mm_name'] and row['status'] != 'failed' and row['mm_name'] != row['slack_name']:
            out[row['slack_name']] = row['mm_name']
    return out


def prepare(input_zip, upload_zips, identity_rows, chat_users, chat_channels, emoji,
            output_zip, channel_map_path, archive_state=None):
    stats = collections.Counter()
    with zipfile.ZipFile(input_zip) as zf:
        infos = {member_name(i): i for i in zf.infolist() if not i.is_dir()}
        channels = json.loads(zf.read(infos['channels.json']))
        users = json.loads(zf.read(infos['users.json']))
        folder_files = collections.defaultdict(list)
        for name in infos:
            parts = name.split('/')
            if len(parts) == 2 and parts[1].endswith('.json') and not parts[0].startswith('__'):
                folder_files[parts[0]].append(name)
        folder_messages = {f: [m for n in sorted(names) for m in json.loads(zf.read(infos[n]))]
                           for f, names in folder_files.items()}

        # Uploads: the input's own __uploads, then each extra archive (earlier downloads).
        file_sizes = {}
        bot_labels = {}
        for msgs in folder_messages.values():
            for m in msgs:
                for f in (m.get('files') or []) + ([m['file']] if m.get('file') else []):
                    if f.get('id'):
                        file_sizes[f['id']] = f.get('size')
                if (m.get('subtype') in ('slackbot_response', 'tombstone')
                        or m.get('user') == SLACKBOT_USER):
                    bot_labels[SLACKBOT_BOT] = 'Slackbot'
                elif m.get('bot_id') or m.get('subtype') == 'bot_message':
                    bid = m.get('bot_id') or m.get('user') or m.get('username')
                    if bid:
                        label = ((m.get('bot_profile') or {}).get('name') or m.get('username') or '')
                        bot_labels.setdefault(bid, label)
                        if not bot_labels[bid] and label:
                            bot_labels[bid] = label
        uploads = {}
        sources = [zf] + [zipfile.ZipFile(p) for p in upload_zips]
        try:
            for src in sources:
                for info in src.infolist():
                    parts = member_name(info).split('/')
                    if len(parts) != 3 or parts[0] != '__uploads' or parts[1] in uploads:
                        continue
                    data = src.read(info)
                    if good_upload(data, file_sizes.get(parts[1])):
                        uploads[parts[1]] = (parts[2], data)
                    else:
                        stats['downloads rejected (wrong size or an HTML error page)'] += 1
        finally:
            for src in sources[1:]:
                src.close()
        available = {fid: True for fid in uploads}

        ids_in_users = {u['id'] for u in users}
        missing_rows = [r for r in identity_rows
                        if r['slack_id'] not in ids_in_users and r['is_bot'] != 'true']
        identities = resolve_identities(identity_rows, chat_users)
        out_users = plan_users(users, identities, missing_rows, bot_labels,
                               {u['username'].lower() for u in chat_users})
        bot_users = {u['id']: (u.get('profile') or {}).get('bot_id') or u['id']
                     for u in users if u.get('is_bot')}
        bot_users[SLACKBOT_USER] = SLACKBOT_BOT
        records, map_rows, folder_to_mm = plan_channels(
            channels, set(folder_messages), chat_channels, folder_messages, bot_users,
            archive_state)

        tmp = output_zip + '.partial'
        with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as out:
            out.writestr('channels.json', json.dumps(records, ensure_ascii=False, indent=1))
            out.writestr('users.json', json.dumps(out_users, ensure_ascii=False, indent=1))
            for name, info in sorted(infos.items()):
                parts = name.split('/')
                if name in ('channels.json', 'users.json') or parts[0] == '__uploads':
                    continue
                if len(parts) == 2 and parts[0] in folder_to_mm and parts[1].endswith('.json'):
                    msgs = json.loads(zf.read(info))
                    fixed = [fix_message(m, available, emoji, stats, bot_users) for m in msgs]
                    out.writestr(f'{folder_to_mm[parts[0]]}/{parts[1]}',
                                 json.dumps(fixed, ensure_ascii=False, indent=1))
                elif len(parts) == 1:
                    out.writestr(name, zf.read(info))
            for fid, (fname, data) in sorted(uploads.items()):
                out.writestr(f'__uploads/{fid}/{fname}', data)
        os.replace(tmp, output_zip)
    write_csv(channel_map_path, map_rows, CHANNEL_MAP_FIELDS)
    stats['channels'] = len(map_rows)
    stats['archived channels'] = sum(1 for r in map_rows if r['archived'] == 'true')
    stats['channels renamed'] = sum(1 for r in map_rows if r['mm_name'] != r['slack_name'])
    stats['bot accounts'] = sum(1 for u in out_users if u.get('is_bot'))
    stats['people'] = sum(1 for u in out_users if not u.get('is_bot'))
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True, help='enriched Slack export zip (not modified)')
    ap.add_argument('--uploads', action='append', default=[], help='extra zip with __uploads/ (repeatable)')
    ap.add_argument('--identity', required=True, help='identity_map.csv')
    ap.add_argument('--chat-users', required=True, help='mmctl user list --all --json output')
    ap.add_argument('--chat-channels', required=True, help='mmctl channel list ifl output')
    ap.add_argument('--emoji-map', help='emoji_map.csv from import_emoji.py')
    ap.add_argument('--output', required=True)
    ap.add_argument('--channel-map', required=True, help='channel_map.csv to write')
    ap.add_argument('--report', required=True)
    ap.add_argument('--archive-state', help='channel_counts.csv from the pre-freeze export')
    a = ap.parse_args(argv)
    if os.path.abspath(a.output) == os.path.abspath(a.input):
        print('error: --output must differ from --input', file=sys.stderr)
        return 2
    try:
        stats = prepare(a.input, a.uploads, read_csv(a.identity), load_chat_users(a.chat_users),
                        load_chat_channels(a.chat_channels), load_emoji_map(a.emoji_map),
                        a.output, a.channel_map,
                        {r['folder']: r['archived'] == 'true' for r in read_csv(a.archive_state)}
                        if a.archive_state else None)
    except MigrationError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    lines = ['# prepare_export report', ''] + [f'- {k}: {v}' for k, v in sorted(stats.items())]
    with open(a.report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines))
    return 0


if __name__ == '__main__':
    sys.exit(main())
