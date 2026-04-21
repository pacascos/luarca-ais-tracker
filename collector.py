"""Collector de datos AIS en tiempo real via aisstream.io WebSocket."""

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone

import websockets

from config import (
    AISSTREAM_API_KEY,
    AISSTREAM_WS_URL,
    ACTIVE_BBOX,
    SHIP_TYPE_FISHING,
    SPANISH_MMSI_PREFIXES,
)
from db import init_db, upsert_vessel, insert_position

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# Estadísticas de sesión
stats = {"messages": 0, "positions_saved": 0, "vessels_seen": set()}


def build_subscription():
    """Construye el mensaje de suscripción para aisstream.io."""
    return {
        "APIKey": AISSTREAM_API_KEY,
        "BoundingBoxes": [ACTIVE_BBOX],
        "FilterMessageTypes": ["PositionReport", "ShipStaticData"],
    }


def is_fishing_vessel(mmsi, ship_type=None):
    """Determina si un barco es pesquero (por tipo AIS o MMSI español)."""
    if ship_type == SHIP_TYPE_FISHING:
        return True
    # Si no sabemos el tipo, aceptamos barcos españoles para no perder datos
    mmsi_str = str(mmsi)
    return mmsi_str.startswith(SPANISH_MMSI_PREFIXES)


def process_position_report(message):
    """Procesa un mensaje de tipo PositionReport."""
    meta = message.get("MetaData", {})
    report = message.get("Message", {}).get("PositionReport", {})
    if not report:
        return

    mmsi = str(meta.get("MMSI", ""))
    ship_type = meta.get("ShipType")

    timestamp = meta.get("time_utc", datetime.now(timezone.utc).isoformat())
    lat = report.get("Latitude")
    lon = report.get("Longitude")

    if lat is None or lon is None:
        return

    sog = report.get("Sog")
    cog = report.get("Cog")
    heading = report.get("TrueHeading")
    nav_status = report.get("NavigationalStatus")
    rot = report.get("RateOfTurn")

    # Actualizar vessel primero (FK)
    name = meta.get("ShipName", "").strip()
    upsert_vessel(mmsi, name=name if name else None, ship_type=ship_type)

    # Guardar posición
    insert_position(mmsi, timestamp, lat, lon, sog, cog, heading, nav_status, rot)
    stats["positions_saved"] += 1
    stats["vessels_seen"].add(mmsi)

    log.info(
        "POS %s (%s) lat=%.4f lon=%.4f sog=%.1f cog=%.1f",
        mmsi, name or "?", lat, lon, sog or 0, cog or 0,
    )


def process_static_data(message):
    """Procesa un mensaje de tipo ShipStaticData."""
    meta = message.get("MetaData", {})
    static = message.get("Message", {}).get("ShipStaticData", {})
    if not static:
        return

    mmsi = str(meta.get("MMSI", ""))
    ship_type = static.get("Type")

    name = meta.get("ShipName", "").strip()
    callsign = static.get("CallSign", "").strip()
    imo = str(static.get("ImoNumber", "")) if static.get("ImoNumber") else None
    dimension = static.get("Dimension", {})
    length = None
    width = None
    if dimension:
        a = dimension.get("A", 0) or 0
        b = dimension.get("B", 0) or 0
        c = dimension.get("C", 0) or 0
        d = dimension.get("D", 0) or 0
        length = a + b if (a + b) > 0 else None
        width = c + d if (c + d) > 0 else None

    upsert_vessel(
        mmsi,
        name=name if name else None,
        ship_type=ship_type,
        length=length,
        width=width,
        callsign=callsign if callsign else None,
        imo=imo,
    )

    log.info("STATIC %s name=%s type=%s len=%s", mmsi, name, ship_type, length)


async def collect():
    """Bucle principal de recolección de datos AIS."""
    if not AISSTREAM_API_KEY:
        log.error("AISSTREAM_API_KEY no configurada. Copia .env.example a .env y pon tu API key.")
        log.error("Regístrate gratis en https://aisstream.io")
        sys.exit(1)

    init_db()
    log.info("Conectando a aisstream.io...")
    log.info("Bounding box: %s", ACTIVE_BBOX)

    reconnect_delay = 5

    while True:
        try:
            async with websockets.connect(AISSTREAM_WS_URL) as ws:
                sub = build_subscription()
                await ws.send(json.dumps(sub))
                log.info("Suscripción enviada. Esperando datos...")
                reconnect_delay = 5

                async for raw in ws:
                    stats["messages"] += 1
                    try:
                        message = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    msg_type = message.get("MessageType", "")

                    if msg_type == "PositionReport":
                        process_position_report(message)
                    elif msg_type == "ShipStaticData":
                        process_static_data(message)

                    if stats["messages"] % 100 == 0:
                        log.info(
                            "--- Stats: %d mensajes, %d posiciones guardadas, %d barcos únicos ---",
                            stats["messages"],
                            stats["positions_saved"],
                            len(stats["vessels_seen"]),
                        )

        except websockets.exceptions.ConnectionClosed as e:
            log.warning("Conexión cerrada: %s. Reconectando en %ds...", e, reconnect_delay)
        except Exception as e:
            log.error("Error: %s. Reconectando en %ds...", e, reconnect_delay)

        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 60)


def main():
    loop = asyncio.new_event_loop()

    def shutdown(sig, frame):
        log.info(
            "Parando collector. %d posiciones guardadas de %d barcos.",
            stats["positions_saved"],
            len(stats["vessels_seen"]),
        )
        loop.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    loop.run_until_complete(collect())


if __name__ == "__main__":
    main()
