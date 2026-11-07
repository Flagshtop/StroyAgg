"""Пути к файлам приложения (работает и из исходников, и из собранного .exe)."""
import os
import sys
from pathlib import Path


def app_dir() -> Path:
    """Папка рядом с .exe (или корень проекта при запуске из исходников)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def bundle_dir() -> Path:
    """Папка со встроенными ресурсами (PyInstaller распаковывает их в _MEIPASS)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent.parent


def resource(name: str) -> Path:
    """Сначала ищем файл рядом с exe (чтобы его можно было править), потом встроенный."""
    p = app_dir() / name
    if p.exists():
        return p
    return bundle_dir() / name


def data_dir() -> Path:
    """%LOCALAPPDATA%\\StroyAgg — профиль браузера, логи."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
    p = Path(base) / "StroyAgg"
    p.mkdir(parents=True, exist_ok=True)
    return p
