import hashlib
import io

from PIL import Image

import import_emoji as ie

SYSTEM = {'+1', 'thumbsup', 'smile'}


def png(w, h, color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new('RGBA', (w, h), color).save(buf, 'PNG')
    return buf.getvalue()


def gif(frames, side=32):
    imgs = [Image.new('RGB', (side, side), (i * 3 % 256, 0, 0)) for i in range(frames)]
    buf = io.BytesIO()
    imgs[0].save(buf, 'GIF', save_all=True, append_images=imgs[1:], duration=50, loop=0)
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
    import pytest
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
    import pytest
    from common import MigrationError
    with pytest.raises(MigrationError, match='--chat-url must be one of'):
        ie.ChatClient('https://chat.example.org', 't', session=RecordingSession())
    ie.ChatClient('https://chat-staging.iflgm.com/', 't', session=RecordingSession())
