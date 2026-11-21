"""Import the Slack workspace's custom emoji into IFL Chat (league chat spec §5).

  import_emoji.py --slack-env ~/.config/ifl-migration/slack.env \\
      --chat-url https://chat.iflgm.com --chat-env ~/.config/ifl-migration/ifl-bot.env \\
      --system-emoji server/public/model/emoji_data.go --out-dir DIR [--dry-run]

1. Fetches Slack `emoji.list` (needs `emoji:read`).
2. Downloads every image, including animated GIFs.
3. Resolves aliases and alias chains; reports missing targets and cycles.
   An alias of a Slack built-in emoji maps to the chat built-in of the same
   name when chat has one, and is not uploaded.
4. Gives each alias its own custom emoji using the resolved image.
5. Normalizes names (lower case; characters other than a-z 0-9 _ - + become
   `_`; at most 64). A name chat already uses for a built-in emoji gets
   `_ifl`; remaining clashes get `_2`, `_3`, ... in sorted Slack-name order.
6. Writes emoji_map.csv and emoji_report.md in --out-dir.
7. Fits images to the server's limits (server/channels/app/emoji.go:33-38):
   512 KiB, 128 x 128 stored size, 70 GIF frames. An image already within
   the limits is uploaded byte for byte. Dropped frames are reported as
   "simplified"; an animation reduced to one frame is reported as
   "flattened" (this includes animated PNG and WebP, which are never left
   animated when they must be re-encoded). A GIF re-encoded only to get under
   512 KiB is reported as "simplified" with a note.
8. Uploads with POST /api/v4/emoji as the IFL bot.
9. A rerun compares an existing chat emoji's stored image with the prepared
   image: equal means "unchanged"; different means "failed" (never
   overwritten).
10. Re-import (--prior-map FIRST_RUN/emoji_map.csv): every Slack name the
   first run named keeps that chat name, and new emoji never take one of
   them, so a new emoji cannot shift the `_2`, `_3` numbering of old ones.
Tokens are read from mode-600 files, never from the command line. The Slack
token is sent only to https://slack.com/api/emoji.list; emoji images are
fetched from *.slack-edge.com without it; the bot token only to the two IFL
Chat URLs. No request follows a redirect.
"""
import argparse
import hashlib
import io
import json
import math
import os
import re
import sys
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # run with python -I
from common import MigrationError, load_env_file, read_csv, write_csv  # noqa: E402

MAX_BYTES = 512 * 1024
MAX_SIDE = 128
MAX_FRAMES = 70
NAME_MAX = 64
MAP_FIELDS = ['slack_name', 'kind', 'target', 'mm_name', 'status', 'renamed', 'resized',
              'simplified', 'sha256', 'note']
SLACK_IMAGE_HOST_SUFFIX = '.slack-edge.com'   # emoji images; fetched without any token
CHAT_URLS = ('https://chat.iflgm.com', 'https://chat-staging.iflgm.com')


# ---------------------------------------------------------------- names

def normalize(name):
    n = re.sub(r'[^a-z0-9_+\-]', '_', name.lower())[:NAME_MAX]
    return n or 'emoji'


def resolve(raw, system):
    """raw: Slack emoji.list {name: url | 'alias:target'}.
    Returns entries sorted by Slack name:
      {'slack_name', 'kind': custom|alias|alias-to-system|failed, 'target', 'url', 'note'}"""
    out = []
    for name in sorted(raw):
        value = raw[name]
        if not value.startswith('alias:'):
            out.append({'slack_name': name, 'kind': 'custom', 'target': '', 'url': value, 'note': ''})
            continue
        chain, cur = [name], value[len('alias:'):]
        while True:
            if cur in chain:
                out.append({'slack_name': name, 'kind': 'failed', 'target': cur, 'url': '',
                            'note': 'alias cycle: ' + ' -> '.join(chain + [cur])})
                break
            if cur not in raw:
                if cur in system:
                    out.append({'slack_name': name, 'kind': 'alias-to-system', 'target': cur,
                                'url': '', 'note': ''})
                else:
                    out.append({'slack_name': name, 'kind': 'failed', 'target': cur, 'url': '',
                                'note': f'alias target {cur} does not exist'})
                break
            if not raw[cur].startswith('alias:'):
                out.append({'slack_name': name, 'kind': 'alias', 'target': cur, 'url': raw[cur],
                            'note': '' if len(chain) == 1 else 'alias chain: ' + ' -> '.join(chain + [cur])})
                break
            chain.append(cur)
            cur = raw[cur][len('alias:'):]
    return out


def assign_names(entries, system, prior=None):
    """Set entry['mm_name'] and entry['renamed'] deterministically. prior
    (re-import): {slack_name: mm_name} from the first run's map; those names
    are kept and reserved."""
    prior = prior or {}
    used = set(prior.values())
    for e in entries:
        if e['kind'] in ('alias-to-system', 'failed') or e['slack_name'] not in prior:
            continue
        e['mm_name'] = prior[e['slack_name']]
        e['renamed'] = 'yes' if e['mm_name'] != e['slack_name'] else 'no'
    for e in entries:
        if e.get('mm_name') and e['kind'] not in ('alias-to-system', 'failed'):
            continue
        if e['kind'] == 'alias-to-system':
            e['mm_name'], e['renamed'] = e['target'], 'yes'
            continue
        if e['kind'] == 'failed':
            e['mm_name'], e['renamed'] = '', 'no'
            continue
        base = normalize(e['slack_name'])
        if base in system:
            base = base[:NAME_MAX - 4] + '_ifl'
        name, n = base, 2
        while name in used or name in system:
            suffix = f'_{n}'
            name = base[:NAME_MAX - len(suffix)] + suffix
            n += 1
        used.add(name)
        e['mm_name'] = name
        e['renamed'] = 'yes' if name != e['slack_name'] else 'no'
    return entries


# ---------------------------------------------------------------- images

def process_image(data):
    """Return (bytes, extension, flags) within the server's limits.
    flags ⊆ {'resized', 'simplified', 'flattened', 'reencoded'}. Raises ValueError."""
    from PIL import Image, ImageSequence
    img = Image.open(io.BytesIO(data))
    fmt = (img.format or '').upper()
    frames_total = getattr(img, 'n_frames', 1)
    animated = frames_total > 1
    w, h = img.size
    fits = w <= MAX_SIDE and h <= MAX_SIDE
    if fits and len(data) <= MAX_BYTES and frames_total <= MAX_FRAMES and fmt in ('PNG', 'GIF', 'JPEG'):
        return data, {'PNG': 'png', 'GIF': 'gif', 'JPEG': 'jpg'}[fmt], set()
    flags = set()
    scale = min(1.0, MAX_SIDE / w, MAX_SIDE / h)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    if scale < 1:
        flags.add('resized')
    if not animated or fmt != 'GIF':
        # A still image, or an animated PNG/WebP that cannot be kept as is:
        # it becomes one PNG frame, and the caller is told.
        if animated:
            flags.add('flattened')
        frame = img.convert('RGBA').resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        frame.save(buf, 'PNG', optimize=True)
        out = buf.getvalue()
        if len(out) > MAX_BYTES:
            raise ValueError(f'{len(out)} bytes after resizing')
        return out, 'png', flags
    frames, durations = [], []
    for f in ImageSequence.Iterator(img):
        frames.append(f.convert('RGBA').resize(size, Image.LANCZOS))
        durations.append(f.info.get('duration', img.info.get('duration', 100)) or 100)
    loop = img.info.get('loop')   # None: the source has no loop extension (plays once)
    step = max(1, math.ceil(len(frames) / MAX_FRAMES))
    while True:
        kept = frames[::step]
        kept_d = [sum(durations[i:i + step]) for i in range(0, len(frames), step)]
        buf = io.BytesIO()
        opts = {} if loop is None else {'loop': loop}
        kept[0].save(buf, 'GIF', save_all=len(kept) > 1, append_images=kept[1:],
                     duration=kept_d, disposal=2, **opts)
        out = buf.getvalue()
        if step > 1:
            flags.add('simplified')
        if len(out) <= MAX_BYTES:
            if len(kept) == 1:
                flags.add('flattened')
            if step == 1 and 'resized' not in flags and len(data) > MAX_BYTES:
                flags.add('reencoded')   # same frames, same size: re-encoded only to fit
            return out, 'gif', flags
        if len(kept) == 1:
            raise ValueError(f'{len(out)} bytes even as a single frame')
        step *= 2


# ---------------------------------------------------------------- HTTP

def _new_session(requests):
    s = requests.Session()
    s.trust_env = False   # no proxy, .netrc or CA settings from the environment
    return s


class SlackClient:
    def __init__(self, token, session=None):
        import requests
        self.http = session or _new_session(requests)
        self.token = token

    def emoji_list(self):
        # The token goes to this one fixed Slack API URL only, never to a URL
        # taken from data, and redirects are not followed.
        r = self.http.get('https://slack.com/api/emoji.list', timeout=30, allow_redirects=False,
                          headers={'Authorization': f'Bearer {self.token}'})
        if r.status_code != 200:
            raise MigrationError(f'Slack emoji.list: HTTP {r.status_code}')
        body = r.json()
        if not body.get('ok'):
            raise MigrationError(f'Slack emoji.list failed: {body.get("error")}')
        return body['emoji']

    def image(self, url):
        host = urlsplit(url).hostname or ''
        if urlsplit(url).scheme != 'https' or not host.endswith(SLACK_IMAGE_HOST_SUFFIX):
            raise MigrationError(f'refusing to download emoji from {host}')
        r = self.http.get(url, timeout=30, allow_redirects=False)  # public CDN: no token
        if r.status_code != 200:
            raise MigrationError(f'HTTP {r.status_code}')
        return r.content


class ChatClient:
    def __init__(self, base_url, token, session=None):
        import requests
        if base_url.rstrip('/') not in CHAT_URLS:
            raise MigrationError(f'--chat-url must be one of {", ".join(CHAT_URLS)}')
        self.base = base_url.rstrip('/') + '/api/v4'
        self.http = session or _new_session(requests)
        self.http.headers['Authorization'] = f'Bearer {token}'

    def _ok(self, r, what):
        if r.status_code >= 300:  # includes redirects, which are never followed
            try:
                err = r.json().get('id', '')
            except ValueError:
                err = ''
            raise MigrationError(f'{what}: HTTP {r.status_code} {err}')
        return r

    def me(self):
        return self._ok(self.http.get(self.base + '/users/me', timeout=30, allow_redirects=False),
                        'users/me').json()

    def all_emoji(self):
        out, page = {}, 0
        while True:
            r = self._ok(self.http.get(self.base + '/emoji', params={'page': page, 'per_page': 200, 'sort': 'name'},
                                       timeout=30, allow_redirects=False), 'list emoji')
            batch = r.json()
            for e in batch:
                out[e['name']] = e
            if len(batch) < 200:
                return out
            page += 1

    def emoji_image(self, emoji_id):
        return self._ok(self.http.get(f'{self.base}/emoji/{emoji_id}/image', timeout=30,
                                      allow_redirects=False), 'emoji image').content

    def create_emoji(self, name, creator_id, data, ext):
        files = {'image': (f'{name}.{ext}', data, f'image/{"jpeg" if ext == "jpg" else ext}')}
        form = {'emoji': json.dumps({'name': name, 'creator_id': creator_id})}
        return self._ok(self.http.post(self.base + '/emoji', files=files, data=form, timeout=60,
                                       allow_redirects=False), f'create {name}').json()


# ---------------------------------------------------------------- driver

def _reason(err):
    """A short failure reason that cannot carry a token: our own errors carry
    only status codes and names; library errors are reduced to their class."""
    from PIL import Image
    if isinstance(err, MigrationError):
        return str(err)
    if isinstance(err, Image.DecompressionBombError):
        return 'image too large (decompression bomb)'
    if isinstance(err, ValueError):
        return f'image: {err}'
    return f'{type(err).__name__}'


def _entry_errors():
    import requests
    from PIL import Image
    return (MigrationError, ValueError, OSError, EOFError, SyntaxError,
            Image.DecompressionBombError, requests.RequestException)


def _add_note(e, text):
    e['note'] = (e['note'] + '; ' if e['note'] else '') + text


def _import_one(e, slack, chat, existing, creator, dry_run, images):
    if e['url'] not in images:
        images[e['url']] = process_image(slack.image(e['url']))
    data, ext, flags = images[e['url']]
    e['resized'] = 'yes' if 'resized' in flags else 'no'
    e['simplified'] = 'yes' if flags & {'simplified', 'flattened', 'reencoded'} else 'no'
    if 'flattened' in flags:
        _add_note(e, 'animation reduced to one frame')
    if 'reencoded' in flags:
        _add_note(e, 're-encoded to fit 512 KiB')
    e['sha256'] = hashlib.sha256(data).hexdigest()
    have = existing.get(e['mm_name'])
    if have is not None:
        stored = hashlib.sha256(chat.emoji_image(have['id'])).hexdigest()
        if stored == e['sha256']:
            e['status'] = 'unchanged'
        else:
            e['status'] = 'failed'
            _add_note(e, 'name already used by a different image')
        return
    if dry_run:
        e['status'] = 'would import'
        return
    chat.create_emoji(e['mm_name'], creator, data, ext)
    e['status'] = 'imported'


def load_prior_names(path):
    """{slack_name: mm_name} for the custom emoji and aliases a first run named."""
    return {r['slack_name']: r['mm_name'] for r in read_csv(path)
            if r['mm_name'] and r['kind'] in ('custom', 'alias')}


def run(slack, chat, system, dry_run=False, prior=None):
    """One emoji's failure (network, bad image, 429/5xx) becomes a `failed`
    row; it never stops the others."""
    entries = assign_names(resolve(slack.emoji_list(), system), system, prior)
    existing = chat.all_emoji() if chat else {}
    creator = chat.me()['id'] if chat and not dry_run else ''
    images = {}
    errors = _entry_errors()
    for e in entries:
        e.update(status='', resized='no', simplified='no', sha256='')
        if e['kind'] == 'failed':
            e['status'] = 'failed'
            continue
        if e['kind'] == 'alias-to-system':
            e['status'] = 'built-in'
            continue
        try:
            _import_one(e, slack, chat, existing, creator, dry_run, images)
        except errors as err:
            e['status'] = 'failed'
            _add_note(e, _reason(err))
    return entries


def report(entries):
    def count(**kw):
        return sum(1 for e in entries if all(e[k] == v for k, v in kw.items()))
    lines = ['# Emoji import report', '',
             f'- Slack emoji: {len(entries)}',
             f'- imported: {count(status="imported")}',
             f'- unchanged (already in chat): {count(status="unchanged")}',
             f'- would import (dry run): {count(status="would import")}',
             f'- aliases of built-in emoji (not uploaded): {count(status="built-in")}',
             f'- renamed: {count(renamed="yes")}',
             f'- resized: {count(resized="yes")}',
             f'- animation simplified or re-encoded: {count(simplified="yes")}',
             f'- animation flattened to one frame: {sum(1 for e in entries if "one frame" in e["note"])}',
             f'- failed: {count(status="failed")}', '', '## Failed and simplified', '']
    for e in entries:
        if e['status'] == 'failed' or e['simplified'] == 'yes':
            lines.append(f'- `{e["slack_name"]}` -> `{e["mm_name"]}`: {e["status"]} {e["note"]}')
    return lines


def load_system_emoji(path):
    with open(path, encoding='utf-8') as f:
        return set(re.findall(r'^\s*"([^"]+)":\s*"', f.read(), re.M))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--slack-env', required=True, help='mode-600 file with SLACK_API_TOKEN=')
    ap.add_argument('--chat-url', required=True)
    ap.add_argument('--chat-env', required=True, help='mode-600 file with IFL_BOT_TOKEN=')
    ap.add_argument('--system-emoji', required=True, help='server/public/model/emoji_data.go')
    ap.add_argument('--out-dir', required=True)
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--prior-map', help="re-import: the first run's emoji_map.csv (its names are kept)")
    a = ap.parse_args(argv)
    try:
        prior = load_prior_names(a.prior_map) if a.prior_map else None
        slack = SlackClient(load_env_file(a.slack_env, 'SLACK_API_TOKEN'))
        chat = ChatClient(a.chat_url, load_env_file(a.chat_env, 'IFL_BOT_TOKEN'))
        entries = run(slack, chat, load_system_emoji(a.system_emoji), a.dry_run, prior)
    except MigrationError as e:
        print(f'error: {e}', file=sys.stderr)
        return 2
    except _entry_errors()[-1] as e:   # requests.RequestException: no message, it could echo a URL
        print(f'error: {type(e).__name__} talking to Slack or chat', file=sys.stderr)
        return 2
    os.makedirs(a.out_dir, exist_ok=True)
    write_csv(os.path.join(a.out_dir, 'emoji_map.csv'), entries, MAP_FIELDS)
    lines = report(entries)
    with open(os.path.join(a.out_dir, 'emoji_report.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[:12]))
    return 1 if any(e['status'] == 'failed' for e in entries) else 0


if __name__ == '__main__':
    sys.exit(main())
