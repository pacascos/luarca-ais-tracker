# AIS Luarca

Seguimiento de rutas y zonas de pesca de la flota pesquera de Luarca
(Asturias, Golfo de Vizcaya) a partir de datos AIS en tiempo real.

## Arquitectura

```
.
├── collector.py        # Captura continua AIS vía aisstream.io (WebSocket)
├── vesseltracker.py    # Snapshots puntuales vía VesselTracker REST API
├── analyzer.py         # Clasifica actividad (pesca/tránsito/amarrado), detecta viajes, agrega zonas
├── visualizer.py       # Genera los 3 mapas HTML (Folium)
├── db.py               # SQLite schema + helpers
├── config.py           # Bounding box, coordenadas, umbrales de velocidad
├── requirements.txt
├── .env.example
└── web/                # Sitio estático desplegable (mapas HTML)
    ├── index.html
    ├── mapa_tracks.html
    ├── mapa_pesca.html
    └── mapa_viajes.html
```

## Los 3 mapas

- **mapa_tracks.html** — Tracks completos coloreados por actividad (pesca,
  tránsito, amarrado, slow_transit).
- **mapa_pesca.html** — Mapa de calor de densidad de pesca + capa de celdas
  clicables (~1 km) con popup detallado: coordenadas, lista de barcos que
  han faenado ahí, nº de posiciones por barco, velocidad media, y rango
  temporal.
- **mapa_viajes.html** — Viajes individuales puerto → mar → puerto con
  duración y porcentaje de tiempo faenando.

Los 3 mapas incluyen varias capas cartográficas seleccionables:
Esri Ocean (batimetría), Satélite, OpenStreetMap, CartoDB, cartas náuticas
OpenSeaMap, batimetría EMODnet (multicolor + isóbatas) y GEBCO global.

## Despliegue solo-web (sin Python)

El directorio `web/` es un sitio estático autocontenido. Para desplegarlo
en cualquier servidor:

```bash
# Copiar el directorio a un servidor estático
rsync -av web/ user@server:/var/www/ais-luarca/

# O servirlo localmente
cd web && python -m http.server 8000
```

Para **GitHub Pages**: activar Pages en el repo apuntando a `/web` (rama
`main`) y el sitio estará en `https://<user>.github.io/<repo>/`.

## Ejecutar el pipeline de datos

Requiere Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # rellenar con las API keys

# Captura continua AIS (se reconecta solo, pensar en systemd/tmux)
python collector.py

# Snapshot puntual vía VesselTracker
python vesseltracker.py

# Regenerar los mapas a web/
python visualizer.py
```

## Fuentes de datos

- [aisstream.io](https://aisstream.io) — WebSocket gratuito con datos AIS
  en tiempo real (filtrado por bounding box).
- [VesselTracker](https://www.vesseltracker.com) — API REST (cuenta
  Antenna Operator, estación física VT-6372 en Luarca).

## Clasificación de actividad

Basada en velocidad sobre el fondo (SOG), configurable en `config.py`:

- `≤ 0.5 kn` → amarrado
- `1.0 – 7.0 kn` → pesca
- `≥ 8.0 kn` → tránsito
- resto → slow_transit
