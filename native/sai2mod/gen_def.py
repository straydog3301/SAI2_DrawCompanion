"""產生代理 DLL 用的 .def 檔：把系統 DLL 的所有匯出（含無名稱序數）轉發回 System32 原版。

用法：python gen_def.py dwmapi  →  產生 dwmapi.def
"""
import os
import sys

import pefile


def gen_def(name: str, out_dir: str) -> str:
    sys_path = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', f'{name}.dll')
    pe = pefile.PE(sys_path, fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_EXPORT']])
    target = sys_path[:-4]
    lines = [f'LIBRARY {name}', 'EXPORTS']
    for sym in pe.DIRECTORY_ENTRY_EXPORT.symbols:
        if sym.name:
            n = sym.name.decode()
            lines.append(f'    {n}="{target}.{n}" @{sym.ordinal}')
        else:
            lines.append(f'    __ord{sym.ordinal}="{target}.#{sym.ordinal}" @{sym.ordinal} NONAME')
    out = os.path.join(out_dir, f'{name}.def')
    with open(out, 'w', encoding='ascii') as f:
        f.write('\n'.join(lines) + '\n')
    return out


if __name__ == '__main__':
    print(gen_def(sys.argv[1] if len(sys.argv) > 1 else 'dwmapi',
                  os.path.dirname(os.path.abspath(__file__))))
