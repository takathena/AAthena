"""
AAguard IoT - Peran user dan izin granular (Paket A).

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


def resolve_role(is_admin, stored_role):
    """Peran efektif dari (is_admin, role). is_admin menang untuk admin/superadmin."""
    if is_admin:
        return ROLE_SUPERADMIN if stored_role == ROLE_SUPERADMIN else ROLE_ADMIN
    if stored_role == ROLE_MODERATOR:
        return ROLE_MODERATOR
    return ROLE_USER


def is_privileged(role):
    return role in (ROLE_SUPERADMIN, ROLE_ADMIN)


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

