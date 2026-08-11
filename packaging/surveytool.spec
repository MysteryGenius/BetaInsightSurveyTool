from PyInstaller.utils.hooks import copy_metadata

datas = copy_metadata("surveytool")
datas += [("../surveytool/desktop/static", "surveytool/desktop/static")]

a = Analysis(
    ["../surveytool/desktop/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["webview.platforms.edgechromium"],
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
    name="SurveyTool",
    console=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="SurveyTool",
)
