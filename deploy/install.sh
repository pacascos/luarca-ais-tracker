#!/usr/bin/env bash
# Instalador del stack AIS Luarca en un servidor Linux con systemd.
#
# Uso (como root o con sudo):
#   sudo ./install.sh
#
# Variables de entorno opcionales:
#   LUARCA_USER  (def: luarca)            usuario de sistema dedicado
#   LUARCA_HOME  (def: /opt/luarca-ais)   directorio de instalación
#   LUARCA_PORT  (def: 8765)              puerto del servidor web local
#
# Tras instalar, edita /opt/luarca-ais/.env con las API keys y arranca los
# servicios (instrucciones al final del script).

set -euo pipefail

LUARCA_USER="${LUARCA_USER:-luarca}"
LUARCA_HOME="${LUARCA_HOME:-/opt/luarca-ais}"
LUARCA_PORT="${LUARCA_PORT:-8765}"

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta como root (sudo $0)" >&2
  exit 1
fi

echo "==> Instalando AIS Luarca"
echo "    Usuario:    $LUARCA_USER"
echo "    Directorio: $LUARCA_HOME"
echo "    Puerto web: $LUARCA_PORT"
echo "    Origen:     $SRC_DIR"
echo

# 1) Dependencias del sistema
echo "==> Verificando dependencias del sistema"
if ! command -v python3 >/dev/null; then
  echo "ERROR: python3 no instalado. Instala python3 + python3-venv primero." >&2
  exit 1
fi
PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "    python3 $PY_VERSION"
if ! python3 -c 'import venv' 2>/dev/null; then
  echo "ERROR: módulo venv no disponible. apt install python3-venv (o equivalente)." >&2
  exit 1
fi

# 2) Usuario de sistema
if id -u "$LUARCA_USER" >/dev/null 2>&1; then
  echo "==> Usuario $LUARCA_USER ya existe"
else
  echo "==> Creando usuario $LUARCA_USER"
  useradd --system --create-home --home-dir "$LUARCA_HOME" --shell /usr/sbin/nologin "$LUARCA_USER"
fi

# 3) Directorio de instalación
echo "==> Preparando $LUARCA_HOME"
install -d -o "$LUARCA_USER" -g "$LUARCA_USER" -m 755 "$LUARCA_HOME"
install -d -o "$LUARCA_USER" -g "$LUARCA_USER" -m 755 "$LUARCA_HOME/web"

# 4) Copia de ficheros del proyecto
echo "==> Copiando código del proyecto"
RSYNC_EXCLUDES=(
  --exclude='.git/'
  --exclude='.venv/'
  --exclude='__pycache__/'
  --exclude='.DS_Store'
  --exclude='.claude/'
  --exclude='*.log'
  --exclude='ais_luarca.db'   # no machacar la BD existente
)
rsync -a "${RSYNC_EXCLUDES[@]}" --chown="$LUARCA_USER":"$LUARCA_USER" "$SRC_DIR/" "$LUARCA_HOME/"

# 5) .env
if [[ ! -f "$LUARCA_HOME/.env" ]]; then
  echo "==> Creando $LUARCA_HOME/.env desde plantilla"
  install -o "$LUARCA_USER" -g "$LUARCA_USER" -m 600 "$SRC_DIR/.env.example" "$LUARCA_HOME/.env"
else
  echo "==> $LUARCA_HOME/.env ya existe (no se sobrescribe)"
fi

# 6) Virtualenv + dependencias
echo "==> Creando virtualenv y instalando dependencias"
sudo -u "$LUARCA_USER" python3 -m venv "$LUARCA_HOME/.venv"
sudo -u "$LUARCA_USER" "$LUARCA_HOME/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$LUARCA_USER" "$LUARCA_HOME/.venv/bin/pip" install --quiet -r "$LUARCA_HOME/requirements.txt"

# 7) systemd units
echo "==> Instalando units de systemd"
TMPDIR_UNITS=$(mktemp -d)
trap 'rm -rf "$TMPDIR_UNITS"' EXIT

for f in "$SRC_DIR"/deploy/systemd/*.service "$SRC_DIR"/deploy/systemd/*.timer; do
  out="$TMPDIR_UNITS/$(basename "$f")"
  sed -e "s|__USER__|$LUARCA_USER|g" \
      -e "s|__HOME__|$LUARCA_HOME|g" \
      -e "s|__PORT__|$LUARCA_PORT|g" \
      "$f" > "$out"
done
install -m 644 "$TMPDIR_UNITS"/*.service /etc/systemd/system/
install -m 644 "$TMPDIR_UNITS"/*.timer   /etc/systemd/system/

systemctl daemon-reload

cat <<EOF

==> Instalación completada.

Siguientes pasos:

  1. Edita $LUARCA_HOME/.env con tus API keys:
       sudo -u $LUARCA_USER \$EDITOR $LUARCA_HOME/.env

  2. (Opcional) Migra la BD existente desde tu máquina local:
       scp ais_luarca.db servidor:/tmp/
       sudo install -o $LUARCA_USER -g $LUARCA_USER -m 644 \\
            /tmp/ais_luarca.db $LUARCA_HOME/ais_luarca.db

  3. Habilita y arranca los servicios:
       sudo systemctl enable --now luarca-ais-collector.service
       sudo systemctl enable --now luarca-ais-visualizer.timer
       sudo systemctl enable --now luarca-ais-web.service

  4. Verifica el estado:
       sudo systemctl status luarca-ais-collector
       sudo journalctl -u luarca-ais-collector -f
       sudo systemctl list-timers luarca-ais-visualizer.timer

  5. Web local en http://127.0.0.1:$LUARCA_PORT/ (montar nginx/caddy
     delante para exponerlo a internet — ver deploy/nginx.example.conf).
EOF
