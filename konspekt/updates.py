"""Проверка новой версии на GitHub и обновление собранной программы.

Версию программы записывает сборка в Actions (файл _build.py, его нет в git):
из исходников версия неизвестна, и сама программа о новой версии не спрашивает.

Обновление: скачиваем Konspekt-windows.zip последнего релиза, распаковываем во
временную папку и запускаем оттуда новую программу с --finish-update. Она ждёт,
пока старая закроется, кладёт себя на место старой папки и запускает её.
Профили почерков лежат в %APPDATA% и при обновлении не трогаются.
"""

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO = "Carpmana/konspekty-ot-ruki"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPO}/releases/latest"
ASSET_NAME = "Konspekt-windows.zip"
FINISH_ARG = "--finish-update"


def current_version() -> str | None:
    try:
        from ._build import VERSION
    except ImportError:
        return None
    return VERSION


def parse_version(text: str) -> tuple[int, ...] | None:
    m = re.search(r"(\d+(?:\.\d+)*)", text or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def is_newer(latest: str, current: str | None) -> bool:
    new, old = parse_version(latest), parse_version(current or "")
    return bool(new and old and new > old)


@dataclass
class Release:
    version: str        # «0.2.21», без «v»
    notes: str
    page_url: str
    download_url: str   # пусто, если в релизе нет архива программы
    size: int


def _open(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": "Konspekt", "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def fetch_latest(timeout: float = 8.0) -> Release:
    """Последний релиз на GitHub. Без интернета — исключение OSError."""
    with _open(LATEST_API, timeout) as r:
        data = json.load(r)
    asset = next((a for a in data.get("assets", []) if a.get("name") == ASSET_NAME), {})
    return Release(
        version=str(data.get("tag_name", "")).lstrip("v"),
        notes=(data.get("body") or "").strip(),
        page_url=data.get("html_url") or RELEASES_PAGE,
        download_url=asset.get("browser_download_url", ""),
        size=int(asset.get("size") or 0),
    )


def app_dir() -> Path:
    return Path(sys.executable).resolve().parent


def can_self_update() -> bool:
    """Обновлять сами можем только собранную программу для Windows в папке,
    куда разрешено писать."""
    if not (getattr(sys, "frozen", False) and sys.platform == "win32"):
        return False
    try:
        with tempfile.TemporaryFile(dir=app_dir().parent):
            pass
    except OSError:
        return False
    return True


class Cancelled(Exception):
    pass


def download(rel: Release, progress=None, cancelled=lambda: False) -> Path:
    """Скачивает и распаковывает архив. Возвращает папку новой программы
    (в ней Konspekt.exe). progress(done_bytes, total_bytes)."""
    work = Path(tempfile.mkdtemp(prefix="konspekt-update-"))
    zpath = work / ASSET_NAME
    try:
        with _open(rel.download_url, 30) as r, open(zpath, "wb") as f:
            total = int(r.headers.get("Content-Length") or rel.size or 0)
            done = 0
            while chunk := r.read(1 << 18):
                if cancelled():
                    raise Cancelled
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(work / "new")
        zpath.unlink()
        exe = next((work / "new").rglob("Konspekt.exe"), None)
        if exe is None:
            raise OSError("В архиве нет Konspekt.exe")
        return exe.parent
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def spawn(args: list[str]) -> None:
    """Запуск другой собранной программы: без переменных, которые PyInstaller
    и Qt выставили для нашей папки, иначе она может искать файлы у нас."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(("_PYI", "_MEI", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(args, env=env, close_fds=True, creationflags=flags, cwd=str(Path(args[0]).parent))


def start_finish(new_dir: Path) -> None:
    """Запускает новую программу, которая заменит текущую, когда та закроется."""
    spawn([str(new_dir / "Konspekt.exe"), FINISH_ARG, str(app_dir()), str(os.getpid())])


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        k.GetExitCodeProcess(h, ctypes.byref(code))
        k.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def replace_dir(source: Path, target: Path, retries: int = 40) -> None:
    """Кладёт папку source на место target. Если что-то пошло не так —
    старая программа остаётся на месте."""
    old = target.with_name(target.name + ".old")
    shutil.rmtree(old, ignore_errors=True)
    for i in range(retries):  # файлы старой программы освобождаются не сразу
        try:
            target.rename(old)
            break
        except FileNotFoundError:
            break
        except OSError:
            if i == retries - 1:
                raise
            time.sleep(0.5)
    try:
        shutil.copytree(source, target)
    except BaseException:
        shutil.rmtree(target, ignore_errors=True)
        if old.exists():
            old.rename(target)
        raise
    shutil.rmtree(old, ignore_errors=True)


def finish_update(target: str, pid: str) -> Path:
    """Вызывается из новой программы во временной папке. Возвращает путь
    к обновлённому Konspekt.exe."""
    deadline = time.time() + 60
    while _pid_alive(int(pid)) and time.time() < deadline:
        time.sleep(0.3)
    replace_dir(app_dir(), Path(target))
    return Path(target) / "Konspekt.exe"


def cleanup_leftovers() -> None:
    """Убирает временные папки прошлых обновлений (кроме той, где мы сами)."""
    me = app_dir()
    for d in Path(tempfile.gettempdir()).glob("konspekt-update-*"):
        if d not in me.parents:
            shutil.rmtree(d, ignore_errors=True)
