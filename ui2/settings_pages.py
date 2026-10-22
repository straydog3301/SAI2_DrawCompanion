# -*- coding: utf-8 -*-
"""設定頁（放在主視窗的「設定」群組裡）：一般、寵物、參考圖來源、快捷鍵。變更立即套用並存檔"""

from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QComboBox, QFileDialog, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QSlider,
                               QSpinBox, QVBoxLayout, QWidget)

from core import hotkeys, pet_pack
from ui2.pet_window import to_pixmap
from ui2.widgets import Card, PageHeader, Segmented, SettingGroup, Stepper, ToggleSwitch, button, label


def _page(title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
    w = QWidget()
    lay = QVBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(24)
    lay.addWidget(PageHeader(title, subtitle))
    return w, lay


def _toggle(ctl, key: str, after=None) -> ToggleSwitch:
    t = ToggleSwitch(bool(ctl.settings.get(key)))

    def changed(v):
        ctl.settings.set(key, v)
        ctl.settings.save()
        if after:
            after()
    t.toggled.connect(changed)
    return t


def _path_field(ctl, key: str, title: str, placeholder: str = '未設定', file_filter: str | None = None) -> QWidget:
    w = QWidget()
    row = QHBoxLayout(w)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    ed = QLineEdit(ctl.settings.get(key, '') or '')
    ed.setPlaceholderText(placeholder)
    ed.setMinimumWidth(320)
    pick = button('瀏覽…')

    def choose():
        if file_filter:
            path, _ = QFileDialog.getOpenFileName(w, title, os.path.dirname(ed.text()), file_filter)
        else:
            path = QFileDialog.getExistingDirectory(w, title, ed.text())
        if path:
            ed.setText(os.path.normpath(path))
    pick.clicked.connect(choose)
    ed.textChanged.connect(lambda v: (ctl.settings.set(key, v.strip()), ctl.settings.save()))
    row.addWidget(ed, 1)
    row.addWidget(pick)
    return w


def _spin(ctl, key: str, lo: int, hi: int, suffix: str, cast=int, after=None) -> QWidget:
    sp = QSpinBox()
    sp.setRange(lo, hi)
    sp.setSuffix(suffix)
    sp.setValue(int(ctl.settings.get(key, lo)))

    def changed(v):
        ctl.settings.set(key, cast(v))
        ctl.settings.save()
        if after:
            after()
    sp.valueChanged.connect(changed)
    return Stepper(sp, 170)


# ── 一般 ──
def general_page(ctl) -> QWidget:
    w, lay = _page('一般', '這些設定都有預設值，不改也能使用。')
    g = SettingGroup('啟動')
    auto = ToggleSwitch(ctl.autostart_enabled())
    auto.toggled.connect(ctl.set_autostart)
    g.row('登入 Windows 時自動啟動', '在背景執行，寵物會出現在桌面', auto)
    lay.addWidget(g)

    g = SettingGroup('SAI2')
    g.row('SAI2 執行檔', 'SAI2 開著時會自動記下；也可以自己指定', _path_field(ctl, 'sai2_exe', '選擇 SAI2 執行檔',
          '開著 SAI2 時會自動填入', 'sai2.exe (*.exe)'), stack=True)
    g.row('停筆多久不算動筆', '超過這段時間沒有下筆，就不計入動筆時間（下次啟動生效）',
          _spin(ctl, 'idle_timeout', 3, 120, ' 秒', float))
    g.row('記錄還沒存檔的新畫布', '預設不記錄：未存檔的畫布多半是暫時貼參考圖用（下次啟動生效）',
          _toggle(ctl, 'track_unsaved'))
    lay.addWidget(g)

    g = SettingGroup('資料')
    open_btn = button('開啟資料夾', ic='works')
    open_btn.clicked.connect(lambda: os.startfile(ctl.settings.app_dir))
    g.row('資料位置', ctl.settings.app_dir, open_btn)
    lang = QComboBox()
    lang.addItem('繁體中文')
    lang.setEnabled(False)
    lang.setFixedWidth(150)
    g.row('語言', '英文、日文會在 2.0 收尾階段加入', lang)
    lay.addWidget(g)
    lay.addStretch(1)
    return w


# ── 寵物 ──
class PetPage(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.s = ctl.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        head = PageHeader('寵物', '換成自己畫的角色：在角色資料夾放一個資料夾，裡面放 idle.png、drawing.gif 這類以狀態命名的圖檔')
        folder = button('角色資料夾', ic='works')
        folder.clicked.connect(self._open_pets_dir)
        head.actions.addWidget(folder)
        lay.addWidget(head)

        # 角色與預覽
        card = Card()
        row = QHBoxLayout()
        row.setSpacing(24)
        self.preview = QLabel()
        self.preview.setFixedSize(180, 180)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet('background:#8e8e93;border-radius:14px;')
        row.addWidget(self.preview)
        col = QVBoxLayout()
        col.setSpacing(10)
        col.addWidget(label('角色', 'caption'))
        pick = QHBoxLayout()
        self.pack_combo = QComboBox()
        self.pack_combo.setMinimumWidth(240)
        reload_btn = button('重新整理', 'ghost', ic='refresh')
        pick.addWidget(self.pack_combo, 1)
        pick.addWidget(reload_btn)
        col.addLayout(pick)
        self.pack_warn = label('', 'warn')
        col.addWidget(self.pack_warn)
        col.addWidget(label('預覽狀態', 'caption'))
        self.state_combo = QComboBox()
        for st in pet_pack.STATES:
            self.state_combo.addItem(pet_pack.STATE_LABELS[st], st)
        col.addWidget(self.state_combo)
        self.state_info = label('', 'caption')
        col.addWidget(self.state_info)
        col.addStretch(1)
        row.addLayout(col, 1)
        card.lay.addLayout(row)
        fmt = label('支援 PNG、GIF、APNG、WebP、橫排精靈圖（在 pet.json 寫 frames、fps）。'
                    '建議 APNG 或 WebP、512×512 透明背景、腳底置中；GIF 的邊緣會有鋸齒。', 'caption')
        card.lay.addWidget(fmt)
        lay.addWidget(card)

        g = SettingGroup('外觀')
        g.row('大小', '', self._slider('pet.size', 48, 256, lambda v: f'{v} px', True))
        g.row('透明度', '', self._slider('pet.opacity', 20, 100, lambda v: f'{v}%', False, scale=100))
        g.row('動筆時變半透明', '畫圖時寵物不會擋住視線', _toggle(ctl, 'pet.fade_when_drawing', self._apply))
        g.row('拖曳放開時貼齊螢幕邊緣', '', _toggle(ctl, 'pet.snap_edges', self._apply))
        lay.addWidget(g)

        g = SettingGroup('提醒')
        g.row('連續動筆提醒休息', '0 = 不提醒', _spin(ctl, 'pet.rest_minutes', 0, 240, ' 分', int, self._apply))
        seg = Segmented([('important', '只有重要的'), ('all', '全部'), ('off', '關閉')], self.s.get('pet.bubbles', 'important'))
        seg.changed.connect(lambda v: (self.s.set('pet.bubbles', v), self.s.save()))
        g.row('對話泡泡', '', seg)
        g.row('晚上 11 點到早上 6 點顯示睡覺', '', _toggle(ctl, 'pet.night_sleep', self._apply))
        lay.addWidget(g)
        lay.addStretch(1)

        self._frames, self._i = [], 0
        self._t = QTimer(self, timeout=self._next)
        self._reload_packs()
        self.pack_combo.currentIndexChanged.connect(self._pack_changed)
        reload_btn.clicked.connect(lambda: (self._reload_packs(), self._preview_state()))
        self.state_combo.currentIndexChanged.connect(lambda *_: self._preview_state())
        self._preview_state()

    def _slider(self, key, lo, hi, fmt, reload_frames, scale=1):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        val = int(float(self.s.get(key, lo)) * scale)
        sl.setValue(val)
        sl.setFixedWidth(220)
        lb = label(fmt(val), 'muted', wrap=False)
        lb.setFixedWidth(56)

        def changed(v):
            lb.setText(fmt(v))
            self.s.set(key, v / scale if scale != 1 else v)
            self.s.save()
            self._apply(reload_frames)
        sl.valueChanged.connect(changed)
        row.addWidget(sl)
        row.addWidget(lb)
        return w

    def _apply(self, reload_frames=False):
        self.ctl.apply_pet_settings(reload_frames=reload_frames)

    def _reload_packs(self):
        self.packs = pet_pack.list_packs(self.s.pets_dir)
        cur = self.s.get('pet.pack', '')
        self.pack_combo.blockSignals(True)
        self.pack_combo.clear()
        for p in self.packs:
            self.pack_combo.addItem(p.name, p.pack_id)
        ids = [p.pack_id for p in self.packs]
        self.pack_combo.setCurrentIndex(ids.index(cur) if cur in ids else 0)
        self.pack_combo.blockSignals(False)
        self._show_warnings()

    def _show_warnings(self):
        p = self.packs[self.pack_combo.currentIndex()]
        self.pack_warn.setText('\n'.join(p.warnings))
        self.pack_warn.setVisible(bool(p.warnings))

    def _pack_changed(self, i):
        self._show_warnings()
        self.s.set('pet.pack', self.packs[i].pack_id)
        self.s.save()
        self._apply(True)
        self._preview_state()

    def _preview_state(self):
        p = self.packs[self.pack_combo.currentIndex()]
        st = self.state_combo.currentData()
        real = p.resolve(st)
        try:
            self._frames = [(to_pixmap(img), ms) for img, ms in p.frames(st, 160)]
        except Exception as e:
            self._frames = []
            self.state_info.setText(f'無法載入：{e}')
            return
        info = f'{len(self._frames)} 格'
        if real != st:
            info += f'；沒有設定圖檔，沿用「{pet_pack.STATE_LABELS[real]}」'
        self.state_info.setText(info)
        self._i = 0
        self._t.stop()
        if self._frames:
            self.preview.setPixmap(self._frames[0][0])
            self._t.start(self._frames[0][1])

    def _next(self):
        if not self._frames:
            return
        self._i = (self._i + 1) % len(self._frames)
        self.preview.setPixmap(self._frames[self._i][0])
        self._t.start(self._frames[self._i][1])

    def _open_pets_dir(self):
        os.makedirs(self.s.pets_dir, exist_ok=True)
        os.startfile(self.s.pets_dir)


# ── 參考圖來源 ──
def sources_page(ctl) -> QWidget:
    w, lay = _page('參考圖來源', '速寫與臨摹研究共用。都不設定也能用：研究會用美術館的公有領域作品；速寫需要本機資料夾或圖庫金鑰其中一個。')
    g = SettingGroup('本機圖庫')
    g.row('參考圖資料夾', '底下的子資料夾會當作題目（例如「手部」「pose」），速寫任務會自動挑名稱相符的',
          _path_field(ctl, 'sources.local_dir', '選擇本機參考圖資料夾'), stack=True)
    lay.addWidget(g)

    g = SettingGroup('線上圖庫', '免費申請金鑰後填入，速寫就能用線上照片')
    for key, title, url in (('unsplash_key', 'Unsplash Access Key', 'https://unsplash.com/developers'),
                            ('pexels_key', 'Pexels API Key', 'https://www.pexels.com/api/')):
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        ed = QLineEdit(ctl.settings.get(f'sources.{key}', '') or '')
        ed.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        ed.setPlaceholderText('未設定')
        ed.setFixedWidth(260)
        ed.textChanged.connect(lambda v, k=key: (ctl.settings.set(f'sources.{k}', v.strip()), ctl.settings.save()))
        link = button('申請', 'link')
        link.clicked.connect(lambda _=False, u=url: webbrowser.open(u))
        row.addWidget(ed)
        row.addWidget(link)
        g.row(title, '', box)
    lay.addWidget(g)

    g = SettingGroup('練習畫布', '研究時按「畫布」會建立與參考圖同比例、依課程命名的 PSD')
    g.row('存放位置', '預設在「文件 › SAI2 練習 › 技能名稱」', _path_field(ctl, 'study.canvas_dir', '選擇練習畫布資料夾'), stack=True)
    side = QComboBox()
    for v in (1500, 2000, 3000, 4000):
        side.addItem(f'長邊 {v} px', v)
    side.setCurrentIndex(max(0, side.findData(int(ctl.settings.get('study.canvas_side', 2000)))))
    side.setFixedWidth(150)
    side.currentIndexChanged.connect(lambda _i: (ctl.settings.set('study.canvas_side', side.currentData()), ctl.settings.save()))
    g.row('畫布尺寸', '依參考圖的比例決定寬高', side)
    lay.addWidget(g)
    lay.addStretch(1)
    return w


# ── 快捷鍵 ──
class HotkeysPage(QWidget):
    def __init__(self, ctl):
        super().__init__()
        self.ctl = ctl
        self.s = ctl.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        head = PageHeader('快捷鍵', '在任何程式中都能使用。避免和 SAI2 或 1.x 的快捷鍵重複；留白代表不使用。')
        reset = button('恢復預設', ic='refresh')
        reset.clicked.connect(self._reset)
        head.actions.addWidget(reset)
        lay.addWidget(head)
        groups = [('寵物與面板', ('panel', 'toggle_pet', 'open_sai2', 'snapshot')),
                  ('參考小窗', ('ref_toggle', 'click_through', 'compare')),
                  ('速寫', ('sketch_next', 'sketch_pause'))]
        self.edits, self.rows = {}, {}
        for title, actions in groups:
            g = SettingGroup(title)
            for action in actions:
                label_text = hotkeys.ACTIONS[action][0]
                box = QWidget()
                row = QHBoxLayout(box)
                row.setContentsMargins(0, 0, 0, 0)
                ed = QKeySequenceEdit(QKeySequence(self.s.get(f'hotkeys.{action}', '') or ''))
                ed.setMaximumSequenceLength(1)
                ed.setFixedWidth(200)
                inner = ed.findChild(QLineEdit)
                if inner:
                    inner.setPlaceholderText('點這裡後按下快捷鍵')
                ed.editingFinished.connect(lambda a=action, e=ed: self._changed(a, e))
                clear = button('清除', 'ghost')
                clear.clicked.connect(lambda _=False, a=action, e=ed: (e.clear(), self._changed(a, e)))
                row.addWidget(ed)
                row.addWidget(clear)
                self.rows[action] = g.row(label_text, '', box)
                self.edits[action] = ed
            lay.addWidget(g)
        lay.addStretch(1)
        QTimer.singleShot(0, self._report)

    def _changed(self, action, ed):
        text = ed.keySequence().toString(QKeySequence.PortableText)
        try:
            text = hotkeys.normalize(text) if text else ''
        except ValueError as e:
            self.rows[action].set_note(str(e))
            return
        self.s.set(f'hotkeys.{action}', text)
        self.s.save()
        self._report()

    def _reset(self):
        for action, (_l, default) in hotkeys.ACTIONS.items():
            self.s.set(f'hotkeys.{action}', default)
            if action in self.edits:
                self.edits[action].setKeySequence(QKeySequence(default))
        self.s.save()
        self._report()

    def _report(self):
        failed = self.ctl.apply_hotkeys()
        conf = hotkeys.conflicts(self.s.get('hotkeys', {}))
        for action, row in self.rows.items():
            row.set_note(conf.get(action) or failed.get(action, ''))

