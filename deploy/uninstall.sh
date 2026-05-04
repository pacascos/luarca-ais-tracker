#!/usr/bin/env bash
# Desinstala el stack AIS Luarca. NO borra la BD por defecto (ver --purge).
#
# Uso:
#   sudo ./uninstall.sh           # quita servicios y código pero conserva BD
#   sudo ./uninstall.sh --purge   # también borra usuario, home y BD

set -euo pipefail

LUARCA_USER="${LUARCA_USER:-luarca}"
LUARCA_HOME="${LUARCA_HOME:-/opt/luarca-ais}"
PURGE=0

if [[ "${1:-}" == "--purge" ]]; then
  PURGE=1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Ejecuta como root (sudo $0)" >&2
  exit 1
fi

echo "==> Parando y deshabilitando servicios"
for unit in luarca-ais-collector.service luarca-ais-visualizer.timer luarca-ais-visualizer.service luarca-ais-web.service; do
  systemctl disable --now "$unit" 2>/dev/null || true
done

echo "==> Eliminando units"
for unit in luarca-ais-collector.service luarca-ais-visualizer.service luarca-ais-visualizer.timer luarca-ais-web.service; do
  rm -f "/etc/systemd/system/$unit"
done
systemctl daemon-reload

if [[ $PURGE -eq 1 ]]; then
  echo "==> Purgando $LUARCA_HOME y usuario $LUARCA_USER"
  rm -rf "$LUARCA_HOME"
  if id -u "$LUARCA_USER" >/dev/null 2>&1; then
    userdel "$LUARCA_USER" || true
  fi
else
  echo "==> Conservando $LUARCA_HOME (incluida la BD). Usa --purge para borrar."
fi

echo "==> Hecho."
