"""Base de datos SQLite para almacenar datos AIS."""

import sqlite3
from contextlib import contextmanager
from config import DB_PATH


def init_db():
    """Crea las tablas si no existen."""
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
                timestamp TEXT NOT NULL,
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
            CREATE INDEX IF NOT EXISTS idx_positions_mmsi_ts
                ON positions(mmsi, timestamp);
        """)


@contextmanager
def get_conn():
    """Context manager para conexiones SQLite."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_vessel(mmsi, name=None, ship_type=None, flag=None,
                  length=None, width=None, callsign=None, imo=None):
    """Inserta o actualiza un barco."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO vessels (mmsi, name, ship_type, flag, length, width,
                                callsign, imo, first_seen, last_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
            ON CONFLICT(mmsi) DO UPDATE SET
                name = COALESCE(excluded.name, vessels.name),
                ship_type = COALESCE(excluded.ship_type, vessels.ship_type),
                flag = COALESCE(excluded.flag, vessels.flag),
                length = COALESCE(excluded.length, vessels.length),
                width = COALESCE(excluded.width, vessels.width),
                callsign = COALESCE(excluded.callsign, vessels.callsign),
                imo = COALESCE(excluded.imo, vessels.imo),
                last_seen = datetime('now')
        """, (mmsi, name, ship_type, flag, length, width, callsign, imo))


def insert_position(mmsi, timestamp, lat, lon, sog=None, cog=None,
                    heading=None, nav_status=None, rot=None):
    """Inserta una posición AIS."""
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO positions (mmsi, timestamp, lat, lon, sog, cog,
                                   heading, nav_status, rot)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (mmsi, timestamp, lat, lon, sog, cog, heading, nav_status, rot))


if __name__ == "__main__":
    init_db()
    print(f"Base de datos inicializada en {DB_PATH}")
