"""Visualización de rutas AIS en mapas HTML con Folium."""

import argparse
import json
import os
from datetime import datetime, timedelta, timezone

import folium
from folium.plugins import HeatMap

from config import LUARCA_LAT, LUARCA_LON, FLEET_MMSI
from analyzer import analyze_vessel_tracks, get_trip_summary, load_vessels

# Directorio de salida de los mapas. En un despliegue permanente conviene
# sacarlo fuera del clon de git (WEB_DIR en .env) para que `git pull` no
# choque con los HTML regenerados.
WEB_DIR = os.getenv("WEB_DIR") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "web"
)

# Periodo mostrado por defecto al abrir un mapa (el slider permite ampliarlo
# hasta todo el histórico embebido en la página).
DEFAULT_WINDOW_DAYS = 30

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


FILTER_PANEL_TEMPLATE = r"""
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.css">
<script src="https://cdn.jsdelivr.net/npm/nouislider@15.7.1/dist/nouislider.min.js"></script>
<style>
  #df-panel {
    position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%);
    z-index: 1000; width: min(760px, calc(100vw - 60px));
    background: rgba(255,255,255,0.96); padding: 12px 22px 18px; border-radius: 8px;
    border: 1px solid #aaa; font-family: -apple-system, sans-serif;
    font-size: 13px; box-shadow: 0 2px 10px rgba(0,0,0,0.25);
  }
  #df-panel .df-row { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
  #df-panel .df-stats { color:#444; flex:1; min-width: 200px; }
  #df-panel select, #df-panel button {
    padding:3px 10px; border:1px solid #aaa; border-radius:4px; background:#fff;
    font-size:12px; cursor:pointer;
  }
  #df-panel .noUi-connect { background: __COLOR__; }
  #df-panel .noUi-horizontal { height: 12px; }
  #df-panel .noUi-horizontal .noUi-handle {
    width: 22px; height: 22px; top: -6px; right: -11px;
    border-radius: 50%; box-shadow: 0 1px 3px rgba(0,0,0,0.3);
  }
  #df-panel .noUi-handle::before, #df-panel .noUi-handle::after { display: none; }
</style>
<div id="df-panel">
  <div class="df-row">
    <b>Periodo</b>
    <span class="df-stats">
      <b id="df-min">—</b> &nbsp;→&nbsp; <b id="df-max">—</b>
      &nbsp;·&nbsp; <span id="df-stats"></span>
    </span>
    <select id="df-vessel"></select>
    <select id="df-range" title="Periodo mostrado">
      <option value="0">Hoy</option>
      <option value="7">Última semana</option>
      <option value="30">Último mes</option>
      <option value="90">Últimos 90 días</option>
      <option value="180">Últimos 180 días</option>
      <option value="all">Todo el histórico</option>
      <option value="custom" disabled hidden>Personalizado</option>
    </select>
  </div>
  <div id="df-slider" style="margin: 10px 8px 0;"></div>
</div>
<script>
// Panel de filtros compartido por los mapas. Cada mapa llama a
// setupFilters({minTs, maxTs, vessels, fleet, onChange}) cuando sus capas
// existen. onChange(minTs, maxTs, allow) recibe en allow un Set de MMSI
// permitidos, o null para todos.
window.setupFilters = function(opts){
  var DAY = 24*60*60*1000;
  function midnight(ts){ var d = new Date(ts); d.setHours(0,0,0,0); return d.getTime(); }
  // Rango alineado a medianoche local para que el paso de un día caiga en días enteros
  var MIN_TS = midnight(opts.minTs);
  var MAX_TS = midnight(opts.maxTs) + DAY;
  if (MAX_TS <= MIN_TS) MAX_TS = MIN_TS + DAY;
  var TODAY = midnight(Date.now());
  var rangeSel = document.getElementById('df-range');
  function presetLo(v){
    if (v === 'all') return MIN_TS;
    if (v === '0') return Math.max(MIN_TS, Math.min(TODAY, MAX_TS - DAY));
    return Math.max(MIN_TS, MAX_TS - (+v) * DAY);
  }
  var DEFAULT_PRESET = '__DAYS__';
  var DEFAULT_LO = presetLo(DEFAULT_PRESET);

  function pad(n){ return n.toString().padStart(2, '0'); }
  function fmtDate(ts){ var d = new Date(ts); return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + '/' + d.getFullYear(); }

  var sel = document.getElementById('df-vessel');
  var FLEET = new Set(opts.fleet || []);
  function addOpt(value, text){
    var o = document.createElement('option'); o.value = value; o.textContent = text; sel.appendChild(o);
  }
  if (FLEET.size) addOpt('__fleet__', 'Flota de Luarca (' + FLEET.size + ')');
  addOpt('', 'Todos los barcos (' + Object.keys(opts.vessels).length + ')');
  Object.keys(opts.vessels).map(function(m){ return [opts.vessels[m] || m, m]; })
    .sort(function(a, b){
      var fa = FLEET.has(a[1]) ? 0 : 1, fb = FLEET.has(b[1]) ? 0 : 1;
      return fa - fb || a[0].localeCompare(b[0]);
    })
    .forEach(function(v){ addOpt(v[1], (FLEET.has(v[1]) ? '\u2693 ' : '') + v[0]); });
  if (FLEET.size) sel.value = '__fleet__';   // por defecto, solo la flota de Luarca
  function allowed(){
    if (sel.value === '__fleet__') return FLEET;
    if (sel.value === '') return null;
    return new Set([sel.value]);
  }

  var slider = document.getElementById('df-slider');
  noUiSlider.create(slider, {
    start: [DEFAULT_LO, MAX_TS], connect: true,
    range: {min: MIN_TS, max: MAX_TS},
    step: DAY, behaviour: 'drag-tap',
  });

  function syncPreset(lo, hi){
    // Selecciona en el desplegable el preajuste que coincide con el slider, si hay
    var match = 'custom';
    if (hi >= MAX_TS){
      var opts_ = ['all','0','7','30','90','180'];   // 'all' primero: si el histórico es corto, gana
      for (var i = 0; i < opts_.length; i++){
        if (Math.abs(presetLo(opts_[i]) - lo) < DAY / 2){ match = opts_[i]; break; }
      }
    }
    rangeSel.value = match;
  }
  function apply(values){
    var lo = +values[0], hi = +values[1];
    syncPreset(lo, hi);
    opts.onChange(lo <= MIN_TS ? null : lo, hi >= MAX_TS ? null : hi - 1, allowed());
  }

  slider.noUiSlider.on('update', function(values){
    document.getElementById('df-min').textContent = fmtDate(+values[0]);
    document.getElementById('df-max').textContent = fmtDate(+values[1] - 1);
  });
  var pending = null;
  slider.noUiSlider.on('slide', function(values){
    if (pending) clearTimeout(pending);
    pending = setTimeout(function(){ apply(values); }, 100);
  });
  slider.noUiSlider.on('set', function(values){ apply(values); });
  sel.addEventListener('change', function(){ apply(slider.noUiSlider.get()); });
  rangeSel.addEventListener('change', function(){
    if (rangeSel.value === 'custom') return;
    slider.noUiSlider.set([presetLo(rangeSel.value), MAX_TS]);
  });

  apply(slider.noUiSlider.get());
};
window.setFilterStats = function(html){ document.getElementById('df-stats').innerHTML = html; };
</script>
"""


def _filter_panel(color):
    return (FILTER_PANEL_TEMPLATE
            .replace("__COLOR__", color)
            .replace("__DAYS__", str(DEFAULT_WINDOW_DAYS)))


def _wait_for(ready_expr, body_js):
    """Envuelve body_js en un poll hasta que las variables de Folium existen."""
    return f"""
<script>
(function(){{
  var tries = 0;
  var iv = setInterval(function(){{
    tries++;
    if ({ready_expr} && typeof window.setupFilters === 'function') {{
      clearInterval(iv); init();
    }} else if (tries > 400) {{
      clearInterval(iv); console.error('map layers not ready after 20s');
    }}
  }}, 50);
  function init(){{
{body_js}
  }}
}})();
</script>
"""


def _vessel_names(mmsis):
    """{mmsi: nombre} solo para los MMSI presentes en el mapa."""
    vessels_db = load_vessels()
    names = {str(r.mmsi): (r.name or "?") for r in vessels_db.itertuples(index=False)}
    return {m: names.get(m, m) for m in sorted(set(mmsis))}


TRACKS_JS = r"""
    var ALL = __POINTS__;
    var NAMES = __NAMES__;
    var LAYERS = __LAYERS__;
    var ACT_NAMES = ['fishing','transit','moored','slow_transit','unknown'];
    var ACT_COLORS = ['#e74c3c','#3498db','#95a5a6','#f39c12','#bdc3c7'];
    var MAX_GAP_MS = 30 * 60 * 1000;   // no unir posiciones separadas > 30 min

    function rebuild(minTs, maxTs, allow){
      var pts = ALL.filter(function(p){
        if (allow && !allow.has(p[3])) return false;
        if (minTs != null && p[2] < minTs) return false;
        if (maxTs != null && p[2] > maxTs) return false;
        return true;
      });
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
          if (p2[2] - p1[2] > MAX_GAP_MS) continue;
          var act = p1[4];
          var layer = LAYERS[act];
          if (!layer) continue;
          L.polyline([[p1[0], p1[1]], [p2[0], p2[1]]], {
            color: ACT_COLORS[act], weight: 3, opacity: 0.7
          }).bindPopup(name + ' | ' + ACT_NAMES[act] + ' | SOG: ' + p1[5].toFixed(1) + ' kn')
            .addTo(layer);
        }
      }
      window.setFilterStats('<b>' + pts.length + '</b> pos · <b>' + vesselCount + '</b> barcos');
    }

    window.setupFilters({
      minTs: __MIN_TS__, maxTs: __MAX_TS__, vessels: NAMES, fleet: __FLEET__,
      onChange: rebuild
    });
"""


ACTIVITY_ORDER = ["fishing", "transit", "moored", "slow_transit", "unknown"]


def map_vessel_tracks(mmsi=None, since=None, output=None):
    """Tracks coloreadas por actividad con filtro de fecha y barco client-side."""
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

    names = _vessel_names(p[3] for p in points)

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

    body = (
        TRACKS_JS
        .replace("__POINTS__", json.dumps(points))
        .replace("__NAMES__", json.dumps(names))
        .replace("__FLEET__", json.dumps(sorted(m for m in names if m in FLEET_MMSI)))
        .replace("__LAYERS__", layers_js)
        .replace("__MIN_TS__", str(min_ts))
        .replace("__MAX_TS__", str(max_ts))
    )
    m.get_root().html.add_child(folium.Element(_filter_panel("#3498db")))
    m.get_root().html.add_child(folium.Element(_wait_for(ready_js, body)))

    m.save(output)
    print(f"Mapa guardado en {output} ({len(points)} puntos)")
    return m


FISHING_JS = r"""
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

    function rebuild(minTs, maxTs, allow){
      var pts = ALL.filter(function(p){
        if (allow && !allow.has(p[3])) return false;
        if (minTs != null && p[2] < minTs) return false;
        if (maxTs != null && p[2] > maxTs) return false;
        return true;
      });

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

      window.setFilterStats('<b>' + pts.length + '</b> pos · <b>' + cells.length + '</b> celdas');
    }

    window.setupFilters({
      minTs: __MIN_TS__, maxTs: __MAX_TS__, vessels: NAMES, fleet: __FLEET__,
      onChange: rebuild
    });
"""


def map_fishing_zones(mmsi=None, since=None, output=None, grid_size=0.01):
    """Genera el mapa de zonas de pesca con filtro de fecha y barco client-side."""
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

    names = _vessel_names(p[3] for p in points)

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

    layer_names = [heat_layer.get_name(), top_layer.get_name(),
                   detail_layer.get_name(), positions_layer.get_name()]
    ready_js = " && ".join(f"typeof {n} !== 'undefined'" for n in layer_names)

    body = (
        FISHING_JS
        .replace("__POINTS__", json.dumps(points))
        .replace("__NAMES__", json.dumps(names))
        .replace("__FLEET__", json.dumps(sorted(m for m in names if m in FLEET_MMSI)))
        .replace("__GRID__", str(grid_size))
        .replace("__HEAT__", heat_layer.get_name())
        .replace("__TOP__", top_layer.get_name())
        .replace("__DETAIL__", detail_layer.get_name())
        .replace("__POSITIONS__", positions_layer.get_name())
        .replace("__MIN_TS__", str(min_ts))
        .replace("__MAX_TS__", str(max_ts))
    )
    m.get_root().html.add_child(folium.Element(_filter_panel("#e74c3c")))
    m.get_root().html.add_child(folium.Element(_wait_for(ready_js, body)))

    m.save(output)
    print(f"Mapa de zonas de pesca guardado en {output} ({len(points)} puntos)")
    return m


TRIPS_JS = r"""
    var ALL = __TRIPS__;
    var NAMES = __NAMES__;
    var layer = __LAYER__;
    var PALETTE = ['#e74c3c','#3498db','#2ecc71','#f39c12','#9b59b6',
                   '#1abc9c','#e67e22','#34495e','#d35400','#c0392b'];

    function pad(n){ return n.toString().padStart(2, '0'); }
    function fmt(ts){ var d = new Date(ts); return pad(d.getDate()) + '/' + pad(d.getMonth()+1) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes()); }

    function rebuild(minTs, maxTs, allow){
      layer.clearLayers();
      var trips = ALL.filter(function(t){
        if (allow && !allow.has(t.mmsi)) return false;
        if (maxTs != null && t.start > maxTs) return false;
        if (minTs != null && t.end < minTs) return false;
        return true;
      });
      for (var i = 0; i < trips.length; i++){
        var t = trips[i];
        if (!t.coords || t.coords.length < 2) continue;
        var color = PALETTE[i % PALETTE.length];
        var vessel = NAMES[t.mmsi] || t.mmsi;
        var popup =
            '<b>' + (NAMES[t.mmsi] || t.mmsi) + '</b><br>' +
            'MMSI: ' + t.mmsi + ' · Sesión #' + t.trip_id + '<br>' +
            'Señal recibida: ' + fmt(t.start) + ' &rarr; ' + fmt(t.end) + '<br>' +
            'Duración con señal: ' + t.duration_h.toFixed(1) + ' h<br>' +
            'Distancia máx. a Luarca: ' + t.max_dist_nm.toFixed(1) + ' NM<br>' +
            'Tiempo pescando: ' + t.pct_fishing.toFixed(0) + '%' +
            '<div style="color:#777;font-size:11px;margin-top:4px">Solo el tramo con cobertura AIS; ' +
            'la salida o la pesca lejos de la costa pueden faltar.</div>';
        // Tramos agrupados por actividad: la pesca en color y grueso, el
        // tránsito fino y gris para que no tape lo importante.
        var runs = [], cur = null;
        for (var k = 0; k < t.coords.length; k++){
          var c = t.coords[k], fishing = c[3] === 0;
          if (!cur || cur.fishing !== fishing){
            var start = cur ? cur.pts[cur.pts.length - 1] : null;
            cur = {fishing: fishing, pts: start ? [start] : []};
            runs.push(cur);
          }
          cur.pts.push([c[0], c[1]]);
        }
        for (var r = 0; r < runs.length; r++){
          if (runs[r].pts.length < 2) continue;
          L.polyline(runs[r].pts, runs[r].fishing
            ? {color: color, weight: 4, opacity: 0.9}
            : {color: '#555', weight: 1.5, opacity: 0.55, dashArray: '4 4'}
          ).bindPopup(popup).addTo(layer);
        }
        var latlngs = t.coords.map(function(c){ return [c[0], c[1]]; });
        L.circleMarker(latlngs[0], {
          radius: 4, color: '#2ecc71', fillColor: '#2ecc71',
          fillOpacity: 0.9, weight: 2
        }).bindPopup(vessel + '<br>Primera señal recibida: ' + fmt(t.start)).addTo(layer);
        L.circleMarker(latlngs[latlngs.length - 1], {
          radius: 4, color: '#e74c3c', fillColor: '#e74c3c',
          fillOpacity: 0.9, weight: 2
        }).bindPopup(vessel + '<br>Última señal recibida: ' + fmt(t.end)).addTo(layer);
      }
      window.setFilterStats('<b>' + trips.length + '</b> viajes');
    }

    window.setupFilters({
      minTs: __MIN_TS__, maxTs: __MAX_TS__, vessels: NAMES, fleet: __FLEET__,
      onChange: rebuild
    });
"""


def map_trips(mmsi=None, since=None, output=None):
    """Viajes puerto → mar → puerto con filtro de fecha y barco client-side."""
    output = output or _web_path("mapa_viajes.html")
    df = analyze_vessel_tracks(mmsi=mmsi, since=since)
    trips_df = get_trip_summary(df) if not df.empty else df

    m = create_base_map(zoom=10)
    m.get_root().html.add_child(folium.Element("""
    <div style="position:fixed; top:10px; right:60px; z-index:1000; background:rgba(255,255,255,0.93);
         padding:8px 12px; border-radius:6px; border:1px solid #aaa; font:12px -apple-system,sans-serif;">
      <span style="display:inline-block;width:26px;height:4px;background:#e74c3c;vertical-align:middle"></span> pesca
      &nbsp;&nbsp;<span style="display:inline-block;width:26px;border-top:2px dashed #555;vertical-align:middle"></span> tránsito
      &nbsp;&nbsp;<span style="color:#2ecc71">&#9679;</span> inicio &nbsp;<span style="color:#e74c3c">&#9679;</span> fin
    </div>"""))
    trip_layer = folium.FeatureGroup(name="Viajes").add_to(m)
    folium.LayerControl().add_to(m)

    trips_payload = []
    if not trips_df.empty:
        for _, t in trips_df.iterrows():
            tdf = df[(df["mmsi"] == t["mmsi"]) & (df["trip_id"] == t["trip_id"])].sort_values("timestamp")
            if len(tdf) < 2:
                continue
            act_idx = {a: i for i, a in enumerate(ACTIVITY_ORDER)}
            coords = [[round(float(r.lat), 6), round(float(r.lon), 6),
                       int(r.timestamp.timestamp() * 1000),
                       act_idx.get(r.activity, 4)]
                      for r in tdf.itertuples(index=False)]
            trips_payload.append({
                "mmsi": str(t["mmsi"]),
                "trip_id": int(t["trip_id"]),
                "start": int(t["start"].timestamp() * 1000),
                "end": int(t["end"].timestamp() * 1000),
                "duration_h": round(float(t["duration_h"]), 2),
                "max_dist_nm": round(float(t["max_dist_nm"]), 2),
                "pct_fishing": round(float(t["pct_fishing"]), 1),
                "coords": coords,
            })

    names = _vessel_names(t["mmsi"] for t in trips_payload)

    if not trips_payload:
        min_ts = max_ts = 0
    else:
        min_ts = min(t["start"] for t in trips_payload)
        max_ts = max(t["end"] for t in trips_payload)

    body = (
        TRIPS_JS
        .replace("__TRIPS__", json.dumps(trips_payload))
        .replace("__NAMES__", json.dumps(names))
        .replace("__FLEET__", json.dumps(sorted(m for m in names if m in FLEET_MMSI)))
        .replace("__LAYER__", trip_layer.get_name())
        .replace("__MIN_TS__", str(min_ts))
        .replace("__MAX_TS__", str(max_ts))
    )
    ready_js = f"typeof {trip_layer.get_name()} !== 'undefined'"
    m.get_root().html.add_child(folium.Element(_filter_panel("#2ecc71")))
    m.get_root().html.add_child(folium.Element(_wait_for(ready_js, body)))

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
    .card .q { color: #666; font-style: italic; font-size: 0.9rem; margin-bottom: 0; }
    h2 { font-size: 1.15rem; margin-top: 2.5rem; }
    ul { padding-left: 1.2rem; }
    li { margin-bottom: 0.5rem; }
    footer { margin-top: 3rem; color: #888; font-size: 0.9rem; }
    @media (prefers-color-scheme: dark) {
      body { background: #1a1a1a; color: #eee; }
      .card { border-color: #444; }
      .sub, footer, .card .q { color: #aaa; }
    }
  </style>
</head>
<body>
  <h1>AIS Luarca</h1>
  <p class="sub">Rutas y zonas de pesca de la flota pesquera de Luarca (Golfo de Vizcaya) a partir de datos AIS.</p>

  <p>Los barcos llevan un transmisor AIS que emite su posición, rumbo y velocidad
  cada pocos segundos. Estos mapas recogen esas señales de los pesqueros de Luarca
  (y del resto de la costa entre San Cibrao y Gijón) y las convierten en tres vistas
  de la misma información. <b>Todos abren mostrando el último mes y solo la flota de
  Luarca.</b> El panel inferior permite cambiar el periodo, ver un barco concreto o
  ampliar a todos los barcos de la zona.</p>

  <div class="cards">
    <a class="card" href="mapa_tracks.html">
      <h3>Tracks de barcos</h3>
      <p><b>Dónde ha estado cada barco y qué hacía.</b> El recorrido completo,
      coloreado por actividad: rojo pescando, azul en tránsito, gris parado,
      naranja a velocidad intermedia.</p>
      <p class="q">Responde a: ¿por dónde se mueve este barco?</p>
    </a>
    <a class="card" href="mapa_pesca.html">
      <h3>Zonas de pesca</h3>
      <p><b>Dónde se concentra la pesca.</b> Mapa de calor con solo los momentos de
      pesca; los círculos marcan las 20 celdas más frecuentadas. La capa "Detalle por
      celda" muestra qué barcos pescaron en cada kilómetro cuadrado, cuántas veces y
      en qué fechas.</p>
      <p class="q">Responde a: ¿cuáles son los caladeros habituales? ¿quién pesca aquí?</p>
    </a>
    <a class="card" href="mapa_viajes.html">
      <h3>Viajes</h3>
      <p><b>Cada marea, una a una.</b> Desde que el barco deja un puerto hasta que
      vuelve: inicio en verde, fin en rojo, pesca en color y tránsito en gris
      discontinuo. Al pinchar: barco, fecha, duración, distancia máxima y porcentaje
      de tiempo pescando.</p>
      <p class="q">Responde a: ¿cómo fue la salida del martes? ¿cuánto tarda en llegar al caladero?</p>
    </a>
  </div>

  <h2>Cómo interpretarlos</h2>
  <ul>
    <li><b>La cobertura no es perfecta.</b> Las señales se reciben por antenas en
    tierra y los barcos pequeños o lejanos se pierden a ratos. Un viaje puede
    aparecer partido en dos si hubo más de media hora sin señal.</li>
    <li><b>"Pesca" es una deducción.</b> Se apoya en el estado que el barco declara en
    su AIS y, si no lo declara, en su velocidad (entre 1 y 5 nudos; a más de 6 se
    considera tránsito aunque declare pesca). Un barco a la
    deriva o navegando despacio puede confundirse con uno pescando.</li>
    <li><b>Un barco que no aparece no es que no haya salido.</b> Puede que su AIS
    estuviera apagado o fuera del alcance de las antenas.</li>
  </ul>

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


def main():
    ap = argparse.ArgumentParser(description="Genera los mapas HTML en web/")
    ap.add_argument("--since", help="Solo datos desde esta fecha (p.ej. 2026-04-01)")
    ap.add_argument("--days", type=int,
                    help="Solo los últimos N días (limita el histórico embebido)")
    ap.add_argument("--mmsi", help="Solo un barco")
    args = ap.parse_args()

    since = args.since
    if args.days:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    print("Generando mapas...")
    map_vessel_tracks(mmsi=args.mmsi, since=since)
    map_fishing_zones(mmsi=args.mmsi, since=since)
    map_trips(mmsi=args.mmsi, since=since)
    build_index()
    print("Listo.")


if __name__ == "__main__":
    main()
