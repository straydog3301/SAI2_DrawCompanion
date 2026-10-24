# -*- coding: utf-8 -*-
"""
ai_review.py - 課程打卡的 AI 評鑑（不含 UI）

打卡時把「課程目標＋評分標準」「臨摹對象（參考圖）」「使用者的作品（畫布快照）」傳給使用者自己的 LLM，
取回 1～5 分與簡評，分數決定是否進入下一課（daily_quests.PASS_RATING）。

- 評分標準：預設由課程的目標、專注重點、完成檢查與常見錯誤組成；課程有 ai_criteria（之後社群自製課程由設計者撰寫）時改用它
- 回傳格式：固定由系統加在最後（FORMAT_PROMPT），課程不能改，才能穩定解析
- 服務：Google AI Studio（Gemini，有每日免費額度）或 OpenAI 相容 API（OpenAI、OpenRouter、本機 Ollama／LM Studio…）
- 金鑰只存在本機設定（ai_review.api_key），匯出設定與診斷資訊都不包含（core/backup.SECRETS）
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request

PROVIDERS = {
    'gemini': {'name': 'Google AI Studio（Gemini）', 'base_url': 'https://generativelanguage.googleapis.com',
               'key_url': 'https://aistudio.google.com/apikey'},
    'openai': {'name': 'OpenAI 相容 API', 'base_url': 'https://api.openai.com/v1', 'key_url': ''},
}
FALLBACK_GEMINI_MODEL = 'gemini-2.5-flash'   # 沒選模型時用：穩定、快（2026-10 實測約 3 秒）、有免費額度
IMAGE_MAX_SIDE = 1024
TIMEOUT = 60

SYSTEM_PROMPT = ('你是有耐心的繪畫老師，正在評鑑學生的臨摹練習。請依「評分標準」比較學生作品與參考圖，'
                 '只評這堂課要練的重點；不要因為畫風、筆刷、上色與否或其他課程沒要求的地方扣分。'
                 '學生作品是畫布的截圖，可能還在進行中。')

RATING_WORDS = {1: '還差很多', 2: '有些抓到', 3: '大致做到', 4: '做得不錯', 5: '非常接近'}


def format_prompt(pass_rating: int) -> str:
    """系統固定加在最後的回傳格式（課程的評分標準不能改這部分）"""
    scale = '、'.join(f'{k} {v}' for k, v in RATING_WORDS.items())
    return ('\n\n【回傳格式】只回傳一個 JSON 物件，不要有任何其他文字或 Markdown：\n'
            '{"score": 1 到 5 的整數, "summary": "一句話總評（40 字內）", '
            '"strengths": ["做得好的地方，最多 3 項"], "improve": ["下次可以改進的地方，最多 3 項"]}\n'
            f'分數意義：{scale}。{pass_rating} 分以上代表這堂課的重點已經做到，可以進入下一課。\n'
            '請用繁體中文，語氣具體、鼓勵，指出畫面上的位置。')


def criteria_for(lesson: dict) -> str:
    """課程的評分標準：有 ai_criteria（設計者自訂）就用它，否則由課程內容組成"""
    custom = (lesson.get('ai_criteria') or '').strip()
    head = f"課程：{lesson.get('name', '')}（Lv{lesson.get('level', '')}）"
    if custom:
        return f'{head}\n{custom}'
    lines = [head, f"目標：{lesson.get('goal', '')}", f"這堂課只專注：{lesson.get('focus', '')}"]
    if lesson.get('checks'):
        lines.append('完成檢查：' + ''.join(f'\n- {c}' for c in lesson['checks']))
    if lesson.get('mistakes'):
        lines.append('常見錯誤：' + ''.join(f'\n- {m}' for m in lesson['mistakes']))
    return '\n'.join(lines)


def build_prompt(lesson: dict, note: str = '', has_reference: bool = True, pass_rating: int = 3) -> str:
    parts = ['【評分標準】', criteria_for(lesson)]
    if (note or '').strip():
        parts.append(f'\n【學生的心得】{note.strip()}')
    if not has_reference:
        parts.append('\n（這次沒有參考圖，請只依評分標準評鑑學生作品。）')
    return '\n'.join(parts) + format_prompt(pass_rating)


def encode_image(img) -> str:
    """PIL 圖片 → 縮小後的 JPEG base64"""
    from PIL import Image
    im = img.convert('RGB')
    im.thumbnail((IMAGE_MAX_SIDE, IMAGE_MAX_SIDE), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format='JPEG', quality=85)
    return base64.b64encode(buf.getvalue()).decode('ascii')


class ReviewError(Exception):
    """給使用者看的錯誤訊息；code 是 HTTP 狀態碼（有的話）"""
    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


# ─── HTTP ──
def _request(url: str, headers: dict, body: dict | None, opener, timeout: float | None = None) -> dict:
    timeout = timeout or TIMEOUT
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', **headers},
                                 method='POST' if body is not None else 'GET')
    try:
        with opener(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        raise ReviewError(_http_message(e), e.code) from None
    except urllib.error.URLError as e:
        raise ReviewError(f'無法連線到 AI 服務：{getattr(e, "reason", e)}') from None
    except TimeoutError:
        raise ReviewError('AI 服務回應逾時（這個模型可能比較慢，可以到「設定 › AI 評鑑」換成其他模型）') from None
    except (ValueError, OSError) as e:
        raise ReviewError(f'AI 服務的回應無法讀取：{e}') from None


def _http_message(e) -> str:
    detail = ''
    try:
        payload = json.loads(e.read().decode('utf-8', 'replace'))
        err = payload.get('error') if isinstance(payload, dict) else None
        detail = (err.get('message') if isinstance(err, dict) else str(err or '')) or ''
    except Exception:
        pass
    low = detail.lower()
    if e.code in (401, 403) or 'api key' in low or 'api_key' in low:
        return '金鑰無效或沒有使用權限，請到「設定 › AI 評鑑」確認金鑰'
    if e.code == 404:
        return '找不到這個模型，請到「設定 › AI 評鑑」重新選擇模型'
    if e.code == 429:
        return '超過使用額度（免費額度每天有上限），請稍後再試'
    if e.code >= 500:
        return 'AI 服務暫時無法使用，請稍後再試'
    return f'AI 服務回傳錯誤（{e.code}）' + (f'：{detail[:120]}' if detail else '')


# ─── 解析 ──
def parse_result(text: str) -> dict:
    """從模型回覆中取出 JSON；分數限制在 1～5"""
    t = (text or '').strip()
    t = re.sub(r'^```(?:json)?\s*|\s*```$', '', t)
    m = re.search(r'\{.*\}', t, re.S)
    if not m:
        raise ReviewError('AI 的回覆不是預期的格式，請再試一次')
    try:
        data = json.loads(m.group(0))
    except ValueError:
        raise ReviewError('AI 的回覆不是預期的格式，請再試一次') from None
    try:
        score = int(round(float(data.get('score'))))
    except (TypeError, ValueError):
        raise ReviewError('AI 的回覆沒有分數，請再試一次') from None

    def items(v):
        if isinstance(v, str):
            v = [v]
        return [str(x).strip() for x in (v or []) if str(x).strip()][:3]
    return {'score': max(1, min(5, score)), 'summary': str(data.get('summary') or '').strip()[:200],
            'strengths': items(data.get('strengths')), 'improve': items(data.get('improve'))}


# ─── 服務 ──
def _base(cfg: dict) -> str:
    return (cfg.get('base_url') or PROVIDERS.get(cfg.get('provider'), PROVIDERS['gemini'])['base_url']).rstrip('/')


def _gemini(cfg, system, prompt, images, opener) -> str:
    parts = [{'text': prompt}]
    for label, b64 in images:
        parts += [{'text': label}, {'inline_data': {'mime_type': 'image/jpeg', 'data': b64}}]
    body = {'systemInstruction': {'parts': [{'text': system}]},
            'contents': [{'role': 'user', 'parts': parts}],
            'generationConfig': {'temperature': 0.2, 'responseMimeType': 'application/json'}}
    model = cfg.get('model') or FALLBACK_GEMINI_MODEL
    model = model[len('models/'):] if model.startswith('models/') else model
    thinking = thinking_config(model)
    if thinking:
        body['generationConfig']['thinkingConfig'] = thinking
    data = _request(f'{_base(cfg)}/v1beta/models/{model}:generateContent', {'x-goog-api-key': cfg.get('api_key', '')},
                    body, opener)
    cands = data.get('candidates') or []
    if not cands:
        reason = (data.get('promptFeedback') or {}).get('blockReason')
        raise ReviewError('AI 拒絕評鑑這張圖' + (f'（{reason}）' if reason else '') + '，請改用自評')
    return ''.join(p.get('text', '') for p in (cands[0].get('content') or {}).get('parts', []))


def thinking_config(model: str) -> dict | None:
    """評分不需要長時間推理：較新的 Gemini 預設會先「思考」，可能要等超過一分鐘，這裡調到最低"""
    m = re.search(r'gemini-(\d+(?:\.\d+)?)', model)
    if not m:
        return {'thinkingLevel': 'low'} if 'latest' in model else None
    ver = float(m.group(1))
    if ver >= 3:
        return {'thinkingLevel': 'low'}
    if ver >= 2.5 and 'pro' not in model:
        return {'thinkingBudget': 0}
    return None


def _openai(cfg, system, prompt, images, opener) -> str:
    content = [{'type': 'text', 'text': prompt}]
    for label, b64 in images:
        content += [{'type': 'text', 'text': label},
                    {'type': 'image_url', 'image_url': {'url': f'data:image/jpeg;base64,{b64}'}}]
    body = {'model': cfg.get('model') or '', 'temperature': 0.2,
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]}
    headers = {'Authorization': f"Bearer {cfg['api_key']}"} if cfg.get('api_key') else {}
    data = _request(f'{_base(cfg)}/chat/completions', headers, body, opener)
    try:
        msg = data['choices'][0]['message']['content']
    except (KeyError, IndexError, TypeError):
        raise ReviewError('AI 服務的回應不是預期的格式') from None
    if isinstance(msg, list):
        msg = ''.join(x.get('text', '') for x in msg if isinstance(x, dict))
    return msg or ''


def ready(cfg: dict) -> bool:
    """已開啟且設定完成（OpenAI 相容的本機服務可以不需要金鑰，但要有模型）"""
    if not cfg or not cfg.get('enabled'):
        return False
    if cfg.get('provider') == 'openai':
        return bool(cfg.get('model')) and bool(cfg.get('api_key') or cfg.get('base_url'))
    return bool(cfg.get('api_key'))


def review(cfg: dict, lesson: dict, work_img, ref_img=None, note: str = '', pass_rating: int = 3,
           opener=urllib.request.urlopen) -> dict:
    """評鑑一次打卡；回傳 {'score', 'summary', 'strengths', 'improve', 'provider', 'model', 'passed'}，失敗丟 ReviewError"""
    if work_img is None:
        raise ReviewError('沒有擷取到畫布，無法評鑑')
    images = []
    if ref_img is not None:
        images.append(('參考圖（臨摹對象）：', encode_image(ref_img)))
    images.append(('學生的作品：', encode_image(work_img)))
    prompt = build_prompt(lesson, note, has_reference=ref_img is not None, pass_rating=pass_rating)
    if cfg.get('provider') == 'openai':
        text = _openai(cfg, SYSTEM_PROMPT, prompt, images, opener)
    else:
        chosen = cfg.get('model')
        cfg = dict(cfg, model=chosen or FALLBACK_GEMINI_MODEL)
        try:
            text = _gemini(cfg, SYSTEM_PROMPT, prompt, images, opener)
        except ReviewError as e:
            # 沒指定模型、預設模型又被 Google 停用時，改用清單上最新的一般 Flash
            if e.code != 404 or chosen:
                raise
            cfg['model'] = pick_default_model(list_models(cfg, opener=opener))
            text = _gemini(cfg, SYSTEM_PROMPT, prompt, images, opener)
    out = parse_result(text)
    out.update({'provider': cfg.get('provider') or 'gemini', 'model': cfg.get('model') or '',
                'passed': out['score'] >= pass_rating})
    return out


# ─── 模型清單與連線測試 ──
def list_models(cfg: dict, opener=urllib.request.urlopen) -> list[str]:
    if cfg.get('provider') == 'openai':
        headers = {'Authorization': f"Bearer {cfg['api_key']}"} if cfg.get('api_key') else {}
        data = _request(f'{_base(cfg)}/models', headers, None, opener, timeout=20)
        return sorted(str(m.get('id')) for m in data.get('data', []) if m.get('id'))
    data = _request(f'{_base(cfg)}/v1beta/models?pageSize=200', {'x-goog-api-key': cfg.get('api_key', '')}, None,
                    opener, timeout=20)
    return [m['name'].split('/', 1)[-1] for m in data.get('models', [])
            if 'generateContent' in (m.get('supportedGenerationMethods') or []) and m.get('name')]


def pick_default_model(names: list[str]) -> str:
    """Gemini 預設模型：版本最新的一般 flash（免費額度較多、速度快、能看圖）；不選 lite、預覽、語音、生圖等特殊版本"""
    skip = ('lite', 'tts', 'image', 'live', 'audio', 'embedding', 'preview', 'exp', 'thinking', 'learnlm')

    def version(n):
        m = re.search(r'(\d+(?:\.\d+)?)', n)
        return float(m.group(1)) if m else 0.0
    flash = [n for n in names if 'gemini' in n and 'flash' in n and not any(s in n for s in skip)]
    pool = flash or [n for n in names if 'gemini' in n and not any(s in n for s in skip)]
    if not pool:
        return FALLBACK_GEMINI_MODEL
    return sorted(pool, key=lambda n: (version(n), -len(n)), reverse=True)[0]


def test_connection(cfg: dict, opener=urllib.request.urlopen) -> str:
    """送一個很短的文字請求，確認金鑰與模型可以用；回傳實際使用的模型名稱"""
    probe = {'goal': '測試', 'focus': '測試', 'name': '連線測試', 'level': 0}
    from PIL import Image
    img = Image.new('RGB', (64, 64), 'white')
    return review(cfg, probe, img, None, note='這是連線測試，請回傳 3 分。', opener=opener)['model']
