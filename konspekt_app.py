"""Точка входа для сборки .exe (PyInstaller): запускает окно приложения."""

from konspekt.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
