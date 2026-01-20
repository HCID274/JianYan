# -*- mode: python ; coding: utf-8 -*-

"""
优化版 spec 文件 v2：
1. 使用 onedir 模式，避免每次启动解压
2. 使用 collect_all 完整收集 funasr
3. console=True 便于调试
"""

import sys
from PyInstaller.utils.hooks import collect_all, collect_submodules, collect_data_files

# 完整收集 funasr（包括数据文件、二进制、隐藏导入）
funasr_datas, funasr_binaries, funasr_hiddenimports = collect_all('funasr')

# torch 相关
torch_imports = [
    'torch',
    'torchaudio',
]

# 其他必需模块（只列出已安装的）
extra_imports = [
    'sentencepiece',
    'soundfile',
    'sounddevice',
    'numpy',
    'yaml',
    'pystray',
    'PIL',
    'keyboard',
    'requests',
    'urllib3',
    'certifi',
    'librosa',
    'jaconv',
    'jamo',
    'jieba',
    'kaldiio',
    'hydra',
    'omegaconf',
    'win11toast',
    'winrt',
]

hiddenimports = funasr_hiddenimports + torch_imports + extra_imports

# 收集数据文件
datas = funasr_datas

# 二进制文件
binaries = funasr_binaries

a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['hooks'],  # 使用自定义 hooks
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 排除不需要的大模块
        'modelscope',  # 完全不需要 modelscope
        'tensorflow',
        'keras',
        'paddle',
        'paddlepaddle',
        'transformers',
        'datasets',
        'matplotlib',
        'IPython',
        'notebook',
        'jupyter',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

# 使用 onedir 模式（COLLECT）而不是 onefile
exe = EXE(
    pyz,
    a.scripts,
    [],  # 空列表表示 onedir 模式
    exclude_binaries=True,  # 关键：分离二进制文件
    name='Jianyan',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # 关闭控制台，隐藏黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
)

# COLLECT 将所有文件收集到一个目录
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Jianyan',  # 输出目录名
)
