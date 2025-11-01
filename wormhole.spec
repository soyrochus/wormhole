# wormhole.spec — one-folder, single executable "wormhole"
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None
entry = 'wormhole/__main__.py'

datas = []

hidden = collect_submodules('wormhole')

a = Analysis([entry], pathex=[], binaries=[], datas=datas,
             hiddenimports=hidden, hookspath=[], runtime_hooks=[],
             excludes=[], noarchive=False)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# console=True so CLI works; GUI users will launch via desktop wrappers that hide the console on Windows
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas,
          name='wormhole', console=True, debug=False, strip=False, upx=False)

coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas,
               strip=False, upx=False, name='wormhole')
