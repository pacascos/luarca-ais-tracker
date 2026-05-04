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


TRACKS_JS_TEMPLATE = r"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.css">
<script src="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.js"></script>
<style>
  #df-panel .noUi-connect { background: #3498db; }
  #df-panel .noUi-horizontal { height: 12px; }
  #df-panel .noUi-horizontal .noUi-handle {
    width: 22px; height: 22px; top: -6px; right: -11px;
    border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  #df-panel .noUi-handle::before, #df-panel .noUi-handle::after { display: none; }
</style>
<div id="df-panel" style="
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  z-index: 1000; width: min(720px, calc(100vw - 60px));
  background: rgba(255,255,255,0.96); padding: 14px 22px 18px; border-radius: 8px;
  border: 1px solid #aaa; font-family: -apple-system, sans-serif;
  font-size: 13px; box-shadow: 0 2px 10px rgba(0,0,0,0.25);
">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
    <b>Periodo</b>
    <span style="color:#444;">
      <b id="df-min">—</b> &nbsp;→&nbsp; <b id="df-max">—</b>
      &nbsp;·&nbsp; <b id="df-count">0</b> pos
      &nbsp;·&nbsp; <b id="df-vessels">0</b> barcos
    </span>
    <button id="df-clear" style="padding:3px 12px;cursor:pointer;border:1px solid #aaa;border-radius:4px;background:#fff;">Reset</button>
  </div>
  <div id="df-slider" style="margin: 10px 8px 0;"></div>
</div>
<script>
(function(){
  var tries = 0;
  var iv = setInterval(function(){
    tries++;
    if (__READY__ && typeof noUiSlider !== 'undefined') {
      clearInterval(iv); init();
    } else if (tries > 400) {
      clearInterval(iv); console.error('tracks layers not ready');
    }
  }, 50);

  function init(){
    var ALL = __POINTS__;
    var NAMES = __NAMES__;
    var MIN_TS = __MIN_TS__;
    var MAX_TS = __MAX_TS__;
    var LAYERS = __LAYERS__;
    var ACT_NAMES = ['fishing','transit','moored','slow_transit','unknown'];
    var ACT_COLORS = ['#e74c3c','#3498db','#95a5a6','#f39c12','#bdc3c7'];

    function pad(n){ return n.toString().padStart(2, '0'); }
    function fmtDate(ts){ var d = new Date(ts); return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear(); }

    function filterPts(minTs, maxTs){
      if (minTs == null && maxTs == null) return ALL;
      return ALL.filter(function(p){
        if (minTs != null && p[2] < minTs) return false;
        if (maxTs != null && p[2] > maxTs) return false;
        return true;
      });
    }

    function rebuild(minTs, maxTs){
      var pts = filterPts(minTs, maxTs);
      for (var k in LAYERS) LAYERS[k].clearLayers();

      var byMmsi = {};
      for (var i = 0; i < pts.length; i++){
        var p = pts[i];
        if (!byMmsi[p[3]]) byMmsi[p[3]] = [];
        byMmsi[p[3]].push(p);
      }
      var vesselCount = 0;
      for (var m in byMmsi){
        vesselCount++;
        var vp = byMmsi[m];
        vp.sort(function(a,b){ return a[2] - b[2]; });
        var name = NAMES[m] || m;
        for (var j = 0; j < vp.length - 1; j++){
          var p1 = vp[j], p2 = vp[j + 1];
          var act = p1[4];
          var layer = LAYERS[act];
          if (!layer) continue;
          L.polyline([[p1[0], p1[1]], [p2[0], p2[1]]], {
            color: ACT_COLORS[act], weight: 3, opacity: 0.7
          }).bindPopup(name + ' | ' + ACT_NAMES[act] + ' | SOG: ' + p1[5].toFixed(1) + ' kn')
            .addTo(layer);
        }
      }

      document.getElementById('df-count').textContent = pts.length;
      document.getElementById('df-vessels').textContent = vesselCount;
    }

    var slider = document.getElementById('df-slider');
    noUiSlider.create(slider, {
      start: [MIN_TS, MAX_TS], connect: true,
      range: {min: MIN_TS, max: MAX_TS},
      step: 24*60*60*1000, behaviour: 'drag-tap',
    });
    slider.noUiSlider.on('update', function(values){
      document.getElementById('df-min').textContent = fmtDate(+values[0]);
      document.getElementById('df-max').textContent = fmtDate(+values[1]);
    });
    var pending = null;
    slider.noUiSlider.on('slide', function(values){
      if (pending) clearTimeout(pending);
      pending = setTimeout(function(){
        var lo = +values[0], hi = +values[1];
        rebuild(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi);
      }, 100);
    });
    slider.noUiSlider.on('set', function(values){
      var lo = +values[0], hi = +values[1];
      rebuild(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi);
    });
    document.getElementById('df-clear').addEventListener('click', function(){
      slider.noUiSlider.set([MIN_TS, MAX_TS]);
    });

    rebuild(null, null);
  }
})();
</script>
"""


ACTIVITY_ORDER = ["fishing", "transit", "moored", "slow_transit", "unknown"]


def map_vessel_tracks(mmsi=None, since=None, output=None):
    """Tracks coloreadas por actividad con filtro de fecha client-side."""
    output = output or _web_path("mapa_tracks.html")
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)

    m = create_base_map(zoom=10)

    activity_layers = {}
    for act in ACTIVITY_ORDER:
        fg = folium.FeatureGroup(name=f"Actividad: {act}")
        fg.add_to(m)
        activity_layers[act] = fg

    folium.LayerControl().add_to(m)

    # [lat, lon, ts_ms, mmsi, act_idx, sog]
    act_idx = {a: i for i, a in enumerate(ACTIVITY_ORDER)}
    points = []
    if not df.empty:
        for row in df.itertuples(index=False):
            sog = float(row.sog) if row.sog is not None else 0.0
            points.append([
                round(float(row.lat), 6),
                round(float(row.lon), 6),
                int(row.timestamp.timestamp() * 1000),
                str(row.mmsi),
                act_idx.get(row.activity, 4),
                round(sog, 2),
            ])

    vessels_db = load_vessels()
    names = {str(r.mmsi): (r.name or "?") for r in vessels_db.itertuples(index=False)}

    if df.empty:
        min_ts = max_ts = 0
    else:
        min_ts = int(df["timestamp"].min().timestamp() * 1000)
        max_ts = int(df["timestamp"].max().timestamp() * 1000)

    layer_names = [activity_layers[a].get_name() for a in ACTIVITY_ORDER]
    layers_js = "{" + ", ".join(
        f"{i}: {layer_names[i]}" for i in range(len(ACTIVITY_ORDER))
    ) + "}"
    ready_js = " && ".join(f"typeof {n} !== 'undefined'" for n in layer_names)

    js = (
        TRACKS_JS_TEMPLATE
        .replace("__POINTS__", json.dumps(points))
        .replace("__NAMES__", json.dumps(names))
        .replace("__LAYERS__", layers_js)
        .replace("__READY__", ready_js)
        .replace("__MIN_TS__", str(min_ts))
        .replace("__MAX_TS__", str(max_ts))
    )
    m.get_root().html.add_child(folium.Element(js))

    m.save(output)
    print(f"Mapa guardado en {output} ({len(points)} puntos)")
    return m


FISHING_JS_TEMPLATE = r"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.css">
<script src="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.js"></script>
<style>
  #df-panel .noUi-connect { background: #e74c3c; }
  #df-panel .noUi-horizontal { height: 12px; }
  #df-panel .noUi-horizontal .noUi-handle {
    width: 22px; height: 22px; top: -6px; right: -11px;
    border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  #df-panel .noUi-handle::before, #df-panel .noUi-handle::after { display: none; }
</style>
<div id="df-panel" style="
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  z-index: 1000; width: min(720px, calc(100vw - 60px));
  background: rgba(255,255,255,0.96); padding: 14px 22px 18px; border-radius: 8px;
  border: 1px solid #aaa; font-family: -apple-system, sans-serif;
  font-size: 13px; box-shadow: 0 2px 10px rgba(0,0,0,0.25);
">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
    <b>Periodo</b>
    <span style="color:#444;">
      <b id="df-min">—</b> &nbsp;→&nbsp; <b id="df-max">—</b>
      &nbsp;·&nbsp; <b id="df-count">0</b> pos
      &nbsp;·&nbsp; <b id="df-cells">0</b> celdas
    </span>
    <button id="df-clear" style="padding:3px 12px;cursor:pointer;border:1px solid #aaa;border-radius:4px;background:#fff;">Reset</button>
  </div>
  <div id="df-slider" style="margin: 10px 8px 0;"></div>
</div>
<script>
(function(){
  var tries = 0;
  var iv = setInterval(function(){
    tries++;
    if (typeof __HEAT__ !== 'undefined' &&
        typeof __TOP__ !== 'undefined' &&
        typeof __DETAIL__ !== 'undefined' &&
        typeof __POSITIONS__ !== 'undefined' &&
        typeof noUiSlider !== 'undefined') {
      clearInterval(iv);
      init();
    } else if (tries > 400) {
      clearInterval(iv);
      console.error('Folium layers / noUiSlider not ready after 20s');
    }
  }, 50);

  function init(){
    var ALL = __POINTS__;
    var NAMES = __NAMES__;
    var GRID = __GRID__;
    var MIN_TS = __MIN_TS__;
    var MAX_TS = __MAX_TS__;
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
    function fmtDate(ts){
      var d = new Date(ts);
      return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear();
    }

    function filterPts(minTs, maxTs){
      if (minTs == null && maxTs == null) return ALL;
      return ALL.filter(function(p){
        if (minTs != null && p[2] < minTs) return false;
        if (maxTs != null && p[2] > maxTs) return false;
        return true;
      });
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

    function rebuild(minTs, maxTs){
      var pts = filterPts(minTs, maxTs);

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

    var slider = document.getElementById('df-slider');
    var DAY = 24 * 60 * 60 * 1000;
    noUiSlider.create(slider, {
      start: [MIN_TS, MAX_TS],
      connect: true,
      range: {min: MIN_TS, max: MAX_TS},
      step: DAY,
      behaviour: 'drag-tap',
    });

    slider.noUiSlider.on('update', function(values){
      var lo = +values[0], hi = +values[1];
      document.getElementById('df-min').textContent = fmtDate(lo);
      document.getElementById('df-max').textContent = fmtDate(hi);
    });

    var pending = null;
    slider.noUiSlider.on('slide', function(values){
      // Redraw durante el arrastre (con throttle ligero).
      var lo = +values[0], hi = +values[1];
      if (pending) clearTimeout(pending);
      pending = setTimeout(function(){
        rebuild(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi);
      }, 80);
    });
    slider.noUiSlider.on('set', function(values){
      var lo = +values[0], hi = +values[1];
      rebuild(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi);
    });

    document.getElementById('df-clear').addEventListener('click', function(){
      slider.noUiSlider.set([MIN_TS, MAX_TS]);
    });

    rebuild(null, null);
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
        min_ts = max_ts = 0
    else:
        min_ts = int(fishing["timestamp"].min().timestamp() * 1000)
        max_ts = int(fishing["timestamp"].max().timestamp() * 1000)

    js = (
        FISHING_JS_TEMPLATE
        .replace("__POINTS__", json.dumps(points))
        .replace("__NAMES__", json.dumps(names))
        .replace("__GRID__", str(grid_size))
        .replace("__HEAT__", heat_layer.get_name())
        .replace("__TOP__", top_layer.get_name())
        .replace("__DETAIL__", detail_layer.get_name())
        .replace("__POSITIONS__", positions_layer.get_name())
        .replace("__MIN_TS__", str(min_ts))
        .replace("__MAX_TS__", str(max_ts))
    )
    m.get_root().html.add_child(folium.Element(js))

    m.save(output)
    print(f"Mapa de zonas de pesca guardado en {output} ({len(points)} puntos)")
    return m


TRIPS_JS_TEMPLATE = r"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.css">
<script src="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.js"></script>
<style>
  #df-panel .noUi-connect { background: #2ecc71; }
  #df-panel .noUi-horizontal { height: 12px; }
  #df-panel .noUi-horizontal .noUi-handle {
    width: 22px; height: 22px; top: -6px; right: -11px;
    border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  #df-panel .noUi-handle::before, #df-panel .noUi-handle::after { display: none; }
</style>
<div id="df-panel" style="
  position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
  z-index: 1000; width: min(720px, calc(100vw - 60px));
  background: rgba(255,255,255,0.96); padding: 14px 22px 18px; border-radius: 8px;
  border: 1px solid #aaa; font-family: -apple-system, sans-serif;
  font-size: 13px; box-shadow: 0 2px 10px rgba(0,0,0,0.25);
">
  <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px;">
    <b>Periodo</b>
    <span style="color:#444;">
      <b id="df-min">—</b> &nbsp;→&nbsp; <b id="df-max">—</b>
      &nbsp;·&nbsp; <b id="df-count">0</b> viajes
    </span>
    <button id="df-clear" style="padding:3px 12px;cursor:pointer;border:1px solid #aaa;border-radius:4px;background:#fff;">Reset</button>
  </div>
  <div id="df-slider" style="margin: 10px 8px 0;"></div>
</div>
<script>
(function(){
  var tries = 0;
  var iv = setInterval(function(){
    tries++;
    if (typeof __LAYER__ !== 'undefined' && typeof noUiSlider !== 'undefined'){
      clearInterval(iv); init();
    } else if (tries > 400){ clearInterval(iv); console.error('trips layer not ready'); }
  }, 50);

  function init(){
    var ALL = __TRIPS__;
    var MIN_TS = __MIN_TS__;
    var MAX_TS = __MAX_TS__;
    var layer = __LAYER__;
    var PALETTE = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6',
                   '#1abc9c','#e67e22','#34495e','#d35400','#c0392b'];

    function pad(n){ return n.toString().padStart(2, '0'); }
    function fmt(ts){ var d = new Date(ts); return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }
    function fmtDate(ts){ var d = new Date(ts); return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear(); }

    function rebuild(minTs, maxTs){
      layer.clearLayers();
      var trips = ALL.filter(function(t){
        if (maxTs != null && t.start > maxTs) return false;
        if (minTs != null && t.end < minTs) return false;
        return true;
      });
      for (var i = 0; i < trips.length; i++){
        var t = trips[i];
        if (!t.coords || t.coords.length < 2) continue;
        var color = PALETTE[i % PALETTE.length];
        var popup =
            '<b>' + (t.name || t.mmsi) + '</b><br>' +
            'MMSI: ' + t.mmsi + ' · Sesión #' + t.trip_id + '<br>' +
            fmt(t.start) + ' &rarr; ' + fmt(t.end) + '<br>' +
            'Duración: ' + t.duration_h.toFixed(1) + ' h<br>' +
            'Max dist: ' + t.max_dist_nm.toFixed(1) + ' NM<br>' +
            'Pesca: ' + t.pct_fishing.toFixed(0) + '%';
        var latlngs = t.coords.map(function(c){ return [c[0], c[1]]; });
        L.polyline(latlngs, {color: color, weight: 3, opacity: 0.85})
          .bindPopup(popup).addTo(layer);
        L.circleMarker(latlngs[0], {
          radius: 5, color: '#2ecc71', fillColor: '#2ecc71',
          fillOpacity: 0.9, weight: 2
        }).bindPopup('Inicio sesión: ' + fmt(t.start)).addTo(layer);
        L.circleMarker(latlngs[latlngs.length - 1], {
          radius: 5, color: '#e74c3c', fillColor: '#e74c3c',
          fillOpacity: 0.9, weight: 2
        }).bindPopup('Fin sesión: ' + fmt(t.end)).addTo(layer);
      }
      document.getElementById('df-count').textContent = trips.length;
    }

    var slider = document.getElementById('df-slider');
    noUiSlider.create(slider, {
      start: [MIN_TS, MAX_TS], connect: true,
      range: {min: MIN_TS, max: MAX_TS},
      step: 24*60*60*1000, behaviour: 'drag-tap',
    });
    slider.noUiSlider.on('update', function(values){
      document.getElementById('df-min').textContent = fmtDate(+values[0]);
      document.getElementById('df-max').textContent = fmtDate(+values[1]);
    });
    var pending = null;
    slider.noUiSlider.on('slide', function(values){
      if (pending) clearTimeout(pending);
      pending = setTimeout(function(){
        var lo = +values[0], hi = +values[1];
        rebuild(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi);
      }, 100);
    });
    slider.noUiSlider.on('set', function(values){
      var lo = +values[0], hi = +values[1];
      rebuild(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi);
    });
    document.getElementById('df-clear').addEventListener('click', function(){
      slider.noUiSlider.set([MIN_TS, MAX_TS]);
    });

    rebuild(null, null);
  }
})();
</script>
"""


def map_trips(mmsi=None, since=None, output=None):
    """Viajes puerto → mar → puerto con filtro de fecha client-side."""
    output = output or _web_path("mapa_viajes.html")
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)
    trips_df = get_trip_summary(df) if not df.empty else df

    m = create_base_map(zoom=10)
    trip_layer = folium.FeatureGroup(name="Viajes").add_to(m)
    folium.LayerControl().add_to(m)

    vessels_db = load_vessels()
    name_by_mmsi = dict(zip(vessels_db["mmsi"], vessels_db["name"]))

    trips_payload = []
    if not trips_df.empty:
        for _, t in trips_df.iterrows():
            tdf = df[(df["mmsi"] == t["mmsi"]) & (df["trip_id"] == t["trip_id"])].sort_values("timestamp")
            if len(tdf) < 2:
                continue
            coords = [[round(float(r.lat), 6), round(float(r.lon), 6),
                       int(r.timestamp.timestamp() * 1000)]
                      for r in tdf.itertuples(index=False)]
            trips_payload.append({
                "mmsi": str(t["mmsi"]),
                "name": name_by_mmsi.get(t["mmsi"]) or "?",
                "trip_id": int(t["trip_id"]),
                "start": int(t["start"].timestamp() * 1000),
                "end": int(t["end"].timestamp() * 1000),
                "duration_h": round(float(t["duration_h"]), 2),
                "max_dist_nm": round(float(t["max_dist_nm"]), 2),
                "pct_fishing": round(float(t["pct_fishing"]), 1),
                "coords": coords,
            })

    if not trips_payload:
        min_ts = max_ts = 0
    else:
        min_ts = min(t["start"] for t in trips_payload)
        max_ts = max(t["end"] for t in trips_payload)

    js = (
        TRIPS_JS_TEMPLATE
        .replace("__TRIPS__", json.dumps(trips_payload))
        .replace("__LAYER__", trip_layer.get_name())
        .replace("__MIN_TS__", str(min_ts))
        .replace("__MAX_TS__", str(max_ts))
    )
    m.get_root().html.add_child(folium.Element(js))

    m.save(output)
    print(f"Mapa de viajes guardado en {output} ({len(trips_payload)} viajes)")
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
