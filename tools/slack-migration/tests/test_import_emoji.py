import hashlib
import io
import json
import random

import pytest
import requests

from PIL import Image

import import_emoji as ie

SYSTEM = {'+1', 'thumbsup', 'smile'}


def png(w, h, color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new('RGBA', (w, h), color).save(buf, 'PNG')
    return buf.getvalue()


def gif(frames, side=32, **kw):
    kw.setdefault('loop', 0)
    imgs = [Image.new('RGB', (side, side), (i * 3 % 256, 0, 0)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, 'GIF', save_all=True, append_images=imgs[1:], duration=50, **kw)
    return buf.getvalue()


def noisy_gif(frames, side=128):
    rnd = random.Random(1)
    imgs = [Image.frombytes('RGB', (side, side), rnd.randbytes(side * side * 3)) for _ in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, 'GIF', save_all=True, append_images=imgs[1:], duration=50, loop=0)
    return buf.getvalue()


def gradient_gif(frames, side=128):
    imgs = []
    for i in range(frames):
        im = Image.new('RGB', (side, side))
        px = im.load()
        for x in range(side):
            for y in range(side):
                px[x, y] = ((x * 2 + i * 4) % 256, (y * 2) % 256, (x + y + i) % 256)
        imgs.append(im)
    buf = io.BytesIO()
    imgs[0].save(buf, 'GIF', save_all=True, append_images=imgs[1:], duration=50, loop=0)
    return buf.getvalue()


def apng(frames, side=300):
    imgs = [Image.new('RGBA', (side, side), (i * 40 % 256, 0, 0, 255)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, 'PNG', save_all=True, append_images=imgs[1:], duration=50, loop=0)
    return buf.getvalue()


def webp(frames, side=32):
    imgs = [Image.new('RGBA', (side, side), (i * 40 % 256, 0, 0, 255)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, 'WEBP', save_all=True, append_images=imgs[1:], duration=50, lossless=True)
    return buf.getvalue()


def test_resolve_aliases():
    raw = {'parrot': 'https://emoji.slack-edge.com/T/parrot/a.gif',
           'pp': 'alias:parrot', 'ppp': 'alias:pp',
           'yes': 'alias:thumbsup', 'loop1': 'alias:loop2', 'loop2': 'alias:loop1',
           'ghost': 'alias:nothing'}
    out = {e['slack_name']: e for e in ie.resolve(raw, SYSTEM)}
    assert out['pp']['kind'] == 'alias' and out['pp']['url'].endswith('a.gif')
    assert out['ppp']['kind'] == 'alias' and out['ppp']['target'] == 'parrot'
    assert 'alias chain' in out['ppp']['note']
    assert out['yes']['kind'] == 'alias-to-system' and out['yes']['target'] == 'thumbsup'
    assert out['loop1']['kind'] == 'failed' and 'cycle' in out['loop1']['note']
    assert out['ghost']['kind'] == 'failed' and 'does not exist' in out['ghost']['note']


def test_assign_names():
    raw = {'smile': 'https://emoji.slack-edge.com/a.png', 'Big.Deal': 'https://emoji.slack-edge.com/b.png',
           'big_deal': 'https://emoji.slack-edge.com/c.png', 'yes': 'alias:thumbsup'}
    out = {e['slack_name']: e for e in ie.assign_names(ie.resolve(raw, SYSTEM), SYSTEM)}
    assert out['smile']['mm_name'] == 'smile_ifl'          # chat has a built-in :smile:
    assert out['Big.Deal']['mm_name'] == 'big_deal'
    assert out['big_deal']['mm_name'] == 'big_deal_2'
    assert out['yes']['mm_name'] == 'thumbsup'
    again = {e['slack_name']: e['mm_name'] for e in ie.assign_names(ie.resolve(raw, SYSTEM), SYSTEM)}
    assert again == {k: v['mm_name'] for k, v in out.items()}   # deterministic


def test_small_images_pass_through_unchanged():
    data = png(64, 64)
    assert ie.process_image(data) == (data, 'png', set())
    g = gif(10)
    assert ie.process_image(g) == (g, 'gif', set())


def test_large_png_is_resized():
    out, ext, flags = ie.process_image(png(400, 200))
    assert ext == 'png' and flags == {'resized'}
    assert Image.open(io.BytesIO(out)).size == (128, 64)


def test_long_gif_keeps_animation_within_frame_limit():
    out, ext, flags = ie.process_image(gif(150))
    img = Image.open(io.BytesIO(out))
    assert ext == 'gif' and 'simplified' in flags and 'flattened' not in flags
    assert 1 < img.n_frames <= ie.MAX_FRAMES


class FakeSlack:
    def __init__(self, raw, images):
        self.raw, self.images = raw, images

    def emoji_list(self):
        return self.raw

    def image(self, url):
        return self.images[url]


class FakeChat:
    def __init__(self):
        self.emoji, self.images, self.created = {}, {}, []

    def me(self):
        return {'id': 'bot1'}

    def all_emoji(self):
        return dict(self.emoji)

    def emoji_image(self, emoji_id):
        return self.images[emoji_id]

    def create_emoji(self, name, creator_id, data, ext):
        eid = f'e{len(self.created)}'
        self.emoji[name] = {'id': eid, 'name': name, 'creator_id': creator_id}
        self.images[eid] = data
        self.created.append((name, creator_id, ext))
        return self.emoji[name]


def test_run_imports_then_rerun_is_unchanged():
    a, b = png(16, 16), png(16, 16, (0, 255, 0, 255))
    slack = FakeSlack({'parrot': 'u1', 'pp': 'alias:parrot', 'yes': 'alias:thumbsup', 'blob': 'u2'},
                      {'u1': a, 'u2': b})
    chat = FakeChat()
    first = {e['slack_name']: e for e in ie.run(slack, chat, SYSTEM)}
    assert sorted(chat.created) == [('blob', 'bot1', 'png'), ('parrot', 'bot1', 'png'), ('pp', 'bot1', 'png')]
    assert first['yes']['status'] == 'built-in'
    assert first['parrot']['sha256'] == hashlib.sha256(a).hexdigest()
    second = {e['slack_name']: e['status'] for e in ie.run(slack, chat, SYSTEM)}
    assert second == {'blob': 'unchanged', 'parrot': 'unchanged', 'pp': 'unchanged', 'yes': 'built-in'}
    assert len(chat.created) == 3


def test_run_never_overwrites_a_different_image():
    chat = FakeChat()
    chat.create_emoji('parrot', 'someone', png(8, 8), 'png')
    slack = FakeSlack({'parrot': 'u1'}, {'u1': png(16, 16)})
    [e] = ie.run(slack, chat, SYSTEM)
    assert e['status'] == 'failed' and 'different image' in e['note']
    assert len(chat.created) == 1


def test_dry_run_uploads_nothing():
    chat = FakeChat()
    [e] = ie.run(FakeSlack({'parrot': 'u1'}, {'u1': png(8, 8)}), chat, SYSTEM, dry_run=True)
    assert e['status'] == 'would import' and chat.created == []


def test_slack_image_host_is_checked():
    from common import MigrationError
    with pytest.raises(MigrationError, match='refusing'):
        ie.SlackClient('t', session=object()).image('https://evil.example/x.png')


class RecordingSession:
    def __init__(self, status=200, body=None):
        self.calls, self.headers = [], {}
        self.status, self.body = status, body or {'ok': True, 'emoji': {}}

    def get(self, url, **kw):
        self.calls.append((url, kw))

        class R:
            status_code = self.status
            content = b'x'

            def json(r):
                return self.body
        return R()


def test_slack_token_goes_only_to_the_api_and_never_follows_redirects():
    s = RecordingSession()
    c = ie.SlackClient('xoxp-secret', session=s)
    c.emoji_list()
    c.image('https://emoji.slack-edge.com/T1/parrot/abc.gif')
    (api_url, api_kw), (img_url, img_kw) = s.calls
    assert api_url == 'https://slack.com/api/emoji.list' and api_kw['allow_redirects'] is False
    assert api_kw['headers']['Authorization'] == 'Bearer xoxp-secret'
    assert 'headers' not in img_kw and img_kw['allow_redirects'] is False
    assert s.headers == {}


def test_chat_url_must_be_an_ifl_chat_host():
    from common import MigrationError
    with pytest.raises(MigrationError, match='--chat-url must be one of'):
        ie.ChatClient('https://chat.example.org', 't', session=RecordingSession())
    ie.ChatClient('https://chat-staging.iflgm.com/', 't', session=RecordingSession())


# ------------------------------------------------------------ review round 1

from common import MigrationError, read_csv  # noqa: E402


class FakeResponse(requests.Response):
    def __init__(self, status=200, body=b'{}'):
        super().__init__()
        self.status_code = status
        self._content = body if isinstance(body, bytes) else json.dumps(body).encode()


class CapturingSession(requests.Session):
    """A real Session (real header, multipart and query building) whose
    network send is replaced by a canned reply."""

    def __init__(self, reply):
        super().__init__()
        self.reply, self.sent = reply, []

    def send(self, request, **kw):
        self.sent.append((request, kw))
        return self.reply(request) if callable(self.reply) else self.reply


def chat_with(reply):
    s = CapturingSession(reply)
    return ie.ChatClient('https://chat.iflgm.com', 'bot-token', session=s), s


def test_all_emoji_asks_for_name_order_and_pages_past_200():
    from urllib.parse import parse_qs, urlsplit
    names = [f'e{i:04d}' for i in range(450)]
    calls = []

    def reply(req):
        q = parse_qs(urlsplit(req.url).query)
        calls.append(q)
        order = list(names)
        if q.get('sort') != ['name']:
            random.Random(len(calls)).shuffle(order)   # the server's unsorted order is arbitrary
        page, per = int(q['page'][0]), int(q['per_page'][0])
        return FakeResponse(200, [{'id': n, 'name': n} for n in order[page * per:(page + 1) * per]])
    chat, _ = chat_with(reply)
    assert sorted(chat.all_emoji()) == names
    assert len(calls) == 3 and all(q['sort'] == ['name'] for q in calls)


@pytest.mark.parametrize('call', [
    lambda c: c.me(), lambda c: c.all_emoji(), lambda c: c.emoji_image('x'),
    lambda c: c.create_emoji('a', 'u', b'1', 'png')])
def test_chat_client_treats_a_redirect_as_an_error(call):
    chat, s = chat_with(FakeResponse(302, b''))
    with pytest.raises(MigrationError, match='HTTP 302'):
        call(chat)
    assert s.sent[0][1]['allow_redirects'] is False


def test_chat_upload_is_multipart_with_image_content_type():
    chat, s = chat_with(FakeResponse(201, {'id': 'e1'}))
    chat.create_emoji('parrot', 'bot1', b'GIF89a-bytes', 'gif')
    chat.create_emoji('pic', 'bot1', b'jpegbytes', 'jpg')
    (req, kw), (req2, _) = s.sent
    assert req.method == 'POST' and req.url == 'https://chat.iflgm.com/api/v4/emoji'
    assert req.headers['Authorization'] == 'Bearer bot-token'
    assert req.headers['Content-Type'].startswith('multipart/form-data; boundary=')
    body = req.body
    assert b'name="image"; filename="parrot.gif"' in body and b'Content-Type: image/gif' in body
    assert b'GIF89a-bytes' in body and b'name="emoji"' in body
    assert b'"creator_id": "bot1"' in body and b'"name": "parrot"' in body
    assert b'filename="pic.jpg"' in req2.body and b'Content-Type: image/jpeg' in req2.body
    assert kw['allow_redirects'] is False


def test_sessions_ignore_the_environment():
    assert ie.SlackClient('t').http.trust_env is False
    assert ie.ChatClient('https://chat.iflgm.com', 't').http.trust_env is False


def test_apng_that_needs_resizing_is_flagged_flattened():
    out, ext, flags = ie.process_image(apng(3))
    assert ext == 'png' and flags == {'resized', 'flattened'}
    img = Image.open(io.BytesIO(out))
    assert img.size == (128, 128) and getattr(img, 'n_frames', 1) == 1


def test_animated_webp_is_never_silently_flattened():
    out, ext, flags = ie.process_image(webp(3))
    assert 'flattened' in flags and ext == 'png'


def test_apng_within_limits_passes_through():
    data = apng(3, side=64)
    assert ie.process_image(data) == (data, 'png', set())


def test_run_reports_flattened_note_and_simplified():
    chat = FakeChat()
    [e] = ie.run(FakeSlack({'spin': 'u'}, {'u': apng(3)}), chat, SYSTEM)
    assert e['status'] == 'imported' and e['simplified'] == 'yes' and e['resized'] == 'yes'
    assert 'animation reduced to one frame' in e['note']
    assert any('spin' in line and 'one frame' in line for line in ie.report([e]))


def test_gif_over_512_kib_drops_frames_and_is_reported():
    data = noisy_gif(45)
    assert len(data) > ie.MAX_BYTES
    out, ext, flags = ie.process_image(data)
    assert ext == 'gif' and len(out) <= ie.MAX_BYTES
    assert 'simplified' in flags and 'flattened' not in flags


def test_gif_reencoded_only_to_fit_512_kib_is_flagged():
    data = gradient_gif(60)
    data += b'\0' * (ie.MAX_BYTES - len(data) + 1000)    # trailing junk: a bulky but valid GIF
    assert len(data) > ie.MAX_BYTES
    out, ext, flags = ie.process_image(data)
    assert ext == 'gif' and len(out) <= ie.MAX_BYTES
    assert Image.open(io.BytesIO(out)).n_frames == 60
    assert flags == {'reencoded'}
    chat = FakeChat()
    [e] = ie.run(FakeSlack({'big': 'u'}, {'u': data}), chat, SYSTEM)
    assert e['simplified'] == 'yes' and 're-encoded' in e['note']


def test_gif_loop_behaviour_is_preserved():
    for loop in (0, 3):
        out, _, flags = ie.process_image(gif(150, loop=loop))
        assert 'simplified' in flags and Image.open(io.BytesIO(out)).info['loop'] == loop
    out, _, flags = ie.process_image(gif(150, loop=None))   # no loop extension: plays once
    assert 'simplified' in flags and 'loop' not in Image.open(io.BytesIO(out)).info


@pytest.mark.parametrize('url', ['https://evilslack-edge.com/x', 'http://emoji.slack-edge.com/x',
                                 'https://user@evil.example/x', 'https://slack-edge.com.evil.example/x'])
def test_slack_image_host_check_rejects_lookalikes(url):
    s = RecordingSession()
    with pytest.raises(MigrationError, match='refusing'):
        ie.SlackClient('t', session=s).image(url)
    assert s.calls == []


def test_collision_with_existing_custom_emoji():
    chat = FakeChat()
    chat.create_emoji('parrot', 'someone', png(8, 8), 'png')
    slack = FakeSlack({'Parrot': 'u1', 'blob': 'u2'}, {'u1': png(16, 16), 'u2': png(8, 8)})
    out = {e['slack_name']: e for e in ie.run(slack, chat, SYSTEM)}
    assert out['Parrot']['mm_name'] == 'parrot' and out['Parrot']['status'] == 'failed'
    assert 'different image' in out['Parrot']['note']
    assert out['blob']['status'] == 'imported'
    assert [c[0] for c in chat.created] == ['parrot', 'blob']   # parrot only from the setup


class Boom(Exception):
    pass


@pytest.mark.parametrize('make', [
    lambda: requests.ConnectionError('dns xoxp-SECRET'),
    lambda: requests.Timeout('slow xoxp-SECRET'),
    lambda: MigrationError('HTTP 503'),
])
def test_one_bad_download_does_not_abort_the_run(make):
    class Slack(FakeSlack):
        def image(self, url):
            if url == 'bad':
                raise make()
            return super().image(url)
    chat = FakeChat()
    out = {e['slack_name']: e for e in ie.run(Slack({'a': 'bad', 'b': 'ok'}, {'ok': png(8, 8)}), chat, SYSTEM)}
    assert out['a']['status'] == 'failed' and out['b']['status'] == 'imported'
    assert 'xoxp-SECRET' not in out['a']['note'] and out['a']['note']


def test_decompression_bomb_is_a_failed_row(monkeypatch):
    monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 10)
    chat = FakeChat()
    [e] = ie.run(FakeSlack({'bomb': 'u'}, {'u': png(100, 100)}), chat, SYSTEM)
    assert e['status'] == 'failed' and 'too large' in e['note'] and chat.created == []


@pytest.mark.parametrize('status', [429, 500, 503])
def test_existing_image_fetch_error_is_a_failed_row(status):
    class Chat(FakeChat):
        def emoji_image(self, emoji_id):
            raise MigrationError(f'emoji image: HTTP {status} ')
    chat = Chat()
    chat.create_emoji('a', 'x', png(8, 8), 'png')
    slack = FakeSlack({'a': 'u1', 'b': 'u2'}, {'u1': png(8, 8), 'u2': png(9, 9)})
    out = {e['slack_name']: e for e in ie.run(slack, chat, SYSTEM)}
    assert out['a']['status'] == 'failed' and str(status) in out['a']['note']
    assert out['b']['status'] == 'imported'


def test_upload_transport_error_is_a_failed_row():
    class Chat(FakeChat):
        def create_emoji(self, name, creator_id, data, ext):
            if name == 'a':
                raise requests.ConnectionError('reset by xoxp-SECRET')
            return super().create_emoji(name, creator_id, data, ext)
    out = {e['slack_name']: e for e in ie.run(
        FakeSlack({'a': 'u', 'b': 'u'}, {'u': png(8, 8)}), Chat(), SYSTEM)}
    assert out['a']['status'] == 'failed' and 'ConnectionError' in out['a']['note']
    assert 'xoxp-SECRET' not in out['a']['note'] and out['b']['status'] == 'imported'


# ---------------------------------------------------------------- main()

SLACK_TOKEN, BOT_TOKEN = 'xoxp-SLACKSECRET', 'botSECRET99'


@pytest.fixture
def cli(tmp_path, monkeypatch):
    def env(name, key, value):
        p = tmp_path / name
        p.write_text(f'{key}={value}\n')
        p.chmod(0o600)
        return str(p)
    system = tmp_path / 'emoji_data.go'
    system.write_text('\t"smile": "1f604",\n\t"thumbsup": "1f44d",\n')
    out_dir = tmp_path / 'deep' / 'out'

    def go(slack, chat, *extra):
        monkeypatch.setattr(ie, 'SlackClient', lambda token: slack)
        monkeypatch.setattr(ie, 'ChatClient', lambda url, token: chat)
        argv = ['--slack-env', env('s.env', 'SLACK_API_TOKEN', SLACK_TOKEN), '--chat-url',
                'https://chat.iflgm.com', '--chat-env', env('c.env', 'IFL_BOT_TOKEN', BOT_TOKEN),
                '--system-emoji', str(system), '--out-dir', str(out_dir), *extra]
        return ie.main(argv), out_dir
    return go


def test_main_exit_0_and_creates_out_dir(cli):
    code, out_dir = cli(FakeSlack({'a': 'u'}, {'u': png(8, 8)}), FakeChat())
    assert code == 0
    assert [r['status'] for r in read_csv(out_dir / 'emoji_map.csv')] == ['imported']


def test_main_failed_row_reaches_csv_and_exits_1(cli):
    slack = FakeSlack({'x': 'alias:y', 'y': 'alias:x', 'ok': 'u'}, {'u': png(8, 8)})
    code, out_dir = cli(slack, FakeChat())
    rows = {r['slack_name']: r for r in read_csv(out_dir / 'emoji_map.csv')}
    assert code == 1 and rows['x']['kind'] == 'failed' and rows['x']['status'] == 'failed'
    assert rows['ok']['status'] == 'imported'
    assert 'cycle' in rows['x']['note'] and (out_dir / 'emoji_report.md').exists()


def test_main_exits_2_on_a_fatal_error_and_writes_nothing(cli, capsys):
    class Slack(FakeSlack):
        def emoji_list(self):
            raise MigrationError('Slack emoji.list: HTTP 401')
    code, out_dir = cli(Slack({}, {}), FakeChat())
    assert code == 2 and 'HTTP 401' in capsys.readouterr().err and not out_dir.exists()


def test_main_exits_2_when_slack_is_unreachable(cli, capsys):
    class Slack(FakeSlack):
        def emoji_list(self):
            raise requests.ConnectionError(f'cannot reach {SLACK_TOKEN}')
    code, _ = cli(Slack({}, {}), FakeChat())
    captured = capsys.readouterr()
    assert code == 2 and SLACK_TOKEN not in captured.err + captured.out


def test_outputs_never_contain_token_text(cli, capsys):
    class Slack(FakeSlack):
        def image(self, url):
            if url == 'bad':
                raise requests.ConnectionError(f'{SLACK_TOKEN} {BOT_TOKEN}')
            return super().image(url)

    class Chat(FakeChat):
        def create_emoji(self, name, creator_id, data, ext):
            if name == 'c':
                raise requests.Timeout(BOT_TOKEN)
            return super().create_emoji(name, creator_id, data, ext)
    slack = Slack({'a': 'bad', 'b': 'u', 'c': 'u'}, {'u': png(8, 8)})
    code, out_dir = cli(slack, Chat())
    captured = capsys.readouterr()
    text = captured.out + captured.err
    for f in out_dir.iterdir():
        text += f.read_text()
    assert code == 1 and SLACK_TOKEN not in text and BOT_TOKEN not in text
    assert [r['status'] for r in read_csv(out_dir / 'emoji_map.csv')] == ['failed', 'imported', 'failed']
