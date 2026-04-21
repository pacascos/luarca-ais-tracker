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
SPANISH_MMSI_PREFIXES = ("224", "225")

# Clasificación de actividad por velocidad (nudos)
SPEED_MOORED_MAX = 0.5       # Amarrado / fondeado
SPEED_FISHING_MIN = 1.0      # Mínima para considerar pesca
SPEED_FISHING_MAX = 7.0      # Máxima para considerar pesca
SPEED_TRANSIT_MIN = 8.0      # Mínima para considerar tránsito

# Base de datos
DB_PATH = os.getenv("DB_PATH", "ais_luarca.db")
