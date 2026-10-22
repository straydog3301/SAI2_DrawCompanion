# -*- coding: utf-8 -*-
"""速寫視窗的網路圖源（以假的 urlopen 代替連網）：網址池節省 API 次數、歷史縮圖、429 自動重試、401 不重試"""
import io
import os
import sys
import json
import types
import urllib.error
import urllib.request
import tkinter as tk
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, headless_main, run_mainloop  # noqa: E402

M, tmp = headless_main()
from PIL import Image  # noqa: E402

buf = io.BytesIO()
Image.new('RGB', (3000, 2000), 'gray').save(buf, 'PNG')
PNG = buf.getvalue()
calls = {'api': 0, 'img': 0, 'fail': 0, 'code': 429}


class Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def fake_urlopen(req, timeout=0):
    url = req.full_url
    if ('api.pexels' in url or 'api.unsplash' in url) and calls['fail'] > 0:
        calls['fail'] -= 1
        raise urllib.error.HTTPError(url, calls['code'], 'x', {}, io.BytesIO(b''))
    if 'api.pexels.com' in url:
        calls['api'] += 1
        return Resp(json.dumps({'total_results': 500, 'photos': [
            {'src': {'large': f'https://img/{calls["api"]}_{i}'}} for i in range(80)]}).encode())
    if 'api.unsplash.com' in url:
        calls['api'] += 1
        check('count=30' in url, 'unsplash asks for a batch of 30')
        return Resp(json.dumps([{'urls': {'regular': f'https://u/{calls["api"]}_{i}'}} for i in range(30)]).encode())
    calls['img'] += 1
    return Resp(PNG)


urllib.request.urlopen = fake_urlopen
M.SketchPracticeWindow.WEB_RATE_LIMIT_RETRY_SEC = 1
root = tk.Tk()
root.withdraw()
app = types.SimpleNamespace(_settings={'sketch_source_mode': 'pexels', 'sketch_pexels_key': 'k',
                                       'sketch_unsplash_key': 'k', 'sketch_interval': 30, 'sketch_topmost': False},
                            quests=None)
w = M.SketchPracticeWindow(root, app)
for _ in range(100):
    w._fetch_web_image('pexels', 'k', 'pose')
check(calls['api'] == 2 and calls['img'] == 100, f"pexels pool: {calls['api']} API calls for 100 images")
calls['api'] = 0
for _ in range(60):
    w._fetch_web_image('unsplash', 'k', 'hands')
check(calls['api'] == 2, f"unsplash pool: {calls['api']} API calls for 60 images")
kept = w._push_history(w._fetch_web_image('pexels', 'k', 'pose'))
check(max(kept.size) == w.HISTORY_MAX_SIDE, f'history thumbnail {kept.size}')

# 429：排程重試，之後成功載入
w._web_pool.clear()
calls['fail'] = 1
w._loading = False
w._load_web('pexels')
for _ in range(30):
    run_mainloop(root, 100)
    if w._history and len(w._history) > 1:
        break
check(len(w._history) >= 2 and w._web_retry_job is None, '429 retried then loaded')

# 401：金鑰錯誤不重試
w._web_pool.clear()
calls.update(fail=1, code=401)
w._load_web('pexels')
for _ in range(10):
    run_mainloop(root, 100)
    if not w._loading:
        break
check('401' in w.var_status.get() and w._web_retry_job is None, f'401 no retry: {w.var_status.get()}')
w._on_close()
root.destroy()
done()
