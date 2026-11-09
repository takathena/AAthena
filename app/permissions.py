"""
NEXUS IoT - Peran user dan izin granular (Paket A).

Sumber kebenaran tetap di backend. UI hanya menyembunyikan kontrol.

Peran (users.role):
  superadmin  akun awal dari .env. Tidak bisa dihapus, diturunkan, atau diubah peran-nya.
  admin       semua izin. Hanya superadmin yang bisa memberi peran admin.
  moderator   saat ini berperilaku seperti user (lihat dashboard di Paket B).
  user        hanya dashboard yang dimiliki / dibagikan, plus izin eksplisit.

Penentuan admin memakai users.is_admin (sudah dipakai backend sejak v1). Peran
di kolom role hanya membedakan superadmin, admin, moderator, dan user. Keduanya
harus selalu konsisten; set_role() menjaga itu.
"""
ROLE_SUPERADMIN = 'superadmin'
ROLE_ADMIN = 'admin'
ROLE_MODERATOR = 'moderator'
ROLE_USER = 'user'
ROLES = (ROLE_SUPERADMIN, ROLE_ADMIN, ROLE_MODERATOR, ROLE_USER)

PERMISSION_DENIED_ERROR = 'Anda tidak punya izin untuk fitur ini'


def resolve_role(is_admin, stored_role):
    """Peran efektif dari (is_admin, role). is_admin menang untuk admin/superadmin."""
    if is_admin:
        return ROLE_SUPERADMIN if stored_role == ROLE_SUPERADMIN else ROLE_ADMIN
    if stored_role == ROLE_MODERATOR:
        return ROLE_MODERATOR
    return ROLE_USER


def is_privileged(role):
    return role in (ROLE_SUPERADMIN, ROLE_ADMIN)


def get_user_info(conn, user_id):
    """Return dict {id, role, is_admin} atau None bila user tidak ada."""
    if not user_id:
        return None
    row = conn.execute(
        'SELECT id, is_admin, role FROM users WHERE id = ?', (user_id,)
    ).fetchone()
    if not row:
        return None
    return {
        'id': row['id'],
        'role': resolve_role(row['is_admin'], row['role']),
        'is_admin': bool(row['is_admin']),
    }


def explicit_permissions(conn, user_id):
    rows = conn.execute(
        'SELECT permission FROM user_permissions WHERE user_id = ?', (user_id,)
    ).fetchall()
    return {r['permission'] for r in rows}


def effective_permissions(conn, user_id):
    """Semua izin yang berlaku saat ini untuk user (dibaca dari DB setiap kali)."""
    return explicit_permissions(conn, user_id)


def has_permission(conn, user_id, permission):
    return permission in effective_permissions(conn, user_id)


def set_user_permissions(conn, user_id, permissions, granted_by=None):
    """Replace explicit permissions. Caller must commit."""
    conn.execute('DELETE FROM user_permissions WHERE user_id = ?', (user_id,))
    for p in permissions:
        conn.execute(
            'INSERT INTO user_permissions (user_id, permission, granted_by) VALUES (?, ?, ?)',
            (user_id, p, granted_by),
        )
    return set(permissions)


async def get_user_info_async(conn, user_id):
    if not user_id:
        return None
    row = await (await conn.execute(
        'SELECT id, is_admin, role FROM users WHERE id = ?', (user_id,)
    )).fetchone()
    if not row:
        return None
    return {
        'id': row['id'],
        'role': resolve_role(row['is_admin'], row['role']),
        'is_admin': bool(row['is_admin']),
    }


async def explicit_permissions_async(conn, user_id):
    rows = await (await conn.execute(
        'SELECT permission FROM user_permissions WHERE user_id = ?', (user_id,)
    )).fetchall()
    return {r['permission'] for r in rows}


async def effective_permissions_async(conn, user_id):
    return await explicit_permissions_async(conn, user_id)


async def set_user_permissions_async(conn, user_id, permissions, granted_by=None):
    await conn.execute('DELETE FROM user_permissions WHERE user_id = ?', (user_id,))
    for p in permissions:
        await conn.execute(
            'INSERT INTO user_permissions (user_id, permission, granted_by) VALUES (?, ?, ?)',
            (user_id, p, granted_by),
        )
    return set(permissions)

