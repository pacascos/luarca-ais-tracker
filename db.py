"""Base de datos SQLite para almacenar datos AIS."""

import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH

log = logging.getLogger(__name__)

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

# aisstream.io: "2026-05-06 14:05:27.563473488 +0000 UTC"
_AISSTREAM_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.\d+)? ([+-]\d{4}) UTC$"
)


def normalize_ts(value):
    """Convierte cualquier timestamp conocido a ISO 8601 UTC sin fracción.

    Acepta datetimes, el formato de aisstream.io, el de VesselTracker
    ("2026-04-06T16:00+0200") y cualquier ISO 8601 con o sin zona. Los
    valores sin zona se asumen UTC.
    """
    if isinstance(value, datetime):
        dt = value
    else:
        s = str(value).strip()
        m = _AISSTREAM_RE.match(s)
        if m:
            s = f"{m.group(1)}T{m.group(2)}{m.group(3)}"
        elif s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # Recorta fracciones de más de 6 dígitos (fromisoformat no las admite)
        s = re.sub(r"(\.\d{6})\d+", r"\1", s)
        dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime(TS_FORMAT)


def utcnow_ts():
    return datetime.now(timezone.utc).strftime(TS_FORMAT)


def open_conn():
    """Abre una conexión configurada (WAL + claves foráneas)."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def get_conn():
    """Context manager para conexiones SQLite de un solo uso."""
    conn = open_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def _use(conn):
    """Usa la conexión dada sin commit, o abre una temporal con commit."""
    if conn is not None:
        yield conn
    else:
        with get_conn() as c:
            yield c


def init_db():
    """Crea las tablas e índices si no existen."""
    with get_conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS vessels (
                mmsi TEXT PRIMARY KEY,
                name TEXT,
                ship_type INTEGER,
                flag TEXT,
                length REAL,
                width REAL,
                callsign TEXT,
                imo TEXT,
                first_seen TEXT,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mmsi TEXT NOT NULL,
                timestamp TEXT NOT NULL,   -- ISO 8601 UTC: 2026-05-06T14:05:27Z
                lat REAL NOT NULL,
                lon REAL NOT NULL,
                sog REAL,           -- speed over ground (nudos)
                cog REAL,           -- course over ground (grados)
                heading REAL,
                nav_status INTEGER,
                rot REAL,           -- rate of turn
                FOREIGN KEY (mmsi) REFERENCES vessels(mmsi)
            );

            CREATE INDEX IF NOT EXISTS idx_positions_mmsi
                ON positions(mmsi);
            CREATE INDEX IF NOT EXISTS idx_positions_timestamp
                ON positions(timestamp);
        """)
        # BDs antiguas tienen este índice sin UNIQUE: se sustituye
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_positions_mmsi_ts'"
        ).fetchone()
        if row and "UNIQUE" not in row[0].upper():
            conn.execute("DROP INDEX idx_positions_mmsi_ts")
        try:
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_mmsi_ts
                    ON positions(mmsi, timestamp)
            """)
        except sqlite3.IntegrityError:
            log.warning(
                "positions tiene duplicados (mmsi, timestamp); "
                "ejecuta migrate_db.py para limpiarlos y crear el índice único"
            )


def upsert_vessel(mmsi, name=None, ship_type=None, flag=None,
                  length=None, width=None, callsign=None, imo=None,
                  conn=None):
    """Inserta o actualiza un barco."""
    now = utcnow_ts()
    with _use(conn) as c:
        c.execute("""
            INSERT INTO vessels (mmsi, name, ship_type, flag, length, width,
                                callsign, imo, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(mmsi) DO UPDATE SET
                name = COALESCE(excluded.name, vessels.name),
                ship_type = COALESCE(excluded.ship_type, vessels.ship_type),
                flag = COALESCE(excluded.flag, vessels.flag),
                length = COALESCE(excluded.length, vessels.length),
                width = COALESCE(excluded.width, vessels.width),
                callsign = COALESCE(excluded.callsign, vessels.callsign),
                imo = COALESCE(excluded.imo, vessels.imo),
                last_seen = excluded.last_seen
        """, (str(mmsi), name, ship_type, flag, length, width, callsign, imo,
              now, now))


def insert_position(mmsi, timestamp, lat, lon, sog=None, cog=None,
                    heading=None, nav_status=None, rot=None, conn=None):
    """Inserta una posición AIS. Devuelve False si ya existía (mismo
    MMSI y timestamp)."""
    ts = normalize_ts(timestamp)
    with _use(conn) as c:
        cur = c.execute("""
            INSERT OR IGNORE INTO positions
                (mmsi, timestamp, lat, lon, sog, cog, heading, nav_status, rot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (str(mmsi), ts, lat, lon, sog, cog, heading, nav_status, rot))
        return cur.rowcount == 1


def load_ship_types(conn=None):
    """Devuelve {mmsi: ship_type} de todos los barcos conocidos."""
    with _use(conn) as c:
        return dict(c.execute("SELECT mmsi, ship_type FROM vessels"))


if __name__ == "__main__":
    init_db()
    print(f"Base de datos inicializada en {DB_PATH}")
