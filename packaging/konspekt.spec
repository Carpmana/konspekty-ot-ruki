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

# Лишнее, что тянут библиотеки, а программе не нужно: видео в OpenCV, программный
# OpenGL, QML/Quick (их тянет экранная клавиатура), PDF-модуль Qt, AVIF и словари
# переносов других языков. Без них архив заметно меньше и быстрее качается.
DROP = ("opencv_videoio_ffmpeg", "opengl32sw", "Qt6Quick", "Qt6Qml", "Qt6VirtualKeyboard",
        "qtvirtualkeyboardplugin", "Qt6Pdf", "qpdf.dll", "qdirect2d", "_avif.")


# Словари переносов: только языки, которые знает layout.HYPH_LANGS.
HYPH_FILES = ("hyph_ru_RU.dic", "hyph_be_BY.dic", "hyph_en_US.dic")


def keep(entry):
    name = entry[0].replace("\\", "/")
    if any(d in name for d in DROP):
        return False
    return not ("pyphen/dictionaries/" in name and not name.endswith(HYPH_FILES))


a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Konspekt", console=False,
          icon=str(ROOT / "konspekt" / "assets" / "icon.ico"))
coll = COLLECT(exe, a.binaries, a.datas, name="Konspekt")
