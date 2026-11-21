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
  * Re-import (--reimport-from FIRST_RUN_DIR --prior-emoji-map FIRST_MAP): a
    second export on top of the first import. Channels the first run imported
    keep the chat names its channel_map.csv gave them (never `-slack`; each
    must still be in chat); people and bots keep the usernames its prepared
    users.json gave them and are accepted as existing chat accounts; the
    first run's emoji renames win over the new map. So unchanged messages
    come out of mmetl with exactly the text chat already holds. New channels,
    people and bots get the usual handling.
"""
import argparse
import collections
import contextlib
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run with python -I
from common import (DISPLAY_NAME_MAX, SLACK_GENERAL, TOWN_SQUARE,  # noqa: E402
                    MigrationError, load_chat_channels, load_chat_users, load_prior_users,
                    member_name, open_private, prior_paths, read_csv, resolve_identities, slug,
                    truncate, valid_channel_name, valid_username, write_csv)

SLACKBOT_USER = 'USLACKBOT'
SLACKBOT_BOT = 'BSLACKBOT'
SLACKBOT_NAME = 'slackbot'
CHANNEL_MAP_FIELDS = ['slack_id', 'slack_name', 'folder', 'mm_name', 'mm_display_name',
                      'archived', 'delete_at', 'messages', 'reason']
EMOJI_TOKEN = re.compile(r':([A-Za-z0-9_+\'\-]+):')
HTML_PREFIXES = (b'<!doctype', b'<html')
HEAD_BYTES = 64
REJECT_SIZE = 'downloads rejected (wrong size or an HTML error page)'
REJECT_NAME = 'downloads rejected (file name differs from the message)'

NOTE_HIDDEN = "_[File not available: hidden by Slack's free-plan limit]_"
NOTE_DELETED = '_[File deleted in Slack]_'
TOMBSTONE_TEXT = '_[This message was deleted in Slack]_'


def note_missing(name):
    return f'_[File not available: {name}]_'


# ---------------------------------------------------------------- channels

def plan_channels(channels, folders, chat_channels, folder_messages, bot_users=(),
                  archive_state=None, prior_channels=None):
    """Return (channel records to write, channel_map rows, folder -> mm name).

    prior_channels (re-import): the first run's channel_map rows by slack_id;
    those channels keep their chat name and display name."""
    by_name = {c['name']: c for c in channels}
    records, rows, used, folder_to_mm = [], [], set(), {}
    prior_channels = prior_channels or {}
    used.update(r['mm_name'] for r in prior_channels.values())

    def unique(name):
        # Slack channels never take a name a chat channel (or an earlier
        # Slack channel) already has, whatever suffix got them there.
        base, n = name, 2
        while name in used or name in chat_channels:
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
    missing = []
    for rec in records:
        folder = rec['name']
        prior = prior_channels.get(rec['id'])
        if prior is not None:
            mm, reason = prior['mm_name'], 'imported by the first run'
            if mm not in chat_channels and mm != TOWN_SQUARE:
                missing.append(mm)
        else:
            mm, reason = mm_name_for(rec['name'], rec['id'])
        if rec.get('_orphan') and prior is None:
            reason = 'folder not in channels.json; imported as archived'
        if prior is not None or (mm == TOWN_SQUARE and rec['name'] == SLACK_GENERAL):
            used.add(mm)
        else:
            wanted, mm = mm, unique(mm)
            if mm != wanted:
                reason = (reason + '; ' if reason else '') + 'name taken; number added'
        msgs = folder_messages.get(folder, [])
        delete_at = ''
        if rec.get('is_archived'):
            archive_ts = [float(m['ts']) for m in msgs if m.get('subtype') == 'channel_archive']
            last_ts = max(archive_ts or [float(m['ts']) for m in msgs] or [float(rec.get('created') or 0)])
            delete_at = int(last_ts * 1000) or 1
            rec['updated'] = delete_at  # mmetl uses `updated` (ms) as the archive time
        display = 'Town Square' if mm == TOWN_SQUARE else truncate(rec['name'].strip('_-') or mm, DISPLAY_NAME_MAX)
        if prior is not None:
            display = prior['mm_display_name']
        rows.append({'slack_id': rec['id'], 'slack_name': rec['name'], 'folder': folder,
                     'mm_name': mm, 'mm_display_name': display,
                     'archived': str(bool(rec.get('is_archived'))).lower(),
                     'delete_at': delete_at, 'messages': len(msgs), 'reason': reason})
        folder_to_mm[folder] = mm
        rec['name'] = mm
        rec.pop('_orphan', None)
    if missing:
        raise MigrationError('channels the first import created are not in the chat snapshot '
                             f'(renamed or deleted in chat?): {", ".join(sorted(missing))}')
    return records, rows, folder_to_mm


# ---------------------------------------------------------------- people and bots

def plan_users(users, identities, missing_rows, bot_names_seen, taken_names, prior_bots=None):
    """users.json with final usernames and emails, plus synthetic users/bots.

    prior_bots (re-import): {user or bot id: username} from the first run; those
    bots keep that name (their chat account already exists)."""
    out = []
    prior_bots = prior_bots or {}
    used = set(taken_names) | {i['username'] for i in identities.values()} | set(prior_bots.values())
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
        if u.get('is_bot') and u['id'] in prior_bots:
            u['name'] = prior_bots[u['id']]
        elif u.get('is_bot'):
            name = u['name'].lower()
            if name in used or not valid_username(name):
                name = unique_bot_name(slug(name, r'a-z0-9._-') or 'bot', used)
            used.add(name)
            u['name'] = name
    # Every other bot that posted gets an account named after how it posted.
    for bot_id, label in sorted(bot_names_seen.items()):
        if bot_id in bot_ids:
            continue
        if bot_id == SLACKBOT_BOT and SLACKBOT_USER in prior_bots:
            name, uid, real = prior_bots[SLACKBOT_USER], SLACKBOT_USER, 'Slackbot'
        elif bot_id in prior_bots:
            name, uid, real = prior_bots[bot_id], bot_id, label or bot_id
        elif bot_id == SLACKBOT_BOT:
            name = SLACKBOT_NAME if SLACKBOT_NAME not in used else unique_bot_name(SLACKBOT_NAME, used)
            uid, real = SLACKBOT_USER, 'Slackbot'
        else:
            # No label: name the account from the bot id (stable and unique).
            base = slug(re.sub(r'\s+', '-', label), r'a-z0-9._-') or slug('integration-' + bot_id, r'a-z0-9._-')
            name = unique_bot_name(base, used)
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


def fix_message(m, available, emoji, stats, bot_users=None, username_bots=None):
    """Rewrite one Slack message in place. `available` maps file id -> True
    when its bytes will be in the prepared zip; `bot_users` maps a bot's
    user id to its bot id; `username_bots` maps a bot's username to its bot id."""
    bot_users = bot_users or {}
    if (m.get('subtype') == 'bot_message' and not m.get('bot_id') and not m.get('user')
            and m.get('username') in (username_bots or {})):
        m['bot_id'] = username_bots[m['username']]
        stats['bot posts with only a username given their bot id'] += 1
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
            title = (f.get('title') or f.get('name') or url).replace('\\', '\\\\')
            title = title.replace('[', '\\[').replace(']', '\\]')
            url = url.replace(' ', '%20').replace('(', '%28').replace(')', '%29')
            notes.append(f'[{title}]({url})')
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
        if r.get('name') in emoji and emoji[r['name']] != r['name']:
            r['name'] = emoji[r['name']]
            stats['reactions renamed'] += 1
    return m


def good_upload(head, declared_size, expected_size):
    """Judge an upload from its first bytes and its declared size, without
    reading it all: not an HTML error page, and the size the message says."""
    if any(head.lstrip().lower().startswith(p) for p in HTML_PREFIXES):
        return False
    return expected_size in (None, 0) or declared_size == expected_size


def synthetic_bot_id(username):
    return 'BUSER' + hashlib.sha1(username.encode('utf-8')).hexdigest()[:10].upper()


def stream_zip_member(src, info, out, name):
    """Copy one member from `src` into `out` in chunks."""
    zi = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
    zi.compress_type = zipfile.ZIP_DEFLATED
    with src.open(info) as fin, out.open(zi, 'w', force_zip64=True) as fout:
        shutil.copyfileobj(fin, fout, 1 << 20)


# ---------------------------------------------------------------- driver

def load_emoji_map(path):
    if not path:
        return {}
    out = {}
    for row in read_csv(path):
        if row['mm_name'] and row['status'] != 'failed' and row['mm_name'] != row['slack_name']:
            out[row['slack_name']] = row['mm_name']
    return out


def load_prior_emoji_map(path):
    """Re-import: every Slack name the first run's map lists, pinned to what the
    first run did with it (its chat name, or unchanged when it was not renamed
    or failed), so the new map cannot change an old message's text."""
    out = {}
    for row in read_csv(path):
        usable = row['mm_name'] and row['status'] != 'failed'
        out[row['slack_name']] = row['mm_name'] if usable else row['slack_name']
    return out


def prepare(input_zip, upload_zips, identity_rows, chat_users, chat_channels, emoji,
            output_zip, channel_map_path, archive_state=None, prior=None):
    """prior (re-import): {'channels': {slack_id: channel_map row}, 'people': ...,
    'bots': ...} from the first run (common.load_prior_users)."""
    stats = collections.Counter()
    tmp = output_zip + '.partial'
    try:
        with contextlib.ExitStack() as stack:
            zf = stack.enter_context(zipfile.ZipFile(input_zip))
            sources = [zf] + [stack.enter_context(zipfile.ZipFile(p)) for p in upload_zips]
            out_users, map_rows = _write_prepared(zf, sources, identity_rows, chat_users, chat_channels,
                                                  emoji, tmp, archive_state, stats, prior)
        os.replace(tmp, output_zip)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    write_csv(channel_map_path, map_rows, CHANNEL_MAP_FIELDS, private=True)
    stats['channels'] = len(map_rows)
    stats['archived channels'] = sum(1 for r in map_rows if r['archived'] == 'true')
    stats['channels renamed'] = sum(1 for r in map_rows if r['mm_name'] != r['slack_name'])
    stats['bot accounts'] = sum(1 for u in out_users if u.get('is_bot'))
    stats['people'] = sum(1 for u in out_users if not u.get('is_bot'))
    if prior:
        stats['re-import: channels from the first import'] = sum(
            1 for r in map_rows if r['reason'] == 'imported by the first run')
        stats['re-import: new channels'] = len(map_rows) - stats['re-import: channels from the first import']
        stats['re-import: people from the first import'] = sum(
            1 for u in out_users if not u.get('is_bot') and u['id'] in prior['people'])
        stats['re-import: new people'] = stats['people'] - stats['re-import: people from the first import']
        stats['re-import: bots from the first import'] = sum(
            1 for u in out_users if u.get('is_bot') and u['id'] in prior['bots'])
        stats['re-import: new bots'] = stats['bot accounts'] - stats['re-import: bots from the first import']
    return stats


def scan_messages(folder_messages, users):
    """File ids -> declared size and name, bot labels, and username -> bot id."""
    file_sizes, file_names, bot_labels, username_bots = {}, {}, {}, {}
    for u in users:
        bid = (u.get('profile') or {}).get('bot_id')
        if u.get('is_bot') and bid:
            for key in (u.get('real_name'), u.get('name')):
                if key:
                    username_bots.setdefault(key, bid)
    for msgs in folder_messages.values():
        for m in msgs:
            if m.get('bot_id') and m.get('username'):
                username_bots.setdefault(m['username'], m['bot_id'])
    for msgs in folder_messages.values():
        for m in msgs:
            for f in (m.get('files') or []) + ([m['file']] if m.get('file') else []):
                if f.get('id'):
                    file_sizes[f['id']] = f.get('size')
                    file_names.setdefault(f['id'], f.get('name'))
            if (m.get('subtype') in ('slackbot_response', 'tombstone')
                    or m.get('user') == SLACKBOT_USER):
                bot_labels[SLACKBOT_BOT] = 'Slackbot'
            elif m.get('bot_id') or m.get('subtype') == 'bot_message':
                if not m.get('bot_id') and not m.get('user') and m.get('username'):
                    username_bots.setdefault(m['username'], synthetic_bot_id(m['username']))
                bid = m.get('bot_id') or m.get('user') or username_bots.get(m.get('username'))
                if bid:
                    label = ((m.get('bot_profile') or {}).get('name') or m.get('username') or '')
                    bot_labels.setdefault(bid, label)
                    if not bot_labels[bid] and label:
                        bot_labels[bid] = label
    return file_sizes, file_names, bot_labels, username_bots


def choose_uploads(sources, file_sizes, file_names, stats):
    """File id -> (published name, source, ZipInfo) for each upload that looks
    right. Only ZipInfo and the first bytes are read; the copy streams later."""
    uploads = {}
    for src in sources:
        for info in src.infolist():
            parts = member_name(info).split('/')
            if len(parts) != 3 or parts[0] != '__uploads' or parts[1] in uploads:
                continue
            fid, fname = parts[1], parts[2]
            if fid not in file_names:
                stats['uploads no message refers to'] += 1
                continue
            with src.open(info) as f:
                head = f.read(HEAD_BYTES)
            if not good_upload(head, info.file_size, file_sizes.get(fid)):
                stats[REJECT_SIZE] += 1
            elif file_names[fid] != fname:
                stats[REJECT_NAME] += 1
            else:
                uploads[fid] = (fname, src, info)
    return uploads


def _write_prepared(zf, sources, identity_rows, chat_users, chat_channels, emoji, tmp,
                    archive_state, stats, prior=None):
    prior = prior or {}
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
    file_sizes, file_names, bot_labels, username_bots = scan_messages(folder_messages, users)
    uploads = choose_uploads(sources, file_sizes, file_names, stats)
    available = {fid: True for fid in uploads}

    ids_in_users = {u['id'] for u in users}
    missing_rows = [r for r in identity_rows
                    if r['slack_id'] not in ids_in_users and r['is_bot'] != 'true']
    identities = resolve_identities(identity_rows, chat_users, prior.get('people'))
    out_users = plan_users(users, identities, missing_rows, bot_labels,
                           {u['username'].lower() for u in chat_users}, prior.get('bots'))
    bot_users = {u['id']: (u.get('profile') or {}).get('bot_id') or u['id']
                 for u in users if u.get('is_bot')}
    bot_users[SLACKBOT_USER] = SLACKBOT_BOT
    records, map_rows, folder_to_mm = plan_channels(
        channels, set(folder_messages), chat_channels, folder_messages, bot_users,
        archive_state, prior.get('channels'))

    with open_private(tmp, 'wb') as raw, zipfile.ZipFile(raw, 'w', zipfile.ZIP_DEFLATED) as out:
        out.writestr('channels.json', json.dumps(records, ensure_ascii=False, indent=1))
        out.writestr('users.json', json.dumps(out_users, ensure_ascii=False, indent=1))
        for name, info in sorted(infos.items()):
            parts = name.split('/')
            if name in ('channels.json', 'users.json') or parts[0] == '__uploads':
                continue
            if len(parts) == 2 and parts[0] in folder_to_mm and parts[1].endswith('.json'):
                msgs = json.loads(zf.read(info))
                fixed = [fix_message(m, available, emoji, stats, bot_users, username_bots)
                         for m in msgs]
                out.writestr(f'{folder_to_mm[parts[0]]}/{parts[1]}',
                             json.dumps(fixed, ensure_ascii=False, indent=1))
            elif len(parts) == 1:
                out.writestr(name, zf.read(info))
        for fid, (fname, src, info) in sorted(uploads.items()):
            stream_zip_member(src, info, out, f'__uploads/{fid}/{fname}')
    return out_users, map_rows


def same_file(a, b):
    if os.path.realpath(a) == os.path.realpath(b):
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def clash(paths, others):
    return any(same_file(p, o) for p in paths for o in others)


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
    ap.add_argument('--reimport-from', metavar='FIRST_RUN_DIR',
                    help="re-import: the first run's work directory (channel_map.csv, prepared.zip, import.zip)")
    ap.add_argument('--prior-emoji-map', help="re-import: the emoji_map.csv the first run used")
    a = ap.parse_args(argv)
    if bool(a.reimport_from) != bool(a.prior_emoji_map):
        print('error: --reimport-from and --prior-emoji-map go together', file=sys.stderr)
        return 2
    inputs = [a.input, *a.uploads, a.identity, a.chat_users, a.chat_channels]
    inputs += [p for p in (a.emoji_map, a.archive_state, a.prior_emoji_map) if p]
    outputs = [a.output, a.channel_map, a.report]
    if clash(outputs, inputs) or clash(outputs[:1], outputs[1:]) or clash(outputs[1:2], outputs[2:]):
        print('error: --output, --channel-map and --report must be three different files, '
              'none of them an input', file=sys.stderr)
        return 2
    try:
        prior, emoji = None, load_emoji_map(a.emoji_map)
        if a.reimport_from:
            paths = prior_paths(a.reimport_from)
            if clash(outputs, list(paths.values())):
                print('error: outputs must not overwrite the first run\'s files', file=sys.stderr)
                return 2
            people, bots = load_prior_users(paths['prepared.zip'])
            prior = {'channels': {r['slack_id']: r for r in read_csv(paths['channel_map.csv'])},
                     'people': people, 'bots': bots}
            # The first run's renames win, so old text is rewritten exactly as before.
            emoji.update(load_prior_emoji_map(a.prior_emoji_map))
        stats = prepare(a.input, a.uploads, read_csv(a.identity), load_chat_users(a.chat_users),
                        load_chat_channels(a.chat_channels), emoji,
                        a.output, a.channel_map,
                        {r['folder']: r['archived'] == 'true' for r in read_csv(a.archive_state)}
                        if a.archive_state else None, prior)
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
