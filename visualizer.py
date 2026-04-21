"""Visualización de rutas AIS en mapas HTML con Folium."""

import os

import folium
from folium.plugins import HeatMap, MarkerCluster

from config import LUARCA_LAT, LUARCA_LON

WEB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
from analyzer import (
    analyze_vessel_tracks,
    get_fishing_zones,
    get_fishing_zone_details,
    get_trip_summary,
    load_vessels,
)

# Colores por tipo de actividad
ACTIVITY_COLORS = {
    "fishing": "#e74c3c",     # rojo
    "transit": "#3498db",     # azul
    "moored": "#95a5a6",      # gris
    "slow_transit": "#f39c12", # naranja
    "unknown": "#bdc3c7",     # gris claro
}


def create_base_map(zoom=11):
    """Crea un mapa base centrado en la franja costera (coast + mar) al norte de Luarca.

    Encaja el viewport en un bounding box que deja Luarca en el borde sur y
    maximiza la superficie de mar visible (Golfo de Vizcaya).
    """
    m = folium.Map(
        location=[LUARCA_LAT, LUARCA_LON],
        zoom_start=zoom,
        tiles=None,
    )
    # Fit a sea-dominant view: south edge at Luarca coast, extending north to open sea
    m.fit_bounds([[43.50, -7.10], [44.10, -5.85]])

    # --- Capas base (seleccionables como radio; la primera es la activa) ---
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satélite",
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Ocean",
        name="Esri Ocean (batimetría)",
        max_zoom=13,
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap", overlay=False).add_to(m)
    folium.TileLayer(
        "CartoDB positron", name="CartoDB claro", overlay=False
    ).add_to(m)

    # --- Overlays náuticos ---
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Esri Ocean Reference (etiquetas)",
        max_zoom=13,
        overlay=True,
        control=True,
        show=False,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png",
        attr="OpenSeaMap",
        name="Cartas náuticas (OpenSeaMap)",
        overlay=True,
        control=True,
        show=True,
    ).add_to(m)
    folium.raster_layers.WmsTileLayer(
        url="https://ows.emodnet-bathymetry.eu/wms",
        layers="emodnet:mean_multicolour",
        name="Batimetría EMODnet",
        fmt="image/png",
        transparent=True,
        version="1.3.0",
        attr="EMODnet Bathymetry",
        overlay=True,
        control=True,
        show=True,
    ).add_to(m)
    folium.raster_layers.WmsTileLayer(
        url="https://ows.emodnet-bathymetry.eu/wms",
        layers="emodnet:contours",
        name="Isóbatas EMODnet",
        fmt="image/png",
        transparent=True,
        version="1.3.0",
        attr="EMODnet Bathymetry",
        overlay=True,
        control=True,
        show=True,
    ).add_to(m)
    folium.raster_layers.WmsTileLayer(
        url="https://wms.gebco.net/mapserv",
        layers="GEBCO_LATEST",
        name="GEBCO batimetría global",
        fmt="image/png",
        transparent=True,
        version="1.3.0",
        attr="GEBCO",
        overlay=True,
        control=True,
        show=False,
    ).add_to(m)

    # Marcador del puerto
    folium.Marker(
        [LUARCA_LAT, LUARCA_LON],
        popup="Puerto de Luarca",
        icon=folium.Icon(color="green", icon="anchor", prefix="fa"),
    ).add_to(m)
    return m


def _web_path(filename):
    os.makedirs(WEB_DIR, exist_ok=True)
    return os.path.join(WEB_DIR, filename)


def map_vessel_tracks(mmsi=None, since=None, output=None):
    output = output or _web_path("mapa_tracks.html")
    """Genera un mapa con las tracks de los barcos coloreadas por actividad."""
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)
    if df.empty:
        print("No hay datos para visualizar.")
        return None

    m = create_base_map(zoom=10)

    # Capa por cada tipo de actividad
    layers = {}
    for activity, color in ACTIVITY_COLORS.items():
        layers[activity] = folium.FeatureGroup(name=f"Actividad: {activity}")
        layers[activity].add_to(m)

    # Dibujar tracks por barco
    vessels = df["mmsi"].unique()
    for vessel_mmsi in vessels:
        vdf = df[df["mmsi"] == vessel_mmsi].sort_values("timestamp")
        name = vdf.iloc[0].get("mmsi", vessel_mmsi)

        # Obtener nombre del barco
        vessels_db = load_vessels()
        vessel_info = vessels_db[vessels_db["mmsi"] == vessel_mmsi]
        if not vessel_info.empty and vessel_info.iloc[0]["name"]:
            name = vessel_info.iloc[0]["name"]

        # Segmentos coloreados por actividad
        for i in range(len(vdf) - 1):
            p1 = vdf.iloc[i]
            p2 = vdf.iloc[i + 1]
            activity = p1["activity"]
            color = ACTIVITY_COLORS.get(activity, "#bdc3c7")

            line = folium.PolyLine(
                [[p1["lat"], p1["lon"]], [p2["lat"], p2["lon"]]],
                color=color,
                weight=3,
                opacity=0.7,
                popup=f"{name} | {activity} | SOG: {p1['sog']:.1f} kn",
            )
            if activity in layers:
                line.add_to(layers[activity])

    folium.LayerControl().add_to(m)
    m.save(output)
    print(f"Mapa guardado en {output}")
    return m


def map_fishing_zones(mmsi=None, since=None, output=None, grid_size=0.01):
    output = output or _web_path("mapa_pesca.html")
    """Genera un mapa de calor de las zonas de pesca."""
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)
    zones = get_fishing_zones(df, grid_size=grid_size)

    m = create_base_map(zoom=10)

    if not zones.empty:
        # Heatmap
        heat_data = zones[["lat_grid", "lon_grid", "count"]].values.tolist()
        HeatMap(
            heat_data,
            radius=20,
            blur=15,
            max_zoom=13,
            name="Densidad de pesca",
        ).add_to(m)

        # Marcadores en las zonas top
        cluster = MarkerCluster(name="Zonas de pesca (top)").add_to(m)
        for _, z in zones.head(20).iterrows():
            folium.CircleMarker(
                [z["lat_grid"], z["lon_grid"]],
                radius=min(z["count"] / 2, 20),
                color="#e74c3c",
                fill=True,
                fill_opacity=0.6,
                popup=(
                    f"Posiciones: {int(z['count'])}<br>"
                    f"Barcos: {int(z['vessels'])}<br>"
                    f"SOG media: {z['avg_sog']:.1f} kn"
                ),
            ).add_to(cluster)

        # Capa interactiva: celdas clicables con detalles por barco
        details = get_fishing_zone_details(df, grid_size=grid_size)
        detail_layer = folium.FeatureGroup(
            name="Detalle por celda (click)", show=False
        )
        half = grid_size / 2
        for (lat_g, lon_g), info in details.items():
            rows = "".join(
                f"<tr><td>{v['name']}</td>"
                f"<td>{v['mmsi']}</td>"
                f"<td style='text-align:right'>{v['positions']}</td>"
                f"<td style='text-align:right'>{v['avg_sog']:.1f}</td>"
                f"<td>{v['first'].strftime('%d/%m %H:%M')}</td>"
                f"<td>{v['last'].strftime('%d/%m %H:%M')}</td></tr>"
                for v in info["vessel_breakdown"]
            )
            html = (
                f"<div style='font-family:sans-serif;font-size:12px;min-width:420px'>"
                f"<b>Celda {lat_g:.3f}, {lon_g:.3f}</b><br>"
                f"Posiciones: {info['count']} · Barcos: {info['vessels']} · "
                f"SOG media: {info['avg_sog']:.1f} kn"
                f"<table style='border-collapse:collapse;margin-top:6px;width:100%'>"
                f"<thead><tr style='background:#f2f2f2'>"
                f"<th style='text-align:left;padding:2px 6px'>Barco</th>"
                f"<th style='text-align:left;padding:2px 6px'>MMSI</th>"
                f"<th style='text-align:right;padding:2px 6px'>Pos</th>"
                f"<th style='text-align:right;padding:2px 6px'>SOG</th>"
                f"<th style='text-align:left;padding:2px 6px'>Primera</th>"
                f"<th style='text-align:left;padding:2px 6px'>Última</th>"
                f"</tr></thead><tbody>{rows}</tbody></table></div>"
            )
            folium.Rectangle(
                bounds=[[lat_g - half, lon_g - half], [lat_g + half, lon_g + half]],
                color="#e74c3c",
                weight=1,
                fill=True,
                fill_opacity=0.05,
                popup=folium.Popup(html, max_width=520),
                tooltip=(
                    f"{lat_g:.3f}, {lon_g:.3f} · "
                    f"{info['count']} pos · {info['vessels']} barcos"
                ),
            ).add_to(detail_layer)
        detail_layer.add_to(m)

    # Posiciones de pesca individuales
    fishing = df[df["activity"] == "fishing"]
    if not fishing.empty:
        fg = folium.FeatureGroup(name="Posiciones de pesca", show=False)
        for _, row in fishing.iterrows():
            folium.CircleMarker(
                [row["lat"], row["lon"]],
                radius=2,
                color="#e74c3c",
                fill=True,
                popup=f"MMSI: {row['mmsi']}<br>SOG: {row['sog']:.1f}<br>{row['timestamp']}",
            ).add_to(fg)
        fg.add_to(m)

    folium.LayerControl().add_to(m)
    m.save(output)
    print(f"Mapa de zonas de pesca guardado en {output}")
    return m


def map_trips(mmsi=None, since=None, output=None):
    output = output or _web_path("mapa_viajes.html")
    """Genera un mapa con los viajes individuales (puerto -> mar -> puerto)."""
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)
    trips = get_trip_summary(df)

    if trips.empty:
        print("No hay viajes detectados.")
        return None

    m = create_base_map(zoom=10)

    # Un color por viaje
    palette = [
        "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
        "#1abc9c", "#e67e22", "#34495e", "#d35400", "#c0392b",
    ]

    trip_layer = folium.FeatureGroup(name="Viajes")
    for idx, (_, trip) in enumerate(trips.iterrows()):
        trip_df = df[
            (df["mmsi"] == trip["mmsi"]) & (df["trip_id"] == trip["trip_id"])
        ].sort_values("timestamp")

        if len(trip_df) < 2:
            continue

        color = palette[idx % len(palette)]
        coords = trip_df[["lat", "lon"]].values.tolist()

        folium.PolyLine(
            coords,
            color=color,
            weight=3,
            opacity=0.8,
            popup=(
                f"MMSI: {trip['mmsi']}<br>"
                f"Viaje #{int(trip['trip_id'])}<br>"
                f"{trip['start'].strftime('%d/%m %H:%M')} - {trip['end'].strftime('%d/%m %H:%M')}<br>"
                f"Duración: {trip['duration_h']:.1f}h<br>"
                f"Max dist: {trip['max_dist_nm']:.1f} NM<br>"
                f"Pesca: {trip['pct_fishing']:.0f}%"
            ),
        ).add_to(trip_layer)

        # Marcador de inicio
        start = trip_df.iloc[0]
        folium.Marker(
            [start["lat"], start["lon"]],
            icon=folium.Icon(color="green", icon="play", prefix="fa"),
            popup=f"Salida: {trip['start'].strftime('%d/%m %H:%M')}",
        ).add_to(trip_layer)

    trip_layer.add_to(m)
    folium.LayerControl().add_to(m)
    m.save(output)
    print(f"Mapa de viajes guardado en {output}")
    return m


def build_index():
    """Genera web/index.html con enlaces a los 3 mapas."""
    html = """<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AIS Luarca — Rutas de pesca</title>
  <style>
    :root { color-scheme: light dark; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      max-width: 900px; margin: 2rem auto; padding: 0 1rem; line-height: 1.5;
    }
    h1 { margin-bottom: 0.2rem; }
    .sub { color: #666; margin-top: 0; }
    .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 1rem; margin-top: 2rem; }
    .card {
      border: 1px solid #ccc; border-radius: 8px; padding: 1rem; text-decoration: none;
      color: inherit; transition: transform 0.1s, box-shadow 0.1s;
    }
    .card:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
    .card h3 { margin-top: 0; }
    footer { margin-top: 3rem; color: #888; font-size: 0.9rem; }
    @media (prefers-color-scheme: dark) {
      body { background: #1a1a1a; color: #eee; }
      .card { border-color: #444; }
      .sub, footer { color: #aaa; }
    }
  </style>
</head>
<body>
  <h1>AIS Luarca</h1>
  <p class="sub">Rutas y zonas de pesca de la flota pesquera de Luarca (Golfo de Vizcaya) a partir de datos AIS.</p>

  <div class="cards">
    <a class="card" href="mapa_tracks.html">
      <h3>Tracks de barcos</h3>
      <p>Trayectorias completas coloreadas por actividad (pesca, tránsito, amarrado).</p>
    </a>
    <a class="card" href="mapa_pesca.html">
      <h3>Zonas de pesca</h3>
      <p>Mapa de calor + celdas clicables con detalle de barcos que pescaron en cada zona.</p>
    </a>
    <a class="card" href="mapa_viajes.html">
      <h3>Viajes</h3>
      <p>Viajes individuales puerto → mar → puerto con duración y porcentaje de pesca.</p>
    </a>
  </div>

  <footer>
    Datos: aisstream.io + VesselTracker · Cartografía: OpenStreetMap, Esri Ocean,
    OpenSeaMap, EMODnet Bathymetry, GEBCO.
  </footer>
</body>
</html>
"""
    path = _web_path("index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Index guardado en {path}")


if __name__ == "__main__":
    print("Generando mapas...")
    map_vessel_tracks()
    map_fishing_zones()
    map_trips()
    build_index()
    print("Listo.")
