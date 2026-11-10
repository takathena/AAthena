import logging

from app import logging_config
from app.config import get_config


def test_setup_logging_falls_back_to_console(monkeypatch):
    def broken(*args, **kwargs):
        raise OSError('permission denied')

    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    monkeypatch.setattr(logging_config, 'RotatingFileHandler', broken)
    try:
        logging_config.setup_logging(get_config())
        assert not any(isinstance(h, logging.FileHandler) for h in root.handlers)
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
    finally:
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in handlers:
            root.addHandler(handler)
        root.setLevel(level)
