from loguru import logger
import sys
logger.remove()
from androguard.core.apk import APK
from androguard.core.dex import DEX

out_lines = []
apk = APK(r'd:\PY\VGuard\V-Guard Smart 2.0 2.0.17\base.apk')
for i, dex_bytes in enumerate(apk.get_all_dex()):
    d = DEX(dex_bytes)
    for c in d.get_classes():
        if c.get_name() == 'LP7/V$a;':
            out_lines.append(f"=== Found in dex {i}: {c.get_name()} ===")
            for m in c.get_methods():
                out_lines.append(f"Method: {m.get_name()}")
                code = m.get_code()
                if code:
                    insts = list(code.get_bc().get_instructions())
                    for idx, inst in enumerate(insts):
                        out_lines.append(f"{idx:04x}: {inst.get_name()} {inst.get_output()}")

with open(r'd:\PY\VGuard\scratch\v_a_bytecode.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(out_lines))
print(f"Wrote {len(out_lines)} lines to scratch/v_a_bytecode.txt")
