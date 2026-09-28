"""Migración / limpieza de la base de datos AIS.

- Hace una copia de seguridad en dumps/ antes de tocar nada.
- Normaliza todos los timestamps a ISO 8601 UTC (2026-05-06T14:05:27Z).
- Elimina posiciones duplicadas (mismo MMSI y timestamp) y crea el índice
  único que impide que vuelvan a aparecer.
- Con --purge-non-fishing, borra las posiciones de barcos con tipo AIS
  conocido no pesquero (cargueros, tanques...). Por defecto no borra nada:
  el analizador ya los excluye al cargar.

Uso:
    python migrate_db.py [--purge-non-fishing] [--no-backup]
"""

import argparse
import os
import sqlite3
from datetime import datetime, timezone

from config import DB_PATH, is_fishing_candidate
from db import init_db, normalize_ts

BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dumps")


def backup(conn):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = os.path.join(BACKUP_DIR, f"ais_luarca-{stamp}-premigracion.db")
    dest = sqlite3.connect(path)
    with dest:
        conn.backup(dest)
    dest.close()
    print(f"Copia de seguridad: {path}")


def normalize_timestamps(conn):
    rows = conn.execute("SELECT id, timestamp FROM positions").fetchall()
    updates = []
    for pid, ts in rows:
        try:
            new = normalize_ts(ts)
        except ValueError:
            print(f"  ! timestamp no reconocido en id={pid}: {ts!r}")
            continue
        if new != ts:
            updates.append((new, pid))
    conn.executemany("UPDATE positions SET timestamp = ? WHERE id = ?", updates)
    print(f"Timestamps normalizados: {len(updates)} de {len(rows)}")


def dedupe(conn):
    cur = conn.execute("""
        DELETE FROM positions WHERE id NOT IN (
            SELECT MIN(id) FROM positions GROUP BY mmsi, timestamp
        )
    """)
    print(f"Posiciones duplicadas eliminadas: {cur.rowcount}")


def purge_non_fishing(conn):
    vessels = conn.execute("SELECT mmsi, ship_type FROM vessels").fetchall()
    drop = [m for m, t in vessels if not is_fishing_candidate(m, t)]
    total = 0
    for mmsi in drop:
        cur = conn.execute("DELETE FROM positions WHERE mmsi = ?", (mmsi,))
        total += cur.rowcount
    print(f"Posiciones de barcos no pesqueros eliminadas: {total} "
          f"({len(drop)} barcos)")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--purge-non-fishing", action="store_true",
                    help="borra posiciones de barcos con tipo conocido no pesquero")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(DB_PATH):
        print(f"No existe {DB_PATH}; nada que migrar.")
        return

    conn = sqlite3.connect(DB_PATH)
    try:
        if not args.no_backup:
            backup(conn)
        with conn:
            normalize_timestamps(conn)
            dedupe(conn)
            if args.purge_non_fishing:
                purge_non_fishing(conn)
        conn.execute("VACUUM")
    finally:
        conn.close()

    # Crea el índice único (ya sin duplicados)
    init_db()
    print("Migración completada.")


if __name__ == "__main__":
    main()
