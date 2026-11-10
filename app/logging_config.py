"""
AAguard IoT - Logging Configuration
"""
import os
import logging
from logging.handlers import RotatingFileHandler


def setup_logging(config):
    formatter = logging.Formatter(
        '[%(asctime)s] %(levelname)-8s [%(name)s:%(lineno)d] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    level_name = str(config.LOG_LEVEL).upper()
    level = getattr(logging, level_name, logging.INFO)

    file_handler = None
    try:
        log_dir = os.path.dirname(config.LOG_FILE)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        # Satu file per worker: RotatingFileHandler tidak aman dipakai bersama
        # beberapa proses Gunicorn (rollover balapan -> log hilang).
        file_handler = RotatingFileHandler(
            f'{config.LOG_FILE}.{os.getpid()}',
            maxBytes=config.LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding='utf-8',
        )
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)
    except OSError as exc:
        # Bind mount bisa dimiliki user lain; jangan gagalkan startup.
        file_handler = None
        logging.getLogger('aaguard').warning('File logging disabled: %s', exc)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(level)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    if file_handler is not None:
        root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    logging.getLogger('werkzeug').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)

    logger = logging.getLogger('aaguard')
    logger.info("Logging initialized")
    return logger