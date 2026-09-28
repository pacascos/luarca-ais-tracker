"""Configuración del proyecto AIS Luarca."""

import os
from dotenv import load_dotenv

load_dotenv()

# aisstream.io
AISSTREAM_API_KEY = os.getenv("AISSTREAM_API_KEY", "")
AISSTREAM_WS_URL = "wss://stream.aisstream.io/v0/stream"

# Puerto de Luarca
LUARCA_LAT = 43.547
LUARCA_LON = -6.536

# Bounding boxes para suscripción AIS
# Zona amplia: costa asturiana / Golfo de Vizcaya
BBOX_REGIONAL = [[43.40, -7.50], [44.00, -5.50]]

# Zona costera ~10 NM alrededor de Luarca
BBOX_LUARCA = [[43.50, -6.70], [43.70, -6.35]]

# Bounding box activo (cambiar según necesidad)
ACTIVE_BBOX = BBOX_REGIONAL

# Filtros de barcos pesqueros
SHIP_TYPE_FISHING = 30
SHIP_TYPES_UNKNOWN = (None, 0)          # 0 = "not available" en AIS
SPANISH_MMSI_PREFIXES = ("224", "225")

# Flota pesquera de Luarca: VesselTracker ID -> {name, mmsi}
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
# Barcos que amarran habitualmente en Luarca pero no están en el grupo de
# VesselTracker (detectados por sus posiciones en puerto).
FLEET_EXTRA = {
    "224028620": "NUEVO ENZO",
}
FLEET_NAMES = {v["mmsi"]: v["name"] for v in PESQUEROS_LUARCA.values()} | FLEET_EXTRA
FLEET_MMSI = frozenset(FLEET_NAMES)


def is_fishing_candidate(mmsi, ship_type=None):
    """Decide si un barco entra en el análisis de pesca.

    Entra si pertenece a la flota de Luarca, si declara tipo AIS pesquero,
    o si es español y aún no conocemos su tipo (para no perder datos hasta
    que llegue su ShipStaticData). Un barco español con tipo conocido no
    pesquero (carguero, tanque...) queda fuera.
    """
    mmsi = str(mmsi)
    if mmsi in FLEET_MMSI:
        return True
    if ship_type == SHIP_TYPE_FISHING:
        return True
    if ship_type in SHIP_TYPES_UNKNOWN:
        return mmsi.startswith(SPANISH_MMSI_PREFIXES)
    return False


# Estados de navegación AIS relevantes
NAV_STATUS_AT_ANCHOR = 1
NAV_STATUS_MOORED = 5
NAV_STATUS_FISHING = 7

# Clasificación de actividad por velocidad (nudos), usada cuando el estado
# de navegación no es concluyente
SPEED_MOORED_MAX = 0.5       # Amarrado / fondeado
SPEED_FISHING_MIN = 1.0      # Mínima para considerar pesca
SPEED_FISHING_MAX = 7.0      # Máxima para considerar pesca
SPEED_TRANSIT_MIN = 8.0      # Mínima para considerar tránsito

# Puertos de la zona (dentro del bounding box regional): (nombre, lat, lon,
# radio NM). Una posición dentro del radio de cualquiera cuenta como "en
# puerto" y no forma parte de ningún viaje. Sin esta lista, un barco
# amarrado en Gijón aparecía como una sesión de tracking en el mar.
PORTS = [
    ("Luarca",              43.547, -6.536, 1.0),
    ("Puerto de Vega",      43.563, -6.643, 0.7),
    ("Navia",               43.545, -6.722, 1.0),
    ("Ortiguera",           43.560, -6.803, 0.6),
    ("Viavélez",            43.560, -6.853, 0.6),
    ("Tapia de Casariego",  43.572, -6.943, 0.7),
    ("Ribadeo",             43.540, -7.040, 1.2),
    ("Foz",                 43.572, -7.252, 0.8),
    ("Burela",              43.663, -7.357, 1.0),
    ("San Cibrao",          43.710, -7.450, 1.5),
    ("Cudillero",           43.566, -6.148, 0.7),
    ("San Esteban de Pravia", 43.560, -6.082, 1.0),
    ("Avilés",              43.578, -5.930, 2.0),
    ("Luanco",              43.615, -5.792, 0.7),
    ("Candás",              43.590, -5.760, 0.7),
    ("Gijón (El Musel)",    43.560, -5.700, 2.0),
    ("Gijón (marina)",      43.545, -5.663, 0.8),
]
# Radio (NM) alrededor de Luarca usado para dist_from_port (compatibilidad)
PORT_RADIUS_NM = 1.0

# Base de datos
DB_PATH = os.getenv("DB_PATH", "ais_luarca.db")
