"""Cliente para la API REST de VesselTracker (cuenta Antenna Operator)."""

import logging
import time
from datetime import datetime, timezone

import requests

from config import DB_PATH
from db import init_db, upsert_vessel, insert_position, get_conn

log = logging.getLogger(__name__)

# --- Config ---

VT_API_BASE = "https://restapi.vesseltracker.com/api/v1"
VT_LOGIN_URL = f"{VT_API_BASE}/login"

# Pesqueros Luarca - VesselTracker IDs y MMSIs
PESQUEROS_LUARCA = {
    2767978:  {"name": "YODAM",                "mmsi": "224218130"},
    3224248:  {"name": "GAMUSIN",              "mmsi": "224249880"},
    368041:   {"name": "NAGORE II",            "mmsi": "224221940"},
    1543738:  {"name": "NUEVO HERMANOS POLA",  "mmsi": "224218660"},
    1745130:  {"name": "TRES HN0S CACHAREL0S", "mmsi": "224094590"},
    3113789:  {"name": "ISLA ERBOSA",          "mmsi": "224159140"},
    2157044:  {"name": "MADIMAR",              "mmsi": "224067630"},
    1760268:  {"name": "MADRE RAFAELA",        "mmsi": "224026280"},
    377843:   {"name": "NAVEOTE",              "mmsi": "224062390"},
    2733777:  {"name": "JOSERCRIS",            "mmsi": "225993201"},
    1538922:  {"name": "MUNDAKA",              "mmsi": "224085560"},
    799611:   {"name": "NUEVO SOCIO",          "mmsi": "224181230"},
    888235:   {"name": "PICO SACRO",           "mmsi": "224095140"},
    1050022:  {"name": "REGINO JESUS",         "mmsi": "224081130"},
    1076589:  {"name": "RINCHADOR",            "mmsi": "224052340"},
    1050262:  {"name": "RIO XUNCO",            "mmsi": "224208650"},
}


class VesselTrackerClient:
    """Cliente autenticado para la API REST de VesselTracker."""

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.token = None
        self.token_expiry = None
        self.session = requests.Session()

    def login(self):
        """Obtiene un access token via /login."""
        resp = self.session.post(VT_LOGIN_URL, json={
            "username": self.email,
            "password": self.password,
        })
        resp.raise_for_status()
        data = resp.json()
        self.token = data["accessToken"]
        self.token_expiry = data.get("expiry")
        self.session.headers["Authorization"] = f"Bearer {self.token}"
        log.info("Login OK. Token expira: %s", self.token_expiry)

    def _ensure_auth(self):
        if not self.token:
            self.login()

    def get_vessel_details(self, vt_id: int) -> dict:
        """Obtiene detalles completos de un barco por su VT ID."""
        self._ensure_auth()
        resp = self.session.get(f"{VT_API_BASE}/vessels/{vt_id}/details")
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get(str(vt_id), {})

    def get_vessels_in_area(self, top_lat: float, left_lon: float,
                           bottom_lat: float, right_lon: float,
                           zoom: int = 10) -> dict:
        """Obtiene barcos en un bounding box."""
        self._ensure_auth()
        bounds = f"{top_lat},{left_lon}|{bottom_lat},{right_lon}"
        resp = self.session.get(f"{VT_API_BASE}/vessels", params={
            "viewportBounds": bounds,
            "zoomLevel": zoom,
            "lastSeen": 720,
            "lengthMax": 450,
            "limit": 200,
            "explicitVessels": "[]",
        })
        resp.raise_for_status()
        return resp.json()

    def poll_pesqueros(self) -> list:
        """Consulta posición actual de todos los pesqueros de Luarca.

        Retorna lista de dicts con datos de cada barco.
        """
        self._ensure_auth()
        results = []
        for vt_id, info in PESQUEROS_LUARCA.items():
            try:
                details = self.get_vessel_details(vt_id)
                if not details:
                    continue
                results.append({
                    "vt_id": vt_id,
                    "mmsi": str(details.get("mmsi", info["mmsi"])),
                    "name": details.get("name", info["name"]),
                    "lat": details.get("latitude"),
                    "lon": details.get("longitude"),
                    "sog": details.get("speedOverGround"),
                    "cog": details.get("courseOverGround"),
                    "status": details.get("status"),
                    "region": details.get("currentLocation", {}).get("value"),
                    "last_port": details.get("lastPort", {}).get("name"),
                    "destination": details.get("destination", {}).get("name")
                                  if isinstance(details.get("destination"), dict)
                                  else details.get("destination"),
                    "ship_type": details.get("shipTypeModel", {}).get("type"),
                    "length": details.get("lengthOverAll"),
                    "width": details.get("width"),
                    "last_seen": details.get("lastSeen"),
                })
            except Exception as e:
                log.warning("Error consultando %s (%s): %s",
                            info["name"], vt_id, e)
        return results

    def save_to_db(self, vessels: list):
        """Guarda las posiciones obtenidas de VesselTracker en la BD."""
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
        saved = 0
        for v in vessels:
            if v["lat"] is None or v["lon"] is None:
                continue
            if v["lat"] == 0 and v["lon"] == 0:
                continue

            # Upsert vessel
            upsert_vessel(
                mmsi=v["mmsi"],
                name=v["name"],
                ship_type=30 if v["ship_type"] == "fishing_vessel" else None,
                length=v["length"],
                width=v["width"],
            )

            # Insertar posicion con timestamp de last_seen o ahora
            ts = v.get("last_seen") or now
            insert_position(
                mmsi=v["mmsi"],
                timestamp=ts,
                lat=v["lat"],
                lon=v["lon"],
                sog=v["sog"],
                cog=v["cog"],
            )
            saved += 1

        log.info("Guardadas %d posiciones de VesselTracker", saved)
        return saved


def main():
    """Hace un poll de los pesqueros y guarda en la BD."""
    import os
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    email = os.getenv("VESSELTRACKER_EMAIL")
    password = os.getenv("VESSELTRACKER_PASSWORD")
    if not email or not password:
        log.error("Configura VESSELTRACKER_EMAIL y VESSELTRACKER_PASSWORD en .env")
        return

    init_db()
    client = VesselTrackerClient(email, password)

    log.info("Consultando posiciones de %d pesqueros...", len(PESQUEROS_LUARCA))
    vessels = client.poll_pesqueros()

    print(f"\n{'='*70}")
    print(f"PESQUEROS LUARCA - VesselTracker")
    print(f"{'='*70}")
    for v in vessels:
        status_icon = {
            "moving": ">>", "waiting": "..", "moored": "==",
            "anchorage": "~~"
        }.get(v["status"], "??")
        print(
            f"  {status_icon} {v['name']:25s} "
            f"SOG={v['sog'] or 0:5.1f} kn  "
            f"status={v['status']:10s} "
            f"({v['lat']:.4f}, {v['lon']:.4f})  "
            f"port={v['last_port'] or '?'}"
        )

    saved = client.save_to_db(vessels)
    print(f"\nGuardadas {saved} posiciones en {DB_PATH}")


if __name__ == "__main__":
    main()
