# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

datas = collect_data_files("robot_sketch_studio", includes=["static/*"])
hiddenimports = [
    "robot_sketch_studio.app",
    *collect_submodules("uvicorn"),
]

analysis = Analysis(
    ["src/robot_sketch_studio/__main__.py"],
    pathex=["src"],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "rembg",
        "onnxruntime",
        "pytest",
        "_pytest",
        "coverage",
        "httpx",
        "ruff",
    ],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="RobotSketchStudio",
    console=False,
)
collection = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    name="RobotSketchStudio",
)
