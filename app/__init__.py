"""
NEXUS IoT - Application Factory
Refactor: create_app dipecah menjadi helper kecil; validasi config dipindah
ke create_app() agar import app tidak lagi me-exit proses saat config buruk.
"""
import os
import sys
from flask import Flask, jsonify, request, render_template

from app.config import get_config
from app.logging_config import setup_logging
from app.database import init_db, close_db, get_wib_time
from app.extensions import cors, csrf, limiter

__version__ = '2.0.0'

config = get_config()
logger = setup_logging(config)


def validate_config_or_exit():
    """Validasi config; gagal -> cetak pesan dan SystemExit(1). Dipanggil create_app()."""
    try:
        config.validate()
        logger.info("Configuration validated")
    except ValueError as e:
        print(str(e), file=sys.stderr)
        raise SystemExit(1) from e


def warn_if_insecure_cookie(app_config, env=None, log=None):
    """Peringatkan bila production berjalan dengan cookie sesi non-Secure."""
    env = (env if env is not None else os.getenv('FLASK_ENV', 'production')).lower()
    log = log or logger
    if env == 'production' and not app_config.get('SESSION_COOKIE_SECURE'):
        log.warning(
            "SESSION_COOKIE_SECURE=False di production: cookie sesi dikirim "
            "tanpa flag Secure. Hanya untuk jaringan tepercaya tanpa HTTPS; "
            "aktifkan HTTPS lalu set SESSION_COOKIE_SECURE=True / ENABLE_HSTS=True."
        )
        return True
    return False


def _apply_proxy_fix(app):
    """ProxyFix — dapat IP device asli di belakang Nginx."""
    from werkzeug.middleware.proxy_fix import ProxyFix
    if not app.config.get('TESTING'):
        app.wsgi_app = ProxyFix(
            app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1,
        )


def _init_extensions(app):
    cors.init_app(app, resources={
        r"/api/*": {
            "origins": config.CORS_ORIGINS,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "X-CSRFToken"],
            "max_age": 3600,
        }
    })
    limiter.init_app(app)
    csrf.init_app(app)
    app.teardown_appcontext(close_db)


def _register_static_cache_bust(app):
    """Nginx menyajikan /static/ immutable 30d; tambahkan ?v=<mtime> agar URL berubah."""
    @app.url_defaults
    def _static_cache_bust(endpoint, values):
        if endpoint == 'static' and 'v' not in values:
            filename = values.get('filename')
            if filename:
                try:
                    values['v'] = int(os.path.getmtime(
                        os.path.join(app.static_folder, filename)
                    ))
                except OSError:
                    pass


def _register_blueprints(app):
    from app.auth import auth_bp
    from app.api import api_bp
    from app.views import views_bp
    from app.dashboards import dashboards_bp
    from app.chat import chat_bp, llm_configured

    for bp in (auth_bp, api_bp, views_bp, dashboards_bp, chat_bp):
        app.register_blueprint(bp)

    @app.context_processor
    def inject_chat_enabled():
        # N7: widget chat tidak dirender bila LLM belum dikonfigurasi.
        return {'chat_enabled': llm_configured()}

    logger.info("CSRF: only /api/v1/data is exempt (device endpoint)")


def _register_security_headers(app):
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=(), payment=(), usb=()'
        )
        # HSTS hanya bila ENABLE_HSTS=True (bukan karena cookie Secure).
        if app.config.get('ENABLE_HSTS'):
            response.headers['Strict-Transport-Security'] = (
                'max-age=31536000; includeSubDomains'
            )
        csp = (
            f"default-src 'self'; "
            f"script-src {config.CSP_SCRIPT_SRC}; "
            f"style-src {config.CSP_STYLE_SRC}; "
            f"font-src {config.CSP_FONT_SRC}; "
            f"img-src {config.CSP_IMG_SRC}; "
            f"connect-src {config.CSP_CONNECT_SRC}; "
            f"object-src 'none'; "
            f"base-uri 'self'; "
            f"form-action 'self'; "
            f"frame-ancestors 'self'"
        )
        if config.CSP_REPORT_ONLY:
            response.headers['Content-Security-Policy-Report-Only'] = csp
        else:
            response.headers['Content-Security-Policy'] = csp
        return response


def _error_response(status, api_error, title, message):
    """JSON untuk endpoint API, halaman error HTML untuk route halaman."""
    logger.info(f"HTTP {status} {request.method} {request.path}")
    if request.path.startswith('/api/'):
        return jsonify({'success': False, 'error': api_error}), status
    return render_template('error.html', code=status,
                           title=title, message=message), status


def _register_error_handlers(app):
    @app.errorhandler(400)
    def bad_request(e):
        return _error_response(400, 'Bad request',
                               'Permintaan Tidak Valid',
                               'Permintaan tidak bisa diproses. Coba ulangi.')

    @app.errorhandler(401)
    def unauthorized(e):
        return _error_response(401, 'Unauthorized',
                               'Perlu Masuk',
                               'Sesi Anda tidak valid. Silakan masuk kembali.')

    @app.errorhandler(403)
    def forbidden(e):
        return _error_response(403, 'Forbidden',
                               'Akses Ditolak',
                               'Anda tidak punya izin untuk membuka halaman ini.')

    @app.errorhandler(404)
    def not_found(e):
        return _error_response(404, 'Not found',
                               'Halaman Tidak Ditemukan',
                               'Alamat yang Anda tuju tidak ada di sistem ini.')

    @app.errorhandler(413)
    def payload_too_large(e):
        max_mb = config.MAX_CONTENT_LENGTH / (1024 * 1024)
        logger.warning(
            f"Payload too large from {request.remote_addr}: "
            f"{request.content_length} bytes"
        )
        return jsonify({
            'success': False,
            'error': f'Payload terlalu besar. Maksimal {max_mb:.1f} MB.',
            'max_bytes': config.MAX_CONTENT_LENGTH,
        }), 413

    @app.errorhandler(429)
    def rate_limit_exceeded(e):
        return _error_response(429, 'Rate limit exceeded. Coba lagi nanti.',
                               'Terlalu Banyak Permintaan',
                               'Anda mengirim terlalu banyak permintaan. Coba lagi nanti.')

    @app.errorhandler(500)
    def internal_error(e):
        logger.error(f"Internal server error on {request.method} {request.path}")
        try:
            from app.database import get_db
            db = get_db()
            db.rollback()
        except Exception:
            pass
        return _error_response(500, 'Internal server error',
                               'Terjadi Kesalahan',
                               'Ada gangguan di server. Coba beberapa saat lagi.')

    @app.errorhandler(Exception)
    def unhandled_exception(e):
        from werkzeug.exceptions import HTTPException
        if isinstance(e, HTTPException):
            return e
        logger.error(f"Unhandled exception on {request.method} {request.path}: {e}", exc_info=True)
        return _error_response(500, 'Internal server error',
                               'Terjadi Kesalahan',
                               'Ada gangguan di server. Coba beberapa saat lagi.')


def _register_health_routes(app):
    @app.route('/health')
    @limiter.exempt
    def health_check():
        try:
            from app.database import get_db_context
            with get_db_context() as conn:
                conn.execute('SELECT 1').fetchone()
            return jsonify({
                'status': 'healthy',
                'timestamp': get_wib_time().isoformat(),
                'database': 'connected',
                'version': __version__,
            }), 200
        except Exception as e:
            # Detail hanya ke log; klien cukup tahu statusnya.
            logger.error(f"Health check failed: {e}", exc_info=True)
            return jsonify({'status': 'unhealthy', 'error': 'database tidak tersedia'}), 503

    @app.route('/ready')
    @limiter.exempt
    def readiness_check():
        return jsonify({'status': 'ready'}), 200


def create_app(config_override=None):
    validate_config_or_exit()

    app = Flask(__name__, template_folder='../templates', static_folder='../static')
    app.config.from_object(config)

    if config_override:
        app.config.update(config_override)

    warn_if_insecure_cookie(app.config)
    from app.ratelimit import warn_if_memory_limiter_multiworker
    warn_if_memory_limiter_multiworker(config.RATE_LIMIT_STORAGE)

    _apply_proxy_fix(app)
    _init_extensions(app)
    _register_static_cache_bust(app)
    _register_blueprints(app)
    _register_security_headers(app)
    _register_error_handlers(app)
    _register_health_routes(app)

    if config.DEBUG:
        @app.before_request
        def log_request():
            logger.debug(f"{request.method} {request.path}")

    # Restore tertunda diterapkan SEBELUM koneksi database mana pun dibuka.
    from app.database import _get_db_path
    from app.restore import apply_pending_restore
    try:
        apply_pending_restore(_get_db_path(), logger)
    except Exception as e:
        logger.error(f"Gagal menerapkan restore tertunda: {e}", exc_info=True)

    with app.app_context():
        init_db()

    if not app.config.get('TESTING'):
        from app.background import start_background_tasks
        start_background_tasks()

    logger.info("Application ready")
    return app
