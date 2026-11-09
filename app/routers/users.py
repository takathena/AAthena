"""NEXUS IoT - FastAPI user endpoints (dari app/api.py USER MANAGEMENT)."""
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app import permissions as perm
from app.api_common import _clean_timestamp, _validate_username
from app.config import get_config
from app.deps import audit, get_current_user, limiter, require_admin, safe_json

logger = logging.getLogger('nexus')
router = APIRouter(prefix='/api/v1', tags=['users'])


@router.get('/users/me')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_current_user_endpoint(request: Request):
    user = get_current_user(request)
    uid = user['user_id']
    if not uid:
        return JSONResponse({'success': False, 'error': 'Session invalid'}, status_code=401)
    from app.database import get_db_context

    async def _do():
        async with get_db_context() as conn:
            row = await (await conn.execute(
                'SELECT id, username, display_name FROM users WHERE id = ?',
                (uid,)
            )).fetchone()
            info = await perm.get_user_info_async(conn, uid)
            effective = sorted(await perm.effective_permissions_async(conn, uid)) if info else []
        return row, info, effective

    row, info, effective = await _do()
    if not row or not info:
        return JSONResponse({'success': False, 'error': 'User tidak ditemukan'}, status_code=404)
    return JSONResponse({'success': True, 'user': {
        'id': row['id'],
        'username': row['username'],
        'display_name': row['display_name'] or row['username'],
        'is_admin': info['is_admin'],
        'role': info['role'],
        'permissions': effective,
    }})


@router.get('/users')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def list_users(request: Request):
    await require_admin(request)
    from app.database import get_db_context

    async def _do():
        async with get_db_context() as conn:
            rows = await (await conn.execute('''
                SELECT id, username, display_name, is_admin, role, created_at
                FROM users
                ORDER BY is_admin DESC, username ASC
            ''')).fetchall()
        return rows

    rows = await _do()
    users = []
    for r in rows:
        d = dict(r)
        d['is_admin'] = bool(d['is_admin'])
        d['role'] = perm.resolve_role(d['is_admin'], d.pop('role', None))
        d['created_at'] = _clean_timestamp(d.get('created_at'))
        users.append(d)
    return JSONResponse({'success': True, 'users': users})


@router.post('/users')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def create_user(request: Request):
    await require_admin(request)
    from app.database import get_db_context, get_wib_time
    from werkzeug.security import generate_password_hash
    user = get_current_user(request)
    payload = await safe_json(request) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    display_name = (payload.get('display_name') or '').strip() or username
    requested = payload.get('role')
    if requested is None:
        requested = perm.ROLE_ADMIN if payload.get('is_admin') else perm.ROLE_USER
    if requested not in (perm.ROLE_ADMIN, perm.ROLE_MODERATOR, perm.ROLE_USER):
        return JSONResponse({'success': False, 'error': 'Peran tidak valid'}, status_code=400)
    is_admin = requested == perm.ROLE_ADMIN
    uerr = _validate_username(username)
    if uerr:
        return JSONResponse({'success': False, 'error': uerr}, status_code=400)
    if not password or len(password) < 8:
        return JSONResponse(
            {'success': False, 'error': 'Password minimal 8 karakter'}, status_code=400)
    if len(display_name) > 128:
        return JSONResponse(
            {'success': False, 'error': 'Display name maksimal 128 karakter'}, status_code=400)

    async def _do():
        async with get_db_context() as conn:
            caller = await perm.get_user_info_async(conn, user['user_id'])
            if is_admin and not (caller and caller['role'] == perm.ROLE_SUPERADMIN):
                return JSONResponse(
                    {'success': False,
                     'error': 'Hanya superadmin yang bisa memberi peran admin'},
                    status_code=403), None
            existing = await (await conn.execute(
                'SELECT id FROM users WHERE username = ?', (username,))).fetchone()
            if existing:
                return JSONResponse(
                    {'success': False, 'error': 'Username sudah dipakai'}, status_code=400), None
            pw_hash = generate_password_hash(password)
            cur = await conn.execute('''
                INSERT INTO users (username, password_hash, display_name, is_admin, role, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (username, pw_hash, display_name, 1 if is_admin else 0,
                  requested, get_wib_time()))
            new_id = cur.lastrowid
            await audit(conn, request, user['user_id'], user['username'],
                  'user.create', f'user={username} id={new_id} role={requested}')
            await conn.commit()
        return None, new_id

    err, new_id = await _do()
    if err is not None:
        return err
    logger.info(f"User created: {username} (id={new_id}, admin={is_admin})")
    return JSONResponse({'success': True, 'user': {
        'id': new_id, 'username': username, 'display_name': display_name,
        'is_admin': is_admin, 'role': requested}}, status_code=201)


@router.put('/users/{user_id:int}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_user(user_id: int, request: Request):
    await require_admin(request)
    from app.database import get_db_context
    from werkzeug.security import generate_password_hash
    user = get_current_user(request)
    caller_id = user['user_id']
    payload = await safe_json(request) or {}

    async def _do():
        async with get_db_context() as conn:
            user_row = await (await conn.execute(
                'SELECT id, username, is_admin, role FROM users WHERE id = ?',
                (user_id,))).fetchone()
            if not user_row:
                return JSONResponse(
                    {'success': False, 'error': 'User tidak ditemukan'}, status_code=404)
            target = await perm.get_user_info_async(conn, user_id)
            caller = await perm.get_user_info_async(conn, caller_id)
            caller_super = bool(caller and caller['role'] == perm.ROLE_SUPERADMIN)
            self_edit = user_id == caller_id
            if perm.is_privileged(target['role']) and not caller_super and not self_edit:
                return JSONResponse(
                    {'success': False,
                     'error': 'Hanya superadmin yang bisa mengubah admin lain'},
                    status_code=403)
            requested_role = None
            if 'role' in payload:
                requested_role = payload.get('role')
            elif 'is_admin' in payload:
                requested_role = (perm.ROLE_ADMIN if payload.get('is_admin')
                                  else perm.ROLE_USER)
            fields, params = [], []
            if 'display_name' in payload:
                dn = (payload.get('display_name') or '').strip()
                if not dn:
                    return JSONResponse(
                        {'success': False, 'error': 'Display name tidak boleh kosong'},
                        status_code=400)
                if len(dn) > 128:
                    return JSONResponse(
                        {'success': False, 'error': 'Display name maksimal 128 karakter'},
                        status_code=400)
                fields.append('display_name = ?')
                params.append(dn)
            if 'password' in payload:
                pw = payload.get('password') or ''
                if pw:
                    if len(pw) < 8:
                        return JSONResponse(
                            {'success': False, 'error': 'Password minimal 8 karakter'},
                            status_code=400)
                    fields.append('password_hash = ?')
                    params.append(generate_password_hash(pw))
            role_changed = None
            if requested_role is not None and requested_role != target['role']:
                if target['role'] == perm.ROLE_SUPERADMIN:
                    return JSONResponse(
                        {'success': False, 'error': 'Peran superadmin tidak bisa diubah'},
                        status_code=403)
                if requested_role not in (perm.ROLE_ADMIN, perm.ROLE_MODERATOR,
                                          perm.ROLE_USER):
                    return JSONResponse(
                        {'success': False, 'error': 'Peran tidak valid'}, status_code=400)
                if self_edit and not caller_super:
                    return JSONResponse(
                        {'success': False,
                         'error': 'Anda tidak bisa mengubah peran akun sendiri'},
                        status_code=403)
                if requested_role == perm.ROLE_ADMIN and not caller_super:
                    return JSONResponse(
                        {'success': False,
                         'error': 'Hanya superadmin yang bisa memberi peran admin'},
                        status_code=403)
                if perm.is_privileged(target['role']) and not perm.is_privileged(requested_role):
                    admin_count = (await (await conn.execute(
                        'SELECT COUNT(*) FROM users WHERE is_admin = 1')).fetchone())[0]
                    if admin_count <= 1:
                        return JSONResponse(
                            {'success': False, 'error': 'Tidak bisa demote admin terakhir'},
                            status_code=400)
                fields.append('role = ?')
                params.append(requested_role)
                fields.append('is_admin = ?')
                params.append(1 if perm.is_privileged(requested_role) else 0)
                role_changed = (target['role'], requested_role)
            if not fields:
                return JSONResponse(
                    {'success': False, 'error': 'Tidak ada field yang diupdate'},
                    status_code=400)
            params.append(user_id)
            await conn.execute(f'UPDATE users SET {", ".join(fields)} WHERE id = ?', params)
            if role_changed:
                await audit(conn, request, caller_id, user['username'], 'user.role',
                      f"user={user_row['username']} id={user_id} "
                      f"{role_changed[0]}->{role_changed[1]}")
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    logger.info(f"User updated: id={user_id}")
    return JSONResponse({'success': True})


@router.delete('/users/{user_id:int}')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def delete_user(user_id: int, request: Request):
    await require_admin(request)
    from app.database import get_db_context
    user = get_current_user(request)
    if user_id == user['user_id']:
        return JSONResponse(
            {'success': False, 'error': 'Tidak bisa hapus akun sendiri'}, status_code=400)

    async def _do():
        async with get_db_context() as conn:
            user_row = await (await conn.execute(
                'SELECT id, username, is_admin, role FROM users WHERE id = ?',
                (user_id,))).fetchone()
            if not user_row:
                return JSONResponse(
                    {'success': False, 'error': 'User tidak ditemukan'}, status_code=404)
            target_role = perm.resolve_role(user_row['is_admin'], user_row['role'])
            caller = await perm.get_user_info_async(conn, user['user_id'])
            if target_role == perm.ROLE_SUPERADMIN:
                return JSONResponse(
                    {'success': False, 'error': 'Superadmin tidak bisa dihapus'},
                    status_code=403)
            if perm.is_privileged(target_role) and not (caller and caller['role']
                                                         == perm.ROLE_SUPERADMIN):
                return JSONResponse(
                    {'success': False, 'error': 'Hanya superadmin yang bisa menghapus admin'},
                    status_code=403)
            if user_row['is_admin']:
                admin_count = (await (await conn.execute(
                    'SELECT COUNT(*) FROM users WHERE is_admin = 1')).fetchone())[0]
                if admin_count <= 1:
                    return JSONResponse(
                        {'success': False, 'error': 'Tidak bisa hapus admin terakhir'},
                        status_code=400)
            dash_ids = [r[0] for r in await (await conn.execute(
                'SELECT id FROM dashboards WHERE user_id = ?', (user_id,))).fetchall()]
            acting = await (await conn.execute(
                'SELECT id FROM dashboards WHERE user_id = ? '
                'ORDER BY is_default DESC, id ASC LIMIT 1',
                (user['user_id'],))).fetchone()
            target_dash = acting['id'] if acting else None
            if target_dash is None and dash_ids:
                orphan = 0
                for did in dash_ids:
                    orphan += (await (await conn.execute(
                        'SELECT COUNT(*) FROM devices WHERE dashboard_id = ?',
                        (did,))).fetchone())[0]
                if orphan:
                    return JSONResponse({'success': False, 'error': (
                        f'Anda belum punya dashboard tujuan untuk menampung '
                        f'{orphan} perangkat milik user ini. Buat '
                        f'dashboard dulu, lalu hapus ulang user.')}, status_code=409)
            moved_devices = 0
            from app.deps import purge_dashboard
            for did in dash_ids:
                moved_devices += (await conn.execute(
                    'UPDATE devices SET dashboard_id = ? WHERE dashboard_id = ?',
                    (target_dash, did))).rowcount
                await purge_dashboard(conn, did)
            await conn.execute('DELETE FROM dashboard_members WHERE user_id = ?', (user_id,))
            await conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
            await audit(conn, request, user['user_id'], user['username'], 'user.delete',
                  f"user={user_row['username']} id={user_id} "
                  f"devices_moved={moved_devices}")
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    logger.warning(f"User deleted: id={user_id}")
    return JSONResponse({'success': True})


@router.get('/users/{user_id:int}/permissions')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def get_user_permissions(user_id: int, request: Request):
    await require_admin(request)
    from app.database import get_db_context

    async def _do():
        async with get_db_context() as conn:
            target = await perm.get_user_info_async(conn, user_id)
            if not target:
                return JSONResponse(
                    {'success': False, 'error': 'User tidak ditemukan'}, status_code=404), None
            explicit = sorted(await perm.explicit_permissions_async(conn, user_id))
            effective = sorted(await perm.effective_permissions_async(conn, user_id))
        return None, {'role': target['role'],
                      'implicit_all': perm.is_privileged(target['role']),
                      'explicit': explicit, 'permissions': effective}

    err, data = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, **data})


@router.put('/users/{user_id:int}/permissions')
@limiter.limit(get_config().RATE_LIMIT_DEFAULT)
async def update_user_permissions(user_id: int, request: Request):
    await require_admin(request)
    from app.database import get_db_context
    user = get_current_user(request)

    async def _do():
        async with get_db_context() as conn:
            target = await perm.get_user_info_async(conn, user_id)
            if not target:
                return JSONResponse(
                    {'success': False, 'error': 'User tidak ditemukan'}, status_code=404), None
            if perm.is_privileged(target['role']):
                return JSONResponse(
                    {'success': False,
                     'error': 'Admin dan superadmin sudah punya semua izin'},
                    status_code=400), None
            before = sorted(await perm.explicit_permissions_async(conn, user_id))
            after = sorted(await perm.set_user_permissions_async(conn, user_id, user['user_id']))
            username = (await (await conn.execute(
                'SELECT username FROM users WHERE id = ?', (user_id,))).fetchone())['username']
            if before != after:
                await audit(conn, request, user['user_id'], user['username'], 'user.permissions',
                      f"user={username} id={user_id} "
                      f"{','.join(before) or '-'}->{','.join(after) or '-'}")
            effective = sorted(await perm.effective_permissions_async(conn, user_id))
            await conn.commit()
        return None, effective

    err, effective = await _do()
    if err is not None:
        return err
    return JSONResponse({'success': True, 'permissions': effective})


@router.post('/users/me/password')
@limiter.limit('10 per minute')
async def change_own_password(request: Request):
    from app.database import get_db_context
    from werkzeug.security import check_password_hash, generate_password_hash
    user = get_current_user(request)
    uid = user['user_id']
    if not uid:
        return JSONResponse({'success': False, 'error': 'Session invalid'}, status_code=401)
    payload = await safe_json(request) or {}
    old_password = payload.get('old_password') or ''
    new_password = payload.get('new_password') or ''
    if not old_password or not new_password:
        return JSONResponse(
            {'success': False, 'error': 'Password lama dan baru wajib diisi'}, status_code=400)
    if len(new_password) < 8:
        return JSONResponse(
            {'success': False, 'error': 'Password baru minimal 8 karakter'}, status_code=400)
    if old_password == new_password:
        return JSONResponse(
            {'success': False, 'error': 'Password baru harus berbeda dari yang lama'},
            status_code=400)

    async def _do():
        async with get_db_context() as conn:
            user_row = await (await conn.execute(
                'SELECT id, username, password_hash FROM users WHERE id = ?',
                (uid,))).fetchone()
            if not user_row:
                return JSONResponse(
                    {'success': False, 'error': 'User tidak ditemukan'}, status_code=404)
            try:
                valid = check_password_hash(user_row['password_hash'], old_password)
            except Exception:
                valid = False
            if not valid:
                logger.warning(f"Change password failed (wrong old) for {user_row['username']}")
                return JSONResponse(
                    {'success': False, 'error': 'Password lama salah'}, status_code=400)
            new_hash = generate_password_hash(new_password)
            await conn.execute('UPDATE users SET password_hash = ? WHERE id = ?',
                         (new_hash, uid))
            await conn.commit()
        return None

    err = await _do()
    if err is not None:
        return err
    logger.info(f"Password changed for user id={uid}")
    return JSONResponse({'success': True, 'message': 'Password berhasil diubah'})
