# -*- coding: utf-8 -*-
"""浮動筆記（不含 UI）：每則筆記一個 Markdown 檔、頁籤順序與目前的筆記、改名與刪除、貼上的圖片、
Markdown 切成閱讀模式的區塊（標題、段落、程式碼區塊、圖片）、目錄、複製時去掉記號。只用暫存資料夾"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, tmpdir  # noqa: E402

from PIL import Image  # noqa: E402

from core import notes as N  # noqa: E402

d = tmpdir()
st = N.NoteStore(d)
check(st.names() == ['筆記'] and os.path.isfile(os.path.join(d, 'notes', '筆記.md')), 'first run: one sample note')
check('```' in st.read('筆記'), 'sample shows a copyable block')

a = st.create('色碼')
b = st.create('色碼')
check((a, b) == ('色碼', '色碼 2') and st.current() == '色碼 2', 'unique names; the new note becomes current')
check(st.clean_name('a/b:c*?<>|"') == 'abc' and st.create('  ') == '筆記 2', 'illegal characters removed; blank → default')
st.write('色碼', '# 色碼\n\n```\n#FF0000\n```\n')
check(st.read('色碼').startswith('# 色碼'), 'write / read')
st.move('色碼 2', 0)
check(st.names()[0] == '色碼 2', 'tab order remembered')
new = st.rename('色碼', '常用色碼')
check(new == '常用色碼' and '常用色碼' in st.names() and '色碼' not in st.names() and '#FF0000' in st.read('常用色碼'),
      'rename keeps the content')
check(st.rename('常用色碼', '色碼 2') == '色碼 2 2', 'rename to an existing name gets a number')
st.set_current('筆記')
st.delete('筆記')
check('筆記' not in st.names() and st.current() in st.names(), 'delete; current moves to another note')
st.set_collapsed('色碼 2 2', {'色票', '筆刷'})
check(st.collapsed('色碼 2 2') == {'色票', '筆刷'}, 'collapsed headings remembered')
st.rename('色碼 2 2', '色票')
check(st.collapsed('色票') == {'色票', '筆刷'} and st.collapsed('色碼 2 2') == set(), 'collapsed state follows a rename')
st.set_collapsed('色票', set())
check(st.collapsed('色票') == set(), 'expand all clears it')
open(os.path.join(d, 'notes', '外部.md'), 'w', encoding='utf-8').write('寫在別的編輯器')
check(st.names()[-1] == '外部', 'notes added outside the app show up at the end')

# ─── 圖片 ──
from datetime import datetime  # noqa: E402
now = datetime(2026, 10, 29, 12, 0, 0)
r1 = st.save_image(Image.new('RGB', (40, 30), 'red'), now)
r2 = st.save_image(Image.new('RGB', (40, 30), 'blue'), now)
check((r1, r2) == ('images/20261029_120000.png', 'images/20261029_120000_2.png'), 'images saved with unique names')
check(os.path.isfile(st.image_path(r1)) and Image.open(st.image_path(r2)).getpixel((0, 0)) == (0, 0, 255), 'image files')

# ─── 區塊 ──
text = """# 標題
段落一 **粗體**
第二行

- 清單一
- 清單二

```txt
#FF0000
筆刷 12
```

![參考](images/a.png)

## 小節
> 引用
"""
bl = N.blocks(text)
check([b[0] for b in bl] == ['heading', 'text', 'code', 'image', 'heading', 'text'], f'blocks {[b[0] for b in bl]}')
check(bl[0] == ('heading', 1, '標題') and bl[2] == ('code', 'txt', '#FF0000\n筆刷 12') and bl[3] == ('image', '參考', 'images/a.png'),
      'heading, code and image parsed')
check(bl[1] == ('text', '段落一 **粗體**\n第二行\n\n- 清單一\n- 清單二'), 'text up to the next block stays one section (blank lines kept)')
check(N.blocks('~~~\n#00FF00\n~~~') == [('code', '', '#00FF00')], '~~~ also makes a copy block')
check(N.hard_breaks('一\n二\n\n三') == '一  \n二\n\n三', 'single newlines shown as line breaks')
check(N.headings(text) == [(0, 1, '標題'), (4, 2, '小節')], 'table of contents')
check(N.blocks('```\n未關閉的區塊\n') == [('code', '', '未關閉的區塊')], 'unclosed code block')
check(N.blocks('') == [] and N.blocks('\n\n') == [], 'empty note')
check(N.plain('**粗** 與 `碼` [連結](http://x) *斜*\n> 引用') == '粗 與 碼 連結 斜\n引用', 'copy without markdown marks')
done()
