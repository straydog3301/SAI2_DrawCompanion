"""sai_xref.py <exe> <target rva hex> — 找出以 RIP 相對位址參照 target 的指令（唯讀分析）"""
import struct
import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

path, target = sys.argv[1], int(sys.argv[2], 16)
span = int(sys.argv[3], 16) if len(sys.argv) > 3 else 1
pe = pefile.PE(path, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
img = pe.get_memory_mapped_image()
text = next(s for s in pe.sections if s.Name.startswith(b'.text'))
lo, hi = text.VirtualAddress, text.VirtualAddress + text.Misc_VirtualSize
md = Cs(CS_ARCH_X86, CS_MODE_64)
hits = set()
for i in range(lo, hi - 4):
    disp = struct.unpack_from('<i', img, i)[0]
    for extra in (0, 1, 4):
        t = i + 4 + extra + disp
        if target <= t < target + span:
            for back in range(1, 8):
                start = i - back
                ins = next(md.disasm(img[start:start + 16], base + start), None)
                if ins and ins.address + ins.size == base + i + 4 + extra and 'rip' in ins.op_str:
                    hits.add((start, f'{ins.mnemonic} {ins.op_str}   [+{t - target:#x}]'))
for a, s in sorted(hits):
    print(f'{a:08x}  {s}')
