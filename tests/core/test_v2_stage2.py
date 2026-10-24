# -*- coding: utf-8 -*-
"""2.0 階段二核心：速寫圖源（本機 / 網址池 / 錯誤）、速寫倒數與計張規則、研究分段與練習畫布、設定從 1.x 補帶入"""
import io
import json
import os
import random
import sys
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, tmpdir  # noqa: E402

block_tk()
from PIL import Image  # noqa: E402
from core import settings2, sketch_source as S, study_tools as T, study_lessons  # noqa: E402
from core.daily_quests import UNLIMITED_SKETCH_MIN_SECONDS  # noqa: E402

# ─── 題目與圖源設定 ──
lib = tmpdir()
for sub, n in (('Hands', 3), ('pose', 2)):
    os.makedirs(os.path.join(lib, sub))
    for i in range(n):
        Image.new('RGB', (40, 60), (i * 50, 0, 0)).save(os.path.join(lib, sub, f'{i}.png'))
opts = {'source': 'local', 'local_dir': lib, 'unsplash_key': '', 'pexels_key': ''}
r = S.resolve_quest_topic('hands', opts)
check(r['source'] == 'local' and r['local_category'] == 'Hands' and not r['note'], f'no key -> matching local subdir {r}')
r = S.resolve_quest_topic('kw:dragon', opts)
check(r['source'] == 'local' and r['local_category'] == '' and r['note'], 'no key, no match -> whole library + note')
r = S.resolve_quest_topic('pose', dict(opts, pexels_key='k'))
check(r['source'] == 'pexels' and r['category'] == 'pose', 'key available -> web')
check(S.resolve_quest_topic('local:pose', opts)['local_category'] == 'pose', 'local topic')
check(S.topic_key({'source': 'local', 'local_category': 'pose'}) == 'local:pose', 'topic key local')
check(S.topic_key({'source': 'unsplash', 'category': 'custom', 'custom_query': 'cat'}) == 'kw:cat', 'topic key custom')
check(S.query_for('pose') == 'model pose' and S.query_for('custom', '') == 'portrait', 'query')

# ─── 本機圖源 ──
src = S.SketchSource(random.Random(1))
seen = set()
for _ in range(3):
    img, cap = src.next_image(dict(opts, local_category='Hands'))
    seen.add(img.getpixel((0, 0)))
check(len(seen) == 3 and '[Hands]' in cap, 'local shuffle queue covers each file once')
try:
    src.next_image({'source': 'local', 'local_dir': ''})
    check(False)
except S.SketchError as e:
    check(e.need_setup == 'local_dir', 'missing local dir asks for setup')
try:
    src.next_image({'source': 'unsplash', 'unsplash_key': ''})
    check(False)
except S.SketchError as e:
    check(e.need_setup == 'unsplash_key', 'missing key asks for setup')

# ─── 網路圖源（假的 urlopen） ──
buf = io.BytesIO()
Image.new('RGB', (3000, 2000), 'gray').save(buf, 'PNG')
PNG = buf.getvalue()
calls = {'api': 0, 'fail': None}


class Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def fake(req, timeout=0):
    url = req.full_url
    if 'api.' in url:
        if calls['fail']:
            code = calls['fail']
            raise urllib.error.HTTPError(url, code, 'x', {}, io.BytesIO(b''))
        calls['api'] += 1
        if 'pexels' in url:
            return Resp(json.dumps({'total_results': 500, 'photos': [{'src': {'large': f'https://i/{calls["api"]}_{i}'}}
                                                                      for i in range(80)]}).encode())
        return Resp(json.dumps([{'urls': {'regular': f'https://u/{i}'}} for i in range(30)]).encode())
    return Resp(PNG)


web = S.SketchSource(random.Random(2), opener=fake)
for _ in range(100):
    web.next_image({'source': 'pexels', 'pexels_key': 'k', 'category': 'pose'})
check(calls['api'] == 2, f'pexels pool: {calls["api"]} API calls for 100 images')
calls['api'] = 0
for _ in range(31):
    web.next_image({'source': 'unsplash', 'unsplash_key': 'k', 'category': 'hands'})
check(calls['api'] == 2, 'unsplash pool refills after 30')
web2 = S.SketchSource(opener=fake)
for code, retry, setup in ((429, S.RATE_LIMIT_RETRY_SEC, ''), (401, 0, 'key'), (503, S.RETRY_SEC, '')):
    calls['fail'] = code
    try:
        web2.next_image({'source': 'pexels', 'pexels_key': 'k', 'category': 'feet'})
        check(False)
    except S.SketchError as e:
        check(e.retry_after == retry and e.need_setup == setup, f'HTTP {code}: retry {e.retry_after}')
calls['fail'] = None

# ─── 一輪速寫：倒數、計張、歷史 ──
ses = S.SketchSession(30)
check(not ses.tick(1), 'no image -> nothing')
big = ses.push(Image.new('RGB', (4000, 3000)))
check(max(big.size) == S.HISTORY_MAX_SIDE, 'history keeps thumbnail')
done_at = None
for sec in range(1, 31):
    if ses.tick(1):
        done_at = sec
check(done_at == 30 and ses.completed == 1, 'counts only when countdown reaches zero')
check(not ses.tick(5) and ses.completed == 1, 'no double count while next image loads')
ses.push(Image.new('RGB', (10, 10)))
ses.tick(10)
check(ses.forward() == 0.0, 'skipping early does not count')
ses.paused = True
check(not ses.tick(100) and ses.remaining == 20, 'paused keeps remaining')
check(ses.back() and ses.idx == 0, 'back')
check(ses.forward() == 0.0 and ses.idx == 1, 'forward through history')
for i in range(20):
    ses.push(Image.new('RGB', (10, 10)))
check(len(ses.history) == S.HISTORY_MAX, 'history capped')
free = S.SketchSession(0)
free.push(Image.new('RGB', (10, 10)))
free.tick(UNLIMITED_SKETCH_MIN_SECONDS - 1)
check(free.forward() == 0.0, 'unlimited: too short')
free.push(Image.new('RGB', (10, 10)))
free.tick(UNLIMITED_SKETCH_MIN_SECONDS + 5)
check(free.forward() == UNLIMITED_SKETCH_MIN_SECONDS + 5, 'unlimited: long enough counts')

# ─── 研究：分段、工具、畫布 ──
lesson = study_lessons.lesson('color_2')
check(T.phase_at(lesson, 0)[0] == 0 and T.phase_at(lesson, 10 ** 6) == (len(lesson['phases']) - 1, 0.0), 'phase_at')
name, tail = T.phase_text(lesson, 6 * 60)
check(name.startswith('2/') and tail.startswith('剩'), f'phase text {name} {tail}')
check(T.phase_text(None, 0) == ('研究計時', ''), 'no lesson')
check(T.default_tools(lesson)['palette'], 'lesson default tools')
img = Image.new('RGB', (100, 50), (200, 100, 50))
check(T.process(img, gray=True).getpixel((0, 0))[0] == T.process(img, gray=True).getpixel((0, 0))[2], 'gray')
check(len({c for _n, c in T.process(Image.linear_gradient('L').convert('RGB'), value_levels=3).getcolors(256)}) == 3, 'value 3 levels')
check(len(T.guide_lines('thirds', 90, 60)) == 4 and len(T.guide_lines('diagonal', 9, 6)) == 2, 'guides')
check(len(T.extract_palette(img)) >= 1, 'palette')
folder = T.canvas_dir(tmpdir(), '色彩')
stem = T.canvas_stem(lesson, '色彩', '', day='20261023')
check(stem == f"色彩_Lv2_{lesson['name']}_20261023", stem)
p1, w, h = T.create_canvas(folder, stem, (512, 625), 2000)
p2, _, _ = T.create_canvas(folder, stem, (512, 625), 2000)
check((w, h) == (1638, 2000) and p2.endswith('_2.psd') and os.path.isfile(p1), 'canvas same ratio, no overwrite')
check(T.safe_filename('a/b:c?') == 'a_b_c_', 'safe filename')

# ─── 設定：新建時帶入 1.x 的圖源設定；舊版 2.0 設定補帶入 ──
d = tmpdir()
json.dump({'sketch_pexels_key': 'PK', 'sketch_local_dir': lib, 'sketch_interval': 90, 'study_canvas_dir': 'X:\\c'},
          open(os.path.join(d, 'sai2_timer_settings.json'), 'w', encoding='utf-8'))
s = settings2.Settings2(d)
check(s.get('sources.pexels_key') == 'PK' and s.get('sketch.interval') == 90 and s.get('study.canvas_dir') == 'X:\\c', 'new import')
o = s.sketch_opts()
check(o['pexels_key'] == 'PK' and o['local_dir'] == lib and o['interval'] == 90, 'sketch opts')
check(s.refs_settings()['sketch_pexels_key'] == 'PK', 'refs settings use 1.x key names')
d2 = tmpdir()
json.dump({'sketch_unsplash_key': 'UK'}, open(os.path.join(d2, 'sai2_timer_settings.json'), 'w', encoding='utf-8'))
json.dump({'version': 1, 'pet': {'size': 90}}, open(os.path.join(d2, settings2.SETTINGS_FILE), 'w', encoding='utf-8'))
s2 = settings2.Settings2(d2)
check(s2.get('sources.unsplash_key') == 'UK' and s2.get('pet.size') == 90 and s2.get('version') == settings2.SETTINGS_VERSION, 'upgrade fills new keys')
check(s2.get('hotkeys.ref_toggle') == 'Ctrl+Alt+R', 'new hotkey defaults merged')
done()
