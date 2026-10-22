# -*- coding: utf-8 -*-
"""
執行測試：
    python tests/run_tests.py            # 核心 + 介面（介面測試會開視窗，需要桌面環境）
    python tests/run_tests.py --core     # 只跑核心（不開視窗、不連網）
    python tests/run_tests.py --network  # 另外跑連網測試（美術館 API）
每個測試檔以獨立程序執行，避免 Tk 與模組狀態互相影響。
"""

from __future__ import annotations

import os
import sys
import glob
import time
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
TIMEOUT = {'core': 180, 'ui': 240, 'network': 900}


def run(group: str) -> list[tuple[str, bool, str]]:
    results = []
    for path in sorted(glob.glob(os.path.join(HERE, group, 'test_*.py'))):
        name = f'{group}/{os.path.basename(path)}'
        t = time.time()
        try:
            p = subprocess.run([sys.executable, '-X', 'utf8', path], capture_output=True, text=True,
                               encoding='utf-8', errors='replace', timeout=TIMEOUT[group])
            ok = p.returncode == 0
            out = (p.stdout.strip().splitlines() or [''])[-1] if ok else (p.stdout + p.stderr).strip()
        except subprocess.TimeoutExpired:
            ok, out = False, f'逾時（{TIMEOUT[group]} 秒）'
        results.append((name, ok, out))
        print(f"{'PASS' if ok else 'FAIL'}  {name:42s} {time.time() - t:5.1f}s  {out if ok else ''}", flush=True)
        if not ok:
            print('\n'.join('      ' + line for line in out.splitlines()[-25:]))
    return results


def main():
    args = set(sys.argv[1:])
    groups = ['core'] if '--core' in args else ['core', 'ui']
    if '--network' in args:
        groups.append('network')
    results = [r for g in groups for r in run(g)]
    failed = [n for n, ok, _ in results if not ok]
    print(f'\n{len(results) - len(failed)}/{len(results)} 個測試檔通過' + (f'；失敗：{", ".join(failed)}' if failed else ''))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
