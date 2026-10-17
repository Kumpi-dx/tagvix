# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files

datas = [('config', 'config'), ('icon.ico', '.'), ('icon.png', '.')]
datas += collect_data_files('customtkinter')

hiddenimports = [
    'serial', 'serial.tools.list_ports', 'pymysql', 'customtkinter',
    'pymodbus', 'pymodbus.client', 'pymodbus.client.base',
    'pymodbus.client.serial', 'pymodbus.client.tcp', 'pymodbus.pdu',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='tagvix',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='tagvix',
)
