# -*- coding: utf-8 -*-
"""課程打卡的 AI 評鑑：提示詞（課程評分標準＋系統固定的回傳格式；設計者自訂的 ai_criteria）、Gemini 與 OpenAI 相容的請求、
回覆解析、錯誤訊息、模型選擇、金鑰不匯出、AI 分數推進學習路徑。不連網，以假的 HTTP 回應測試"""
import base64
import io
import json
import os
import sys
import urllib.error
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, quest_manager, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402

from core import ai_review as AR, backup, settings2, study_lessons  # noqa: E402
from core.daily_quests import PASS_RATING  # noqa: E402

LES = study_lessons.lesson('value_1')
WORK = Image.new('RGB', (2400, 1200), 'white')
REF = Image.new('RGB', (800, 600), 'gray')


class Resp:
    def __init__(self, payload):
        self.data = json.dumps(payload).encode('utf-8')

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(payload, sent):
    def op(req, timeout=None):
        sent.append({'url': req.full_url, 'headers': {k.lower(): v for k, v in req.header_items()},
                     'body': json.loads(req.data.decode('utf-8')) if req.data else None, 'method': req.get_method()})
        return Resp(payload)
    return op


def opener_failing(code, body=None):
    def op(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, 'err', {}, io.BytesIO(json.dumps(body or {}).encode('utf-8')))
    return op


ANSWER = {'score': 4, 'summary': '明暗分組清楚', 'strengths': ['亮暗面積接近'], 'improve': ['中間調太多', '邊緣太硬', 'x', 'y']}

# ─── 提示詞 ──
p = AR.build_prompt(LES, note='暗部有點難', pass_rating=PASS_RATING)
check(LES['goal'] in p and LES['focus'] in p and all(c in p for c in LES['checks']), 'criteria built from the lesson')
check('暗部有點難' in p and '【回傳格式】' in p and '"score"' in p and f'{PASS_RATING} 分以上' in p,
      'note and the fixed return format appended')
custom = dict(LES, ai_criteria='只看三個明度的面積比例，其他都不評。')
p2 = AR.build_prompt(custom)
check('只看三個明度的面積比例' in p2 and LES['checks'][0] not in p2 and '【回傳格式】' in p2,
      'designer criteria replace the default, format still added by the system')
check('沒有參考圖' in AR.build_prompt(LES, has_reference=False), 'no reference noted')

# ─── Gemini ──
cfg = {'enabled': True, 'provider': 'gemini', 'api_key': 'test-key', 'model': 'gemini-x-flash'}
sent = []
gem = {'candidates': [{'content': {'parts': [{'text': '```json\n' + json.dumps(ANSWER, ensure_ascii=False) + '\n```'}]}}]}
res = AR.review(cfg, LES, WORK, REF, note='', pass_rating=PASS_RATING, opener=opener_returning(gem, sent))
r = sent[0]
check(r['url'].endswith('/v1beta/models/gemini-x-flash:generateContent') and r['headers'].get('x-goog-api-key') == 'test-key',
      'gemini endpoint + key header (not in the URL)')
check('test-key' not in r['url'], 'key never put in the URL')
parts = r['body']['contents'][0]['parts']
imgs = [x for x in parts if 'inline_data' in x]
check(len(imgs) == 2 and parts[1]['text'].startswith('參考圖') and parts[3]['text'].startswith('學生的作品'),
      'reference first, then the work, each labelled')
big = Image.open(io.BytesIO(base64.b64decode(imgs[1]['inline_data']['data'])))
check(max(big.size) == AR.IMAGE_MAX_SIDE, f'images downsized ({big.size})')
check(r['body']['generationConfig']['responseMimeType'] == 'application/json', 'json response requested')
check(res['score'] == 4 and res['passed'] and res['summary'] == '明暗分組清楚' and len(res['improve']) == 3,
      f'parsed result {res}')
check(res['provider'] == 'gemini' and res['model'] == 'gemini-x-flash', 'provider and model recorded')

# ─── OpenAI 相容（本機服務可不填金鑰） ──
sent = []
oa = {'choices': [{'message': {'content': json.dumps({'score': 2, 'summary': '還要加油'}, ensure_ascii=False)}}]}
ocfg = {'enabled': True, 'provider': 'openai', 'api_key': '', 'model': 'llava', 'base_url': 'http://localhost:11434/v1/'}
res = AR.review(ocfg, LES, WORK, None, opener=opener_returning(oa, sent))
r = sent[0]
check(r['url'] == 'http://localhost:11434/v1/chat/completions' and 'authorization' not in r['headers'], 'local service without key')
content = r['body']['messages'][1]['content']
check(r['body']['model'] == 'llava' and sum(1 for x in content if x['type'] == 'image_url') == 1, 'only the work image')
check(res['score'] == 2 and not res['passed'], 'below the pass mark')
sent = []
AR.review(dict(ocfg, api_key='sk-1', base_url=''), LES, WORK, REF, opener=opener_returning(oa, sent))
check(sent[0]['url'] == 'https://api.openai.com/v1/chat/completions' and sent[0]['headers']['authorization'] == 'Bearer sk-1',
      'default OpenAI url + bearer key')

# ─── 解析 ──
check(AR.parse_result('好的！{"score": 9, "summary": "x", "strengths": "一項"}')['score'] == 5, 'score clamped')
check(AR.parse_result('{"score": "3.6"}')['score'] == 4, 'numeric string rounded')
check(AR.parse_result('{"score": 3, "strengths": "一項"}')['strengths'] == ['一項'], 'string → list')
for bad in ('沒有 JSON', '{"summary": "沒分數"}', '{壞掉的}'):
    try:
        AR.parse_result(bad)
        check(False, f'should fail: {bad}')
    except AR.ReviewError:
        check(True)

# ─── 錯誤訊息 ──
def err_of(op, c=cfg):
    try:
        AR.review(c, LES, WORK, REF, opener=op)
    except AR.ReviewError as e:
        return str(e)
    return ''


check('金鑰無效' in err_of(opener_failing(400, {'error': {'message': 'API key not valid. Please pass a valid API key.'}})),
      'invalid key (Gemini answers 400)')
check('額度' in err_of(opener_failing(429)), 'quota')
check('模型' in err_of(opener_failing(404)), 'unknown model')
check('暫時無法使用' in err_of(opener_failing(503)), 'server error')


def offline(req, timeout=None):
    raise urllib.error.URLError('getaddrinfo failed')


check('無法連線' in err_of(offline), 'offline')
check('拒絕' in err_of(opener_returning({'promptFeedback': {'blockReason': 'SAFETY'}}, [])), 'blocked')
try:
    AR.review(cfg, LES, None)
    check(False, 'no canvas should fail')
except AR.ReviewError as e:
    check('畫布' in str(e), 'no canvas → message')

# ─── 設定是否完成、模型清單與預設模型 ──
check(not AR.ready({'enabled': False, 'api_key': 'k'}) and not AR.ready({'enabled': True, 'provider': 'gemini'}), 'not ready')
check(AR.ready({'enabled': True, 'provider': 'gemini', 'api_key': 'k'}), 'gemini ready with key')
check(AR.ready({'enabled': True, 'provider': 'openai', 'model': 'llava', 'base_url': 'http://localhost:11434/v1'}),
      'local openai-compatible ready without key')
check(not AR.ready({'enabled': True, 'provider': 'openai', 'base_url': 'http://x'}), 'openai needs a model')
models = {'models': [
    {'name': 'models/gemini-2.0-flash', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemini-3.0-flash', 'supportedGenerationMethods': ['generateContent', 'countTokens']},
    {'name': 'models/gemini-3.5-flash-lite', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/gemini-3.5-flash-preview-tts', 'supportedGenerationMethods': ['generateContent']},
    {'name': 'models/text-embedding-004', 'supportedGenerationMethods': ['embedContent']},
    {'name': 'models/gemini-3.0-pro', 'supportedGenerationMethods': ['generateContent']}]}
sent = []
names = AR.list_models(cfg, opener=opener_returning(models, sent))
check('text-embedding-004' not in names and 'gemini-3.0-flash' in names and sent[0]['method'] == 'GET', 'model list')
check(AR.pick_default_model(names) == 'gemini-3.0-flash', f'newest plain flash picked ({AR.pick_default_model(names)})')
check(AR.pick_default_model([]) == AR.FALLBACK_GEMINI_MODEL, 'fallback model')
names = AR.list_models(ocfg, opener=opener_returning({'data': [{'id': 'llava'}, {'id': 'qwen2.5vl'}]}, []))
check(names == ['llava', 'qwen2.5vl'], 'openai model list')

# ─── 不需要長時間推理；沒選模型時用穩定的預設，預設被停用（404）才改用清單上的 ──
check(AR.thinking_config('gemini-2.5-flash') == {'thinkingBudget': 0}, '2.5 flash: no thinking')
check(AR.thinking_config('gemini-3.8-flash') == {'thinkingLevel': 'low'}, '3.x: low thinking')
check(AR.thinking_config('gemini-2.5-pro') is None and AR.thinking_config('gemini-flash-latest') == {'thinkingLevel': 'low'},
      'pro untouched, latest alias low')
sent = []
AR.review(dict(cfg, model=''), LES, WORK, REF, opener=opener_returning(gem, sent))
check(sent[0]['url'].endswith(f'/models/{AR.FALLBACK_GEMINI_MODEL}:generateContent')
      and sent[0]['body']['generationConfig']['thinkingConfig'] == {'thinkingBudget': 0}, 'blank model → stable default')
seq = []


def retired(req, timeout=None):
    seq.append(req.full_url)
    if req.full_url.endswith(f'{AR.FALLBACK_GEMINI_MODEL}:generateContent'):
        raise urllib.error.HTTPError(req.full_url, 404, 'nf', {}, io.BytesIO(b'{}'))
    if req.get_method() == 'GET':
        return Resp(models)
    return Resp(gem)


res = AR.review(dict(cfg, model=''), LES, WORK, REF, opener=retired)
check(res['model'] == 'gemini-3.0-flash' and len(seq) == 3, f'default retired → newest plain flash ({res["model"]})')
check('模型' in err_of(retired, dict(cfg, model=AR.FALLBACK_GEMINI_MODEL)), 'a model the user chose is not replaced')
check(AR.test_connection(cfg, opener=opener_returning(gem, [])) == 'gemini-x-flash', 'connection test returns the model')

# ─── 設定：預設關閉、金鑰不匯出 ──
s = settings2.Settings2(tmpdir())
check(s.get('ai_review.enabled') is False and s.get('ai_review.provider') == 'gemini', 'off by default')
s.set('ai_review.api_key', 'secret-key')
check('api_key' not in backup.shareable(s.data).get('ai_review', {}), 'key never exported (settings / diagnostics)')
check(backup.shareable(s.data).get('ai_review', {}).get('provider') == 'gemini', 'other AI settings are shareable')

# ─── AI 的分數推進學習路徑；改分數會標示 ──
q = quest_manager()
q.ensure_today()
skill = LES['skill']
tpl = next(tp for tp in q.data['templates'] if tp.get('mode') == 'study' and tp.get('params', {}).get('path') == skill)
uid = q.add_today(tpl['id'])['uid']
task = next(x for x in q.today_tasks() if x['uid'] == uid)
check(task['params']['lesson_id'] == LES['id'], 'study task on the first lesson')
task['status'] = 'ready'
ai = {'score': 4, 'summary': '明暗分組清楚', 'strengths': [], 'improve': [], 'provider': 'gemini', 'model': 'm', 'passed': True}
check(q.check_in(task['uid'], '', rating=4, ai_review=ai) is None, 'checked in')
check(task['rating'] == 4 and task['ai_review']['summary'] == '明暗分組清楚' and not task['ai_review']['overridden'],
      'AI review stored with the check-in')
check(task['advanced_to'] and q.path_state(skill)['index'] == 1, 'AI score ≥ pass mark → next lesson')
q2 = quest_manager(seed=2)
q2.ensure_today()
t2 = next(tp for tp in q2.data['templates'] if tp.get('mode') == 'study' and tp.get('params', {}).get('path') == skill)
task2 = q2.add_today(t2['id'])
task2 = next(x for x in q2.today_tasks() if x['uid'] == task2['uid'])
task2['status'] = 'ready'
q2.check_in(task2['uid'], '', rating=2, ai_review=dict(ai, score=4))
check(task2['ai_review']['overridden'] and task2['rating'] == 2 and not task2['advanced_to'],
      'user lowered the AI score → marked overridden, not advanced')
done()
