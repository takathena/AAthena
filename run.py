"""
NEXUS IoT - Entry Point (FastAPI v2.0)
Usage:
   Development: python run.py
   Production:  gunicorn -k uvicorn.workers.UvicornWorker -b 0.0.0.0:5000 run:app

Flask lama (app/__init__.py) tetap ada dan bisa jalan via:
   python -c "from app import create_app; create_app().run()"
"""
import logging
import signal
import sys

from app.config import get_config
from app.main import app  # FastAPI app (dari app/main.py:create_app)

config = get_config()
logger = logging.getLogger('nexus')


def _signal_handler(signum, frame):
    logger.info(f"Received signal {signum}, shutting down...")
    try:
        from app.background import stop_background_tasks
        stop_background_tasks()
    except Exception:
        pass
    sys.exit(0)


if __name__ == '__main__':
    # Signal handler hanya di main process (fallback di luar uvicorn).
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except ValueError:
        pass

    logger.info("=" * 60)
    logger.info("NEXUS IoT starting (FastAPI v2.0)...")
    logger.info(f"   Host    : {config.HOST}")
    logger.info(f"   Port    : {config.PORT}")
    logger.info(f"   Debug   : {config.DEBUG}")
    logger.info(f"   Database: {config.DB_PATH}")
    logger.info(f"   URL     : http://{config.HOST}:{config.PORT}")
    logger.info("=" * 60)

    try:
        import uvicorn
        uvicorn.run(app, host=config.HOST, port=config.PORT,
                    log_level='debug' if config.DEBUG else 'info')
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt, shutting down...")
    except Exception:
        # Fallback sinyal/background bila uvicorn tidak tersedia.
        logger.exception("Uvicorn failed; coba Flask dev server sebagai fallback.")
        try:
            from app import create_app as _create_flask_app
            _create_flask_app().run(host=config.HOST, port=config.PORT,
                                    debug=config.DEBUG, use_reloader=False, threaded=True)
        except Exception as e:
            logger.error(f"Fallback Flask juga gagal: {e}")
            raise
    finally:
        try:
            from app.background import stop_background_tasks
            stop_background_tasks()
        except Exception:
            pass
