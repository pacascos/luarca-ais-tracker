"""Análisis de rutas de pesca a partir de datos AIS almacenados."""

import math
import sqlite3
from datetime import timedelta

import pandas as pd

from config import (
    DB_PATH,
    LUARCA_LAT,
    LUARCA_LON,
    SPEED_MOORED_MAX,
    SPEED_FISHING_MIN,
    SPEED_FISHING_MAX,
    SPEED_TRANSIT_MIN,
)


def load_positions(mmsi=None, since=None):
    """Carga posiciones desde la BD. Opcionalmente filtra por MMSI y fecha."""
    conn = sqlite3.connect(DB_PATH)
    query = "SELECT * FROM positions"
    conditions = []
    params = []

    if mmsi:
        conditions.append("mmsi = ?")
        params.append(mmsi)
    if since:
        conditions.append("timestamp >= ?")
        params.append(since)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY mmsi, timestamp"

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        # Formatos mixtos: aisstream.io ("2026-04-06 02:18:20.910198854 +0000 UTC")
        # y VesselTracker ("2026-04-06T16:00+0200")
        df["timestamp"] = (
            df["timestamp"]
            .str.replace(r"\.\d+ \+0000 UTC$", "", regex=True)
            .pipe(pd.to_datetime, format="mixed", utc=True)
        )
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
    return df


def load_vessels():
    """Carga la tabla de barcos."""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM vessels", conn)
    conn.close()
    return df


def classify_activity(sog):
    """Clasifica la actividad según la velocidad sobre el fondo (SOG)."""
    if sog is None or math.isnan(sog):
        return "unknown"
    if sog <= SPEED_MOORED_MAX:
        return "moored"
    if SPEED_FISHING_MIN <= sog <= SPEED_FISHING_MAX:
        return "fishing"
    if sog >= SPEED_TRANSIT_MIN:
        return "transit"
    return "slow_transit"


def haversine_nm(lat1, lon1, lat2, lon2):
    """Distancia en millas náuticas entre dos puntos."""
    R = 3440.065  # Radio de la Tierra en millas náuticas
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def analyze_vessel_tracks(mmsi=None, since=None):
    """Analiza las tracks de barcos y clasifica segmentos de actividad.

    Retorna un DataFrame con cada posición enriquecida con:
    - activity: moored/fishing/transit/slow_transit/unknown
    - dist_from_port: distancia a Luarca en NM
    - trip_id: identificador de viaje (sale del puerto y vuelve)
    """
    df = load_positions(mmsi=mmsi, since=since)
    if df.empty:
        return df

    # Clasificar actividad por velocidad
    df["activity"] = df["sog"].apply(classify_activity)

    # Distancia al puerto de Luarca
    df["dist_from_port"] = df.apply(
        lambda r: haversine_nm(r["lat"], r["lon"], LUARCA_LAT, LUARCA_LON), axis=1
    )

    # Asignar trip_id: un viaje empieza cuando sale del puerto (>0.5 NM)
    # y termina cuando vuelve (<0.5 NM)
    PORT_RADIUS_NM = 0.5
    df["in_port"] = df["dist_from_port"] <= PORT_RADIUS_NM

    trip_id = 0
    trip_ids = []
    prev_in_port = True

    for _, row in df.iterrows():
        if prev_in_port and not row["in_port"]:
            trip_id += 1
        prev_in_port = row["in_port"]
        trip_ids.append(trip_id if not row["in_port"] else 0)

    df["trip_id"] = trip_ids
    return df


def get_fishing_zones(df=None, mmsi=None, since=None, grid_size=0.01):
    """Identifica zonas de pesca agregando posiciones en una cuadrícula.

    Args:
        grid_size: tamaño de celda en grados (~1 km a esta latitud)

    Retorna DataFrame con columnas: lat_grid, lon_grid, count, avg_sog, hours_fishing
    """
    if df is None:
        df = analyze_vessel_tracks(mmsi=mmsi, since=since)

    fishing = df[df["activity"] == "fishing"].copy()
    if fishing.empty:
        return pd.DataFrame()

    # Redondear a cuadrícula
    fishing["lat_grid"] = (fishing["lat"] / grid_size).round() * grid_size
    fishing["lon_grid"] = (fishing["lon"] / grid_size).round() * grid_size

    zones = fishing.groupby(["lat_grid", "lon_grid"]).agg(
        count=("id", "count"),
        avg_sog=("sog", "mean"),
        vessels=("mmsi", "nunique"),
    ).reset_index()

    zones = zones.sort_values("count", ascending=False)
    return zones


def get_fishing_zone_details(df=None, mmsi=None, since=None, grid_size=0.01):
    """Igual que get_fishing_zones pero añade desglose por barco en cada celda.

    Retorna dict {(lat_grid, lon_grid): {
        'count', 'avg_sog', 'vessels' (n únicos),
        'vessel_breakdown': [
            {'mmsi', 'name', 'positions', 'avg_sog', 'first', 'last'}, ...
        ]
    }}
    """
    if df is None:
        df = analyze_vessel_tracks(mmsi=mmsi, since=since)

    fishing = df[df["activity"] == "fishing"].copy()
    if fishing.empty:
        return {}

    fishing["lat_grid"] = (fishing["lat"] / grid_size).round() * grid_size
    fishing["lon_grid"] = (fishing["lon"] / grid_size).round() * grid_size

    vessels_db = load_vessels()
    name_by_mmsi = dict(zip(vessels_db["mmsi"], vessels_db["name"]))

    details = {}
    for (lat_g, lon_g), cell in fishing.groupby(["lat_grid", "lon_grid"]):
        breakdown = []
        for mmsi_v, vdf in cell.groupby("mmsi"):
            breakdown.append({
                "mmsi": mmsi_v,
                "name": name_by_mmsi.get(mmsi_v) or "?",
                "positions": int(len(vdf)),
                "avg_sog": float(vdf["sog"].mean()),
                "first": vdf["timestamp"].min(),
                "last": vdf["timestamp"].max(),
            })
        breakdown.sort(key=lambda x: x["positions"], reverse=True)
        details[(lat_g, lon_g)] = {
            "count": int(len(cell)),
            "avg_sog": float(cell["sog"].mean()),
            "vessels": int(cell["mmsi"].nunique()),
            "vessel_breakdown": breakdown,
        }
    return details


def get_trip_summary(df=None, mmsi=None, since=None):
    """Resume los viajes de cada barco.

    Retorna DataFrame con: mmsi, trip_id, start, end, duration_h,
    max_dist_nm, pct_fishing, n_positions
    """
    if df is None:
        df = analyze_vessel_tracks(mmsi=mmsi, since=since)

    trips = df[df["trip_id"] > 0]
    if trips.empty:
        return pd.DataFrame()

    summary = trips.groupby(["mmsi", "trip_id"]).agg(
        start=("timestamp", "min"),
        end=("timestamp", "max"),
        max_dist_nm=("dist_from_port", "max"),
        n_positions=("id", "count"),
        n_fishing=("activity", lambda x: (x == "fishing").sum()),
    ).reset_index()

    summary["duration_h"] = (
        (summary["end"] - summary["start"]).dt.total_seconds() / 3600
    )
    summary["pct_fishing"] = (
        summary["n_fishing"] / summary["n_positions"] * 100
    ).round(1)

    return summary


def print_report(since=None):
    """Imprime un resumen por consola."""
    vessels = load_vessels()
    print(f"\n{'='*60}")
    print(f"INFORME AIS LUARCA")
    print(f"{'='*60}")
    print(f"Barcos registrados: {len(vessels)}")

    if vessels.empty:
        print("No hay datos todavía. Ejecuta collector.py primero.")
        return

    fishing_vessels = vessels[vessels["ship_type"] == 30]
    print(f"Barcos pesqueros (type=30): {len(fishing_vessels)}")
    print(f"\nBarcos:")
    for _, v in vessels.iterrows():
        print(f"  {v['mmsi']} - {v['name'] or '?'} (type={v['ship_type']})")

    df = analyze_vessel_tracks(since=since)
    if df.empty:
        print("\nNo hay posiciones registradas.")
        return

    print(f"\nPosiciones totales: {len(df)}")
    activity_counts = df["activity"].value_counts()
    print(f"\nActividad:")
    for act, count in activity_counts.items():
        print(f"  {act}: {count} ({count/len(df)*100:.1f}%)")

    trips = get_trip_summary(df)
    if not trips.empty:
        print(f"\nViajes detectados: {len(trips)}")
        for _, t in trips.iterrows():
            print(
                f"  MMSI {t['mmsi']} viaje #{int(t['trip_id'])}: "
                f"{t['start'].strftime('%d/%m %H:%M')} - {t['end'].strftime('%d/%m %H:%M')} "
                f"({t['duration_h']:.1f}h, max {t['max_dist_nm']:.1f} NM, "
                f"{t['pct_fishing']:.0f}% pesca)"
            )

    zones = get_fishing_zones(df)
    if not zones.empty:
        print(f"\nTop 10 zonas de pesca:")
        for _, z in zones.head(10).iterrows():
            print(
                f"  ({z['lat_grid']:.3f}, {z['lon_grid']:.3f}): "
                f"{int(z['count'])} posiciones, {int(z['vessels'])} barcos, "
                f"avg SOG {z['avg_sog']:.1f} kn"
            )


if __name__ == "__main__":
    print_report()
