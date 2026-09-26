from androguard.core.apk import APK
from androguard.core.dex import DEX
from androguard.core.analysis.analysis import Analysis

apk = APK(r'd:\PY\VGuard\V-Guard Smart 2.0 2.0.17\base.apk')
for dex_data in apk.get_all_dex():
    d = DEX(dex_data)
    dx = Analysis(d)
    
    for method in d.get_methods():
        class_name = method.get_class_name()
        if 'SocketAdapter' in class_name or 'SocketCommand' in class_name or 'SocketService' in class_name:
            print(f"\n--- {class_name} -> {method.get_name()} ---")
            for idx, inst in enumerate(method.get_instructions()):
                print(f"{idx:04x} {inst.get_name()} {inst.get_output()}")
