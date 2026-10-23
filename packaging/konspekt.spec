# Сборка программы: pyinstaller packaging/konspekt.spec
# Результат — папка dist/Konspekt с Konspekt.exe (запуск без установки Python).
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).parent

a = Analysis(
    [str(ROOT / "konspekt_app.py")],
    pathex=[str(ROOT)],
    datas=[(str(ROOT / "konspekt" / "assets"), "konspekt/assets")] + collect_data_files("pyphen"),
    excludes=["tkinter", "pytest", "pandas", "onnxruntime", "lxml", "matplotlib", "scipy", "IPython", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtWebEngineCore",
              "PySide6.QtMultimedia", "PySide6.Qt3DCore"],
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Konspekt", console=False,
          icon=str(ROOT / "konspekt" / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="Konspekt")
