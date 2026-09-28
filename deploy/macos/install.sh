#!/usr/bin/env bash
# Instala (o actualiza) el stack AIS Luarca como LaunchAgents de macOS.
# Se ejecuta como tu usuario, SIN sudo, desde el clon del repositorio.
#
#   ./deploy/macos/install.sh
#
# Es idempotente: tras un `git pull`, volver a ejecutarlo reinstala los
# agentes y reinicia los servicios. No toca .env ni la base de datos.
#
# Variables opcionales:
#   LUARCA_PORT  (def: 8765)                  puerto del servidor web
#   LUARCA_BIND  (def: 0.0.0.0)               0.0.0.0 = accesible en la LAN,
#                                             127.0.0.1 = solo este Mac
#   WEB_DIR      (def: ~/luarca-ais-web)      salida de los mapas, fuera del clon

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LOG_DIR="$PROJECT_DIR/logs"
PYTHON="$PROJECT_DIR/.venv/bin/python"
PORT="${LUARCA_PORT:-8765}"
BIND="${LUARCA_BIND:-0.0.0.0}"
WEB_DIR="${WEB_DIR:-$HOME/luarca-ais-web}"
LABELS=(com.luarca.ais.collector com.luarca.ais.vtpoller com.luarca.ais.visualizer com.luarca.ais.web)

if [[ $EUID -eq 0 ]]; then
  echo "No ejecutes esto con sudo: los LaunchAgents van en tu usuario." >&2
  exit 1
fi

echo "==> AIS Luarca (macOS / launchd)"
echo "    Proyecto: $PROJECT_DIR"
echo "    Mapas:    $WEB_DIR"
echo "    Web:      http://$BIND:$PORT/"
echo

# 1) Python
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 no encontrado. Instálalo con Homebrew (brew install python) o Xcode CLT." >&2
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  echo "ERROR: se necesita Python 3.11+, tienes $(python3 --version)." >&2
  exit 1
fi

# 2) Virtualenv + dependencias
if [[ ! -x "$PYTHON" ]]; then
  echo "==> Creando virtualenv"
  python3 -m venv "$PROJECT_DIR/.venv"
fi
echo "==> Instalando dependencias"
"$PROJECT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install --quiet -r "$PROJECT_DIR/requirements.txt"

# 3) .env
if [[ ! -f "$PROJECT_DIR/.env" ]]; then
  echo "==> Creando .env desde plantilla (rellena AISSTREAM_API_KEY)"
  cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
  chmod 600 "$PROJECT_DIR/.env"
fi
if ! grep -q '^WEB_DIR=' "$PROJECT_DIR/.env"; then
  echo "WEB_DIR=$WEB_DIR" >> "$PROJECT_DIR/.env"
else
  WEB_DIR="$(grep '^WEB_DIR=' "$PROJECT_DIR/.env" | tail -1 | cut -d= -f2-)"
  echo "==> WEB_DIR ya definido en .env: $WEB_DIR"
fi
mkdir -p "$WEB_DIR" "$LOG_DIR"

# 4) Base de datos existente: normalizar (idempotente, hace copia en dumps/)
if [[ -f "$PROJECT_DIR/ais_luarca.db" ]]; then
  echo "==> Migrando/verificando base de datos"
  (cd "$PROJECT_DIR" && "$PYTHON" migrate_db.py)
fi

# 5) Parar agentes anteriores (si los hay)
for label in "${LABELS[@]}"; do
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
done

# 6) Generar e instalar los plists
mkdir -p "$AGENTS_DIR"
for label in "${LABELS[@]}"; do
  sed -e "s|__PROJECT__|$PROJECT_DIR|g" \
      -e "s|__PYTHON__|$PYTHON|g" \
      -e "s|__LOGS__|$LOG_DIR|g" \
      -e "s|__PORT__|$PORT|g" \
      -e "s|__BIND__|$BIND|g" \
      -e "s|__WEB__|$WEB_DIR|g" \
      "$PROJECT_DIR/deploy/macos/$label.plist" > "$AGENTS_DIR/$label.plist"
  plutil -lint -s "$AGENTS_DIR/$label.plist"
done

# 7) Arrancar
if ! grep -qE '^AISSTREAM_API_KEY=.+' "$PROJECT_DIR/.env" \
   || grep -q '^AISSTREAM_API_KEY=your_api_key_here' "$PROJECT_DIR/.env"; then
  echo
  echo "!! AISSTREAM_API_KEY no está en $PROJECT_DIR/.env."
  echo "   Edítalo y luego arranca con:  ./deploy/macos/install.sh"
  exit 0
fi

echo "==> Arrancando agentes"
for label in "${LABELS[@]}"; do
  launchctl bootstrap "gui/$UID" "$AGENTS_DIR/$label.plist"
done

sleep 2
echo
launchctl list | grep com.luarca.ais || true
cat <<EOT

==> Listo.

  Logs:        tail -f $LOG_DIR/collector.log   (y vt_poller.log)
  Web:         http://localhost:$PORT/   (y desde la LAN por la IP de este Mac)
  Reiniciar:   launchctl kickstart -k gui/$UID/com.luarca.ais.collector
  Desinstalar: ./deploy/macos/uninstall.sh

  Para que el Mac no se duerma:  sudo pmset -a sleep 0 disksleep 0
EOT
