"""Sondeo periódico de VesselTracker para la flota de Luarca.

aisstream.io apenas recibe a los pesqueros pequeños de Luarca; la antena
propia (VT-6372) sí, y sus datos llegan por la API REST de VesselTracker.
Este proceso consulta cada POLL_INTERVAL segundos los barcos presentes en
el bounding box regional (una sola llamada) y guarda las posiciones nuevas
de los barcos candidatos a pesquero en la misma BD que el collector.

`lastSeen` tiene precisión de minuto y la pareja (MMSI, timestamp) es
única, así que repetir un sondeo sin novedades no crea filas.

Uso:
    python vt_poller.py            # bucle continuo (pensado para launchd/systemd)
    python vt_poller.py --once     # un solo sondeo
"""

import argparse
import logging
import os
import sys
import time

import requests
from dotenv import load_dotenv

from config import (
    ACTIVE_BBOX,
    FLEET_MMSI,
    SHIP_TYPE_FISHING,
    is_fishing_candidate,
)
from db import init_db, insert_position, load_ship_types, open_conn, upsert_vessel
from vesseltracker import VT_API_BASE, VesselTrackerClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("vt_poller")

POLL_INTERVAL = int(os.getenv("VT_POLL_INTERVAL", "120"))   # segundos
LAST_SEEN_MINUTES = 30      # solo barcos vistos en la última media hora

# Tipos de VesselTracker que descartan a un barco aunque sea español
VT_NON_FISHING = {
    "cargo", "tanker", "passenger", "tug", "pleasure_craft", "sailing",
    "search_and_rescue_vessel", "military", "pilot_vessel", "law_enforcement",
    "high_speed_craft", "dredger", "port_tender", "anti_pollution",
    "medical_transport", "wing_in_ground",
}


def vt_ship_type(v):
    """Mapea shipTypeModel de VesselTracker a lo que entiende is_fishing_candidate."""
    t = (v.get("shipTypeModel") or {}).get("type")
    if t == "fishing_vessel":
        return SHIP_TYPE_FISHING
    if t in VT_NON_FISHING:
        return 99   # conocido y no pesquero
    return None     # "other" / desconocido


def poll_once(client, conn, known_types):
    """Un sondeo: consulta el área y guarda posiciones nuevas. Devuelve (vistos, guardados)."""
    (lat0, lon0), (lat1, lon1) = ACTIVE_BBOX
    resp = client.session.get(f"{VT_API_BASE}/vessels", params={
        "viewportBounds": f"{lat1},{lon0}|{lat0},{lon1}",
        "zoomLevel": 9,
        "lastSeen": LAST_SEEN_MINUTES,
        "lengthMax": 450,
        "limit": 200,
        "explicitVessels": "[]",
    }, timeout=30)
    if resp.status_code == 401:
        raise PermissionError("token caducado o inválido")
    resp.raise_for_status()
    data = resp.json().get("data", {})

    saved = 0
    for v in data.values():
        mmsi = str(v.get("mmsi") or "")
        if not mmsi or v.get("lat") is None or v.get("lon") is None:
            continue
        ship_type = known_types.get(mmsi)
        if ship_type in (None, 0):
            ship_type = vt_ship_type(v)
        if not is_fishing_candidate(mmsi, ship_type):
            continue

        name = (v.get("vesselName") or "").strip() or None
        heading = v.get("heading")
        if heading is not None and heading >= 511:
            heading = None
        upsert_vessel(
            mmsi, name=name,
            ship_type=SHIP_TYPE_FISHING if vt_ship_type(v) == SHIP_TYPE_FISHING else None,
            length=v.get("length") or None, width=v.get("width") or None,
            conn=conn,
        )
        if insert_position(
            mmsi, v.get("lastSeen"), v["lat"], v["lon"],
            sog=v.get("speed"), cog=v.get("courseOverGround"), heading=heading,
            conn=conn,
        ):
            saved += 1
            log.info("VT %s (%s) lat=%.4f lon=%.4f sog=%.1f %s%s",
                     mmsi, name or "?", v["lat"], v["lon"], v.get("speed") or 0,
                     v.get("lastSeen"), " [flota]" if mmsi in FLEET_MMSI else "")
    conn.commit()
    return len(data), saved


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--once", action="store_true", help="un solo sondeo y salir")
    args = ap.parse_args()

    email = os.getenv("VESSELTRACKER_EMAIL")
    password = os.getenv("VESSELTRACKER_PASSWORD")
    if not email or not password:
        log.error("Configura VESSELTRACKER_EMAIL y VESSELTRACKER_PASSWORD en .env")
        sys.exit(1)

    init_db()
    client = VesselTrackerClient(email, password)
    conn = open_conn()
    known_types = load_ship_types(conn)
    log.info("Sondeo VesselTracker cada %ds sobre %s", POLL_INTERVAL, ACTIVE_BBOX)

    backoff = POLL_INTERVAL
    while True:
        try:
            if not client.token:
                client.login()
            seen, saved = poll_once(client, conn, known_types)
            log.info("Sondeo: %d barcos en zona, %d posiciones nuevas", seen, saved)
            backoff = POLL_INTERVAL
        except PermissionError as e:
            log.warning("%s; reautenticando", e)
            client.token = None
            continue
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            backoff = min(backoff * 2, 1800)
            log.error("HTTP %s en la API de VesselTracker; reintento en %ds", status, backoff)
            if status == 429:
                log.error("Límite de consultas alcanzado: considera subir VT_POLL_INTERVAL")
        except Exception as e:
            backoff = min(backoff * 2, 1800)
            log.error("Error: %s; reintento en %ds", e, backoff)

        if args.once:
            break
        time.sleep(backoff)

    conn.close()


if __name__ == "__main__":
    main()
