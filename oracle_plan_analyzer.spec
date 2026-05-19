# -*- mode: python ; coding: utf-8 -*-
# collect_all('cryptography') 로 패키지 전체(모듈+바이너리+데이터)를 자동 수집
# → 버전 업그레이드 후 새 서브모듈이 추가돼도 재발하지 않음
from PyInstaller.utils.hooks import collect_all

crypto_datas, crypto_binaries, crypto_hiddenimports = collect_all('cryptography')

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=crypto_binaries,
    datas=crypto_datas,
    hiddenimports=crypto_hiddenimports + [
        'oracledb',
        'oracledb.thick_impl',
        'oracledb.thin_impl',
        'tkinter',
        'tkinter.ttk',
        'tkinter.filedialog',
        'tkinter.messagebox',
        'tkinter.scrolledtext',
        'app_logger',
        'tns_parser',
        'db_manager',
        'plan_analyzer',
        'tuning_advisor',
        'logging.handlers',
        'cffi',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'PIL', 'scipy'],
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
    name='OraclePlanAnalyzer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 앱 — 콘솔 창 없음
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
