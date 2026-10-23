# -*- coding: utf-8 -*-
"""設定頁（放在主視窗的「設定」群組裡）：一般、寵物、參考圖來源、快捷鍵。變更立即套用並存檔"""

from __future__ import annotations

import os
import webbrowser

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QFrame, QHBoxLayout, QKeySequenceEdit, QLabel, QLineEdit, QMenu,
                               QPushButton, QSlider, QSpinBox, QVBoxLayout, QWidget)

from core import bubble_skin, hotkeys, pet_pack
from ui2 import theme
from ui2.bubble import BubbleBody
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


def _about_group(ctl, parent) -> SettingGroup:
    """版本、錯誤記錄、匯出診斷資訊（回報問題用）"""
    from core import diagnostics
    from core.version import APP_VERSION
    g = SettingGroup('關於與問題回報', '遇到問題時，把診斷資訊寄給開發者；不含圖庫金鑰、本機路徑與作品檔名')
    g.row('版本', '', label(APP_VERSION, 'muted', wrap=False))
    log = diagnostics.log_path(ctl.settings.app_dir)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    open_log = button('開啟錯誤記錄')
    export = button('匯出診斷資訊…', ic='file')
    row.addWidget(open_log)
    row.addWidget(export)
    g.row('錯誤記錄', '程式發生未預期的錯誤時會記在這裡', box)

    def show_log():
        if diagnostics.has_log(ctl.settings.app_dir):
            os.startfile(log)
        else:
            ctl.say('目前沒有錯誤記錄。', important=False)

    def do_export():
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(parent, '匯出診斷資訊', os.path.join(
            os.path.expanduser('~'), 'Desktop', f'DrawCompanion診斷_{datetime.now():%Y%m%d_%H%M}.zip'), '壓縮檔 (*.zip)')
        if not path:
            return
        st = ctl.last_status
        extra = {'paused_for_1x': bool(ctl.service.paused),
                 'sai2_running': bool(st and st.sai2_running), 'pet_pack': ctl.settings.get('pet.pack', '') or 'builtin'}
        try:
            diagnostics.export_bundle(ctl.settings, path, extra)
        except OSError as e:
            ctl.say(f'匯出失敗：{e}')
            return
        ctl.say('已匯出診斷資訊。', actions=[('開啟資料夾', lambda: os.startfile(os.path.dirname(path)))])
    open_log.clicked.connect(show_log)
    export.clicked.connect(do_export)
    return g


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
    g.row('自動擷取作品縮圖', '存檔、停筆時擷取 SAI2 畫布，作品頁就能看到預覽（只存在這台電腦）',
          _toggle(ctl, 'works.thumbnails'))
    lang = QComboBox()
    lang.addItem('繁體中文')
    lang.setEnabled(False)
    lang.setFixedWidth(150)
    g.row('語言', '目前只有繁體中文；英文、日文預計在 2.1 加入', lang)
    lay.addWidget(g)

    g = SettingGroup('備份與分享', '把主題、寵物角色、快捷面板、規則、快捷鍵打包成一個檔案；本機的資料夾路徑不會匯出')
    keys = ToggleSwitch(False)
    g.row('匯出時包含圖庫 API 金鑰', '只給自己備份時再打開；分享給別人時請關閉', keys)
    box = QWidget()
    row = QHBoxLayout(box)
    row.setContentsMargins(0, 0, 0, 0)
    exp = button('匯出設定…', ic='file')
    imp = button('匯入設定…', ic='works')
    row.addWidget(exp)
    row.addWidget(imp)
    g.row('設定檔', '匯入時會合併設定，角色包以新名稱加入，不會覆蓋現有的', box)

    def do_export():
        from core import backup
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(w, '匯出設定', os.path.join(os.path.expanduser('~'), 'Desktop',
                                              f'DrawCompanion設定_{datetime.now():%Y%m%d}.zip'), '設定檔 (*.zip)')
        if not path:
            return
        try:
            info = backup.export_bundle(ctl.settings, path, include_secrets=keys.isChecked())
        except OSError as e:
            ctl.say(f'匯出失敗：{e}')
            return
        ctl.say(f"已匯出設定（含 {info['pets']} 個角色）。", actions=[('開啟資料夾', lambda: os.startfile(os.path.dirname(path)))])

    def do_import():
        from core import backup
        path, _ = QFileDialog.getOpenFileName(w, '匯入設定', '', '設定檔 (*.zip)')
        if not path:
            return
        try:
            info = backup.import_bundle(ctl.settings, path)
        except (ValueError, OSError) as e:
            ctl.say(f'匯入失敗：{e}')
            return
        ctl.reload_settings()
        ctl.say(f"設定匯入完成（新增 {len(info['pets'])} 個角色）。", important=False)
    exp.clicked.connect(do_export)
    imp.clicked.connect(do_import)
    lay.addWidget(g)
    lay.addWidget(_about_group(ctl, w))
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
        head = PageHeader('寵物', '換成自己畫的角色：建立新角色並指定各狀態的圖檔，或匯入別人分享的角色包')
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

        # 角色工作室
        self.studio = Card('角色工作室', '每個狀態可以放不同的動畫；沒有設定的狀態會沿用其他狀態')
        imp = button('匯入角色包', 'ghost', ic='works')
        imp.clicked.connect(self._import_menu)
        new = button('建立新角色', ic='canvas')
        new.clicked.connect(lambda: self.new_form.setVisible(not self.new_form.isVisible()))
        self.studio.head.addWidget(imp)
        self.studio.head.addWidget(new)
        self.new_form = QWidget()
        nf = QHBoxLayout(self.new_form)
        nf.setContentsMargins(0, 0, 0, 0)
        self.new_name = QLineEdit()
        self.new_name.setPlaceholderText('角色名稱')
        self.new_idle = ''
        self.new_pick = button('選擇「待命」圖檔…')
        self.new_pick.clicked.connect(self._pick_new_idle)
        create = button('建立', 'primary')
        create.clicked.connect(self._create_pack)
        nf.addWidget(self.new_name, 1)
        nf.addWidget(self.new_pick)
        nf.addWidget(create)
        self.new_form.hide()
        self.studio.lay.addWidget(self.new_form)
        self.studio_body = QVBoxLayout()
        self.studio_body.setSpacing(0)
        self.studio.lay.addLayout(self.studio_body)
        lay.addWidget(self.studio)

        g = SettingGroup('外觀')
        g.row('大小', '', self._slider('pet.size', 48, 256, lambda v: f'{v} px', True))
        g.row('透明度', '', self._slider('pet.opacity', 20, 100, lambda v: f'{v}%', False, scale=100))
        g.row('動筆時變半透明', '畫圖時寵物不會擋住視線', _toggle(ctl, 'pet.fade_when_drawing', self._apply))
        g.row('拖曳放開時貼齊螢幕邊緣', '', _toggle(ctl, 'pet.snap_edges', self._apply))
        g.row('內建角色跟隨主題色', '「墨墨」的身體顏色換成目前的主色；自己的角色不受影響',
              _toggle(ctl, 'pet.tint_builtin', lambda: (self._apply(True), self._reload_packs(), self._preview_state())))
        g.row('寵物下方顯示計時與錄影開關', '本次動筆時間；紅點可開始／停止縮時錄影（取代 1.x 精簡模式）',
              _toggle(ctl, 'pet.show_timer'))
        lay.addWidget(g)

        g = SettingGroup('對話泡泡', '休息提醒、夜間睡覺改在「規則」頁設定，可以同時讓寵物說話和做動作')
        seg = Segmented([('important', '只有重要的'), ('all', '全部'), ('off', '關閉')], self.s.get('pet.bubbles', 'important'))
        seg.changed.connect(lambda v: (self.s.set('pet.bubbles', v), self.s.save()))
        g.row('要顯示哪些訊息', '', seg)
        lay.addWidget(g)
        lay.addWidget(self._bubble_card())
        lay.addStretch(1)

        self._frames, self._i = [], 0
        self._t = QTimer(self, timeout=self._next)
        self._reload_packs()
        self.pack_combo.currentIndexChanged.connect(self._pack_changed)
        reload_btn.clicked.connect(lambda: (self._reload_packs(), self._preview_state()))
        self.state_combo.currentIndexChanged.connect(lambda *_: self._preview_state())
        self._preview_state()
        self._refresh_studio()

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

    # ── 對話泡泡外觀 ──
    def _bubble_card(self) -> Card:
        card = Card('對話泡泡外觀', '用一張圖當泡泡：圈出放文字的範圍，其他部分以九宮格延伸，四個角不會變形')
        pick = button('選擇圖片…', ic='canvas')
        pick.clicked.connect(self._bubble_pick)
        card.head.addWidget(pick)
        body = QHBoxLayout()
        body.setSpacing(24)
        stage = QFrame()
        stage.setObjectName('bubbleStage')
        stage.setStyleSheet(f'#bubbleStage{{background:{theme.BG};border-radius:12px;}}')
        stage.setMinimumSize(300, 150)
        sl = QVBoxLayout(stage)
        sl.setContentsMargins(16, 16, 16, 16)
        self.bubble_preview = BubbleBody()
        sl.addWidget(self.bubble_preview, 0, Qt.AlignCenter)
        body.addWidget(stage, 1)
        side = QVBoxLayout()
        side.setSpacing(10)
        self.bubble_range = button('圈選文字範圍…')
        self.bubble_range.clicked.connect(self._bubble_edit_range)
        self.bubble_color = button('文字顏色')
        self.bubble_color.clicked.connect(self._bubble_pick_color)
        self.bubble_reset = button('還原內建泡泡', 'ghost')
        self.bubble_reset.clicked.connect(self._bubble_restore)
        scale = QWidget()
        sr = QHBoxLayout(scale)
        sr.setContentsMargins(0, 0, 0, 0)
        sr.addWidget(label('大小', 'muted', wrap=False))
        self.bubble_scale = QSlider(Qt.Horizontal)
        lo, hi = bubble_skin.SCALES
        self.bubble_scale.setRange(int(lo * 100), int(hi * 100))
        self.bubble_scale.setFixedWidth(160)
        self.bubble_scale_lb = label('', 'muted', wrap=False)
        self.bubble_scale_lb.setFixedWidth(44)
        self.bubble_scale.valueChanged.connect(self._bubble_scale_changed)
        sr.addWidget(self.bubble_scale)
        sr.addWidget(self.bubble_scale_lb)
        for w in (self.bubble_range, self.bubble_color, scale, self.bubble_reset):
            side.addWidget(w, 0, Qt.AlignLeft)
        side.addStretch(1)
        body.addLayout(side)
        card.lay.addLayout(body)
        card.lay.addWidget(label('建議用透明背景的 PNG；圖案的花紋、尾巴要放在文字範圍外面。'
                                 '圖片會複製到設定資料夾，原檔可以移動或刪除。', 'caption'))
        self._bubble_refresh()
        return card

    def _bubble_skin(self) -> dict:
        return bubble_skin.normalize(self.s.get('pet.bubble_skin'))

    def _bubble_save(self, skin: dict):
        self.s.set('pet.bubble_skin', skin)
        self.s.save()
        self.ctl.apply_bubble_skin()
        self._bubble_refresh()

    def _bubble_refresh(self):
        skin = self._bubble_skin()
        path = bubble_skin.image_path(self.s.app_dir, skin)
        self.bubble_preview.set_skin(skin, path)
        self.bubble_preview.set_message('已經連續畫了 50 分鐘，起來喝口水、動一動吧')
        self.bubble_preview.fit()
        for w in (self.bubble_range, self.bubble_color, self.bubble_scale, self.bubble_reset):
            w.setEnabled(bool(path))
        self.bubble_scale.blockSignals(True)
        self.bubble_scale.setValue(int(round(skin['scale'] * 100)))
        self.bubble_scale.blockSignals(False)
        self.bubble_scale_lb.setText(f"{int(round(skin['scale'] * 100))}%")
        from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
        sw = QPixmap(14, 14)
        sw.fill(Qt.transparent)
        p = QPainter(sw)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor(255, 255, 255, 120))
        p.setBrush(QColor(skin['color']))
        p.drawRoundedRect(1, 1, 12, 12, 3, 3)
        p.end()
        self.bubble_color.setIcon(QIcon(sw))

    def _bubble_pick(self):
        path, _ = QFileDialog.getOpenFileName(self, '選擇泡泡圖片', '', '圖片 (*.png *.webp *.gif *.jpg *.jpeg *.bmp)')
        if not path:
            return
        try:
            name, w, h = bubble_skin.import_image(self.s.app_dir, path)
        except ValueError as e:
            self.ctl.say(str(e))
            return
        skin = self._bubble_skin()
        skin.update(image=name, text=bubble_skin.default_text_rect(w, h))
        self._bubble_save(skin)
        bubble_skin.remove_unused(self.s.app_dir, keep=name)
        self._bubble_edit_range()

    def _bubble_edit_range(self):
        from ui2.bubble_editor import TextRangeDialog
        skin = self._bubble_skin()
        path = bubble_skin.image_path(self.s.app_dir, skin)
        if not path:
            return
        dlg = TextRangeDialog(self, path, skin)
        if dlg.exec():
            skin['text'] = dlg.result_rect()
            self._bubble_save(skin)

    def _bubble_pick_color(self):
        from PySide6.QtGui import QColor
        from PySide6.QtWidgets import QColorDialog
        skin = self._bubble_skin()
        c = QColorDialog.getColor(QColor(skin['color']), self, '文字顏色')
        if c.isValid():
            skin['color'] = c.name()
            self._bubble_save(skin)

    def _bubble_scale_changed(self, v: int):
        skin = self._bubble_skin()
        skin['scale'] = v / 100
        self._bubble_save(skin)

    def _bubble_restore(self):
        self._bubble_save(bubble_skin.normalize(None))
        bubble_skin.remove_unused(self.s.app_dir)

    def _reload_packs(self):
        self.packs = pet_pack.list_packs(self.s.pets_dir, self.ctl.pet_tint())
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
        self._refresh_studio()

    # ── 角色工作室 ──
    def _current_pack(self):
        return self.packs[self.pack_combo.currentIndex()]

    def _after_edit(self, select: str | None = None):
        if select is not None:
            self.s.set('pet.pack', select)
            self.s.save()
        self._reload_packs()
        self._apply(True)
        self._preview_state()
        self._refresh_studio()

    def _refresh_studio(self):
        lay = self.studio_body
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        pack = self._current_pack()
        if pack.builtin:
            lay.addWidget(label('內建角色「墨墨」不能修改。按「建立新角色」用自己畫的圖，或匯入角色包。', 'muted'))
            return
        for i, st in enumerate(pet_pack.STATES):
            if i:
                line = QFrame()
                line.setProperty('divider', True)
                line.setFixedHeight(1)
                lay.addWidget(line)
            lay.addWidget(self._state_row(pack, st))
        actions = QHBoxLayout()
        ren = QLineEdit(pack.name)
        ren.setPlaceholderText('角色名稱')
        ren.editingFinished.connect(lambda: self._rename(pack, ren.text()))
        actions.addWidget(label('名稱', 'caption'))
        actions.addWidget(ren, 1)
        folder = button('開啟資料夾', 'ghost', ic='works')
        folder.clicked.connect(lambda: os.startfile(pack.folder))
        actions.addWidget(folder)
        delete = button('刪除角色', 'ghost')
        delete.setStyleSheet(f'color:{theme.DANGER};')
        confirm = button('確定刪除', 'primary')
        confirm.setStyleSheet('background:#b91c1c;')
        confirm.hide()
        delete.clicked.connect(lambda: (delete.hide(), confirm.show()))
        confirm.clicked.connect(lambda: self._delete_pack(pack))
        actions.addWidget(delete)
        actions.addWidget(confirm)
        holder = QWidget()
        holder.setLayout(actions)
        actions.setContentsMargins(0, 14, 0, 0)
        lay.addWidget(holder)

    def _state_row(self, pack, st):
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(4, 10, 4, 10)
        row.setSpacing(12)
        name = label(pet_pack.STATE_LABELS[st], 'body', wrap=False)
        name.setFixedWidth(64)
        row.addWidget(name)
        spec = pack.states.get(st)
        if spec:
            text = spec['file']
            if spec.get('frames'):
                text += f"（精靈圖 {spec['frames']} 格・{spec.get('fps') or 12:g} fps）"
            info = label(text, 'muted', wrap=False)
        else:
            info = label(f"沿用「{pet_pack.STATE_LABELS[pack.resolve(st)]}」", 'caption', wrap=False)
        row.addWidget(info, 1)
        if spec and spec['file'].lower().endswith('.png'):
            fr = QSpinBox()
            fr.setRange(1, pet_pack.MAX_FRAMES)
            fr.setValue(int(spec.get('frames') or 1))
            fr.setPrefix('格數 ')
            fr.setToolTip('橫排精靈圖的格數；1 = 單張圖')
            fr.setFixedWidth(110)
            fr.editingFinished.connect(lambda f=fr: self._set_frames(pack, st, f.value()))
            row.addWidget(fr)
        see = button('預覽', 'ghost')
        see.clicked.connect(lambda: self.state_combo.setCurrentIndex(pet_pack.STATES.index(st)))
        row.addWidget(see)
        pick = button('換圖' if spec else '指定圖檔')
        pick.clicked.connect(lambda: self._pick_state(pack, st))
        row.addWidget(pick)
        if spec and st != 'idle':
            clr = button('清除', 'ghost')
            clr.clicked.connect(lambda: self._clear_state(pack, st))
            row.addWidget(clr)
        return w

    def _ask_image(self, title):
        path, _ = QFileDialog.getOpenFileName(self, title, '', '圖片 (*.png *.apng *.gif *.webp)')
        return path

    def _pick_state(self, pack, st):
        path = self._ask_image(f'選擇「{pet_pack.STATE_LABELS[st]}」的圖檔')
        if not path:
            return
        try:
            pet_pack.set_state(pack.folder, st, path)
        except (ValueError, OSError) as e:
            self.ctl.say(str(e))
            return
        self.state_combo.setCurrentIndex(pet_pack.STATES.index(st))
        self._after_edit()

    def _set_frames(self, pack, st, n):
        try:
            pet_pack.set_state(pack.folder, st, frames=n)
        except (ValueError, OSError) as e:
            self.ctl.say(str(e))
            return
        self._after_edit()

    def _clear_state(self, pack, st):
        try:
            pet_pack.clear_state(pack.folder, st)
        except (ValueError, OSError) as e:
            self.ctl.say(str(e))
            return
        self._after_edit()

    def _rename(self, pack, name):
        if name.strip() and name.strip() != pack.name:
            pet_pack.rename_pack(pack.folder, name)
            self._after_edit()

    def _delete_pack(self, pack):
        try:
            pet_pack.delete_pack(self.s.pets_dir, pack.pack_id)
        except (ValueError, OSError) as e:
            self.ctl.say(str(e))
            return
        self.ctl.say(f'已刪除角色「{pack.name}」。', important=False)
        self._after_edit('')

    def _pick_new_idle(self):
        path = self._ask_image('選擇「待命」的圖檔（之後可以再加其他狀態）')
        if path:
            self.new_idle = path
            self.new_pick.setText(os.path.basename(path))

    def _create_pack(self):
        if not self.new_idle:
            self.ctl.say('請先選擇「待命」的圖檔。')
            return
        try:
            pid = pet_pack.create_pack(self.s.pets_dir, self.new_name.text() or '我的角色', self.new_idle)
        except (ValueError, OSError) as e:
            self.ctl.say(str(e))
            return
        self.new_form.hide()
        self.new_name.clear()
        self.new_idle = ''
        self.new_pick.setText('選擇「待命」圖檔…')
        self.ctl.say('角色建立好了！接著可以替其他狀態指定圖檔。', important=False)
        self._after_edit(pid)

    def _import_menu(self):
        m = QMenu(self)
        m.addAction('從 zip 檔匯入…', lambda: self._import(True))
        m.addAction('從資料夾匯入…', lambda: self._import(False))
        m.exec(self.cursor().pos())

    def _import(self, from_zip):
        if from_zip:
            src, _ = QFileDialog.getOpenFileName(self, '選擇角色包', '', '角色包 (*.zip)')
        else:
            src = QFileDialog.getExistingDirectory(self, '選擇角色資料夾')
        if not src:
            return
        try:
            pid = pet_pack.import_pack(src, self.s.pets_dir)
        except (ValueError, OSError) as e:
            self.ctl.say(f'匯入失敗：{e}')
            return
        self.ctl.say('角色包匯入完成，已經換上了！', important=False)
        self._after_edit(pid)

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


# ── 快捷面板 ──
class PanelPage(QWidget):
    """快捷面板的區塊順序與開關、6 格快捷按鈕（內建或自訂動作）"""

    def __init__(self, ctl):
        super().__init__()
        from core import slots as SL
        self.SL = SL
        self.ctl = ctl
        self.s = ctl.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        lay.addWidget(PageHeader('快捷面板', '點寵物出現的面板：要顯示哪些區塊、順序，以及 6 格快捷按鈕要做什麼'))
        self.blocks_group = SettingGroup('區塊', '用箭頭調整順序；關閉的區塊不會顯示')
        lay.addWidget(self.blocks_group)
        g = SettingGroup('最近開啟')
        g.row('顯示幾個檔案', '', _spin(ctl, 'panel.recent_count', 2, 8, ' 個', int))
        lay.addWidget(g)
        self.slots_group = SettingGroup('快捷按鈕', '每格可以是內建功能，或開啟檔案／資料夾、執行程式、開網址')
        lay.addWidget(self.slots_group)
        lay.addStretch(1)
        self._build_blocks()
        self._build_slots()

    def _clear_group(self, g):
        while g.inner.count():
            w = g.inner.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        g._rows = 0

    def _build_blocks(self):
        self._clear_group(self.blocks_group)
        order, on = self._order()
        for i, b in enumerate(order):
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            up = button('', 'ghost', ic='up', tip='往上')
            up.setEnabled(i > 0)
            down = button('', 'ghost', ic='down', tip='往下')
            down.setEnabled(i < len(order) - 1)
            up.clicked.connect(lambda _=False, k=b: self._move(k, -1))
            down.clicked.connect(lambda _=False, k=b: self._move(k, 1))
            t = ToggleSwitch(b in on)
            t.toggled.connect(lambda v, k=b: self._toggle_block(k, v))
            row.addWidget(up)
            row.addWidget(down)
            row.addSpacing(8)
            row.addWidget(t)
            self.blocks_group.row(self.SL.BLOCKS[b], '', box)

    def _save_blocks(self, order, on):
        self.s.set('panel.blocks', [b for b in order if b in on])
        self.s.save()

    def _move(self, key, delta):
        order, on = self._order()
        i = order.index(key)
        j = max(0, min(len(order) - 1, i + delta))
        order[i], order[j] = order[j], order[i]
        self.s.set('panel.block_order', order)
        self._save_blocks(order, on)
        self._build_blocks()

    def _toggle_block(self, key, v):
        order, on = self._order()
        (on.add if v else on.discard)(key)
        self._save_blocks(order, on)

    def _order(self):
        """(全部區塊的排列順序, 開著的區塊)；關閉的區塊也要記住位置，重新打開時回到原處"""
        on = self.SL.normalize_blocks(self.s.get('panel.blocks', []))
        saved =[b for b in (self.s.get('panel.block_order') or []) if b in self.SL.BLOCKS]
        base = saved or (on + [b for b in self.SL.BLOCKS if b not in on])
        order = base + [b for b in self.SL.BLOCKS if b not in base]
        return order, set(on)

    def _build_slots(self):
        self._clear_group(self.slots_group)
        entries = self.SL.normalize_slots(self.s.get('panel.slots', []))
        for i, e in enumerate(entries):
            self.slots_group.add(self._slot_row(i, e))

    def _slot_row(self, i, entry):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 12, 18, 12)
        lay.setSpacing(8)
        top = QHBoxLayout()
        top.addWidget(label(f'第 {i + 1} 格', 'body', wrap=False))
        top.addStretch(1)
        kind = QComboBox()
        kind.setMinimumWidth(200)
        kind.addItem('（空）', None)
        for k, (text, _ic, _tip) in self.SL.BUILTIN.items():
            kind.addItem(text if k != 'open_sai2' else '開啟 SAI2', k)
        for k, (text, _ic) in self.SL.CUSTOM.items():
            kind.addItem(f'自訂：{text}', f'custom:{k}')
        cur = entry if isinstance(entry, str) or entry is None else f"custom:{entry.get('type')}"
        kind.setCurrentIndex(max(0, kind.findData(cur)))
        top.addWidget(kind)
        lay.addLayout(top)
        note = label('', 'warn')
        note.hide()
        if isinstance(entry, dict):
            form = QHBoxLayout()
            name = QLineEdit(entry.get('label', ''))
            name.setPlaceholderText('按鈕文字（最多 6 字）')
            name.setMaxLength(6)
            name.setFixedWidth(150)
            target = QLineEdit(entry.get('target', ''))
            target.setPlaceholderText({'url': 'https://…', 'program': '程式路徑（.exe）', 'path': '檔案或資料夾路徑'}[entry['type']])
            form.addWidget(name)
            form.addWidget(target, 1)
            if entry['type'] != 'url':
                pick = button('瀏覽…')
                pick.clicked.connect(lambda: self._browse(entry['type'], target))
                form.addWidget(pick)
            lay.addLayout(form)
            args = None
            if entry['type'] == 'program':
                args = QLineEdit(entry.get('args', ''))
                args.setPlaceholderText('啟動參數（可留白）')
                lay.addWidget(args)

            def save_custom():
                new = {'type': entry['type'], 'label': name.text().strip(), 'target': target.text().strip()}
                if args is not None:
                    new['args'] = args.text().strip()
                err = self.SL.validate(new)
                note.setText(err or '')
                note.setVisible(bool(err))
                self._set_slot(i, new, rebuild=False)
            for ed in (name, target) + ((args,) if args is not None else ()):
                ed.editingFinished.connect(save_custom)
        lay.addWidget(note)
        kind.currentIndexChanged.connect(lambda _i: self._kind_changed(i, kind.currentData()))
        return w

    def _browse(self, kind, target):
        if kind == 'path':
            path = QFileDialog.getExistingDirectory(self, '選擇資料夾', target.text())
            if not path:
                path, _ = QFileDialog.getOpenFileName(self, '或選擇檔案', target.text())
        else:
            path, _ = QFileDialog.getOpenFileName(self, '選擇程式', target.text(), '程式 (*.exe *.bat *.cmd *.lnk)')
        if path:
            target.setText(os.path.normpath(path))
            target.editingFinished.emit()

    def _kind_changed(self, i, data):
        if isinstance(data, str) and data.startswith('custom:'):
            entry = {'type': data.split(':', 1)[1], 'label': '', 'target': ''}
        else:
            entry = data
        self._set_slot(i, entry, rebuild=True)

    def _set_slot(self, i, entry, rebuild):
        entries = self.SL.normalize_slots(self.s.get('panel.slots', []))
        entries[i] = entry
        self.s.set('panel.slots', entries)
        self.s.save()
        if rebuild:
            self._build_slots()


# ── 規則 ──
class RulesPage(QWidget):
    def __init__(self, ctl):
        super().__init__()
        from core import rules as R
        self.R = R
        self.ctl = ctl
        self.s = ctl.settings
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        head = PageHeader('規則', '讓 DrawCompanion 自動做事：如果發生某件事，就執行某個動作')
        ex = button('加入範例', 'ghost', ic='canvas')
        ex.clicked.connect(self._add_examples)
        add = button('新增規則', 'primary', ic='canvas')
        add.clicked.connect(self._add)
        head.actions.addWidget(ex)
        head.actions.addWidget(add)
        lay.addWidget(head)
        self.group = SettingGroup('我的規則', '休息提醒、夜間睡覺也在這裡設定。1.x 執行中時規則暫停')
        lay.addWidget(self.group)
        lay.addStretch(1)
        self._build()

    def _rules(self):
        return list(self.s.get('rules', []) or [])

    def _save(self, rules):
        self.s.set('rules', rules)
        self.s.save()

    def _scroll_area(self):
        from PySide6.QtWidgets import QScrollArea
        w = self.parentWidget()
        while w is not None and not isinstance(w, QScrollArea):
            w = w.parentWidget()
        return w

    def _scroll_bar(self):
        sa = self._scroll_area()
        return sa.verticalScrollBar() if sa is not None else None

    def _build(self):
        sa = self._scroll_area()
        bar = sa.verticalScrollBar() if sa is not None else None
        keep = bar.value() if bar is not None else None
        fw = QApplication.focusWidget()
        if sa is not None and fw is not None and self.isAncestorOf(fw):
            # 焦點所在的元件要被移除：先把焦點交給捲動區本身。否則 Qt 會自己挑下一個元件，
            # 捲動區再捲過去讓它可見（常常捲回最上面）
            sa.setFocus(Qt.OtherFocusReason)
        self.setUpdatesEnabled(False)
        try:
            self._rebuild()
        finally:
            if bar is not None:
                self.layout().activate()          # 先算好新高度，捲軸範圍才不會把位置夾掉
                bar.setValue(keep)
                self._pin_scroll(bar, keep)
            self.setUpdatesEnabled(True)

    def _pin_scroll(self, bar, keep: int):
        """重排版面時捲動範圍會短暫縮成 0（位置被夾到最上面），之後才恢復；這段時間內範圍一恢復就把位置放回去"""
        self._keep_scroll = keep
        if getattr(self, '_pin_timer', None) is None:
            # 同一個計時器重新計時：連續操作時，前一次的計時不會提早解除這一次的固定
            self._pin_timer = QTimer(self, singleShot=True, interval=500,
                                     timeout=lambda: setattr(self, '_keep_scroll', None))
            bar.rangeChanged.connect(lambda _lo, hi: bar.setValue(self._keep_scroll)
                                     if self._keep_scroll is not None and hi >= self._keep_scroll else None)
        self._pin_timer.start()
        QTimer.singleShot(0, lambda: bar.setValue(keep))

    def _rebuild(self):
        g = self.group
        while g.inner.count():
            w = g.inner.takeAt(0).widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        g._rows = 0
        rules = self._rules()
        if not rules:
            empty = QWidget()
            el = QVBoxLayout(empty)
            el.setContentsMargins(18, 18, 18, 18)
            el.addWidget(label('還沒有規則。按「新增規則」，或「加入範例」看看可以怎麼用。', 'muted'))
            g.add(empty)
        for r in rules:
            g.add(self._row(r))

    def _value_widget(self, kind, value, placeholder, choices=None):
        if kind == 'int':
            w = QSpinBox()
            w.setRange(1, 600)
            w.setValue(int(value or 60))
            w.setSuffix(' 分')
            w.setFixedWidth(110)
            return w, lambda: w.value(), w.editingFinished
        if kind == 'choice':
            w = QComboBox()
            for k, text in (choices or {}).items():
                w.addItem(text, k)
            w.setCurrentIndex(max(0, w.findData(value)))
            return w, lambda: w.currentData(), w.currentIndexChanged
        if kind in ('text', 'time'):
            w = QLineEdit('' if value is None else str(value))
            w.setPlaceholderText(placeholder)
            if kind == 'time':
                w.setFixedWidth(90)
            return w, lambda: w.text().strip(), w.editingFinished
        return None, lambda: '', None

    def _row(self, rule):
        R = self.R
        rule = R.normalize(rule)
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(18, 14, 18, 14)
        lay.setSpacing(8)
        line1 = QHBoxLayout()
        on = ToggleSwitch(rule.get('enabled', True))
        line1.addWidget(on)
        line1.addWidget(label('如果', 'muted', wrap=False))
        tcombo = QComboBox()
        for k, (text, _p, _k) in R.TRIGGERS.items():
            tcombo.addItem(text, k)
        tcombo.setCurrentIndex(max(0, tcombo.findData(rule['trigger']['type'])))
        line1.addWidget(tcombo)
        tdef = R.TRIGGERS[rule['trigger']['type']]
        tval, tget, tsig = self._value_widget(tdef[2], rule['trigger'].get('value'), tdef[1])
        if tval:
            line1.addWidget(tval)
        line1.addStretch(1)
        delete = button('', 'ghost', ic='close', tip='刪除這條規則')
        line1.addWidget(delete)
        lay.addLayout(line1)

        rows = []                                  # [(類型下拉, 取值, 原本的動作)]
        acts = rule['actions']
        for i, act in enumerate(acts):
            line = QHBoxLayout()
            line.addSpacing(52)
            line.addWidget(label('就' if i == 0 else '並且', 'muted', wrap=False))
            acombo = QComboBox()
            for k, (text, _p, _k) in R.ACTIONS.items():
                acombo.addItem(text, k)
            acombo.setCurrentIndex(max(0, acombo.findData(act['type'])))
            line.addWidget(acombo)
            adef = R.ACTIONS[act['type']]
            aval, aget, asig = self._value_widget(adef[2], act.get('value'), adef[1], R.PET_ACTIONS)
            if aval:
                line.addWidget(aval, 1)
            else:
                line.addStretch(1)
            if len(acts) > 1:
                rm = button('', 'ghost', ic='minimize', tip='移除這個動作')
                rm.clicked.connect(lambda _=False, idx=i: save(rebuild=True, drop=idx))
                line.addWidget(rm)
            lay.addLayout(line)
            rows.append((acombo, aget, act, asig))
        more = QHBoxLayout()
        more.addSpacing(52)
        add_act = button('＋ 再加一個動作', 'link')
        add_act.setToolTip('例如寵物說話的同時做動作')
        add_act.clicked.connect(lambda: save(rebuild=True, add=True))
        more.addWidget(add_act)
        more.addStretch(1)
        lay.addLayout(more)
        note = label('', 'warn')
        lay.addWidget(note)

        def save(rebuild=False, add=False, drop=None):
            nt = tcombo.currentData()
            tv = tget() if nt == rule['trigger']['type'] else (60 if nt == 'draw_minutes' else '')
            new_acts = []
            for i, (combo, getter, orig, _sig) in enumerate(rows):
                if i == drop:
                    continue
                na = combo.currentData()
                if na == orig['type']:
                    val = getter()
                else:
                    val = 'cheer' if na == 'pet' else ''
                new_acts.append({'type': na, 'value': val})
            if add:
                new_acts.append({'type': 'pet', 'value': 'cheer'})
            new = {'id': rule['id'], 'enabled': on.isChecked(), 'trigger': {'type': nt, 'value': tv}, 'actions': new_acts}
            err = R.validate(new)
            note.setText(err or '')
            note.setVisible(bool(err))
            self._save([new if x.get('id') == rule['id'] else x for x in self._rules()])
            if rebuild:
                self._build()
        on.toggled.connect(lambda _v: save())
        tcombo.currentIndexChanged.connect(lambda _i: save(True))
        if tsig is not None:
            tsig.connect(lambda *_: save())
        for combo, _g, _o, sig in rows:
            combo.currentIndexChanged.connect(lambda _i: save(True))
            if sig is not None:
                sig.connect(lambda *_: save())
        delete.clicked.connect(lambda: (self._save([x for x in self._rules() if x.get('id') != rule['id']]), self._build()))
        err = R.validate(rule)
        note.setText(err or '')
        note.setVisible(bool(err))
        return w

    def _add(self):
        self._save(self._rules() + [self.R.new_rule()])
        self._build()

    def _add_examples(self):
        have = {self.R.describe(r) for r in self._rules()}
        add = [self.R.new_rule(e['trigger'], e['actions']) for e in self.R.EXAMPLES]
        self._save(self._rules() + [r for r in add if self.R.describe(r) not in have])
        self._build()


# ── 外觀 ──
def appearance_page(ctl) -> QWidget:
    w, lay = _page('外觀', '主色與深淺色會套用到主視窗、快捷面板與設定；參考小窗固定深色，疊在畫布上比較不刺眼')
    g = SettingGroup('主題')
    swatches = QWidget()
    row = QHBoxLayout(swatches)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(10)
    cur = ctl.settings.get('theme.accent', 'purple')
    for key, (name, acc, _b, _h, _t) in theme.ACCENTS.items():
        b = QPushButton()
        b.setFixedSize(32, 32)
        b.setToolTip(name)
        b.setCursor(Qt.PointingHandCursor)
        ring = theme.TEXT if key == cur else 'transparent'
        b.setStyleSheet(f'QPushButton{{background:{acc};border-radius:16px;border:3px solid {ring};padding:0;}}')
        b.clicked.connect(lambda _=False, k=key: ctl.set_theme(accent=k))
        row.addWidget(b)
    g.row('主色', '按鈕、選取、進度條的顏色', swatches)
    seg = Segmented(list(theme.MODES.items()), ctl.settings.get('theme.mode', 'dark'))
    seg.changed.connect(lambda v: ctl.set_theme(mode=v))
    g.row('深色／淺色', '「跟隨 Windows」會依系統的應用程式模式切換', seg)
    lay.addWidget(g)
    g = SettingGroup('無障礙', '主視窗可以用 Ctrl+Tab 切換頁面、Tab 移動到各個按鈕，側欄可以用上下鍵')

    def motion(on):
        theme.MOTION = not on
    g.row('減少動態效果', '開關等元件不做滑動動畫', _toggle(ctl, 'theme.reduce_motion',
                                                     lambda: motion(ctl.settings.get('theme.reduce_motion'))))
    lay.addWidget(g)
    lay.addStretch(1)
    return w


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
        groups = [('寵物與面板', ('panel', 'toggle_pet', 'open_sai2', 'snapshot', 'record_toggle')),
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
