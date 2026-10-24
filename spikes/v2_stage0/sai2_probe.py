# -*- coding: utf-8 -*-
"""
驗證 4：在真的 SAI2 上測開檔流程（會開啟 SAI2 與兩張空白測試畫布，請先存好手上的作品）

    python spikes/v2_stage0/sai2_probe.py --exe E:\\SAI2\\sai2.exe
    python spikes/v2_stage0/sai2_probe.py --exe E:\\SAI2\\sai2.exe --capture   # 另外測畫布擷取（比對用）

依序用 cmdline（再執行一次 sai2.exe <檔案>）與 drop（拖放檔案訊息）兩種方式各開一張測試畫布，
印出每一步、是否多出第二個 SAI2 行程。SAI2 沒開時會先單獨啟動它（驗證「先開 SAI2 再開檔」）。
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, REPO)

from core.psd_writer import write_blank_psd          # noqa: E402
from core.sai2_launcher import Sai2Opener, Win32Backend  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--exe', default=os.path.join(os.path.dirname(REPO), 'sai2.exe'))
    ap.add_argument('--capture', action='store_true')
    args = ap.parse_args()

    folder = tempfile.mkdtemp(prefix='sai2dc_probe_')
    backend = Win32Backend()
    print('SAI2 running before:', backend.find_processes())
    for method in ('cmdline', 'drop'):
        path = os.path.join(folder, f'probe_{method}_{int(time.time())}.psd')
        write_blank_psd(path, 800, 600)
        t0 = time.perf_counter()
        res = Sai2Opener(backend, exe_path=args.exe, method=method).open(path)
        print(f'\n[{method}] {res.status} in {time.perf_counter() - t0:.1f}s ok={res.ok} launched={res.launched} '
              f'extra_instances={res.extra_instances}')
        print('  steps:', res.steps)
        for pid, _ in backend.find_processes():
            print('  titles:', backend.titles(pid))
        time.sleep(2)

    if args.capture:
        from core.snapshots import capture_sai2_canvas
        img = capture_sai2_canvas()
        out = os.path.join(folder, 'capture.png')
        if img is not None:
            img.save(out)
        print('\ncapture:', img.size if img is not None else None, out if img is not None else '')
    print('\ntest files in', folder)


if __name__ == '__main__':
    main()
