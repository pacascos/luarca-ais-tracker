#!/usr/bin/env bash
# Para y elimina los LaunchAgents de AIS Luarca. No borra código, .env ni BD.
set -euo pipefail
AGENTS_DIR="$HOME/Library/LaunchAgents"
for label in com.luarca.ais.collector com.luarca.ais.visualizer com.luarca.ais.web; do
  launchctl bootout "gui/$UID/$label" 2>/dev/null || true
  rm -f "$AGENTS_DIR/$label.plist"
  echo "eliminado $label"
done
