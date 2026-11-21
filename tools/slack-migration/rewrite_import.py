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

Re-import (--reimport-from FIRST_RUN_DIR, with a prepared export made by
prepare_export.py --reimport-from): a second Slack export on top of the first
import. Chat matches posts by channel + create_at + exact text and updates a
match in place; anything else is a new post.
  * Channels, people and bots the first run imported are left as they are:
    their channel, user and bot lines are dropped (a channel line would
    overwrite the header and archive state; a user line would reset locale,
    password and admin flags).
  * --since-first-import (default): only posts and replies newer than the
    first import's latest create_at in their channel are emitted. A new reply
    in an old thread is emitted under its root exactly as the first import
    wrote it (from import.zip: same text and attachments, so it matches and
    keeps its files; reactions left off, so none removed in chat come back).
    Old messages edited in Slack are skipped and counted, not duplicated.
  * --full: every post is emitted. Unchanged ones match and are updated in
    place; one whose text changed (edited in Slack, or rewritten differently)
    becomes a DUPLICATE. Reactions removed in chat come back.
  * --plan: per-channel prediction of what the import adds and skips.
"""
import argparse
import collections
import json
import os
import re
import shutil
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run with python -I
from common import (TEAM, TOWN_SQUARE, MigrationError, PriorImport,  # noqa: E402
                    attachment_names, iter_import_lines, iter_items, load_chat_users,
                    load_prior_users, post_key, prior_paths, reaction_set, read_csv, reply_key,
                    resolve_identities, write_csv)

USABLE_EMOJI_STATUS = ('imported', 'unchanged', 'built-in')
COUNT_FIELDS = ['mm_name', 'posts', 'replies', 'reactions', 'attachments', 'overflow_replies']


def count_overflow_replies(items):
    """Replies mmetl v0.6.0 created for files over the per-post limit
    (createRepliesForAttachments): no text, only attachments, same author, and
    created 1 ms after the post or reply that already holds the limit. items is
    [post, *replies]; the post itself is never an overflow reply."""
    full = {(it.get('user'), it.get('create_at')) for it in items
            if len(it.get('attachments') or []) >= 5}
    return sum(1 for it in items[1:]
               if not (it.get('message') or '').strip() and it.get('attachments')
               and (it.get('user'), (it.get('create_at') or 0) - 1) in full)


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


PLAN_FIELDS = ['mm_name', 'new_channel', 'new_posts', 'new_replies', 'new_reactions',
               'new_attachments', 'carrier_roots', 'carrier_roots_edited', 'unchanged',
               'skipped_changed', 'skipped_reactions', 'skipped_threads', 'skipped_thread_replies',
               'matched', 'duplicates', 'matched_new_reactions', 'matched_attachment_changes']
FULL_WARNING = ('WARNING: --full emits every post. Chat matches a post only by channel, time and '
                'exact text, so each message edited in Slack (or rewritten differently) since the '
                'first export becomes a DUPLICATE post, and reactions members removed in chat come back.')


class Reimport:
    """Chooses which posts of the second run to emit (see the module docstring)."""

    def __init__(self, prior_import, prior, prior_bot_names, full=False):
        self.path = prior_import
        self.prior = prior
        self.bots = set(prior_bot_names)
        self.full = full
        self.plan = collections.defaultdict(collections.Counter)
        self.candidates = {}
        self.prior_files = set()

    def find_carriers(self, lines):
        """Read the first import's version of every old root that gets new replies."""
        if self.full:
            return
        for raw in lines:
            line = json.loads(raw)
            if line.get('type') != 'post':
                continue
            p = line['post']
            cut = self.prior.cutoff.get(p['channel'])
            if cut is None or p['create_at'] > cut:
                continue
            if any(r.get('create_at', 0) > cut for r in p.get('replies') or []):
                self.candidates[(p['channel'], p['create_at'])] = []
        if self.candidates:
            for line in iter_import_lines(self.path):
                if line.get('type') == 'post':
                    p = line['post']
                    if (p['channel'], p.get('create_at')) in self.candidates:
                        self.candidates[(p['channel'], p['create_at'])].append(p)

    def _count_new(self, pl, items, replies):
        pl['new_replies'] += replies
        for it in items:
            pl['new_reactions'] += len(reaction_set(it))
            pl['new_attachments'] += len(it.get('attachments') or [])

    def select(self, p):
        """(post to emit or None, True when it is a carrier root from the first import)."""
        ch = p['channel']
        pl = self.plan[ch]
        cut = self.prior.cutoff.get(ch)
        replies = list(p.get('replies') or [])
        if self.full:
            for key, it, is_reply in iter_items(p):
                if self.prior.has(key):
                    pl['matched'] += 1
                    pl['matched_new_reactions'] += len(reaction_set(it) - self.prior.reactions(key))
                    if attachment_names(it) != self.prior.attachments(key):
                        pl['matched_attachment_changes'] += 1
                    continue
                if cut is not None and it.get('create_at', 0) <= cut:
                    pl['duplicates'] += 1
                elif is_reply:
                    pl['new_replies'] += 1
                else:
                    pl['new_posts'] += 1
                pl['new_reactions'] += len(reaction_set(it))
                pl['new_attachments'] += len(it.get('attachments') or [])
            return p, False
        if cut is None or p['create_at'] > cut:
            pl['new_posts'] += 1
            self._count_new(pl, [p] + replies, len(replies))
            return p, False
        new = [r for r in replies if r.get('create_at', 0) > cut]
        root_key = post_key(ch, p['create_at'], p.get('message'))
        cands = self.candidates.get((ch, p['create_at'])) or []
        exact = [c for c in cands if post_key(ch, c['create_at'], c.get('message')) == root_key]
        match = exact[:1] or (cands if len(cands) == 1 else [])
        # Old replies are matched under the root chat holds (the first import's).
        thread_key = post_key(ch, match[0]['create_at'], match[0].get('message')) if match else root_key
        old = [p] + [r for r in replies if r.get('create_at', 0) <= cut]
        for it in old:
            key = root_key if it is p else reply_key(thread_key, p['create_at'], it.get('create_at'),
                                                     it.get('message'))
            if self.prior.has(key):
                pl['unchanged'] += 1
                pl['skipped_reactions'] += len(reaction_set(it) - self.prior.reactions(key))
            else:
                pl['skipped_changed'] += 1
        if not new:
            return None, False
        if not match:
            # The root is not in chat as one identifiable post: never guess.
            pl['skipped_threads'] += 1
            pl['skipped_thread_replies'] += len(new)
            return None, False
        root = json.loads(json.dumps(match[0]))
        root.pop('reactions', None)
        root['replies'] = new
        pl['carrier_roots'] += 1
        if not exact:
            pl['carrier_roots_edited'] += 1
        for a in root.get('attachments') or []:
            self.prior_files.add(os.path.normpath(a['path']))
        self._count_new(pl, new, len(new))
        return root, True

    def plan_rows(self, new_channels):
        rows = []
        for name in sorted(set(self.plan) | set(new_channels)):
            row = {'mm_name': name, 'new_channel': 'true' if name in new_channels else 'false'}
            row.update({f: self.plan[name][f] for f in PLAN_FIELDS[2:]})
            rows.append(row)
        return rows


def rewrite(lines, identities, channel_map, chat_usernames, system_emoji, custom_emoji,
            attachments_dir, now_ms, expect_existing=(), reimport=None):
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
    if reimport is not None:
        reimport.find_carriers(lines)
        reimport.new_channels = set()
        reimport.skipped = collections.Counter()
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
            if reimport is not None:
                if ch['name'] in reimport.prior.channels:
                    reimport.skipped['channel lines (channels the first import created)'] += 1
                    continue
                reimport.new_channels.add(ch['name'])
        elif kind == 'user':
            u = line['user']
            ident = by_username.get(u['username'])
            if ident is None:
                problems.append(f'line {n}: user {u["username"]} is not in identity_map.csv')
            elif ident.get('prior'):
                # Already in chat from the first import: leave the account alone.
                existing_seen.add(u['username'])
                users_seen.add(u['username'])
                reimport.skipped['user lines (people the first import created)'] += 1
                continue
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
            if reimport is not None and line['bot']['username'] in reimport.bots:
                if line['bot']['username'] not in chat_usernames:
                    problems.append(f'line {n}: bot {line["bot"]["username"]} from the first import '
                                    'is not in chat')
                reimport.skipped['bot lines (bots the first import created)'] += 1
                continue
            if line['bot']['username'] in chat_usernames:
                problems.append(f'line {n}: bot {line["bot"]["username"]} already exists in chat')
        elif kind == 'post':
            p = line['post']
            ch = p['channel']
            if ch not in display:
                problems.append(f'line {n}: post in unknown channel {ch}')
            carrier = False
            if reimport is not None:
                p, carrier = reimport.select(p)
                if p is None:
                    continue
                line['post'] = p
            c = counts[ch]
            items = [p] + list(p.get('replies') or [])
            c['posts'] += 0 if carrier else 1
            c['replies'] += len(items) - 1
            c['overflow_replies'] += count_overflow_replies(items)
            for it in items[1:] if carrier else items:
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
    if reimport is not None and reimport.prior_files:
        # Carrier roots keep the first import's attachments (so the import
        # matches the files already on the post instead of deleting them);
        # the bytes come from the first import.zip.
        with zipfile.ZipFile(reimport.path) as z:
            have = set(z.namelist())
        for rel in sorted(reimport.prior_files):
            if 'data/' + rel.replace(os.sep, '/') not in have:
                problems.append(f'attachment {rel} of an old thread root is not in the first import.zip')
    return out, counts, problems, unknown_emoji, moved[0], sorted(packaged)


def package(jsonl_lines, attachments_dir, attachment_paths, out_zip, prior_zip=None, prior_paths_=()):
    """Write the import zip: import.jsonl plus only the referenced attachments.
    prior_paths_ are copied from prior_zip's data/ (re-import carrier roots) and
    win over a file of the same path in attachments_dir."""
    tmp = out_zip + '.partial'
    os.close(os.open(tmp, os.O_WRONLY | os.O_CREAT, 0o600))
    prior_set = set(prior_paths_)
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
        z.writestr('import.jsonl', '\n'.join(jsonl_lines) + '\n')
        for rel in attachment_paths:
            if rel not in prior_set:
                z.write(os.path.join(attachments_dir, rel), 'data/' + rel.replace(os.sep, '/'))
        if prior_set:
            with zipfile.ZipFile(prior_zip) as src:
                for rel in sorted(prior_set):
                    name = 'data/' + rel.replace(os.sep, '/')
                    with src.open(name) as fin, z.open(name, 'w', force_zip64=True) as fout:
                        shutil.copyfileobj(fin, fout, 1 << 20)
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
    ap.add_argument('--reimport-from', metavar='FIRST_RUN_DIR',
                    help="re-import: the first run's work directory (channel_map.csv, prepared.zip, import.zip)")
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument('--since-first-import', action='store_true',
                      help='re-import (default): only posts newer than the first import, per channel')
    mode.add_argument('--full', action='store_true',
                      help='re-import every post; messages edited in Slack become DUPLICATES')
    ap.add_argument('--plan', help='re-import: per-channel prediction CSV to write')
    a = ap.parse_args(argv)
    if (a.full or a.since_first_import or a.plan) and not a.reimport_from:
        print('error: --since-first-import, --full and --plan need --reimport-from', file=sys.stderr)
        return 2
    if a.reimport_from and not a.plan:
        print('error: --reimport-from needs --plan', file=sys.stderr)
        return 2
    if a.full:
        print(FULL_WARNING, file=sys.stderr)
    import time
    now_ms = a.now_ms or int(time.time() * 1000)
    reimport = None
    try:
        chat_users = load_chat_users(a.chat_users)
        prior_people = None
        if a.reimport_from:
            paths = prior_paths(a.reimport_from)
            mine = [a.output_zip, a.counts, a.report, a.plan]
            if any(os.path.realpath(p) in {os.path.realpath(q) for q in paths.values()} for p in mine):
                print("error: outputs must not overwrite the first run's files", file=sys.stderr)
                return 2
            prior_people, prior_bots = load_prior_users(paths['prepared.zip'])
            reimport = Reimport(paths['import.zip'], PriorImport.load(paths['import.zip']),
                                prior_bots.values(), full=a.full)
        identities = resolve_identities(read_csv(a.identity), chat_users, prior_people)
        with open(a.input, encoding='utf-8') as f:
            lines = [ln for ln in f if ln.strip()]
        out, counts, problems, unknown, moved, attachment_paths = rewrite(
            lines, identities, read_csv(a.channel_map),
            {u['username'].lower() for u in chat_users}, load_system_emoji(a.system_emoji),
            custom_emoji_names(a.emoji_map), a.attachments_dir, now_ms, a.expect_existing,
            reimport)
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
    if reimport is not None:
        rows = reimport.plan_rows(reimport.new_channels)
        write_csv(a.plan, rows, PLAN_FIELDS)
        tot = collections.Counter()
        for r in rows:
            tot.update({f: r[f] for f in PLAN_FIELDS[2:]})
        head = ['', '## Re-import prediction (' + ('--full' if a.full else '--since-first-import') + ')', '',
                f'- new channels: {len(reimport.new_channels)}']
        head += [f'- {f.replace("_", " ")}: {tot[f]}' for f in PLAN_FIELDS[2:]]
        head += [f'- dropped {k}: {v}' for k, v in sorted(reimport.skipped.items())]
        if a.full:
            head += ['', FULL_WARNING]
        report[report.index('## Unknown reaction emoji (most used first)') - 1:
               report.index('## Unknown reaction emoji (most used first)') - 1] = head
    report += [f'- `{k}`: {v}' for k, v in unknown.most_common()]
    report += ['', '## Problems', ''] + [f'- {p}' for p in problems[:500]]
    with open(a.report, 'w', encoding='utf-8') as f:
        f.write('\n'.join(report) + '\n')
    print('\n'.join(report[:10]))
    if reimport is not None:
        start = next(i for i, x in enumerate(report) if x.startswith('## Re-import'))
        print('\n'.join(report[start:report.index('## Unknown reaction emoji (most used first)')]))
    if problems:
        print(f'error: {len(problems)} problems; see {a.report}', file=sys.stderr)
        return 1
    if reimport is not None:
        package(out, a.attachments_dir, attachment_paths, a.output_zip,
                reimport.path, reimport.prior_files)
    else:
        package(out, a.attachments_dir, attachment_paths, a.output_zip)
    print(f'wrote {a.output_zip}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
