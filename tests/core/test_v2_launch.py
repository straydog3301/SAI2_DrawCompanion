# -*- coding: utf-8 -*-
"""2.0 程式行為：單一實例（具名 Mutex）、SAI2 開檔流程（以假的 Win32 backend 代替真的 SAI2）"""
import os
import sys
import uuid
import subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _helpers import check, done, block_tk, REPO  # noqa: E402

block_tk()
from core.single_instance import SingleInstance  # noqa: E402
from core import sai2_launcher as L  # noqa: E402

# ─── 單一實例 ───────────────────────────────────────────────────────────
name = 'SAI2DC_test_' + uuid.uuid4().hex
first = SingleInstance(name)
check(first.acquire(), 'first instance acquires')
second = SingleInstance(name)
check(not second.acquire(), 'second handle in same process sees existing mutex')
probe = ('import sys; sys.path.insert(0, sys.argv[1]); from core.single_instance import SingleInstance; '
         'sys.exit(0 if SingleInstance(sys.argv[2]).acquire() else 3)')
r = subprocess.run([sys.executable, '-c', probe, REPO, name])
check(r.returncode == 3, f'other process is refused while first runs ({r.returncode})')
second.release()
first.release()
r = subprocess.run([sys.executable, '-c', probe, REPO, name])
check(r.returncode == 0, 'acquirable again after release')

# ─── 名稱比對與標題 ─────────────────────────────────────────────────────
check(L.is_sai2_exe_name('SAI2.EXE') and not L.is_sai2_exe_name('sai2SManager.exe'), 'exact exe names')
check(not L.is_sai2_exe_name('SAI2_DrawCompanion.exe') and not L.is_sai2_exe_name('saiyan.exe'), 'no substring match')
check(L.is_sai2_exe_name('sai2_portable.exe', ('sai2_portable.exe',)), 'extra name from settings')
check(L.title_has_file('practice.psd - PaintTool SAI Ver.2 (64bit)', r'C:\x\practice.psd'), 'title file at left')
check(L.title_has_file('* practice.psd - PaintTool SAI Ver.2', r'C:\x\Practice.psd'), 'unsaved marker + case')
check(L.title_has_file('PaintTool SAI Ver.2 (64bit) Preview.2023.07.11 - Artist / AppData / Local / Temp / '
                       'sai2dc_probe / probe_cmdline_1.psd', r'C:\Users\Artist\AppData\Local\Temp\sai2dc_probe\probe_cmdline_1.psd'),
      'real SAI2 title with path segments')
check(not L.title_has_file('PaintTool SAI Ver.2 (64bit)', r'C:\x\practice.psd'), 'no file in title')
check(not L.title_has_file('other.psd - PaintTool SAI Ver.2', r'C:\x\practice.psd'), 'different file')


# ─── 開檔流程 ───────────────────────────────────────────────────────────
class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeSai2:
    """模擬 SAI2：spawn([exe]) 啟動、spawn([exe, path]) 轉交檔案給既有行程後結束"""

    def __init__(self, clock, running=False, window_delay=2.0, opens_on='cmdline', linger=1.0):
        self.c = clock
        self.procs = {}             # pid -> 啟動時間
        self.files = []
        self.spawned = []
        self.dropped = []
        self.focused = []
        self.window_delay = window_delay
        self.opens_on = opens_on
        self.linger = linger
        self._forwarders = {}       # 轉交用的第二個行程 -> 結束時間
        if running:
            self.procs[100] = -99

    def find_processes(self, extra=()):
        alive = [(pid, r'D:\SAI2\sai2.exe') for pid in self.procs]
        alive += [(pid, r'D:\SAI2\sai2.exe') for pid, end in self._forwarders.items() if self.c.now() < end]
        return alive

    def main_window(self, pid):
        start = self.procs.get(pid)
        return 0 if start is None or self.c.now() - start < self.window_delay else 9000 + pid

    def titles(self, pid):
        if pid not in self.procs:
            return []
        cur = self.files[-1] if self.files else None
        return [f'{os.path.basename(cur)} - PaintTool SAI Ver.2 (64bit)' if cur else 'PaintTool SAI Ver.2 (64bit)']

    def spawn(self, args):
        self.spawned.append(list(args))
        pid = 200 + len(self.spawned)
        if len(args) == 1:
            self.procs[pid] = self.c.now()
        else:
            self._forwarders[pid] = self.c.now() + self.linger
            if self.opens_on == 'cmdline':
                self.files.append(args[1])
        return pid

    def wait_input_idle(self, pid, ms):
        return True

    def drop_files(self, hwnd, paths):
        self.dropped.append((hwnd, paths))
        if self.opens_on == 'drop':
            self.files.extend(paths)
        return True

    def focus(self, hwnd):
        self.focused.append(hwnd)


def opener(fake, clock, **kw):
    kw.setdefault('exe_path', r'D:\SAI2\sai2.exe')
    kw.setdefault('method', 'cmdline')
    return L.Sai2Opener(fake, clock=clock.now, sleep=clock.sleep, isfile=lambda p: True, **kw)


ART = r'C:\art\practice.psd'

# SAI2 未開啟：先單獨啟動、等就緒，再交檔
c = Clock()
f = FakeSai2(c)
res = opener(f, c).open(ART)
check(res.ok and res.launched and res.status == 'opened', f'launch then open: {res}')
check(f.spawned[0] == [r'D:\SAI2\sai2.exe'], 'first launch has no file argument')
check(f.spawned[1] == [r'D:\SAI2\sai2.exe', ART], 'file handed over after ready')
check(res.extra_instances == 0 and f.focused, 'forwarder exited + focused')

# SAI2 已開啟：不重新啟動，直接交檔；記下執行檔路徑
c = Clock()
f = FakeSai2(c, running=True)
o = opener(f, c, exe_path='')
res = o.open(ART)
check(res.ok and not res.launched and len(f.spawned) == 1, f'running: hand over only {f.spawned}')
check(o.exe_path == r'D:\SAI2\sai2.exe' and res.exe_path == o.exe_path, 'exe path remembered')

# 已經開著同一個檔案：不重複開
res = o.open(ART)
check(res.ok and len(f.spawned) == 1 and 'already open' in res.steps, 'already open -> no second handoff')

# 拖放方式
c = Clock()
f = FakeSai2(c, running=True, opens_on='drop')
res = opener(f, c, method='drop').open(ART)
check(res.ok and f.dropped and not any(len(a) == 2 for a in f.spawned), 'drop handoff')

# 交檔後標題沒變 → verify_timeout
c = Clock()
f = FakeSai2(c, running=True, opens_on='nothing')
res = opener(f, c).open(ART)
check(not res.ok and res.status == 'verify_timeout', f'verify timeout {res.status}')

# 沒有執行檔路徑、SAI2 也沒開 → need_exe
c = Clock()
res = opener(FakeSai2(c), c, exe_path='').open(ART)
check(res.status == 'need_exe', 'need exe path')

# 主視窗遲遲不出現 → launch_timeout
c = Clock()
res = opener(FakeSai2(c, window_delay=999), c, launch_timeout=5).open(ART)
check(res.status == 'launch_timeout' and res.launched, 'launch timeout')

# 檔案不存在
c = Clock()
res = L.Sai2Opener(FakeSai2(c), clock=c.now, sleep=c.sleep, isfile=lambda p: False).open(ART)
check(res.status == 'not_found', 'missing file')

# 處理中再按一次 → busy
c = Clock()
o = opener(FakeSai2(c), c)
o._lock.acquire()
check(o.open(ART).status == 'busy', 'busy while another open runs')
o._lock.release()

# 預設用拖放：SAI2 已開啟時不需要執行檔路徑
c = Clock()
f = FakeSai2(c, running=True, opens_on='drop')
res = L.Sai2Opener(f, clock=c.now, sleep=c.sleep, isfile=lambda p: True).open(ART)
check(res.ok and f.dropped and len(f.spawned) == 0, 'default drop, no extra process')

# 真的 backend：本機一定沒有叫這個名字的行程
check(L.Win32Backend().find_processes(('no_such_exe_' + uuid.uuid4().hex[:6] + '.exe',)) is not None, 'real backend runs')
done()
