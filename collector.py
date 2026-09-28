"""Collector de datos AIS en tiempo real via aisstream.io WebSocket."""

import asyncio
import json
import logging
import signal
import sys
import time

import websockets

from config import (
    AISSTREAM_API_KEY,
    AISSTREAM_WS_URL,
    ACTIVE_BBOX,
    is_fishing_candidate,
)
from db import init_db, upsert_vessel, insert_position, load_ship_types, open_conn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

COMMIT_EVERY_SECONDS = 5
COMMIT_EVERY_POSITIONS = 50

# Estadísticas de sesión
stats = {"messages": 0, "positions_saved": 0, "skipped": 0, "vessels_seen": set()}

# Cache en memoria {mmsi: ship_type} para filtrar PositionReports, cuyo
# MetaData no incluye el tipo de barco.
ship_types = {}


def build_subscription():
    """Construye el mensaje de suscripción para aisstream.io."""
    return {
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": [ACTIVE_BBOX],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


def process_position_report(message, conn):
    """Procesa un mensaje de tipo PositionReport. Devuelve True si guardó."""
    meta = message.get("MetaData", {})
    report = message.get("Message", {}).get("PositionReport", {})
    if not report:
        return False

    mmsi = str(meta.get("MMSI", ""))
    if not is_fishing_candidate(mmsi, ship_types.get(mmsi)):
        stats["skipped"] += 1
        return False

    lat = report.get("Latitude")
    lon = report.get("Longitude")
    if lat is None or lon is None:
        return False

    timestamp = meta.get("time_utc") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sog = report.get("Sog")
    cog = report.get("Cog")
    heading = report.get("TrueHeading")
    nav_status = report.get("NavigationalStatus")
    rot = report.get("RateOfTurn")

    # Actualizar vessel primero (FK)
    name = (meta.get("ShipName") or "").strip()
    upsert_vessel(mmsi, name=name or None, conn=conn)
    ship_types.setdefault(mmsi, None)

    saved = insert_position(mmsi, timestamp, lat, lon, sog, cog, heading,
                            nav_status, rot, conn=conn)
    if not saved:
        return False

    stats["positions_saved"] += 1
    stats["vessels_seen"].add(mmsi)
    log.info(
        "POS %s (%s) lat=%.4f lon=%.4f sog=%.1f cog=%.1f nav=%s",
        mmsi, name or "?", lat, lon, sog or 0, cog or 0, nav_status,
    )
    return True


def process_static_data(message, conn):
    """Procesa un mensaje de tipo ShipStaticData.

    Se guarda para todos los barcos (no solo pesqueros) para aprender su tipo
    y poder descartar sus posiciones a partir de ese momento.
    """
    meta = message.get("MetaData", {})
    static = message.get("Message", {}).get("ShipStaticData", {})
    if not static:
        return

    mmsi = str(meta.get("MMSI", ""))
    ship_type = static.get("Type")

    name = (meta.get("ShipName") or "").strip()
    callsign = (static.get("CallSign") or "").strip()
    imo = str(static.get("ImoNumber")) if static.get("ImoNumber") else None
    dimension = static.get("Dimension") or {}
    length = width = None
    if dimension:
        a = dimension.get("A") or 0
        b = dimension.get("B") or 0
        c = dimension.get("C") or 0
        d = dimension.get("D") or 0
        length = a + b if (a + b) > 0 else None
        width = c + d if (c + d) > 0 else None

    upsert_vessel(
        mmsi,
        name=name or None,
        ship_type=ship_type,
        length=length,
        width=width,
        callsign=callsign or None,
        imo=imo,
        conn=conn,
    )
    if ship_type is not None:
        ship_types[mmsi] = ship_type

    log.info("STATIC %s name=%s type=%s len=%s", mmsi, name, ship_type, length)


async def session(ws):
    """Consume mensajes de una conexión WebSocket con una conexión SQLite
    persistente y commits por lotes."""
    conn = open_conn()
    last_commit = time.monotonic()
    pending = 0
    try:
        async for raw in ws:
            stats["messages"] += 1
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = message.get("MessageType", "")
            if msg_type == "PositionReport":
                if process_position_report(message, conn):
                    pending += 1
            elif msg_type == "ShipStaticData":
                process_static_data(message, conn)
                pending += 1

            now = time.monotonic()
            if pending and (pending >= COMMIT_EVERY_POSITIONS
                            or now - last_commit >= COMMIT_EVERY_SECONDS):
                conn.commit()
                pending = 0
                last_commit = now

            if stats["messages"] % 500 == 0:
                log.info(
                    "--- Stats: %d mensajes, %d posiciones guardadas, "
                    "%d descartadas (no pesqueros), %d barcos únicos ---",
                    stats["messages"], stats["positions_saved"],
                    stats["skipped"], len(stats["vessels_seen"]),
                )
    finally:
        conn.commit()
        conn.close()


async def collect():
    """Bucle principal de recolección de datos AIS."""
    if not AISSTREAM_API_KEY:
        log.error("AISSTREAM_API_KEY no configurada. Copia .env.example a .env y pon tu API key.")
        log.error("Regístrate gratis en https://aisstream.io")
        sys.exit(1)

    init_db()
    ship_types.update(load_ship_types())
    log.info("Tipos de barco conocidos: %d", len(ship_types))
    log.info("Conectando a aisstream.io...")
    log.info("Bounding box: %s", ACTIVE_BBOX)

    reconnect_delay = 5

    while True:
        try:
            async with websockets.connect(AISSTREAM_WS_URL) as ws:
                await ws.send(json.dumps(build_subscription()))
                log.info("Suscripción enviada. Esperando datos...")
                reconnect_delay = 5
                await session(ws)

        except asyncio.CancelledError:
            raise
        except websockets.exceptions.ConnectionClosed as e:
            log.warning("Conexión cerrada: %s. Reconectando en %ds...", e, reconnect_delay)
        except Exception as e:
            log.error("Error: %s. Reconectando en %ds...", e, reconnect_delay)

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)


async def main_async():
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await collect()
    except asyncio.CancelledError:
        log.info(
            "Parando collector. %d posiciones guardadas de %d barcos.",
            stats["positions_saved"], len(stats["vessels_seen"]),
        )


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
