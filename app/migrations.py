"""
NEXUS IoT - Database Migrations
Schema version 18: multi-user + multi-dashboard (workspace) + analytics tabs + login_failures + audit_log.
Dipisahkan dari app/database.py (connection layer) agar file koneksi tetap kecil.
"""
import hashlib
import os
from datetime import datetime, timedelta, timezone

WIB = timezone(timedelta(hours=7))


def get_wib_time():
    """Return current WIB time as NAIVE datetime (lokal agar hindari circular import)."""
    return datetime.now(WIB).replace(tzinfo=None)


WIB_DEFAULT = "(datetime('now', '+7 hours'))"

def _migrate_v1(cursor):
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS devices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT UNIQUE NOT NULL,
            device_name TEXT NOT NULL,
            device_type TEXT DEFAULT 'ESP32',
            location TEXT DEFAULT '',
            latitude REAL DEFAULT 0,
            longitude REAL DEFAULT 0,
            description TEXT DEFAULT '',
            api_key TEXT UNIQUE NOT NULL,
            status TEXT DEFAULT 'offline',
            last_seen DATETIME,
            created_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS sensor_data (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            sensor_type TEXT NOT NULL,
            data TEXT NOT NULL,
            wifi_ssid TEXT DEFAULT '',
            uptime_seconds INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT {WIB_DEFAULT},
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at DATETIME DEFAULT {WIB_DEFAULT},
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sensor_data_device_timestamp ON sensor_data (device_id, timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sensor_data_timestamp ON sensor_data (timestamp)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_status ON devices (status)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_device_active ON alerts (device_id, is_active)')


def _migrate_v2(cursor):
    cols = [row[1] for row in cursor.execute('PRAGMA table_info(devices)').fetchall()]
    if 'last_ip' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN last_ip TEXT DEFAULT ""')
    if 'firmware_version' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN firmware_version TEXT DEFAULT ""')


def _migrate_v3(cursor):
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS cardholders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT UNIQUE NOT NULL,
            nama TEXT NOT NULL,
            created_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            device_id TEXT NOT NULL,
            timestamp DATETIME DEFAULT {WIB_DEFAULT},
            FOREIGN KEY (uid) REFERENCES cardholders (uid),
            FOREIGN KEY (device_id) REFERENCES devices (device_id)
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_uid_timestamp ON attendance (uid, timestamp)')


def _migrate_v4(cursor):
    fk_was_on = cursor.execute('PRAGMA foreign_keys').fetchone()[0]
    cursor.execute('PRAGMA foreign_keys=OFF')
    try:
        cursor.execute('ALTER TABLE attendance RENAME TO attendance_old')
        cursor.execute(f'''
            CREATE TABLE attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                device_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT {WIB_DEFAULT},
                FOREIGN KEY (device_id) REFERENCES devices (device_id)
            )
        ''')
        cursor.execute('''
            INSERT INTO attendance (id, uid, device_id, timestamp)
            SELECT id, uid, device_id, timestamp FROM attendance_old
        ''')
        cursor.execute('DROP TABLE attendance_old')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_attendance_uid_timestamp ON attendance (uid, timestamp)')
    finally:
        if fk_was_on:
            cursor.execute('PRAGMA foreign_keys=ON')


def _migrate_v5(cursor):
    cols = [row[1] for row in cursor.execute('PRAGMA table_info(devices)').fetchall()]

    if 'offline_timeout' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN offline_timeout INTEGER DEFAULT 900')
    if 'expected_interval' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN expected_interval INTEGER DEFAULT 60')
    if 'alert_rules' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN alert_rules TEXT DEFAULT NULL')
    if 'offline_alert_severity' not in cols:
        cursor.execute("ALTER TABLE devices ADD COLUMN offline_alert_severity TEXT DEFAULT 'danger'")

    alert_cols = [row[1] for row in cursor.execute('PRAGMA table_info(alerts)').fetchall()]
    if 'severity' not in alert_cols:
        cursor.execute("ALTER TABLE alerts ADD COLUMN severity TEXT DEFAULT 'warning'")
    if 'value' not in alert_cols:
        cursor.execute('ALTER TABLE alerts ADD COLUMN value REAL DEFAULT NULL')
    if 'updated_at' not in alert_cols:
        cursor.execute('ALTER TABLE alerts ADD COLUMN updated_at DATETIME DEFAULT NULL')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS alert_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            value REAL,
            action TEXT NOT NULL,
            created_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_history_device ON alert_history (device_id, created_at)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts (severity, is_active)')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS device_status_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            status TEXT NOT NULL,
            reason TEXT DEFAULT '',
            created_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_status_log_device ON device_status_log (device_id, created_at DESC)')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS user_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')


def _migrate_v6(cursor):
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_active_lookup ON alerts (device_id, alert_type, is_active)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alerts_active_severity ON alerts (is_active, severity, alert_type)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_alert_history_action ON alert_history (action, created_at DESC)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_sensor_data_timestamp_desc ON sensor_data (timestamp DESC)')


def _migrate_v7(cursor):
    print("[DB] v7: standardizing timezone to naive WIB...")

    tz_fields = [
        ('devices', 'last_seen'),
        ('sensor_data', 'timestamp'),
        ('alerts', 'created_at'),
        ('alerts', 'updated_at'),
        ('alert_history', 'created_at'),
        ('attendance', 'timestamp'),
        ('device_status_log', 'created_at'),
    ]

    for table, column in tz_fields:
        try:
            result = cursor.execute(
                f"UPDATE {table} SET {column} = REPLACE({column}, '+07:00', '') "
                f"WHERE {column} LIKE '%+07:00'"
            )
            if result.rowcount > 0:
                print(f"[DB] v7: stripped tz from {table}.{column} ({result.rowcount} rows)")
        except Exception as e:
            print(f"[DB] v7 skip {table}.{column}: {e}")

    utc_fields = [
        ('devices', 'created_at'),
        ('cardholders', 'created_at'),
    ]

    for table, column in utc_fields:
        try:
            result = cursor.execute(
                f"UPDATE {table} SET {column} = datetime({column}, '+7 hours') "
                f"WHERE {column} IS NOT NULL AND {column} NOT LIKE '%+07:00'"
            )
            if result.rowcount > 0:
                print(f"[DB] v7: UTC→WIB {table}.{column} ({result.rowcount} rows)")
        except Exception as e:
            print(f"[DB] v7 skip tz-convert {table}.{column}: {e}")

    print("[DB] v7: timezone standardization complete")


def _migrate_v8(cursor):
    print("[DB] v8: hashing API keys...")

    cols = [row[1] for row in cursor.execute('PRAGMA table_info(devices)').fetchall()]
    if 'api_key_hash' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN api_key_hash TEXT DEFAULT NULL')
        print("[DB] v8: added column api_key_hash")

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_api_key_hash ON devices (api_key_hash)')

    rows = cursor.execute(
        'SELECT device_id, api_key FROM devices WHERE api_key IS NOT NULL AND (api_key_hash IS NULL OR api_key_hash = "")'
    ).fetchall()

    hashed = 0
    for row in rows:
        device_id = row[0]
        api_key = row[1]
        if not api_key:
            continue
        key_hash = hashlib.sha256(api_key.encode('utf-8')).hexdigest()
        cursor.execute(
            'UPDATE devices SET api_key_hash = ? WHERE device_id = ?',
            (key_hash, device_id)
        )
        hashed += 1

    print(f"[DB] v8: hashed {hashed} API keys")


def _migrate_v9(cursor):
    print("[DB] v9: creating dashboards & widgets tables...")

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS dashboards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon TEXT DEFAULT 'fa-chart-line',
            is_default INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT {WIB_DEFAULT},
            updated_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS widgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id INTEGER NOT NULL,
            widget_type TEXT NOT NULL,
            title TEXT NOT NULL,
            device_id TEXT,
            config TEXT NOT NULL,
            grid_x INTEGER DEFAULT 0,
            grid_y INTEGER DEFAULT 0,
            grid_w INTEGER DEFAULT 2,
            grid_h INTEGER DEFAULT 2,
            created_at DATETIME DEFAULT {WIB_DEFAULT},
            updated_at DATETIME DEFAULT {WIB_DEFAULT},
            FOREIGN KEY (dashboard_id) REFERENCES dashboards (id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_widgets_dashboard ON widgets (dashboard_id)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dashboards_slug ON dashboards (slug)')

    existing = cursor.execute('SELECT id FROM dashboards WHERE slug = ?', ('default',)).fetchone()
    if not existing:
        cursor.execute('''
            INSERT INTO dashboards (slug, name, description, icon, is_default)
            VALUES ('default', 'Dashboard Utama', 'Dashboard bawaan', 'fa-chart-pie', 1)
        ''')
        print("[DB] v9: default dashboard created")
    else:
        print("[DB] v9: default dashboard already exists")


def _migrate_v10(cursor):
    print("[DB] v10: creating analytics_tabs...")

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS analytics_tabs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            icon TEXT DEFAULT 'fa-chart-line',
            position INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT {WIB_DEFAULT},
            updated_at DATETIME DEFAULT {WIB_DEFAULT},
            FOREIGN KEY (dashboard_id) REFERENCES dashboards (id) ON DELETE CASCADE
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_analytics_tabs_dashboard ON analytics_tabs (dashboard_id, position)')

    cols = [row[1] for row in cursor.execute('PRAGMA table_info(widgets)').fetchall()]
    if 'analytics_tab_id' not in cols:
        cursor.execute('ALTER TABLE widgets ADD COLUMN analytics_tab_id INTEGER DEFAULT NULL')
        print("[DB] v10: added column widgets.analytics_tab_id")

    print("[DB] v10: analytics_tabs ready")


def _migrate_v11(cursor):
    print("[DB] v11: fixing devices.api_key NOT NULL constraint...")

    cols = cursor.execute('PRAGMA table_info(devices)').fetchall()
    api_key_notnull = False
    for row in cols:
        if row[1] == 'api_key':
            api_key_notnull = bool(row[3])
            break

    if not api_key_notnull:
        print("[DB] v11: api_key sudah nullable, skip")
        return

    count = cursor.execute('SELECT COUNT(*) FROM devices').fetchone()[0]
    print(f"[DB] v11: recreating devices table ({count} rows)...")

    cursor.execute('PRAGMA foreign_keys=OFF')
    try:
        stale = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='devices_old_v11'"
        ).fetchone()
        if stale:
            print("[DB] v11: dropping leftover devices_old_v11")
            cursor.execute('DROP TABLE devices_old_v11')

        cursor.execute(f'''
            CREATE TABLE devices_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT UNIQUE NOT NULL,
                device_name TEXT NOT NULL,
                device_type TEXT DEFAULT 'ESP32',
                location TEXT DEFAULT '',
                latitude REAL DEFAULT 0,
                longitude REAL DEFAULT 0,
                description TEXT DEFAULT '',
                api_key TEXT UNIQUE,
                status TEXT DEFAULT 'offline',
                last_seen DATETIME,
                created_at DATETIME DEFAULT {WIB_DEFAULT},
                last_ip TEXT DEFAULT '',
                firmware_version TEXT DEFAULT '',
                offline_timeout INTEGER DEFAULT 900,
                expected_interval INTEGER DEFAULT 60,
                alert_rules TEXT DEFAULT NULL,
                offline_alert_severity TEXT DEFAULT 'danger',
                api_key_hash TEXT DEFAULT NULL
            )
        ''')

        cursor.execute('''
            INSERT INTO devices_new (
                id, device_id, device_name, device_type, location,
                latitude, longitude, description, api_key, status,
                last_seen, created_at, last_ip, firmware_version,
                offline_timeout, expected_interval, alert_rules,
                offline_alert_severity, api_key_hash
            )
            SELECT
                id, device_id, device_name, device_type,
                COALESCE(location, ''),
                COALESCE(latitude, 0),
                COALESCE(longitude, 0),
                COALESCE(description, ''),
                NULL,
                COALESCE(status, 'offline'),
                last_seen, created_at,
                COALESCE(last_ip, ''),
                COALESCE(firmware_version, ''),
                COALESCE(offline_timeout, 900),
                COALESCE(expected_interval, 60),
                alert_rules,
                COALESCE(offline_alert_severity, 'danger'),
                api_key_hash
            FROM devices
        ''')

        cursor.execute('DROP TABLE devices')
        cursor.execute('ALTER TABLE devices_new RENAME TO devices')

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_status ON devices (status)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_api_key_hash ON devices (api_key_hash)')

        print("[DB] v11: api_key NOT NULL removed")
        _rebuild_fk_tables(cursor)
    finally:
        cursor.execute('PRAGMA foreign_keys=ON')


def _rebuild_fk_tables(cursor):
    """Rebuild tabel yang punya FK ke devices."""
    print("[DB] rebuilding FK tables...")

    tables_to_fix = {
        'sensor_data': f'''
            CREATE TABLE sensor_data_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                sensor_type TEXT NOT NULL,
                data TEXT NOT NULL,
                wifi_ssid TEXT DEFAULT '',
                uptime_seconds INTEGER DEFAULT 0,
                timestamp DATETIME DEFAULT {WIB_DEFAULT},
                FOREIGN KEY (device_id) REFERENCES devices (device_id)
            )
        ''',
        'alerts': f'''
            CREATE TABLE alerts_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                alert_type TEXT NOT NULL,
                message TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                created_at DATETIME DEFAULT {WIB_DEFAULT},
                severity TEXT DEFAULT 'warning',
                value REAL DEFAULT NULL,
                updated_at DATETIME DEFAULT NULL,
                FOREIGN KEY (device_id) REFERENCES devices (device_id)
            )
        ''',
        'attendance': f'''
            CREATE TABLE attendance_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                uid TEXT NOT NULL,
                device_id TEXT NOT NULL,
                timestamp DATETIME DEFAULT {WIB_DEFAULT},
                FOREIGN KEY (device_id) REFERENCES devices (device_id)
            )
        ''',
    }

    indexes = {
        'sensor_data': [
            'CREATE INDEX IF NOT EXISTS idx_sensor_data_device_timestamp ON sensor_data (device_id, timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_sensor_data_timestamp ON sensor_data (timestamp)',
            'CREATE INDEX IF NOT EXISTS idx_sensor_data_timestamp_desc ON sensor_data (timestamp DESC)',
        ],
        'alerts': [
            'CREATE INDEX IF NOT EXISTS idx_alerts_device_active ON alerts (device_id, is_active)',
            'CREATE INDEX IF NOT EXISTS idx_alerts_severity ON alerts (severity, is_active)',
            'CREATE INDEX IF NOT EXISTS idx_alerts_active_lookup ON alerts (device_id, alert_type, is_active)',
            'CREATE INDEX IF NOT EXISTS idx_alerts_active_severity ON alerts (is_active, severity, alert_type)',
        ],
        'attendance': [
            'CREATE INDEX IF NOT EXISTS idx_attendance_uid_timestamp ON attendance (uid, timestamp)',
        ],
    }

    for table_name, create_sql in tables_to_fix.items():
        try:
            exists = cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,)
            ).fetchone()
            if not exists:
                continue

            cursor.execute(create_sql)
            cursor.execute(f'INSERT INTO {table_name}_new SELECT * FROM {table_name}')
            cursor.execute(f'DROP TABLE {table_name}')
            cursor.execute(f'ALTER TABLE {table_name}_new RENAME TO {table_name}')

            for idx_sql in indexes.get(table_name, []):
                cursor.execute(idx_sql)

            print(f"[DB] {table_name}: OK")
        except Exception as e:
            print(f"[DB] {table_name}: error - {e}")
            raise

    print("[DB] FK tables rebuilt")


def _migrate_v12(cursor):
    """Multi-user: users table + user_id on dashboards dengan composite unique."""
    print("[DB] v12: multi-user setup...")

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT DEFAULT '',
            is_admin INTEGER DEFAULT 0,
            created_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')

    dash_cols = [r[1] for r in cursor.execute('PRAGMA table_info(dashboards)').fetchall()]

    if 'user_id' not in dash_cols:
        cursor.connection.commit()
        fk_was_on = cursor.execute('PRAGMA foreign_keys').fetchone()[0]
        cursor.execute('PRAGMA foreign_keys=OFF')

        try:
            cursor.execute('DROP TABLE IF EXISTS dashboards_new')
            cursor.execute(f'''
                CREATE TABLE dashboards_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    slug TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    icon TEXT DEFAULT 'fa-chart-line',
                    is_default INTEGER DEFAULT 0,
                    user_id INTEGER DEFAULT NULL,
                    created_at DATETIME DEFAULT {WIB_DEFAULT},
                    updated_at DATETIME DEFAULT {WIB_DEFAULT},
                    UNIQUE (user_id, slug)
                )
            ''')
            cursor.execute('''
                INSERT INTO dashboards_new
                (id, slug, name, description, icon, is_default, user_id, created_at, updated_at)
                SELECT id, slug, name, description, icon, is_default, NULL, created_at, updated_at
                FROM dashboards
            ''')
            cursor.execute('DROP TABLE dashboards')
            cursor.execute('ALTER TABLE dashboards_new RENAME TO dashboards')
            cursor.connection.commit()
            print("[DB] v12: dashboards recreated with user_id + composite unique")
        finally:
            if fk_was_on:
                cursor.execute('PRAGMA foreign_keys=ON')

    admin_user = os.getenv('IOT_USERNAME', 'admin').strip()
    admin_pass = os.getenv('IOT_PASSWORD', '')

    if admin_user and admin_pass:
        existing = cursor.execute(
            'SELECT id FROM users WHERE username = ?', (admin_user,)
        ).fetchone()

        if not existing:
            try:
                from werkzeug.security import generate_password_hash
                pw_hash = generate_password_hash(admin_pass)
                cur = cursor.execute('''
                    INSERT INTO users (username, password_hash, display_name, is_admin)
                    VALUES (?, ?, 'Administrator', 1)
                ''', (admin_user, pw_hash))
                user_id = cur.lastrowid
                cursor.execute(
                    'UPDATE dashboards SET user_id = ? WHERE user_id IS NULL',
                    (user_id,)
                )
                print(f"[DB] v12: user '{admin_user}' (id={user_id}) created")
            except Exception as e:
                print(f"[DB] v12: gagal buat admin user: {e}")
        else:
            cursor.execute(
                'UPDATE dashboards SET user_id = ? WHERE user_id IS NULL',
                (existing['id'],)
            )
            print(f"[DB] v12: admin user '{admin_user}' sudah ada")
    else:
        print("[DB] v12: IOT_PASSWORD kosong, user akan dibuat saat login pertama")

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dashboards_user ON dashboards (user_id, is_default DESC)')
    print("[DB] v12: multi-user ready")


def _migrate_v13(cursor):
    """Repair stale FK references (regex-based, legacy)."""
    import re
    print("[DB] v13: repairing stale FK references...")

    cursor.connection.commit()
    fk_was_on = cursor.execute('PRAGMA foreign_keys').fetchone()[0]
    cursor.execute('PRAGMA foreign_keys=OFF')

    try:
        for table in ('widgets', 'analytics_tabs'):
            row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not row or not row[0]:
                continue
            sql = row[0]
            if '_old_' not in sql:
                print(f"[DB] v13: {table} OK, skip")
                continue

            fixed = re.sub(r'"?dashboards_old_v12"?', 'dashboards', sql)
            fixed = re.sub(
                r'^\s*CREATE TABLE\s+"?' + table + r'"?',
                f'CREATE TABLE {table}_repair', fixed, count=1, flags=re.IGNORECASE
            )

            cursor.execute(f'DROP TABLE IF EXISTS {table}_repair')
            cursor.execute(fixed)
            cursor.execute(f'INSERT INTO {table}_repair SELECT * FROM {table}')
            cursor.execute(f'DROP TABLE {table}')
            cursor.execute(f'ALTER TABLE {table}_repair RENAME TO {table}')
            print(f"[DB] v13: {table} rebuilt")

        cursor.execute('CREATE INDEX IF NOT EXISTS idx_widgets_dashboard ON widgets (dashboard_id)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_analytics_tabs_dashboard ON analytics_tabs (dashboard_id, position)')
        cursor.connection.commit()
    finally:
        if fk_was_on:
            cursor.execute('PRAGMA foreign_keys=ON')


def _migrate_v14(cursor):
    """Safety net v2: verifikasi FK via PRAGMA foreign_key_list + perbaiki jika target tidak ada.

    Ini menangkap kerusakan yang lolos dari v13 (mis. regex tidak match, atau
    tabel dibuat ulang oleh ALTER TABLE RENAME di SQLite versi baru).
    """
    print("[DB] v14: verifying & repairing FK integrity...")

    cursor.connection.commit()
    fk_was_on = cursor.execute('PRAGMA foreign_keys').fetchone()[0]
    cursor.execute('PRAGMA foreign_keys=OFF')

    try:
        existing_tables = {
            r[0] for r in cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }

        for table in ('widgets', 'analytics_tabs'):
            if table not in existing_tables:
                print(f"[DB] v14: {table} tidak ada, skip")
                continue

            fks = cursor.execute(f'PRAGMA foreign_key_list({table})').fetchall()
            # fk columns: id, seq, table, from, to, on_update, on_delete, match
            broken_targets = [fk[2] for fk in fks if fk[2] not in existing_tables]

            sql_row = cursor.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            sql = sql_row[0] if sql_row else ''
            has_stale_sql = 'dashboards_old' in (sql or '')

            if not broken_targets and not has_stale_sql:
                print(f"[DB] v14: {table} OK")
                continue

            print(f"[DB] v14: rebuilding {table} (broken={broken_targets}, stale_sql={has_stale_sql})")
            old_cols = [r[1] for r in cursor.execute(f'PRAGMA table_info({table})').fetchall()]

            if table == 'widgets':
                cursor.execute('DROP TABLE IF EXISTS widgets_v14')
                cursor.execute(f'''
                    CREATE TABLE widgets_v14 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dashboard_id INTEGER NOT NULL,
                        widget_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        device_id TEXT,
                        config TEXT NOT NULL,
                        grid_x INTEGER DEFAULT 0,
                        grid_y INTEGER DEFAULT 0,
                        grid_w INTEGER DEFAULT 2,
                        grid_h INTEGER DEFAULT 2,
                        analytics_tab_id INTEGER DEFAULT NULL,
                        created_at DATETIME DEFAULT {WIB_DEFAULT},
                        updated_at DATETIME DEFAULT {WIB_DEFAULT},
                        FOREIGN KEY (dashboard_id) REFERENCES dashboards (id) ON DELETE CASCADE
                    )
                ''')
                if 'analytics_tab_id' in old_cols:
                    cursor.execute('INSERT INTO widgets_v14 SELECT * FROM widgets')
                else:
                    cursor.execute('''
                        INSERT INTO widgets_v14
                        (id, dashboard_id, widget_type, title, device_id, config,
                         grid_x, grid_y, grid_w, grid_h, analytics_tab_id,
                         created_at, updated_at)
                        SELECT id, dashboard_id, widget_type, title, device_id, config,
                               grid_x, grid_y, grid_w, grid_h, NULL,
                               created_at, updated_at
                        FROM widgets
                    ''')
                cursor.execute('DROP TABLE widgets')
                cursor.execute('ALTER TABLE widgets_v14 RENAME TO widgets')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_widgets_dashboard ON widgets (dashboard_id)')
                print("[DB] v14: widgets rebuilt")

            elif table == 'analytics_tabs':
                cursor.execute('DROP TABLE IF EXISTS analytics_tabs_v14')
                cursor.execute(f'''
                    CREATE TABLE analytics_tabs_v14 (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dashboard_id INTEGER NOT NULL,
                        name TEXT NOT NULL,
                        icon TEXT DEFAULT 'fa-chart-line',
                        position INTEGER DEFAULT 0,
                        created_at DATETIME DEFAULT {WIB_DEFAULT},
                        updated_at DATETIME DEFAULT {WIB_DEFAULT},
                        FOREIGN KEY (dashboard_id) REFERENCES dashboards (id) ON DELETE CASCADE
                    )
                ''')
                cursor.execute('INSERT INTO analytics_tabs_v14 SELECT * FROM analytics_tabs')
                cursor.execute('DROP TABLE analytics_tabs')
                cursor.execute('ALTER TABLE analytics_tabs_v14 RENAME TO analytics_tabs')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_analytics_tabs_dashboard ON analytics_tabs (dashboard_id, position)')
                print("[DB] v14: analytics_tabs rebuilt")

        # Pastikan setiap dashboard punya minimal satu tab "Default"
        dashboards_without_tabs = cursor.execute('''
            SELECT d.id FROM dashboards d
            WHERE NOT EXISTS (
                SELECT 1 FROM analytics_tabs t WHERE t.dashboard_id = d.id
            )
        ''').fetchall()

        for row in dashboards_without_tabs:
            cursor.execute('''
                INSERT INTO analytics_tabs
                (dashboard_id, name, icon, position, created_at, updated_at)
                VALUES (?, 'Default', 'fa-chart-line', 0, ?, ?)
            ''', (row['id'], get_wib_time(), get_wib_time()))
            print(f"[DB] v14: default tab created for dashboard {row['id']}")

        cursor.connection.commit()
        print("[DB] v14: FK integrity verified")
    finally:
        if fk_was_on:
            cursor.execute('PRAGMA foreign_keys=ON')


def _migrate_v15(cursor):
    """devices.interval_manual: 1 = interval diisi manual, auto-detect dimatikan."""
    cols = [r[1] for r in cursor.execute('PRAGMA table_info(devices)').fetchall()]
    if 'interval_manual' not in cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN interval_manual INTEGER DEFAULT 0')
        print("[DB] v15: added column devices.interval_manual")


def _migrate_v16(cursor):
    """login_failures: penghitung login gagal (per username+IP dan per IP) untuk throttle."""
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS login_failures (
            key TEXT PRIMARY KEY,
            fail_count INTEGER NOT NULL DEFAULT 0,
            window_start REAL NOT NULL DEFAULT 0,
            locked_until REAL NOT NULL DEFAULT 0
        )
    ''')
    print("[DB] v16: created table login_failures")


def _migrate_v17(cursor):
    """Workspace: dashboard memiliki perangkat, anggota, dan Telegram sendiri.

    - devices.dashboard_id (kolom biasa, tanpa FK, supaya tidak perlu
      membangun ulang tabel besar).
    - dashboard_members: berbagi dashboard dengan peran viewer/editor.
    - dashboard_telegram: bot Telegram per dashboard (token terenkripsi).
    - audit_log: catatan aksi sensitif (hapus data, ubah Telegram, dll).
    Data lama dipindahkan ke dashboard default milik admin pertama.
    Aman dijalankan ulang (idempotent).
    """
    print("[DB] v17: workspace (dashboard memiliki perangkat)...")

    dev_cols = [r[1] for r in cursor.execute('PRAGMA table_info(devices)').fetchall()]
    if 'dashboard_id' not in dev_cols:
        cursor.execute('ALTER TABLE devices ADD COLUMN dashboard_id INTEGER DEFAULT NULL')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_devices_dashboard ON devices (dashboard_id)')

    card_cols = [r[1] for r in cursor.execute('PRAGMA table_info(cardholders)').fetchall()]
    if 'dashboard_id' not in card_cols:
        cursor.execute('ALTER TABLE cardholders ADD COLUMN dashboard_id INTEGER DEFAULT NULL')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_cardholders_dashboard ON cardholders (dashboard_id)')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS dashboard_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dashboard_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL DEFAULT 'viewer' CHECK (role IN ('viewer', 'editor')),
            created_at DATETIME DEFAULT {WIB_DEFAULT},
            UNIQUE (dashboard_id, user_id),
            FOREIGN KEY (dashboard_id) REFERENCES dashboards (id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_dashboard_members_user ON dashboard_members (user_id)')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS dashboard_telegram (
            dashboard_id INTEGER PRIMARY KEY,
            bot_token_enc TEXT NOT NULL DEFAULT '',
            chat_id TEXT NOT NULL DEFAULT '',
            enabled INTEGER NOT NULL DEFAULT 1,
            updated_at DATETIME DEFAULT {WIB_DEFAULT},
            FOREIGN KEY (dashboard_id) REFERENCES dashboards (id) ON DELETE CASCADE
        )
    ''')

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT DEFAULT '',
            action TEXT NOT NULL,
            detail TEXT DEFAULT '',
            ip TEXT DEFAULT '',
            created_at DATETIME DEFAULT {WIB_DEFAULT}
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_audit_log_created ON audit_log (created_at DESC)')

    target = cursor.execute('''
        SELECT d.id FROM dashboards d
        JOIN users u ON u.id = d.user_id
        WHERE u.is_admin = 1
        ORDER BY d.is_default DESC, u.id ASC, d.id ASC LIMIT 1
    ''').fetchone()

    if target:
        tid = target[0]
        moved = cursor.execute(
            'UPDATE devices SET dashboard_id = ? WHERE dashboard_id IS NULL', (tid,)
        ).rowcount
        moved_cards = cursor.execute(
            'UPDATE cardholders SET dashboard_id = ? WHERE dashboard_id IS NULL', (tid,)
        ).rowcount
        print(f"[DB] v17: {moved} perangkat & {moved_cards} kartu dipindah ke dashboard {tid}")
    else:
        print("[DB] v17: belum ada admin/dashboard, perangkat lama dibiarkan tanpa dashboard "
              "(hanya terlihat oleh admin)")


def _migrate_v18(cursor):
    """Paket A: peran user dan izin granular.

    - users.role: superadmin | admin | moderator | user.
      Backfill: akun seed (IOT_USERNAME) jadi superadmin; is_admin lain jadi admin;
      sisanya user. Bila tidak ada superadmin, admin tertua dijadikan superadmin.
    - user_permissions: izin eksplisit. Migrasi TIDAK memberi izin ke siapa pun.
    Aman dijalankan ulang (idempotent).
    """
    print("[DB] v18: peran user dan izin granular...")

    cols = [r[1] for r in cursor.execute('PRAGMA table_info(users)').fetchall()]
    if 'role' not in cols:
        cursor.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'user'")

    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id INTEGER NOT NULL,
            permission TEXT NOT NULL,
            granted_by INTEGER,
            granted_at DATETIME DEFAULT {WIB_DEFAULT},
            PRIMARY KEY (user_id, permission),
            FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
        )
    ''')

    env_user = os.getenv('IOT_USERNAME', 'admin').strip()
    cursor.execute(
        "UPDATE users SET role = 'superadmin' WHERE username = ? AND is_admin = 1",
        (env_user,)
    )
    cursor.execute(
        "UPDATE users SET role = 'admin' WHERE is_admin = 1 AND role != 'superadmin'"
    )
    has_super = cursor.execute(
        "SELECT 1 FROM users WHERE role = 'superadmin' AND is_admin = 1 LIMIT 1"
    ).fetchone()
    if not has_super:
        cursor.execute(
            "UPDATE users SET role = 'superadmin' WHERE id = "
            "(SELECT MIN(id) FROM users WHERE is_admin = 1)"
        )
    print("[DB] v18: peran diisi, tabel user_permissions siap")


def _migrate_v19(cursor):
    """Hapus fitur absensi: DROP TABLE attendance + cardholders. Aman dijalankan ulang."""
    print("[DB] v19: dropping attendance & cardholders...")
    cursor.execute('DROP TABLE IF EXISTS attendance')
    cursor.execute('DROP TABLE IF EXISTS cardholders')
    print("[DB] v19: attendance & cardholders dibuang")


# Registry migrasi urut. app/database.py (_init_db_inner) memakai daftar ini.
MIGRATIONS = [
    (1, _migrate_v1),
    (2, _migrate_v2),
    (3, _migrate_v3),
    (4, _migrate_v4),
    (5, _migrate_v5),
    (6, _migrate_v6),
    (7, _migrate_v7),
    (8, _migrate_v8),
    (9, _migrate_v9),
    (10, _migrate_v10),
    (11, _migrate_v11),
    (12, _migrate_v12),
    (13, _migrate_v13),
    (14, _migrate_v14),
    (15, _migrate_v15),
    (16, _migrate_v16),
    (17, _migrate_v17),
    (18, _migrate_v18),
    (19, _migrate_v19),
]

# Re-export untuk kompatibilitas: nama lama yang sempat diimpor langsung.
__all__ = [
    "WIB_DEFAULT", "MIGRATIONS",
    "_migrate_v1", "_migrate_v2", "_migrate_v3", "_migrate_v4", "_migrate_v5",
    "_migrate_v6", "_migrate_v7", "_migrate_v8", "_migrate_v9", "_migrate_v10",
    "_migrate_v11", "_migrate_v12", "_migrate_v13", "_migrate_v14", "_migrate_v15",
    "_migrate_v16", "_migrate_v17", "_migrate_v18", "_migrate_v19", "_rebuild_fk_tables",
]
