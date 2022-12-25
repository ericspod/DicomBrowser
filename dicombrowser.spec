
# Run with "pyinstaller dicombrowser.spec -y"

import os
from glob import glob

block_cipher = None

a = Analysis(
    ['dicombrowser\\__main__.py'],
    pathex=[],
    binaries=[],
    datas=[(d, os.path.dirname(d)) for d in glob("dicombrowser/res/*")],
    hiddenimports=["pydicom.encoders.gdcm", "pydicom.encoders.pylibjpeg", "pydicom.encoders.native"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='dicombrowser',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='dicombrowser',
)
