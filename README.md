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
├── migrate_db.py       # Normaliza/limpia una BD de versiones anteriores
├── db.py               # SQLite schema + helpers
├── config.py           # Bounding box, flota de Luarca, umbrales de velocidad
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

Los 3 mapas embeben el histórico completo y se filtran en el navegador sin
recargar: al abrir muestran **el último mes** y el panel inferior permite
cambiar el periodo (slider por días, botones "Último mes" / "Todo") y elegir
un barco concreto.

Los 3 mapas incluyen varias capas cartográficas seleccionables:
Esri Ocean (batimetría), Satélite, OpenStreetMap, CartoDB, cartas náuticas
OpenSeaMap, batimetría EMODnet (multicolor + isóbatas) y GEBCO global.

## Despliegue completo en servidor Linux

Para correr `collector` + regeneración periódica de mapas + servidor web en
un servidor con systemd, usa el paquete de despliegue:

```bash
sudo ./deploy/install.sh
```

Documentación completa, units de systemd, ejemplo nginx + TLS y operación
en [`deploy/README.md`](deploy/README.md).

## Despliegue completo en un Mac siempre encendido

Mismo stack con LaunchAgents (sin `sudo`):

```bash
./deploy/macos/install.sh
```

Guía completa en [`deploy/macos/README.md`](deploy/macos/README.md).

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
python visualizer.py --days 90        # limitar el histórico embebido
python visualizer.py --mmsi 224026280 # solo un barco

# Informe por consola
python analyzer.py [--days 30]

# BD creada con una versión anterior: normaliza timestamps, elimina
# duplicados y crea el índice único (hace copia en dumps/ antes)
python migrate_db.py [--purge-non-fishing]
```

## Qué barcos se guardan

El collector recibe todo el tráfico del bounding box pero solo guarda
posiciones de barcos que pueden ser pesqueros (`config.is_fishing_candidate`):

- los de la flota de Luarca (`PESQUEROS_LUARCA` en `config.py`),
- los que declaran tipo AIS 30 (pesquero),
- los españoles cuyo tipo aún no se conoce (hasta que llega su
  `ShipStaticData`; si resulta ser un carguero se descartan desde entonces).

Los datos estáticos (nombre, tipo, dimensiones) se guardan para todos los
barcos, precisamente para poder descartar a los no pesqueros. El analizador
aplica el mismo criterio al cargar, así que una BD antigua con cargueros
produce los mismos mapas sin necesidad de borrar nada.

Los timestamps se almacenan siempre en ISO 8601 UTC (`2026-05-06T14:05:27Z`)
y la pareja (MMSI, timestamp) es única: repetir un poll de VesselTracker o
recibir un mensaje duplicado no crea filas nuevas.

## Fuentes de datos

- [aisstream.io](https://aisstream.io) — WebSocket gratuito con datos AIS
  en tiempo real (filtrado por bounding box).
- [VesselTracker](https://www.vesseltracker.com) — API REST (cuenta
  Antenna Operator, estación física VT-6372 en Luarca).

## Clasificación de actividad

Por orden de prioridad (umbrales en `config.py`):

1. A menos de 1 NM del puerto → amarrado.
2. Estado de navegación AIS 5 (amarrado) o 1 (fondeado) → amarrado.
3. Estado de navegación AIS 7 (pescando) → pesca, salvo que navegue a
   `≥ 8.0 kn`, en cuyo caso tránsito (es habitual dejar el estado puesto al
   volver a puerto).
4. Sin estado concluyente, por velocidad sobre el fondo (SOG):
   - `≤ 0.5 kn` → amarrado
   - `1.0 – 7.0 kn` → pesca
   - `≥ 8.0 kn` → tránsito
   - resto → slow_transit
