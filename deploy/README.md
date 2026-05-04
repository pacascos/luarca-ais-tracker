# Despliegue en servidor Linux

Este directorio contiene todo lo necesario para desplegar el stack AIS Luarca
en un servidor Linux con systemd:

- `collector` corriendo 24/7 capturando AIS de aisstream.io
- `visualizer` regenerando los mapas HTML cada 5 minutos
- `web` sirviendo `web/` por HTTP local (puerto 8765, bind a 127.0.0.1)

```
deploy/
├── install.sh                # bootstrap completo (sudo)
├── uninstall.sh              # desinstala (con --purge borra todo)
├── nginx.example.conf        # ejemplo para exponer detrás de nginx + TLS
├── README.md
└── systemd/
    ├── luarca-ais-collector.service
    ├── luarca-ais-visualizer.service
    ├── luarca-ais-visualizer.timer
    └── luarca-ais-web.service
```

## Requisitos del servidor

- Linux con systemd (Ubuntu 22.04+, Debian 12, Rocky/Alma, Fedora…)
- Python 3.11+ con `venv`
- Acceso sudo
- Salida HTTPS hacia `stream.aisstream.io` y `api.vesseltracker.com`

En Ubuntu/Debian:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip rsync
```

## Instalación

```bash
# Clonar el repo en el servidor (o copiarlo con rsync)
git clone https://github.com/pacascos/luarca-ais-tracker.git
cd luarca-ais-tracker

# Lanzar el instalador
sudo ./deploy/install.sh
```

El script crea:
- Usuario de sistema `luarca` con home `/opt/luarca-ais`
- Virtualenv en `/opt/luarca-ais/.venv` con dependencias instaladas
- Units de systemd en `/etc/systemd/system/`
- `/opt/luarca-ais/.env` (a partir de `.env.example`) con permisos `600`

Variables de entorno opcionales antes de lanzar `install.sh`:

| Variable      | Default            | Uso |
|---------------|--------------------|-----|
| `LUARCA_USER` | `luarca`           | usuario que ejecuta los servicios |
| `LUARCA_HOME` | `/opt/luarca-ais`  | directorio raíz del proyecto |
| `LUARCA_PORT` | `8765`             | puerto del servidor estático local |

## Tras instalar

1. **Editar `.env`** con tus credenciales:

   ```bash
   sudo -u luarca $EDITOR /opt/luarca-ais/.env
   ```

   Variables obligatorias:
   - `AISSTREAM_API_KEY` — clave de aisstream.io
   - `VESSELTRACKER_EMAIL`, `VESSELTRACKER_PASSWORD` — solo si vas a usar `vesseltracker.py`

2. **Migrar la BD existente** (opcional pero recomendado para conservar histórico):

   Desde tu máquina local:

   ```bash
   scp ais_luarca.db servidor:/tmp/
   ```

   En el servidor:

   ```bash
   sudo install -o luarca -g luarca -m 644 /tmp/ais_luarca.db /opt/luarca-ais/ais_luarca.db
   sudo rm /tmp/ais_luarca.db
   ```

3. **Habilitar y arrancar los servicios:**

   ```bash
   sudo systemctl enable --now luarca-ais-collector.service
   sudo systemctl enable --now luarca-ais-visualizer.timer
   sudo systemctl enable --now luarca-ais-web.service
   ```

4. **Verificar:**

   ```bash
   # Estado del collector
   sudo systemctl status luarca-ais-collector

   # Logs en tiempo real
   sudo journalctl -u luarca-ais-collector -f

   # Próxima ejecución del timer
   sudo systemctl list-timers luarca-ais-visualizer.timer

   # Probar el sitio web local
   curl -I http://127.0.0.1:8765/
   ```

## Exponer a internet

El servicio web escucha solo en `127.0.0.1`. Para hacerlo público recomiendo
nginx + Let's Encrypt:

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

# Editar y copiar el ejemplo
sudo cp deploy/nginx.example.conf /etc/nginx/sites-available/luarca-ais
sudo $EDITOR /etc/nginx/sites-available/luarca-ais   # cambiar server_name
sudo ln -s /etc/nginx/sites-available/luarca-ais /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Cert HTTPS
sudo certbot --nginx -d ais.tu-dominio.com
```

## Operación

| Acción | Comando |
|---|---|
| Ver logs collector | `sudo journalctl -u luarca-ais-collector -f` |
| Ver logs visualizer | `sudo journalctl -u luarca-ais-visualizer -n 50` |
| Forzar regeneración mapas | `sudo systemctl start luarca-ais-visualizer.service` |
| Reiniciar collector | `sudo systemctl restart luarca-ais-collector` |
| Cambiar cadencia mapas | editar `OnUnitActiveSec` en `luarca-ais-visualizer.timer` |
| Backup BD | `sudo -u luarca cp /opt/luarca-ais/ais_luarca.db /tmp/ais-$(date +%Y%m%d).db` |
| Actualizar código | `git pull && sudo ./deploy/install.sh` (re-copia, no borra .env ni BD) |

## Desinstalar

```bash
# Conservando BD y .env:
sudo ./deploy/uninstall.sh

# Borrándolo todo:
sudo ./deploy/uninstall.sh --purge
```

## Sobre la fiabilidad

- Si el servidor se apaga, systemd rearranca todos los servicios al volver
  (`Restart=always` en collector y web; el timer dispara a los 2 min de boot).
- Si aisstream.io tira la conexión, el collector reconecta solo con backoff
  exponencial (lógica en `collector.py`). Si esto se repite, systemd reinicia
  el proceso entero.
- La BD SQLite usa journal mode por defecto, robusta a `kill -9` pero **no
  a fallo de disco** — programa un backup diario si el dato es crítico:

  ```cron
  # /etc/cron.d/luarca-ais-backup
  0 4 * * * luarca cp /opt/luarca-ais/ais_luarca.db /opt/luarca-ais/backups/ais-$(date +\%Y\%m\%d).db && find /opt/luarca-ais/backups -name 'ais-*.db' -mtime +14 -delete
  ```
