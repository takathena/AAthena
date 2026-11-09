"""NEXUS IoT - FastAPI application factory (v2.0 core).

FastAPI jalan via `uvicorn app.main:app` / `run:app` (gunicorn+uvicorn).
Fitur: CORS, CSP/HSTS, SessionMiddleware starlette,
CSRF double-submit (exempt POST /api/v1/data), SlowAPI, exception handlers
JSON/HTML, /health /ready, lifespan init_db + background tasks.
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from slowapi.errors import RateLimitExceeded

from app.config import get_config

__version__ = '2.0.0'
logger = logging.getLogger('nexus')

CSRF_EXEMPT_PREFIX = '/api/v1/data'
CSRF_EXEMPT_PATHS = {'/login'}  # login divalidasi via form csrf_token di views.
CSRF_SAFE_METHODS = {'GET', 'HEAD', 'OPTIONS'}


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        config = get_config()
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = (
            'geolocation=(), microphone=(), camera=(), payment=(), usb=()'
        )
        if config.ENABLE_HSTS:
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


class _CsrfMiddleware(BaseHTTPMiddleware):
    """Double-submit: cookie `csrf_token` harus sama dengan header X-CSRFToken.

    Exempt: method aman, /health, /ready, dan POST /api/v1/data (device).
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in CSRF_SAFE_METHODS:
            return await call_next(request)
        path = request.url.path
        if path in ('/health', '/ready'):
            return await call_next(request)
        if request.method == 'POST' and path == CSRF_EXEMPT_PREFIX:
            return await call_next(request)
        if path in CSRF_EXEMPT_PATHS:
            return await call_next(request)
        cookie_token = request.cookies.get('csrf_token', '')
        header_token = request.headers.get('x-csrftoken', '')
        if not cookie_token or cookie_token != header_token:
            if path.startswith('/api/'):
                return JSONResponse(
                    {'success': False, 'error': 'CSRF validation failed'}, status_code=403)
            return PlainTextResponse('CSRF validation failed', status_code=403)
        return await call_next(request)


def _is_api(request: Request) -> bool:
    return request.url.path.startswith('/api/')


def _html_error(status: int, title: str, message: str) -> HTMLResponse:
    html = (f"<!doctype html><html><head><meta charset='utf-8'>"
            f"<title>{status} {title}</title></head><body>"
            f"<h1>{status} {title}</h1><p>{message}</p></body></html>")
    return HTMLResponse(html, status_code=status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    config = get_config()
    try:
        config.validate()
    except ValueError as e:
        raise SystemExit(1) from e
    from app.database import init_db
    init_result = init_db()
    if init_result is not None:
        await init_result
    if not config.TESTING:
        from app.background import start_background_tasks
        await start_background_tasks()
    logger.info('Application ready (FastAPI)')
    yield
    try:
        from app.background import stop_background_tasks
        await stop_background_tasks()
    except Exception:
        pass


def create_app(config_override=None):
    config = get_config()
    app = FastAPI(title='NEXUS IoT', version=__version__, lifespan=lifespan)

    from app.deps import limiter
    app.state.limiter = limiter

    if config_override:
        for key, value in config_override.items():
            setattr(config, key, value)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(config.CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
        allow_headers=['Content-Type', 'X-CSRFToken', 'X-Dashboard-Id'],
        max_age=3600,
    )
    app.add_middleware(_SecurityHeadersMiddleware)
    app.add_middleware(_CsrfMiddleware)
    secret = config.SECRET_KEY or 'nexus-dev-fallback-change-me-32chars'
    lifetime = int(config.PERMANENT_SESSION_LIFETIME.total_seconds())
    app.add_middleware(
        SessionMiddleware,
        secret_key=secret,
        max_age=lifetime,
        same_site=config.SESSION_COOKIE_SAMESITE.lower(),
        https_only=bool(config.SESSION_COOKIE_SECURE),
        session_cookie='session',
    )

    from app.routers import (alerts, chat, dashboards,
                              devices, ingest, system, users, views)
    app.include_router(ingest.router)
    app.include_router(devices.router)
    app.include_router(alerts.router)
    app.include_router(users.router)
    app.include_router(system.router)
    app.include_router(dashboards.router)
    app.include_router(chat.router)
    app.include_router(views.router)
    # File statik untuk template HTML (disajikan via StaticFiles).
    import os
    from fastapi.staticfiles import StaticFiles
    _static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static')
    if os.path.isdir(_static_dir):
        app.mount('/static', StaticFiles(directory=_static_dir), name='static')

    @app.get('/health')
    async def health_check():
        from app.database import get_db_context, get_wib_time

        async def _check():
            async with get_db_context() as conn:
                await (await conn.execute('SELECT 1')).fetchone()
            return True

        try:
            await _check()
            return JSONResponse({
                'status': 'healthy',
                'timestamp': get_wib_time().isoformat(),
                'database': 'connected',
                'version': __version__,
            })
        except Exception as e:
            logger.error(f'Health check failed: {e}', exc_info=True)
            return JSONResponse(
                {'status': 'unhealthy', 'error': 'database tidak tersedia'}, status_code=503)

    @app.get('/ready')
    async def readiness_check():
        return {'status': 'ready'}

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(request: Request, exc: StarletteHTTPException):
        logger.info(f"HTTP {exc.status_code} {request.method} {request.url.path}")
        # Redirect (mis. HTML auth -> /login): hormati header Location.
        if exc.status_code in (301, 302, 303, 307, 308):
            loc = (exc.headers or {}).get('Location', '/login')
            from fastapi.responses import RedirectResponse as _RR
            resp = _RR(url=loc, status_code=exc.status_code)
            resp.set_cookie  # no-op
            return resp
        detail = exc.detail
        if isinstance(detail, dict) and 'error' in detail:
            return JSONResponse(detail, status_code=exc.status_code)
        if _is_api(request):
            if isinstance(detail, str):
                return JSONResponse({'success': False, 'error': detail},
                                    status_code=exc.status_code)
            return JSONResponse(detail, status_code=exc.status_code)
        titles = {400: 'Permintaan Tidak Valid', 401: 'Perlu Masuk',
                  403: 'Akses Ditolak', 404: 'Halaman Tidak Ditemukan'}
        return _html_error(exc.status_code,
                           titles.get(exc.status_code, 'Kesalahan'),
                           'Permintaan tidak bisa diproses.')

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        if _is_api(request):
            return JSONResponse({'success': False, 'error': 'Bad request'}, status_code=400)
        return _html_error(400, 'Permintaan Tidak Valid', 'Permintaan tidak bisa diproses.')

    @app.exception_handler(RateLimitExceeded)
    async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
        if _is_api(request):
            return JSONResponse(
                {'success': False, 'error': 'Rate limit exceeded. Coba lagi nanti.'},
                status_code=429)
        return _html_error(429, 'Terlalu Banyak Permintaan',
                           'Anda mengirim terlalu banyak permintaan. Coba lagi nanti.')

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.error(f"Unhandled exception on {request.method} {request.url.path}: {exc}",
                     exc_info=True)
        if _is_api(request):
            return JSONResponse({'success': False, 'error': 'Internal server error'},
                                status_code=500)
        return _html_error(500, 'Terjadi Kesalahan',
                           'Ada gangguan di server. Coba beberapa saat lagi.')

    return app


app = create_app()
