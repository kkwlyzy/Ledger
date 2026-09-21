# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 配置：单文件 + 无窗口 GUI + 内置图标。

构建命令：pyinstaller ledger.spec
产物：dist/记账本.exe
"""
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        # matplotlib 后端依赖，确保打包后图表能正常渲染
        'matplotlib.backends.backend_qtagg',
        'PySide6.QtSvg',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不必要的大模块以减小体积
        'tkinter',
        'pydoc',
        'test',
    ],
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
    name='记账本',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,             # 无控制台窗口(GUI 应用)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_plist=None,
    icon=os.path.join('data', 'app.ico'),  # 应用图标
)
