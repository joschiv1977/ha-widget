# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['ha-widget.py'],
    pathex=[],
    binaries=[],
    datas=[],  # Keine Dateien hinzufügen - Programm erstellt Config selbst
    hiddenimports=[
        'PIL',
        'PIL.Image', 
        'PIL.ImageTk',
        'cv2',
        'paho.mqtt.client',
        'tkinter',
        'tkinter.ttk',
        'tkinter.font',
        'tkinter.filedialog', 
        'tkinter.messagebox',
        'requests',
        'threading',
        'json',
        'ssl',
        'io'
    ],
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='3D-Drucker-Widget',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico'
)