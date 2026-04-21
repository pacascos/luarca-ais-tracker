"""Visualización de rutas AIS en mapas HTML con Folium."""

import json
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

    # Enlace flotante de vuelta al índice
    m.get_root().html.add_child(folium.Element(
        """
        <a href=\"index.html\" style=\"
            position: fixed; top: 10px; left: 60px; z-index: 1000;
            background: white; padding: 7px 12px; border-radius: 4px;
            border: 1px solid #aaa; font-family: -apple-system, sans-serif;
            font-size: 13px; color: #222; text-decoration: none;
            box-shadow: 0 1px 4px rgba(0,0,0,0.25);
        \" onmouseover=\"this.style.background='#f4f4f4'\"
           onmouseout=\"this.style.background='white'\">\u2190 \u00cdndice</a>
        """
    ))

    # --- Capas base (seleccionables como radio; solo Satélite se muestra al cargar) ---
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri",
        name="Satélite",
        overlay=False,
        control=True,
        show=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Ocean",
        name="Esri Ocean (batimetría)",
        max_zoom=13,
        overlay=False,
        control=True,
        show=False,
    ).add_to(m)
    folium.TileLayer(
        "OpenStreetMap", name="OpenStreetMap", overlay=False, show=False
    ).add_to(m)
    folium.TileLayer(
        "CartoDB positron", name="CartoDB claro", overlay=False, show=False
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


FISHING_JS_TEMPLATE = r"""
<div id="df-panel" style="
  position: fixed; top: 10px; left: 170px; z-index: 1000;
  background: white; padding: 8px 12px; border-radius: 4px;
  border: 1px solid #aaa; font-family: -apple-system, sans-serif;
  font-size: 13px; box-shadow: 0 1px 4px rgba(0,0,0,0.25);
">
  <label style="margin-right:6px;"><b>Desde</b></label>
  <input type="date" id="df-input" min="__MIN_DATE__" max="__MAX_DATE__" style="padding:2px 4px;">
  <button id="df-clear" style="margin-left:6px;padding:2px 10px;cursor:pointer;">Todo</button>
  <span style="margin-left:10px;color:#666;">
    <b id="df-count">0</b> pos · <b id="df-cells">0</b> celdas
  </span>
</div>
<script>
(function(){
  var tries = 0;
  var iv = setInterval(function(){
    tries++;
    if (typeof __HEAT__ !== 'undefined' &&
        typeof __TOP__ !== 'undefined' &&
        typeof __DETAIL__ !== 'undefined' &&
        typeof __POSITIONS__ !== 'undefined') {
      clearInterval(iv);
      init();
    } else if (tries > 200) {
      clearInterval(iv);
      console.error('Folium layers not ready after 10s');
    }
  }, 50);

  function init(){
    var ALL = __POINTS__;
    var NAMES = __NAMES__;
    var GRID = __GRID__;
    var heat = __HEAT__;
    var top_zones = __TOP__;
    var detail = __DETAIL__;
    var positions = __POSITIONS__;

    function roundG(x){ return Math.round(x / GRID) * GRID; }
    function pad(n){ return n.toString().padStart(2, '0'); }
    function fmt(ts){
      var d = new Date(ts);
      return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + ' ' +
             pad(d.getHours()) + ':' + pad(d.getMinutes());
    }

    function filterPts(minTs){
      if (minTs == null) return ALL;
      return ALL.filter(function(p){ return p[2] >= minTs; });
    }

    function aggregate(pts){
      var cells = {};
      for (var i = 0; i < pts.length; i++){
        var p = pts[i];
        var lg = roundG(p[0]), ln = roundG(p[1]);
        var key = lg.toFixed(3) + '_' + ln.toFixed(3);
        var c = cells[key];
        if (!c){ c = {lat: lg, lon: ln, count: 0, sogSum: 0, vessels: {}}; cells[key] = c; }
        c.count++; c.sogSum += p[4];
        var v = c.vessels[p[3]];
        if (!v){ v = c.vessels[p[3]] = {mmsi: p[3], positions: 0, sogSum: 0, first: p[2], last: p[2]}; }
        v.positions++; v.sogSum += p[4];
        if (p[2] < v.first) v.first = p[2];
        if (p[2] > v.last) v.last = p[2];
      }
      return Object.values(cells);
    }

    function popupHtml(c){
      var vs = Object.values(c.vessels).sort(function(a, b){ return b.positions - a.positions; });
      var rows = '';
      for (var i = 0; i < vs.length; i++){
        var v = vs[i];
        rows += '<tr><td>' + (NAMES[v.mmsi] || '?') +
          '</td><td>' + v.mmsi +
          '</td><td style="text-align:right">' + v.positions +
          '</td><td style="text-align:right">' + (v.sogSum / v.positions).toFixed(1) +
          '</td><td>' + fmt(v.first) + '</td><td>' + fmt(v.last) + '</td></tr>';
      }
      return '<div style="font-family:sans-serif;font-size:12px;min-width:420px">' +
        '<b>Celda ' + c.lat.toFixed(3) + ', ' + c.lon.toFixed(3) + '</b><br>' +
        'Posiciones: ' + c.count + ' · Barcos: ' + Object.keys(c.vessels).length + ' · ' +
        'SOG media: ' + (c.sogSum/c.count).toFixed(1) + ' kn' +
        '<table style="border-collapse:collapse;margin-top:6px;width:100%">' +
        '<thead><tr style="background:#f2f2f2">' +
          '<th style="text-align:left;padding:2px 6px">Barco</th>' +
          '<th style="text-align:left;padding:2px 6px">MMSI</th>' +
          '<th style="text-align:right;padding:2px 6px">Pos</th>' +
          '<th style="text-align:right;padding:2px 6px">SOG</th>' +
          '<th style="text-align:left;padding:2px 6px">Primera</th>' +
          '<th style="text-align:left;padding:2px 6px">Última</th>' +
        '</tr></thead><tbody>' + rows + '</tbody></table></div>';
    }

    function rebuild(minTs){
      var pts = filterPts(minTs);

      heat.setLatLngs(pts.map(function(p){ return [p[0], p[1], 1]; }));

      top_zones.clearLayers();
      var cells = aggregate(pts).sort(function(a, b){ return b.count - a.count; });
      var top = cells.slice(0, 20);
      for (var i = 0; i < top.length; i++){
        var c = top[i];
        L.circleMarker([c.lat, c.lon], {
          radius: Math.min(c.count / 2, 20),
          color: '#e74c3c', fill: true, fillOpacity: 0.6
        }).bindPopup(
          'Posiciones: ' + c.count + '<br>' +
          'Barcos: ' + Object.keys(c.vessels).length + '<br>' +
          'SOG media: ' + (c.sogSum / c.count).toFixed(1) + ' kn'
        ).addTo(top_zones);
      }

      detail.clearLayers();
      var half = GRID / 2;
      for (var j = 0; j < cells.length; j++){
        var c2 = cells[j];
        L.rectangle(
          [[c2.lat - half, c2.lon - half], [c2.lat + half, c2.lon + half]],
          {color: '#e74c3c', weight: 1, fill: true, fillOpacity: 0.05}
        ).bindPopup(popupHtml(c2), {maxWidth: 520})
         .bindTooltip(c2.lat.toFixed(3) + ', ' + c2.lon.toFixed(3) + ' · ' +
           c2.count + ' pos · ' + Object.keys(c2.vessels).length + ' barcos')
         .addTo(detail);
      }

      positions.clearLayers();
      for (var k = 0; k < pts.length; k++){
        var p = pts[k];
        L.circleMarker([p[0], p[1]], {radius: 2, color: '#e74c3c', fill: true})
          .bindPopup('MMSI: ' + p[3] + '<br>' + (NAMES[p[3]] || '?') +
                     '<br>SOG: ' + p[4].toFixed(1) + ' kn<br>' + fmt(p[2]))
          .addTo(positions);
      }

      document.getElementById('df-count').textContent = pts.length;
      document.getElementById('df-cells').textContent = cells.length;
    }

    document.getElementById('df-input').addEventListener('change', function(e){
      var v = e.target.value;
      rebuild(v ? new Date(v).getTime() : null);
    });
    document.getElementById('df-clear').addEventListener('click', function(){
      document.getElementById('df-input').value = '';
      rebuild(null);
    });

    rebuild(null);
  }
})();
</script>
"""


def map_fishing_zones(mmsi=None, since=None, output=None, grid_size=0.01):
    """Genera el mapa de zonas de pesca con filtro de fecha client-side."""
    output = output or _web_path("mapa_pesca.html")
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)

    m = create_base_map(zoom=10)

    fishing = df[df["activity"] == "fishing"].copy() if not df.empty else df

    # Puntos crudos embebidos: [lat, lon, ts_ms, mmsi, sog]
    points = []
    if not fishing.empty:
        for row in fishing.itertuples(index=False):
            sog = float(row.sog) if row.sog is not None else 0.0
            points.append([
                round(float(row.lat), 6),
                round(float(row.lon), 6),
                int(row.timestamp.timestamp() * 1000),
                str(row.mmsi),
                round(sog, 2),
            ])

    vessels_db = load_vessels()
    names = {str(r.mmsi): (r.name or "?") for r in vessels_db.itertuples(index=False)}

    # Capas placeholder — se pueblan client-side. Heatmap exige 1 punto dummy.
    dummy = [[LUARCA_LAT, LUARCA_LON, 0.0001]]
    heat_layer = HeatMap(
        dummy, radius=20, blur=15, max_zoom=13, name="Densidad de pesca"
    )
    heat_layer.add_to(m)
    top_layer = folium.FeatureGroup(name="Zonas de pesca (top)", show=True)
    top_layer.add_to(m)
    detail_layer = folium.FeatureGroup(name="Detalle por celda (click)", show=False)
    detail_layer.add_to(m)
    positions_layer = folium.FeatureGroup(name="Posiciones de pesca", show=False)
    positions_layer.add_to(m)

    folium.LayerControl().add_to(m)

    if fishing.empty:
        min_date = max_date = ""
    else:
        min_date = fishing["timestamp"].min().strftime("%Y-%m-%d")
        max_date = fishing["timestamp"].max().strftime("%Y-%m-%d")

    js = (
        FISHING_JS_TEMPLATE
        .replace("__POINTS__", json.dumps(points))
        .replace("__NAMES__", json.dumps(names))
        .replace("__GRID__", str(grid_size))
        .replace("__HEAT__", heat_layer.get_name())
        .replace("__TOP__", top_layer.get_name())
        .replace("__DETAIL__", detail_layer.get_name())
        .replace("__POSITIONS__", positions_layer.get_name())
        .replace("__MIN_DATE__", min_date)
        .replace("__MAX_DATE__", max_date)
    )
    m.get_root().html.add_child(folium.Element(js))

    m.save(output)
    print(f"Mapa de zonas de pesca guardado en {output} ({len(points)} puntos)")
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
