"""Проверка самообновления собранной программы от начала до конца (Windows, Actions).

    python packaging/check_update.py dist/Konspekt local   # новая версия — эта же сборка
    python packaging/check_update.py dist/Konspekt github  # последний настоящий релиз

Копия программы («старая») запускается в режиме KONSPEKT_UPDATE_SELFTEST: она
сама скачивает архив, запускает из него новую программу и закрывается, а новая
заменяет папку старой и запускает её. Проверяем, что папка заменилась, лишнего
не осталось, а программа снова запущена уже из своей папки.
"""

import functools
import hashlib
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

PORT = 8765


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def running_from(exe: Path) -> list[int]:
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-Process Konspekt -ErrorAction SilentlyContinue | "
                          "ForEach-Object { \"$($_.Id) $($_.Path)\" }"],
                         capture_output=True, text=True).stdout
    pids = []
    for line in out.splitlines():
        pid, _, path = line.strip().partition(" ")
        if path and Path(path).resolve() == exe.resolve():
            pids.append(int(pid))
    return pids


def serve(root: Path) -> None:
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main(dist: str, mode: str) -> int:
    dist = Path(dist).resolve()
    work = Path(os.environ.get("RUNNER_TEMP", ".")) / f"обновление-{mode}"  # кириллица в пути — как у друзей
    shutil.rmtree(work, ignore_errors=True)
    app = work / "Konspekt-windows" / "Konspekt"
    shutil.copytree(dist, app)
    (app / "СТАРАЯ.txt").write_text("эта версия должна исчезнуть", encoding="utf-8")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", KONSPEKT_PROFILES=str(work / "profiles"))
    log = work / "ход.txt"
    env["KONSPEKT_UPDATE_SELFTEST"] = str(log)

    if mode == "local":
        srv = work / "srv"
        srv.mkdir()
        with zipfile.ZipFile(srv / "Konspekt-windows.zip", "w", zipfile.ZIP_DEFLATED) as z:
            for f in dist.rglob("*"):
                z.write(f, Path("Konspekt") / f.relative_to(dist))
            z.writestr("Konspekt/НОВАЯ.txt", "новая")
        (srv / "latest.json").write_text(json.dumps({
            "tag_name": "v9.9.9", "body": "проверка", "html_url": "http://example",
            "assets": [{"name": "Konspekt-windows.zip", "size": (srv / "Konspekt-windows.zip").stat().st_size,
                        "browser_download_url": f"http://127.0.0.1:{PORT}/Konspekt-windows.zip"}]}))
        serve(srv)
        env["KONSPEKT_UPDATE_API"] = f"http://127.0.0.1:{PORT}/latest.json"
        expected_exe = sha(dist / "Konspekt.exe")
    else:
        expected_exe = None  # exe релиза сверим с архивом, который скачаем сами

    t0 = time.time()
    old = subprocess.Popen([str(app / "Konspekt.exe")], env=env, cwd=str(app))
    try:
        code = old.wait(timeout=900)
    except subprocess.TimeoutExpired:
        old.kill()
        print(log.read_text(encoding="utf-8") if log.exists() else "нет записи хода")
        raise SystemExit("старая программа не закрылась за 15 минут")
    print(log.read_text(encoding="utf-8"))
    print(f"старая программа закрылась за {time.time() - t0:.0f} с, код {code}")
    if code != 0:
        raise SystemExit("старая программа завершилась с ошибкой")

    exe = app / "Konspekt.exe"
    deadline = time.time() + 180
    while time.time() < deadline:
        if not (app / "СТАРАЯ.txt").exists() and running_from(exe):
            break
        time.sleep(1)
    print(f"обновление заняло {time.time() - t0:.0f} с")
    pids = running_from(exe)
    problems = []
    if (app / "СТАРАЯ.txt").exists():
        problems.append("папка программы не заменилась")
    if not pids:
        problems.append("обновлённая программа не запустилась")
    if app.with_name("Konspekt.old").exists():
        problems.append("осталась папка Konspekt.old")
    if mode == "local":
        if not (app / "НОВАЯ.txt").exists():
            problems.append("в папке нет файлов новой версии")
        if exe.exists() and sha(exe) != expected_exe:
            problems.append("Konspekt.exe не совпадает с новой версией")
    else:
        import urllib.request
        data = json.load(urllib.request.urlopen(
            "https://api.github.com/repos/Carpmana/konspekty-ot-ruki/releases/latest"))
        url = next(a["browser_download_url"] for a in data["assets"] if a["name"] == "Konspekt-windows.zip")
        with zipfile.ZipFile(urllib.request.urlretrieve(url, work / "check.zip")[0]) as z:
            name = next(n for n in z.namelist() if n.replace("\\", "/").endswith("Konspekt/Konspekt.exe"))
            ref = hashlib.sha256(z.read(name)).hexdigest()
        if exe.exists() and sha(exe) != ref:
            problems.append(f"Konspekt.exe не совпадает с релизом {data['tag_name']}")
    for pid in pids:
        subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
    if problems:
        raise SystemExit("; ".join(problems))
    print("самообновление работает:", mode)
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
