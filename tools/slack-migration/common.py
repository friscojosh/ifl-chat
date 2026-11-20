"""Shared helpers for the IFL Slack migration tools (league chat spec §5).

Slack exports and chat snapshots are untrusted data: these helpers only parse
them. Nothing here prints a token, and files that hold emails are written
with mode 600.
"""
import csv
import json
import os
import re
import stat

PLACEHOLDER_DOMAIN = 'import.invalid'
TEAM = 'ifl'
TOWN_SQUARE = 'town-square'
SLACK_GENERAL = 'general'

# model.IsValidUsername: server/public/model/user.go:1092 and :1102.
USERNAME_RE = re.compile(r'^[a-z0-9.\-_]{1,64}$')
RESTRICTED_USERNAMES = {'all', 'channel', 'matterbot', 'system'}
# model.IsValidChannelIdentifier (validSimpleAlphaNum): server/public/model/utils.go:710-717.
CHANNEL_NAME_RE = re.compile(r'^[a-z0-9]+([a-z\-_0-9]+|(__)?)[a-z0-9]*$')
CHANNEL_NAME_MAX = 64
DISPLAY_NAME_MAX = 64
SLACK_USER_ID_RE = re.compile(r'^[UW][A-Z0-9]{2,30}$')

IDENTITY_FIELDS = [
    'slack_id', 'slack_username', 'slack_real_name', 'slack_email',
    'slack_deleted', 'is_bot', 'match', 'site_id', 'site_username',
    'site_email', 'site_member', 'chat_username', 'chat_email',
    'chat_active', 'confirmed', 'mm_username_override',
]


class MigrationError(Exception):
    """A problem that must be fixed before the pipeline can continue."""


def member_name(info):
    """A zip member's name as text. Slack writes UTF-8 names without the
    UTF-8 flag, so Python decodes them as cp437 ('kyliesko╤Åner' for
    'kylieskoяner'); undo that."""
    if info.flag_bits & 0x800:
        return info.filename
    try:
        return info.filename.encode('cp437').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def placeholder_email(slack_id):
    return f'slack-{slack_id.lower()}@{PLACEHOLDER_DOMAIN}'


def valid_username(name):
    return bool(USERNAME_RE.match(name)) and name not in RESTRICTED_USERNAMES


def valid_channel_name(name):
    return 1 <= len(name) <= CHANNEL_NAME_MAX and bool(CHANNEL_NAME_RE.match(name))


def slug(text, allowed=r'a-z0-9_-'):
    """Lower-case `text`; each run of characters outside `allowed` becomes '-'."""
    out = re.sub(f'[^{allowed}]+', '-', text.lower())
    return re.sub(r'-{2,}', '-', out).strip('_-.')


def truncate(text, limit):
    return text if len(text) <= limit else text[:limit]


def open_private(path, mode='w', **kwargs):
    """Open a file for writing that only the owner can read."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.chmod(path, 0o600)
    return os.fdopen(fd, mode, **kwargs)


def write_csv(path, rows, fields, private=False):
    opener = open_private if private else open
    with opener(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, '') for k in fields})


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        return [{k: (v or '') for k, v in row.items()} for row in csv.DictReader(f)]


def slack_file_url(url):
    """True only for https://files.slack.com/... — the one host that may
    receive the Slack token when downloading (spec §5; plan 5)."""
    from urllib.parse import urlsplit
    try:
        parts = urlsplit(url or '')
        return parts.scheme == 'https' and parts.hostname == 'files.slack.com' and parts.port is None
    except ValueError:
        return False


def load_env_file(path, key):
    """Read KEY=VALUE from a file only its owner can read. Refuses group- or
    world-readable files so a token is never left exposed."""
    mode = stat.S_IMODE(os.stat(path).st_mode)
    if mode & 0o077:
        raise MigrationError(f'{path} must be mode 600 (is {oct(mode)})')
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            if k.strip() == key:
                v = v.strip().strip('"').strip("'")
                if v:
                    return v
    raise MigrationError(f'{key} not found in {path}')


def load_chat_users(path):
    """`mmctl --local user list --all --json` output: a JSON array of users."""
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise MigrationError(f'{path}: expected a JSON array of users')
    return [u for u in data if isinstance(u, dict) and u.get('username')]


def load_chat_channels(path):
    """`mmctl --local channel list ifl` output: one channel per line, with an
    optional ' (archived)' or ' (private)' suffix."""
    names = set()
    with open(path, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('There are '):
                names.add(line.split(' ', 1)[0])
    return names


def resolve_identities(rows, chat_users):
    """Final chat identity for every human Slack user in identity_map.csv.

    Returns {slack_id: {...}}. A row is linked to a site account only when
    `confirmed` is `yes` and it has a site_id. A linked member who already has
    a chat account keeps that account's username and email (the import then
    matches it by auth data and changes nothing about it). Everyone else keeps
    their Slack username unless `mm_username_override` is set; unlinked people
    get a placeholder email and are imported deactivated. So does a confirmed
    row whose site_member is `no:unverified_email` (flagged `unverified_email`).
    """
    chat_by_name = {u['username'].lower(): u for u in chat_users}
    chat_by_email = {(u.get('email') or '').lower(): u for u in chat_users if u.get('email')}
    out, errors, seen, seen_auth = {}, [], {}, {}
    for row in rows:
        if row['is_bot'] == 'true':
            continue
        sid = row['slack_id']
        linked = row['confirmed'].strip().lower() == 'yes' and row['site_id'].strip() != ''
        # slack-match writes `no:unverified_email` when the site email is not
        # verified. Linking would give that unverified address to a chat
        # account (and sign-in by site id), so such a row imports unmatched,
        # deactivated, under the placeholder email; link-slack-user links it
        # once the member verifies. An existing chat account cannot be
        # unlinked by the import, so that case stops here instead.
        unverified = linked and row['site_member'].strip() == 'no:unverified_email'
        if unverified and row['chat_username']:
            errors.append(f'{sid}: site user {row["site_id"].strip()} has an unverified email but '
                          f'already has chat account {row["chat_username"]!r}; resolve it by hand '
                          'before the import')
            continue
        if unverified:
            linked = False
        override = row['mm_username_override'].strip().lower()
        if linked and row['chat_username']:
            ident = {
                'username': row['chat_username'].lower(),
                'email': row['chat_email'].lower(),
                'auth_data': row['site_id'].strip(),
                'active': row['site_member'] == 'yes',
                'existing': True,
            }
        elif linked:
            ident = {
                'username': override or row['slack_username'].lower(),
                'email': row['site_email'].lower(),
                'auth_data': row['site_id'].strip(),
                'active': row['site_member'] == 'yes',
                'existing': False,
            }
        else:
            ident = {
                'username': override or row['slack_username'].lower(),
                'email': placeholder_email(sid),
                'auth_data': None,
                'active': False,
                'existing': False,
            }
        ident['slack_id'] = sid
        if unverified:
            ident['unverified_email'] = True
        name = ident['username']
        if ident['existing']:
            # The import re-links an account whose auth data differs, and
            # revokes its sessions, so an existing account must already be
            # this site user's gitlab account.
            acct = chat_by_name.get(name)
            if acct is None:
                errors.append(f'{sid}: chat account {name!r} is not in the chat snapshot')
            elif (acct.get('auth_service') != 'gitlab'
                  or str(acct.get('auth_data') or '') != ident['auth_data']):
                errors.append(
                    f'{sid}: chat account {name!r} is not the gitlab account for site user '
                    f'{ident["auth_data"]} (auth_service/auth_data differ); fix the identity row')
        if not valid_username(name):
            errors.append(f'{sid}: username {name!r} is not a valid chat username; set mm_username_override')
        if name in seen:
            errors.append(f'{sid}: username {name!r} is also used by {seen[name]}; set mm_username_override')
        seen[name] = sid
        if ident['auth_data']:
            if ident['auth_data'] in seen_auth:
                errors.append(f'{sid}: site user {ident["auth_data"]} is also matched to '
                              f'{seen_auth[ident["auth_data"]]}; confirm only one')
            seen_auth[ident['auth_data']] = sid
        holder = chat_by_name.get(name)
        if holder is not None and not (ident['existing'] and holder['username'].lower() == name):
            errors.append(
                f'{sid}: username {name!r} already belongs to chat account {holder["username"]!r}; '
                'confirm the match or set mm_username_override')
        email_holder = chat_by_email.get(ident['email'])
        if email_holder is not None and not (
                ident['existing'] and email_holder['username'].lower() == name):
            errors.append(f'{sid}: email for {name!r} already belongs to chat account '
                          f'{email_holder["username"]!r}')
        out[sid] = ident
    if errors:
        raise MigrationError('identity problems:\n  ' + '\n  '.join(errors))
    return out
