import sys


def run_console():
    from app.config_loader import Config
    from app.logger_setup import setup_logging
    from app.middleware import Middleware

    print("=" * 60)
    print(" TagVix  |  Omron CP1E (Host Link) -> MySQL")
    print("=" * 60)

    try:
        config = Config()
    except Exception as exc:
        print("[FATAL] Gagal memuat konfigurasi:", exc)
        return 1

    logger = setup_logging(
        level=config.log_level,
        log_file=config.log_file,
        max_bytes=config.log_max_bytes,
        backup_count=config.log_backup_count,
        console=config.log_console,
    )
    logger.info("Memuat konfigurasi dari: %s", config.path)

    middleware = Middleware(config, logger)
    try:
        return middleware.run()
    except Exception as exc:
        logger.exception("Error fatal: %s", exc)
        return 1


def run_gui():
    from app.gui import launch

    launch()
    return 0


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if "--console" in args:
        return run_console()
    try:
        return run_gui()
    except Exception as exc:
        print("[WARN] GUI tidak dapat dijalankan:", exc)
        print("[INFO] Menjalankan mode console...")
        return run_console()


if __name__ == "__main__":
    sys.exit(main())
