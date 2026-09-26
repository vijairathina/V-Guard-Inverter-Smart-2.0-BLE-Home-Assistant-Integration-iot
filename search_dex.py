import re
dex_path = r'd:\PY\VGuard\V-Guard Smart 2.0 2.0.17\extracted\classes.dex'
with open(dex_path, 'rb') as f:
    data = f.read()

def find_context(kw, radius=300):
    for m in re.finditer(kw, data, re.IGNORECASE):
        window = data[max(0, m.start()-radius) : m.end()+radius]
        strings = re.findall(rb'[\x20-\x7e]{3,50}', window)
        print(f"Context for {kw}: {[s.decode('ascii', 'ignore') for s in strings]}")

find_context(b'socketCommand')
find_context(b'writeCharacteristic')
find_context(b'AES')
find_context(b'encrypt')
find_context(b'decrypt')
