import logging
import os
from logging.handlers import RotatingFileHandler

from .paths import resolve_path


def setup_logging(level="INFO", log_file="logs/tagvix.log", max_bytes=1048576,
                  backup_count=5, console=True):
    level_value = getattr(logging, str(level).upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    log_path = resolve_path(log_file)
    log_dir = os.path.dirname(log_path)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    file_handler = RotatingFileHandler(
        log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    file_handler.setLevel(level_value)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    if console:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(level_value)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    return logging.getLogger("tagvix")
