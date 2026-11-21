"""Inventory a Slack public-channel export (league chat spec §5, Plan 5 Task 1).

  inventory.py report  EXPORT.zip --out-dir DIR     inventory.md + channel_counts.csv
  inventory.py users   EXPORT.zip --out slack_users.csv   (mode 600: holds emails)
  inventory.py check-urls EXPORT.zip --env slack.env --out url_check.csv
  inventory.py compare OLD_counts.csv NEW_counts.csv
  inventory.py reconcile --slack prepared_counts.csv --import import_counts.csv \
      [--db db_counts.csv] --out acceptance_counts.csv
  inventory.py accounts BEFORE_users.json AFTER_users.json
  inventory.py members BEFORE_members.csv AFTER_members.csv   (prints the rows to restore, CSV)
  inventory.py reimport-check --prior FIRST/import.zip --new NEW/import.zip \
      [--chat-channels chat_channels.txt] [--allow-duplicates] --out reimport_check.csv
  inventory.py reimport-verify --before db_counts_before.csv --after db_counts_after.csv \
      --check reimport_check.csv --out reimport_verify.csv

Reads the export without changing it. Never prints emails or tokens.
"""
import argparse
import collections
import csv
import datetime as dt
import json
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run with python -I
from common import (MigrationError, PriorImport, attachment_names,  # noqa: E402
                    iter_import_lines, iter_items, load_chat_channels, load_env_file,
                    member_name, reaction_set, read_csv, slack_file_url, valid_username,
                    write_csv)

COUNT_FIELDS = ['folder', 'slack_id', 'slack_name', 'archived', 'in_channels_json',
                'messages', 'replies', 'mmetl_drops', 'mmetl_extra', 'files_import', 'first', 'last', 'files_hidden',
                'files_with_url', 'files_tombstone', 'files_other']
RECONCILE_FIELDS = ['mm_name', 'slack_messages', 'mmetl_drops', 'mmetl_extra', 'expected', 'import_file',
                    'import_overflow', 'overflow_diff', 'files_expected', 'import_files',
                    'files_diff', 'database', 'import_diff', 'database_diff']
# Messages mmetl v0.6.0 does not import (services/slack/intermediate.go:994,
# :1141), counted on the *prepared* export.
MMETL_DROPPED_SUBTYPES = {'pinned_item', 'channel_archive', 'channel_unarchive', 'reminder_add'}


def mmetl_drops(m):
    if m.get('type') != 'message':
        return True
    if m.get('bot_id') or m.get('subtype') == 'bot_message':
        return False
    if m.get('subtype') in MMETL_DROPPED_SUBTYPES:
        return True
    return not m.get('user')


# mmetl v0.6.0 keeps POST_MAX_ATTACHMENTS files on a post or reply and puts the
# rest in extra empty replies of up to that many each
# (services/intermediate/export.go createRepliesForAttachments).
MMETL_POST_MAX_ATTACHMENTS = 5


def importable_files(m, uploads):
    """Files mmetl will really attach to this message: 'file' if present, else
    'files'; de-duplicated by id; named (access granted), id in __uploads (the
    transform runs without --allow-download) and a real downloaded file, not
    hidden_by_limit, tombstone or external. Empty for a dropped message."""
    if mmetl_drops(m):
        return []
    files = [m['file']] if m.get('file') else (m.get('files') or [])
    seen, out = set(), []
    for f in files:
        fid = f.get('id')
        if (fid and fid not in seen and f.get('name') and fid in uploads
                and file_kind(f) == 'url'):
            seen.add(fid)
            out.append(f)
    return out


def mmetl_attachment_replies(m, uploads):
    """Extra replies mmetl adds for a message's importable files beyond the
    per-post limit."""
    over = len(importable_files(m, uploads)) - MMETL_POST_MAX_ATTACHMENTS
    return -(-over // MMETL_POST_MAX_ATTACHMENTS) if over > 0 else 0


USER_FIELDS = ['slack_id', 'slack_username', 'slack_real_name', 'slack_email',
               'slack_deleted', 'is_bot', 'bot_id']


def _day(ts):
    return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).strftime('%Y-%m-%d')


def iter_channel_files(zf):
    """(folder, member) for every <folder>/<day>.json message file."""
    for info in zf.infolist():
        name = member_name(info)
        parts = name.split('/')
        if (len(parts) == 2 and parts[1].endswith('.json')
                and not parts[0].startswith('__') and not info.is_dir()):
            yield parts[0], info


def load_json(zf, name):
    for info in zf.infolist():
        if member_name(info) == name:
            return json.loads(zf.read(info))
    return None


def file_kind(f):
    if f.get('mode') == 'hidden_by_limit':
        return 'hidden'
    if f.get('mode') == 'tombstone':
        return 'tombstone'
    if f.get('url_private_download') or f.get('url_private'):
        return 'url'
    return 'other'


def message_files(m):
    files = list(m.get('files') or [])
    if m.get('file'):
        files.append(m['file'])
    return files


def scan(zf):
    channels = load_json(zf, 'channels.json') or []
    users = load_json(zf, 'users.json') or []
    by_name = {c['name']: c for c in channels}
    per = {}
    subtypes = collections.Counter()
    hosts = collections.Counter()
    totals = collections.Counter()
    referenced = set()
    first = last = None
    uploads = {member_name(i).split('/')[1] for i in zf.infolist()
               if member_name(i).startswith('__uploads/') and member_name(i).count('/') == 2}
    for folder, info in iter_channel_files(zf):
        c = by_name.get(folder)
        row = per.setdefault(folder, {
            'folder': folder, 'slack_id': c['id'] if c else '',
            'slack_name': c['name'] if c else '', 'archived': str(bool(c and c.get('is_archived'))).lower(),
            'in_channels_json': 'yes' if c else 'no', 'messages': 0, 'replies': 0, 'mmetl_drops': 0, 'mmetl_extra': 0,
            'files_import': 0,
            'first': '', 'last': '', 'files_hidden': 0, 'files_with_url': 0,
            'files_tombstone': 0, 'files_other': 0})
        for m in json.loads(zf.read(info)):
            row['messages'] += 1
            totals['messages'] += 1
            if mmetl_drops(m):
                row['mmetl_drops'] += 1
            row['mmetl_extra'] += mmetl_attachment_replies(m, uploads)
            row['files_import'] += len(importable_files(m, uploads))
            subtypes[m.get('subtype') or 'message'] += 1
            ts = m.get('ts')
            if ts:
                day = _day(ts)
                row['first'] = min(row['first'] or day, day)
                row['last'] = max(row['last'] or day, day)
                first = min(first or day, day)
                last = max(last or day, day)
            if m.get('thread_ts') and m.get('thread_ts') != ts:
                row['replies'] += 1
                totals['replies'] += 1
            for r in m.get('reactions') or []:
                totals['reactions'] += 1
                totals['reaction_users'] += len(r.get('users') or [])
                referenced.update(r.get('users') or [])
            if m.get('user'):
                referenced.add(m['user'])
            for f in message_files(m):
                kind = file_kind(f)
                totals['files'] += 1
                row[{'hidden': 'files_hidden', 'url': 'files_with_url',
                     'tombstone': 'files_tombstone'}.get(kind, 'files_other')] += 1
                if kind == 'url':
                    url = f.get('url_private_download') or f.get('url_private')
                    hosts[url.split('/')[2]] += 1
                    if 't=' in url:
                        totals['url_with_t_token'] += 1
                    if f.get('id') in uploads:
                        totals['url_files_in_zip'] += 1
    for c in channels:
        referenced.update(c.get('members') or [])
    known = {u['id'] for u in users}
    # USLACKBOT is Slackbot, never a person; prepare_export.py gives it a bot account.
    missing = sorted(i for i in referenced
                     if i not in known and i != 'USLACKBOT' and i.startswith(('U', 'W')))
    return {
        'channels': channels, 'users': users, 'per': per, 'subtypes': subtypes,
        'hosts': hosts, 'totals': totals, 'first': first, 'last': last,
        'missing_users': missing, 'uploads': uploads,
        'top_files': sorted(member_name(i) for i in zf.infolist() if '/' not in member_name(i)),
    }


def write_report(s, out_dir):
    rows = sorted(s['per'].values(), key=lambda r: -r['messages'])
    write_csv(f'{out_dir}/channel_counts.csv', rows, COUNT_FIELDS)
    users = s['users']
    bots = [u for u in users if u.get('is_bot')]
    humans = [u for u in users if not u.get('is_bot')]
    t = s['totals']
    folders = set(s['per'])
    names = {c['name'] for c in s['channels']}
    lines = [
        '# Slack export inventory', '',
        f'- Top-level files: {", ".join(s["top_files"])}',
        f'- groups.json / dms.json / mpims.json present: '
        f'{[n for n in ("groups.json", "dms.json", "mpims.json") if n in s["top_files"]] or "none"}',
        f'- Channels in channels.json: {len(s["channels"])} '
        f'(archived {sum(1 for c in s["channels"] if c.get("is_archived"))}); '
        f'Slack default channel (is_general): {[c["name"] for c in s["channels"] if c.get("is_general")]}',
        f'- Channel folders: {len(folders)}; folders not in channels.json: {sorted(folders - names)}; '
        f'channels with no folder: {sorted(names - folders)}',
        f'- Users: {len(users)} (humans {len(humans)}, bots {len(bots)}, '
        f'deleted {sum(1 for u in users if u.get("deleted"))}, '
        f'guests {sum(1 for u in users if u.get("is_restricted") or u.get("is_ultra_restricted"))}, '
        f'with email {sum(1 for u in users if (u.get("profile") or {}).get("email"))})',
        f'- Usernames not valid in chat: {[u["name"] for u in users if not valid_username(u["name"])] or "none"}',
        f'- User IDs referenced but missing from users.json: {len(s["missing_users"])}',
        f'- Messages: {t["messages"]} from {s["first"]} to {s["last"]}; thread replies {t["replies"]}; '
        f'reactions {t["reactions"]} ({t["reaction_users"]} user reactions)',
        f'- Subtypes: {dict(s["subtypes"].most_common())}',
        f'- Files referenced: {t["files"]}; hidden_by_limit '
        f'{sum(r["files_hidden"] for r in rows)}; with URL {sum(r["files_with_url"] for r in rows)} '
        f'(hosts {dict(s["hosts"])}; carrying t= {t["url_with_t_token"]}; already in zip '
        f'{t["url_files_in_zip"]}); tombstones {sum(r["files_tombstone"] for r in rows)}; '
        f'other {sum(r["files_other"] for r in rows)}',
        f'- `__uploads/` entries in the zip: {len(s["uploads"])}', '',
        '## Messages per channel', '',
        '| Folder | Archived | Messages | Replies | First | Last | Hidden files | Files with URL |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for r in rows:
        lines.append(f'| {r["folder"]} | {r["archived"]} | {r["messages"]} | {r["replies"]} | '
                     f'{r["first"]} | {r["last"]} | {r["files_hidden"]} | {r["files_with_url"]} |')
    with open(f'{out_dir}/inventory.md', 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    return lines


def user_rows(s):
    rows = []
    for u in s['users']:
        p = u.get('profile') or {}
        rows.append({
            'slack_id': u['id'], 'slack_username': u['name'],
            'slack_real_name': p.get('real_name') or u.get('real_name') or '',
            'slack_email': (p.get('email') or '').lower(),
            'slack_deleted': str(bool(u.get('deleted'))).lower(),
            'is_bot': str(bool(u.get('is_bot'))).lower(), 'bot_id': p.get('bot_id') or '',
        })
    for sid in s['missing_users']:
        rows.append({'slack_id': sid, 'slack_username': sid.lower(),
                     'slack_real_name': 'Deleted User', 'slack_email': '',
                     'slack_deleted': 'true', 'is_bot': 'false', 'bot_id': ''})
    return sorted(rows, key=lambda r: r['slack_id'])


def check_urls(zf, token, out, session=None):
    """Try each files.slack.com URL with the token. The token is sent only to
    https://files.slack.com (common.slack_file_url) and redirects are not
    followed, so it cannot reach another host; other URLs are listed as
    `skipped` without any request."""
    import requests
    http = session or requests.Session()
    rows = []
    for folder, info in iter_channel_files(zf):
        for m in json.loads(zf.read(info)):
            for f in message_files(m):
                url = f.get('url_private_download') or f.get('url_private')
                if not url:
                    continue
                if not slack_file_url(url):
                    rows.append({'folder': folder, 'file_id': f.get('id', ''), 'status': 'skipped',
                                 'content_type': '', 'ok': 'false'})
                    continue
                try:
                    r = http.get(url, stream=True, timeout=30, allow_redirects=False,
                                 headers={'Authorization': f'Bearer {token}'})
                    status = r.status_code
                    ctype = r.headers.get('Content-Type', '')
                    r.close()
                except requests.RequestException as e:
                    status, ctype = type(e).__name__, ''
                ok = status == 200 and not ctype.startswith('text/html')
                rows.append({'folder': folder, 'file_id': f.get('id', ''), 'status': status,
                             'content_type': ctype, 'ok': str(ok).lower()})
    write_csv(out, rows, ['folder', 'file_id', 'status', 'content_type', 'ok'])
    return rows


MEMBER_FIELDS = ['kind', 'target_id', 'user_id', 'username', 'name', 'scheme_admin', 'explicit_roles']
ACCOUNT_FIELDS = ('username', 'email', 'roles', 'auth_service', 'auth_data', 'delete_at')


def accounts(before_path, after_path):
    """Chat accounts that existed before the import and changed in any field
    the import must not touch (roles, auth, email, active state)."""
    from common import load_chat_users
    after = {u['id']: u for u in load_chat_users(after_path)}
    problems = []
    for u in load_chat_users(before_path):
        a = after.get(u['id'])
        if a is None:
            problems.append(f'{u["username"]}: missing after the import')
            continue
        for k in ACCOUNT_FIELDS:
            if (u.get(k) or '') != (a.get(k) or ''):
                problems.append(f'{u["username"]}: {k} {u.get(k)!r} -> {a.get(k)!r}')
    return problems


def members(before_path, after_path):
    """Team and channel memberships of existing accounts whose admin flag or
    explicit roles the import changed (importUserTeams rebuilds both,
    import_functions.go:1306-1376). Rows: MEMBER_FIELDS. Returns the
    `before` rows to restore."""
    def load(p):
        return {(r['kind'], r['target_id'], r['user_id']): r for r in read_csv(p)}
    before, after = load(before_path), load(after_path)
    return [r for k, r in sorted(before.items())
            if k in after and (after[k]['scheme_admin'] != r['scheme_admin']
                               or after[k].get('explicit_roles', '') != r.get('explicit_roles', ''))]


def compare(old_path, new_path):
    """Problems where the newer export lost history the older one had."""
    old = {r['folder']: r for r in read_csv(old_path)}
    new = {r['folder']: r for r in read_csv(new_path)}
    problems = []
    for folder, o in sorted(old.items()):
        n = new.get(folder)
        if n is None:
            problems.append(f'{folder}: missing from the newer export')
        elif int(n['messages']) < int(o['messages']):
            problems.append(f'{folder}: {o["messages"]} -> {n["messages"]} messages')
        elif n['first'] and o['first'] and n['first'] > o['first']:
            problems.append(f'{folder}: oldest day moved {o["first"]} -> {n["first"]}')
    return problems


def reconcile(slack_path, import_path, db_path=None):
    """Per-channel acceptance counts: Slack messages minus the ones mmetl is
    known to drop, plus the replies it adds for files over the per-post limit
    (mmetl_extra; 0 when the counts file predates that column), against the import file and (after import) the database."""
    slack = {r['folder']: r for r in read_csv(slack_path)}
    imp = {r['mm_name']: r for r in read_csv(import_path)}
    db = {r['mm_name']: r for r in read_csv(db_path)} if db_path else {}
    rows = []
    for name in sorted(set(slack) | set(imp)):
        s = slack.get(name, {})
        expected = (int(s.get('messages') or 0) - int(s.get('mmetl_drops') or 0)
                    + int(s.get('mmetl_extra') or 0))
        i = imp.get(name, {})
        in_file = int(i.get('posts') or 0) + int(i.get('replies') or 0)
        # Cross-check the claimed overflow against the import. Preferred: the
        # import's own count of overflow replies (empty, attachment-only,
        # created 1 ms after their parent). Without that column: total
        # attachments, expected (importable files) against imported.
        extra = int(s.get('mmetl_extra') or 0)
        overflow = i.get('overflow_replies')
        overflow_diff = '' if overflow in (None, '') else int(overflow) - extra
        fx = s.get('files_import')
        fi = i.get('attachments')
        files_diff = '' if fx in (None, '') or fi in (None, '') else int(fi) - int(fx)
        if extra and overflow_diff == '' and files_diff == '':
            files_diff = 'unverifiable'       # fail closed: nothing to check the claim against
        row = {'mm_name': name, 'slack_messages': s.get('messages', '0'),
               'mmetl_drops': s.get('mmetl_drops', '0'),
               'mmetl_extra': s.get('mmetl_extra') or '0', 'expected': expected,
               'import_file': in_file, 'import_diff': in_file - expected,
               'import_overflow': overflow if overflow is not None else '',
               'overflow_diff': overflow_diff,
               'files_expected': fx if fx is not None else '',
               'import_files': fi if fi is not None else '', 'files_diff': files_diff,
               'database': '', 'database_diff': ''}
        if db_path:
            in_db = int((db.get(name) or {}).get('posts') or 0)
            row.update(database=in_db, database_diff=in_db - in_file)
        rows.append(row)
    return rows


CHECK_FIELDS = ['mm_name', 'new_channel', 'new_posts', 'new_replies', 'new_reactions',
                'new_attachments', 'matched', 'matched_new_reactions', 'reactions_readded',
                'attachment_changes', 'possible_duplicates']
VERIFY_FIELDS = ['mm_name', 'before', 'after', 'added', 'expected', 'diff']


def reimport_check(prior_path, new_path, chat_channels=None):
    """Predict what importing new_path adds on top of the first import
    (prior_path), using the server's own match rule (common.post_key /
    reply_key). Returns (per-channel rows, users, bots, hazards).

    A hazard is something the import would change in what chat already holds:
    a channel line for an existing channel (overwrites its header, purpose and
    archive state), or a matched post whose attachments differ (the import
    deletes the files it does not find again)."""
    prior = PriorImport.load(prior_path)
    rows = collections.defaultdict(collections.Counter)
    new_channels, hazards = set(), []
    users = bots = 0
    for line in iter_import_lines(new_path):
        kind = line.get('type')
        if kind == 'channel':
            name = line['channel']['name']
            if name in prior.channels:
                hazards.append(f'channel line for {name}, which the first import created')
            elif chat_channels is not None and name in chat_channels:
                hazards.append(f'channel line for {name}, which already exists in chat')
            new_channels.add(name)
        elif kind == 'user':
            users += 1
        elif kind == 'bot':
            bots += 1
        elif kind == 'post':
            p = line['post']
            r = rows[p['channel']]
            cut = prior.cutoff.get(p['channel'])
            for key, it, is_reply in iter_items(p):
                reacts = reaction_set(it)
                if prior.has(key):
                    r['matched'] += 1
                    r['matched_new_reactions'] += len(reacts - prior.reactions(key))
                    r['reactions_readded'] += len(reacts & prior.reactions(key))
                    if attachment_names(it) != prior.attachments(key):
                        r['attachment_changes'] += 1
                    continue
                if cut is not None and (it.get('create_at') or 0) <= cut:
                    r['possible_duplicates'] += 1
                else:
                    r['new_replies' if is_reply else 'new_posts'] += 1
                r['new_reactions'] += len(reacts)
                r['new_attachments'] += len(it.get('attachments') or [])
    out = []
    for name in sorted(set(rows) | new_channels):
        row = {'mm_name': name, 'new_channel': 'true' if name in new_channels else 'false'}
        row.update({f: rows[name][f] for f in CHECK_FIELDS[2:]})
        out.append(row)
    changes = sum(r['attachment_changes'] for r in out)
    if changes:
        hazards.append(f'{changes} post(s) already in chat would get different attachments '
                       '(the import deletes files it does not find again)')
    return out, users, bots, hazards


def reimport_verify(before_path, after_path, check_path):
    """After the second import: per-channel post count growth (counts.sql: posts
    and replies) against reimport-check's prediction."""
    before = {r['mm_name']: int(r['posts'] or 0) for r in read_csv(before_path)}
    after = {r['mm_name']: int(r['posts'] or 0) for r in read_csv(after_path)}
    check = {r['mm_name']: r for r in read_csv(check_path)}
    rows = []
    for name in sorted(set(before) | set(after) | set(check)):
        c = check.get(name, {})
        expected = sum(int(c.get(f) or 0) for f in ('new_posts', 'new_replies', 'possible_duplicates'))
        added = after.get(name, 0) - before.get(name, 0)
        rows.append({'mm_name': name, 'before': before.get(name, 0), 'after': after.get(name, 0),
                     'added': added, 'expected': expected, 'diff': added - expected})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('report'); p.add_argument('export'); p.add_argument('--out-dir', required=True)
    p = sub.add_parser('users'); p.add_argument('export'); p.add_argument('--out', required=True)
    p = sub.add_parser('check-urls'); p.add_argument('export')
    p.add_argument('--env', required=True); p.add_argument('--out', required=True)
    p = sub.add_parser('compare'); p.add_argument('old'); p.add_argument('new')
    p = sub.add_parser('accounts'); p.add_argument('before'); p.add_argument('after')
    p = sub.add_parser('members'); p.add_argument('before'); p.add_argument('after')
    p = sub.add_parser('reconcile'); p.add_argument('--slack', required=True)
    p.add_argument('--import', dest='imp', required=True); p.add_argument('--db')
    p.add_argument('--out', required=True)
    p = sub.add_parser('reimport-check'); p.add_argument('--prior', required=True)
    p.add_argument('--new', required=True); p.add_argument('--chat-channels')
    p.add_argument('--allow-duplicates', action='store_true',
                   help='a --full run: report possible duplicates without failing')
    p.add_argument('--out', required=True)
    p = sub.add_parser('reimport-verify'); p.add_argument('--before', required=True)
    p.add_argument('--after', required=True); p.add_argument('--check', required=True)
    p.add_argument('--out', required=True)
    a = ap.parse_args(argv)
    try:
        if a.cmd == 'accounts':
            problems = accounts(a.before, a.after)
            print('\n'.join(problems) or 'ok: existing chat accounts unchanged')
            return 1 if problems else 0
        if a.cmd == 'members':
            restore = members(a.before, a.after)
            w = csv.DictWriter(sys.stdout, fieldnames=MEMBER_FIELDS, extrasaction='ignore')
            w.writeheader()
            w.writerows(restore)
            print(f'{len(restore)} membership(s) changed', file=sys.stderr)
            return 1 if restore else 0
        if a.cmd == 'reconcile':
            rows = reconcile(a.slack, a.imp, a.db)
            write_csv(a.out, rows, RECONCILE_FIELDS)
            off = [r for r in rows if r['import_diff'] or r['database_diff'] not in ('', 0)
                   or r['overflow_diff'] not in ('', 0) or r['files_diff'] not in ('', 0)]
            for r in off:
                print(f'{r["mm_name"]}: expected {r["expected"]} (mmetl_extra {r["mmetl_extra"]}), '
                      f'import file {r["import_file"]}, '
                      f'import overflow replies {r["import_overflow"] or "-"} (diff {r["overflow_diff"] or "-"}), '
                      f'files diff {r["files_diff"] or "-"}, '
                      f'database {r["database"] if r["database"] != "" else "-"}')
            print(f'{len(rows)} channels; {len(off)} differ; details in {a.out}')
            return 1 if off else 0
        if a.cmd == 'reimport-check':
            chans = load_chat_channels(a.chat_channels) if a.chat_channels else None
            rows, users, bots, hazards = reimport_check(a.prior, a.new, chans)
            write_csv(a.out, rows, CHECK_FIELDS)
            tot = collections.Counter()
            for r in rows:
                tot.update({f: r[f] for f in CHECK_FIELDS[2:]})
            print(f'new channels: {sum(1 for r in rows if r["new_channel"] == "true")}')
            print(f'user lines (new people): {users}; bot lines (new bots): {bots}')
            for f in CHECK_FIELDS[2:]:
                print(f'{f.replace("_", " ")}: {tot[f]}')
            for h in hazards:
                print(f'HAZARD: {h}')
            if tot['reactions_readded']:
                print(f'note: {tot["reactions_readded"]} reaction(s) already in chat are sent again; '
                      'any a member removed in chat comes back')
            if tot['possible_duplicates']:
                print(f'{"WARNING" if a.allow_duplicates else "HAZARD"}: {tot["possible_duplicates"]} '
                      'post(s) or replies at or before the first import\'s last message in their '
                      'channel match nothing in it: edited in Slack, so each becomes a duplicate')
            print(f'details in {a.out}')
            bad = hazards or (tot['possible_duplicates'] and not a.allow_duplicates)
            return 1 if bad else 0
        if a.cmd == 'reimport-verify':
            rows = reimport_verify(a.before, a.after, a.check)
            write_csv(a.out, rows, VERIFY_FIELDS)
            off = [r for r in rows if r['diff']]
            for r in off:
                print(f'{r["mm_name"]}: added {r["added"]}, expected {r["expected"]}')
            print(f'{len(rows)} channels; added {sum(r["added"] for r in rows)}, expected '
                  f'{sum(r["expected"] for r in rows)}; {len(off)} differ; details in {a.out}')
            return 1 if off else 0
        if a.cmd == 'compare':
            problems = compare(a.old, a.new)
            print('\n'.join(problems) or 'ok: no channel lost history')
            return 1 if problems else 0
        with zipfile.ZipFile(a.export) as zf:
            if a.cmd == 'report':
                print('\n'.join(write_report(scan(zf), a.out_dir)[:16]))
            elif a.cmd == 'users':
                rows = user_rows(scan(zf))
                write_csv(a.out, rows, USER_FIELDS, private=True)
                print(f'wrote {len(rows)} users to {a.out} (mode 600)')
            elif a.cmd == 'check-urls':
                rows = check_urls(zf, load_env_file(a.env, 'SLACK_API_TOKEN'), a.out)
                good = sum(1 for r in rows if r['ok'] == 'true')
                print(f'{good} of {len(rows)} files.slack.com URLs downloadable; details in {a.out}')
    except MigrationError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
