"""sai_disasm.py <exe> <rva hex> [count] — 反組譯 SAI2 指定位址（唯讀分析）。需要 capstone、pefile。"""
import sys
import pefile
from capstone import Cs, CS_ARCH_X86, CS_MODE_64

path = sys.argv[1]
rva = int(sys.argv[2], 16)
count = int(sys.argv[3]) if len(sys.argv) > 3 else 60
pe = pefile.PE(path, fast_load=True)
base = pe.OPTIONAL_HEADER.ImageBase
data = pe.get_memory_mapped_image()
md = Cs(CS_ARCH_X86, CS_MODE_64)
n = 0
for ins in md.disasm(data[rva:rva + count * 15], base + rva):
    print(f'{ins.address - base:08x}  {ins.mnemonic:8} {ins.op_str}')
    n += 1
    if n >= count:
        break
