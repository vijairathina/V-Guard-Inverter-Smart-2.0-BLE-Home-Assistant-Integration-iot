import re
dex_path = r'd:\PY\VGuard\V-Guard Smart 2.0 2.0.17\extracted\classes.dex'
with open(dex_path, 'rb') as f:
    data = f.read()

out = open('search_results.utf8.txt', 'w', encoding='utf-8')

def find_context(kw, radius=300):
    out.write(f"\n--- Context for {kw} ---\n")
    for m in re.finditer(kw, data, re.IGNORECASE):
        window = data[max(0, m.start()-radius) : m.end()+radius]
        strings = re.findall(rb'[\x20-\x7e]{3,50}', window)
        out.write(str([s.decode('ascii', 'ignore') for s in strings]) + "\n")

find_context(b'socketCommand')
find_context(b'writeCharacteristic')
find_context(b'AES')
find_context(b'encrypt')
out.close()
