"""AAguard IoT package.

FastAPI app lives in app/main.py. This lazy shim re-exports __version__
without importing the FastAPI app on every `import app.*` (avoids circular
imports during startup).

Usage: from app import __version__
"""

__all__ = ['__version__']


def __getattr__(name):
    if name == '__version__':
        from app.main import __version__ as _version
        return _version
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
