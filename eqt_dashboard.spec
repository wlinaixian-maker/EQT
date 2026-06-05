# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 规格：python build_package.py"""

import os

block_cipher = None
root = os.path.abspath(SPECPATH)

a = Analysis(
    [os.path.join(root, 'serve_dashboard.py')],
    pathex=[root],
    binaries=[],
    datas=[],
    hiddenimports=[
        'app_paths',
        'dashboard_config',
        'hourly_refresh',
        'data_archive',
        'generate_index',
        'build_report_data',
        'fetch_exports_from_har',
        'station_registry',
        'har_export_requests',
        'batch_extract_excel',
        'extract_har_data',
        'backfill_missing_stations',
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
    [],
    exclude_binaries=True,
    name='EQT-Dashboard',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
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
    name='EQT-Dashboard',
)
