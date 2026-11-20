"""Rewrite mmetl output for IFL Chat and package it (league chat spec §5, Plan 5 Task 7).

Input is the JSONL and attachments directory written by
`mmetl transform slack` from the prepared export. Output is one import zip:
`import.jsonl` at the root plus `data/bulk-export-attachments/...`, the
layout Mattermost's import job reads (model.ExportDataDir = "data").

  * Linked people get auth_service=gitlab and auth_data=<site user id>.
    Mattermost matches them by auth data (import_functions.go:398-445), so a
    member who already has a chat account (josh_0) is updated, not
    duplicated.
  * For an existing chat account the user line drops every `roles` value:
    mmetl writes roles=system_user, and importUser would otherwise call
    UpdateUserRoles and remove system_admin (import_functions.go:580-590,
    748-753).
  * People who are not linked, and linked people who are not current league
    members, are imported deactivated.
  * Channel display names come from channel_map.csv; town-square stays open.
  * An identity row that names an existing chat account is refused unless the
    snapshot shows that account linked (gitlab) to the same site id.
  * Every reference is checked: users, channels, attachments (confined to the
    attachments directory; only referenced files are packaged). Unknown
    emoji names are reported, not changed.
Writes per-channel post and reply counts for the acceptance checks.
"""
import argparse
import collections
import json
import os
import re
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run with python -I
from common import (TEAM, TOWN_SQUARE, MigrationError, load_chat_users,  # noqa: E402
                    read_csv, resolve_identities, write_csv)

USABLE_EMOJI_STATUS = ('imported', 'unchanged', 'built-in')
COUNT_FIELDS = ['mm_name', 'posts', 'replies', 'reactions', 'attachments']


def load_system_emoji(path):
    """Names from the fork's server/public/model/emoji_data.go."""
    with open(path, encoding='utf-8') as f:
        return set(re.findall(r'^\s*"([^"]+)":\s*"', f.read(), re.M))


def custom_emoji_names(emoji_map_path):
    if not emoji_map_path:
        return set()
    return {r['mm_name'] for r in read_csv(emoji_map_path)
            if r['mm_name'] and r['status'] in USABLE_EMOJI_STATUS}


def rewrite_user(u, ident, now_ms):
    u['email'] = ident['email']
    if ident['auth_data']:
        u['auth_service'] = 'gitlab'
        u['auth_data'] = ident['auth_data']
        u.pop('password', None)
    if ident['existing']:
        # Leave the live account as it is: no role change (that would drop
        # system_admin), no name change, no active-state change.
        for key in ('roles', 'delete_at', 'nickname', 'first_name', 'last_name', 'position'):
            u.pop(key, None)
        for team in u.get('teams') or []:
            team.pop('roles', None)
            for ch in team.get('channels') or []:
                ch.pop('roles', None)
    elif ident['active']:
        u.pop('delete_at', None)
    else:
        u['delete_at'] = u.get('delete_at') or now_ms
    return u


def rewrite(lines, identities, channel_map, chat_usernames, system_emoji, custom_emoji,
            attachments_dir, now_ms, expect_existing=()):
    """Return (rewritten lines, per-channel counts, problems, unknown emoji, reactions moved,
    attachment paths to package, normalised and relative to attachments_dir)."""
    by_username = {i['username']: i for i in identities.values()}
    display = {r['mm_name']: r['mm_display_name'] for r in channel_map}
    known_users = set(chat_usernames)
    out, problems = [], []
    counts = collections.defaultdict(collections.Counter)
    unknown_emoji = collections.Counter()
    moved = [0]
    packaged = set()
    root = os.path.realpath(attachments_dir)
    users_seen = set()
    existing_seen = set()
    for n, raw in enumerate(lines, 1):
        line = json.loads(raw)
        kind = line.get('type')
        if kind == 'channel':
            ch = line['channel']
            if ch.get('team') != TEAM:
                problems.append(f'line {n}: channel {ch.get("name")} is for team {ch.get("team")}')
            if ch['name'] not in display:
                problems.append(f'line {n}: channel {ch["name"]} is not in channel_map.csv')
            else:
                ch['display_name'] = display[ch['name']]
            if ch['name'] == TOWN_SQUARE:
                ch['type'] = 'O'
                ch.pop('deleted_at', None)
        elif kind == 'user':
            u = line['user']
            ident = by_username.get(u['username'])
            if ident is None:
                problems.append(f'line {n}: user {u["username"]} is not in identity_map.csv')
            else:
                rewrite_user(u, ident, now_ms)
                if ident['existing']:
                    existing_seen.add(u['username'])
            users_seen.add(u['username'])
            for team in u.get('teams') or []:
                if team.get('name') != TEAM:
                    problems.append(f'line {n}: user {u["username"]} joins team {team.get("name")}')
        elif kind == 'bot':
            users_seen.add(line['bot']['username'])
            if line['bot']['username'] in chat_usernames:
                problems.append(f'line {n}: bot {line["bot"]["username"]} already exists in chat')
        elif kind == 'post':
            p = line['post']
            ch = p['channel']
            if ch not in display:
                problems.append(f'line {n}: post in unknown channel {ch}')
            c = counts[ch]
            c['posts'] += 1
            items = [p] + list(p.get('replies') or [])
            c['replies'] += len(items) - 1
            for it in items:
                if it.get('user') not in users_seen and it.get('user') not in known_users:
                    problems.append(f'line {n}: author {it.get("user")} has no user line')
                for a in it.get('attachments') or []:
                    c['attachments'] += 1
                    rel = os.path.normpath(a['path'])
                    full = os.path.realpath(os.path.join(root, rel))
                    if (os.path.isabs(a['path']) or rel == '..' or rel.startswith('..' + os.sep)
                            or os.path.commonpath([root, full]) != root):
                        problems.append(f'line {n}: attachment {a["path"]} escapes the '
                                        'attachments directory')
                    elif not os.path.isfile(full):
                        problems.append(f'line {n}: attachment {a["path"]} is missing')
                    else:
                        a['path'] = rel.replace(os.sep, '/')
                        packaged.add(rel)
                for r in it.get('reactions') or []:
                    c['reactions'] += 1
                    if not isinstance(r.get('create_at'), int):
                        problems.append(f'line {n}: reaction has no create_at')
                    elif r['create_at'] < it.get('create_at', 0):
                        # mmetl can stamp a reaction 1 ms before its post; the
                        # import validator rejects that.
                        r['create_at'] = it['create_at']
                        moved[0] += 1
                    if r.get('user') not in users_seen and r.get('user') not in known_users:
                        problems.append(f'line {n}: reaction by unknown user {r.get("user")}')
                    name = r.get('emoji_name')
                    if name not in system_emoji and name not in custom_emoji:
                        unknown_emoji[name] += 1
        elif kind in ('direct_channel', 'direct_post'):
            problems.append(f'line {n}: {kind} lines are out of scope (public channels only)')
        out.append(json.dumps(line, ensure_ascii=False))
    for name in expect_existing:
        if name not in existing_seen:
            problems.append(f'{name}: no Slack history is linked to this existing chat account '
                            '(check its identity_map.csv row is confirmed)')
    return out, counts, problems, unknown_emoji, moved[0], sorted(packaged)


def package(jsonl_lines, attachments_dir, attachment_paths, out_zip):
    """Write the import zip: import.jsonl plus only the referenced attachments."""
    tmp = out_zip + '.partial'
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT, 0o600))
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr('import.jsonl', '\n'.join(jsonl_lines) + '\n')
        for rel in attachment_paths:
            z.write(os.path.join(attachments_dir, rel), 'data/' + rel.replace(os.sep, '/'))
    os.chmod(tmp, 0o600)
    os.replace(tmp, out_zip)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--input', required=True, help='mmetl JSONL')
    ap.add_argument('--attachments-dir', required=True, help="mmetl's --attachments-dir")
    ap.add_argument('--identity', required=True)
    ap.add_argument('--chat-users', required=True)
    ap.add_argument('--channel-map', required=True)
    ap.add_argument('--emoji-map')
    ap.add_argument('--system-emoji', required=True, help='server/public/model/emoji_data.go')
    ap.add_argument('--output-zip', required=True)
    ap.add_argument('--counts', required=True, help='per-channel counts CSV to write')
    ap.add_argument('--report', required=True)
    ap.add_argument('--now-ms', type=int, default=None)
    ap.add_argument('--expect-existing', action='append', default=[],
                    help='an existing chat username that must receive Slack history (repeatable)')
    a = ap.parse_args(argv)
    import time
    now_ms = a.now_ms or int(time.time() * 1000)
    try:
        chat_users = load_chat_users(a.chat_users)
        identities = resolve_identities(read_csv(a.identity), chat_users)
        with open(a.input, encoding='utf-8') as f:
            lines = [ln for ln in f if ln.strip()]
        out, counts, problems, unknown, moved, attachment_paths = rewrite(
            lines, identities, read_csv(a.channel_map),
            {u['username'].lower() for u in chat_users}, load_system_emoji(a.system_emoji),
            custom_emoji_names(a.emoji_map), a.attachments_dir, now_ms, a.expect_existing)
    except MigrationError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    rows = [{'mm_name': k, **{f: v[f] for f in COUNT_FIELDS[1:]}} for k, v in sorted(counts.items())]
    write_csv(a.counts, rows, COUNT_FIELDS)
    report = ['# rewrite_import report', '',
              f'- lines: {len(out)}',
              f'- posts: {sum(c["posts"] for c in counts.values())}',
              f'- replies: {sum(c["replies"] for c in counts.values())}',
              f'- reactions: {sum(c["reactions"] for c in counts.values())}',
              f'- attachments: {sum(c["attachments"] for c in counts.values())}',
              f'- problems: {len(problems)}',
              f'- confirmed rows with an unverified site email, imported unmatched: '
              f'{sum(1 for i in identities.values() if i.get("unverified_email"))}',
              f'- reactions moved to their post time: {moved}',
              f'- reactions whose emoji is neither built in nor imported: '
              f'{sum(unknown.values())} uses of {len(unknown)} names', '',
              '## Unknown reaction emoji (most used first)', '']
    report += [f'- `{k}`: {v}' for k, v in unknown.most_common()]
    report += ['', '## Problems', ''] + [f'- {p}' for p in problems[:500]]
    with open(a.report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report) + '\n')
    print('\n'.join(report[:10]))
    if problems:
        print(f'error: {len(problems)} problems; see {a.report}', file=sys.stderr)
        return 1
    package(out, a.attachments_dir, attachment_paths, a.output_zip)
    print(f'wrote {a.output_zip}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
