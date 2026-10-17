import os
import sys


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def find_config():
    base = app_dir()
    candidates = [
        os.path.join(base, "config.ini"),
        os.path.join(base, "config", "config.ini"),
    ]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(os.path.join(meipass, "config", "config.ini"))
        candidates.append(os.path.join(meipass, "config.ini"))
    for path in candidates:
        if os.path.isfile(path):
            return path
    raise FileNotFoundError(
        "config.ini tidak ditemukan. Letakkan config.ini di folder: " + base
    )


def resolve_path(relative):
    if os.path.isabs(relative):
        return relative
    return os.path.join(app_dir(), relative)


def resource_path(relative):
    base = app_dir()
    candidate = os.path.join(base, relative)
    if os.path.isfile(candidate):
        return candidate
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidate = os.path.join(meipass, relative)
        if os.path.isfile(candidate):
            return candidate
    return os.path.join(base, relative)
