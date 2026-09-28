# Despliegue en macOS (launchd)

Monta el stack completo en un Mac que esté siempre encendido: collector
24/7, regeneración de mapas cada 5 minutos y servidor web para la LAN.
Todo corre como tu usuario mediante LaunchAgents, sin `sudo`.

```
aisstream.io ──▶ collector.py ─┐
                               ├─▶ ais_luarca.db ──▶ visualizer.py ──▶ ~/luarca-ais-web/ ──▶ http.server :8765
VesselTracker ─▶ vt_poller.py ─┘   (en el clon)     (LaunchAgent,      (fuera del clon,      (LaunchAgent)
(antena propia)  (cada 2 min)                        cada 5 min)        WEB_DIR en .env)
```

## Instalación

```bash
# 1. Clonar (o entrar en el clon existente)
git clone https://github.com/pacascos/luarca-ais-tracker.git ~/code/AIS
cd ~/code/AIS

# 2. (Opcional) Traer la base de datos del Mac que recogía hasta ahora.
#    Hazlo ANTES de instalar, con el collector del otro Mac parado.
#    Desde el otro Mac:
#      scp ~/code/AIS/ais_luarca.db este-mac.local:~/code/AIS/

# 3. Instalar: crea .venv, .env, migra la BD si existe, instala y
#    arranca los tres agentes. Si .env no tiene la API key, se para
#    antes de arrancar y te lo dice.
./deploy/macos/install.sh

# 4. Poner la API key y volver a lanzar
nano .env                       # AISSTREAM_API_KEY=...
./deploy/macos/install.sh

# 5. Comprobar
tail -f logs/collector.log      # "Primer mensaje recibido (SubscriptionConfirmation)"
open http://localhost:8765/
```

Desde cualquier dispositivo de la casa: `http://<ip-o-nombre-del-mac>:8765/`.

## Que el Mac no se duerma

Un LaunchAgent solo corre con la sesión de usuario abierta y el Mac
despierto. Para un servidor doméstico:

```bash
sudo pmset -a sleep 0 disksleep 0 displaysleep 10
```

y en Ajustes del Sistema, Usuarios y grupos, activa el inicio de sesión
automático para que los agentes vuelvan solos tras un reinicio.

## Actualizar el código

```bash
cd ~/code/AIS
git pull
./deploy/macos/install.sh       # reinstala plists, reinicia servicios, migra BD si hace falta
```

Los mapas se escriben en `WEB_DIR` (por defecto `~/luarca-ais-web`), no en
`web/` del clon, así `git pull` nunca choca con HTML regenerados.

## Operación

| Acción | Comando |
|---|---|
| Estado | `launchctl list \| grep com.luarca.ais` (segunda columna: 0 = ok) |
| Logs collector | `tail -f logs/collector.log` |
| Logs mapas | `tail -f logs/visualizer.log` |
| Reiniciar collector | `launchctl kickstart -k gui/$UID/com.luarca.ais.collector` |
| Logs VesselTracker | `tail -f logs/vt_poller.log` |
| Regenerar mapas ya | `launchctl kickstart gui/$UID/com.luarca.ais.visualizer` |
| Parar todo | `./deploy/macos/uninstall.sh` |
| Informe por consola | `.venv/bin/python analyzer.py --days 30` |
| Backup BD | `sqlite3 ais_luarca.db ".backup dumps/ais-$(date +%Y%m%d).db"` |

Los logs no rotan solos. El del collector crece unos 30 KB al día; si molesta,
vacíalo de vez en cuando con `: > logs/collector.log` (el proceso sigue
escribiendo sin problema).

## Publicar fuera de la LAN

`http.server` no está pensado para exponerlo a internet. Opciones sencillas:

- **Tailscale** en el Mac y en tus dispositivos: acceso privado desde
  cualquier sitio sin abrir puertos.
- **Cloudflare Tunnel** (`cloudflared`) apuntando a `localhost:8765` si
  quieres una URL pública.
- **GitHub Pages** sigue funcionando como espejo estático: copia los HTML de
  `WEB_DIR` a `web/` del clon y haz commit + push cuando quieras publicar.
