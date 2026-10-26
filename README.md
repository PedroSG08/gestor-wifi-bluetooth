# gestor-conexiones

Gestor de **Wi-Fi** y **Bluetooth** para Linux.

Todo el programa es **un único fichero en Python** sin dependencias externas
(más allá de las ya típicas de un escritorio Linux: NetworkManager y BlueZ).

```
╔═[ Gestor de conexiones ]══════════════╗
│                                       │
│      Selecciona una opción:           │
│                                       │
│  ▸ Wi-Fi                              │
│    mediante nmcli                     │
│    Bluetooth                          │
│    mediante bluetoothctl              │
│    Salir                              │
│                                       │
│  ↑/↓ Elegir · Enter · Esc Salir       │
╚═══════════════════════════════════════╝
```

## Características

- Menú inicial con dos secciones: **Wi-Fi** (NetworkManager) y
  **Bluetooth** (BlueZ).
- Escaneo en segundo plano (la interfaz no se congela) con caja de espera y
  spinner, al estilo de un greeter.
- Lista de redes Wi-Fi ordenada por señal, con barra de intensidad
  (`▂▄▆█`), indicador `●` si la red está protegida y marcador verde
  `▸` para la red en uso. Se detecta si la red necesita contraseña.
- Pantalla de contraseña oculta con `*` (la tecla `Tab` la muestra) y
  reintento automático si la contraseña es incorrecta.
- Soporte de **redes ocultas** (`n`): pide el SSID y luego la contraseña.
- Bluetooth: enciende el adaptador si está apagado, empareja (`pair`) +
  confía (`trust`) + conecta (`connect`) en un solo paso. Sobre un
  dispositivo ya conectado, `Enter` lo desconecta.
- Mensajes de éxito/error tras cada operación, con opción de reintentar.
- **Contraseñas guardadas** (opcional): con `✓` verde en el listado, en un
  fichero propio con permisos `600`, y gestión (`e`/`d`) desde el listado.
- Funciona igual en TTY, por SSH o dentro de un terminal gráfico; no
  necesita entorno gráfico.

## Requisitos

| Componente   | Uso                     | Arch                     | Debian/Ubuntu         | Fedora            |
|--------------|-------------------------|--------------------------|-----------------------|-------------------|
| Python ≥ 3.7 | Interfaz (curses)       | `python`                 | `python3`             | `python3`         |
| NetworkManager | Wi-Fi                 | `networkmanager`         | `network-manager`     | `NetworkManager`  |
| BlueZ        | Bluetooth               | `bluez` + `bluez-utils`  | `bluez`               | `bluez`           |

En la mayoría de escritorios ya están instalados y con los servicios
`NetworkManager` y `bluetooth` activos:

```bash
systemctl is-active NetworkManager bluetooth
```

## Instalación

El programa es un solo script: `gestor-conexiones.py`. Solo hay que dejarlo
en algún punto del `PATH`.

**Opción A — para todos los usuarios (recomendada, con sudo):**

```bash
git clone https://github.com/PedroSG08/gestor-conexiones.git
cd gestor-conexiones
sudo install -Dm 755 gestor-conexiones.py /usr/local/bin/gestor-conexiones
```

**Opción B — solo tu usuario (`~/.local/bin`):**

```bash
git clone https://github.com/PedroSG08/gestor-conexiones.git
cd gestor-conexiones
mkdir -p ~/.local/bin
install -m 755 gestor-conexiones.py ~/.local/bin/gestor-conexiones
```

Asegúrate de que `~/.local/bin` está en tu `PATH` (la mayoría de distros lo
añaden por defecto en el perfil de la shell; si no, añádelo a `~/.profile`
o `~/.bashrc`):

```bash
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *) export PATH="$HOME/.local/bin:$PATH" ;; esac
```

**Sin instalar nada:** basta con ejecutarlo desde la carpeta:

```bash
python3 gestor-conexiones.py
```

## Uso

```bash
gestor-conexiones
```

| Tecla          | Acción                                            |
|----------------|---------------------------------------------------|
| `↑/↓` o `j/k`  | Mover la selección                                |
| `Enter`        | Abrir sección / conectar / desconectar / aceptar  |
| `r`            | Reescanear redes o dispositivos                   |
| `n`            | Añadir una red oculta (Wi-Fi)                     |
| `Tab`          | Mostrar/ocultar la contraseña                     |
| `g`            | Guardar / no guardar la contraseña (pantalla de contraseña) |
| `e`            | Registrar o cambiar la contraseña de una red (Wi-Fi) |
| `d`            | Borrar la contraseña guardada de una red (Wi-Fi)  |
| `Ctrl+U`       | Borrar todo lo escrito                            |
| `Esc` o `q`    | Atrás (en el menú principal, `Esc` sale)          |
| `Ctrl+C`       | Salir del programa                                |

**Flujo normal:** `Enter` sobre *Wi-Fi* o *Bluetooth* → escaneo → elegir un
elemento → contraseña si hace falta → mensaje de resultado. Si la conexión
falla (p. ej. contraseña incorrecta), el programa ofrece reintentarla.

### Contraseñas guardadas

Al escribir la contraseña aparece la opción **`[g] Guardar: Sí/No`**
(activada por defecto). Tras conectar con éxito:

- **Sí**: la contraseña se guarda en
  `~/.config/gestor-conexiones/contrasenas.json` (JSON con permisos `600`,
  legible solo por tu usuario) y la red queda marcada con una **`✓`**
  verde en el listado. Además el perfil de NetworkManager conserva el
  PSK, de modo que las siguientes conexiones ni siquiera la pediran.
- **No**: se olvida la copia del programa y el perfil de NetworkManager
  se configura para no conservarla (`psk-flags 2`), así que la próxima
  vez se pedirá de nuevo. Es *mejor esfuerzo*: por SSH, sin sesión
  gráfica (polkit), NetworkManager puede denegar el cambio.

Gestión desde el listado de Wi-Fi:

| Tecla | Acción                                        |
|-------|-----------------------------------------------|
| `e`   | Registrar o cambiar la contraseña a mano      |
| `d`   | Borrar la contraseña guardada de la red       |

> **Nota de seguridad**: las contraseñas se guardan **en claro**, igual
> que lo hacen los perfiles de NetworkManager (en
> `/etc/NetworkManager/system-connections/`, legibles solo por root). El
> programa crea el fichero con `chmod 600`; no lo compartas ni lo
> sincronices sin cifrar.

## Integración con Hyprland (opcional)

Añade un atajo de teclado con la **ruta absoluta** (una sesión gráfica no
siempre hereda el `PATH` de `~/.local/bin`, y evita errores tipo
`Failed to launch child: ... No existe el fichero o el directorio`):

```lua
local conexion = "kitty -e /usr/local/bin/gestor-conexiones"   -- ruta absoluta: sin depender del PATH
-- si instalaste en ~/.local/bin: "kitty -e /home/USUARIO/.local/bin/gestor-conexiones"
hl.bind(mainMod .. " + B", hl.dsp.exec_cmd(conexion))
```

Tras editarlo: `hyprctl reload`.

## Desinstalación

Según la vía de instalación usada:

```bash
# Opción A (global)
sudo rm /usr/local/bin/gestor-conexiones

# Opción B (usuario)
rm ~/.local/bin/gestor-conexiones
```

Otras cosas que puede que hayas añadido y quieras retirar:

```bash
rm -rf ~/gestor-conexiones                      # el repositorio clonado (README + script)
sudo systemctl disable --now gestor-conexiones  # si creaste el servicio systemd
sudo rm /etc/systemd/system/gestor-conexiones.service
rm -rf ~/.config/gestor-conexiones              # almacén local de contraseñas
```

El atajo de `SUPER + B` de Hyprland se elimina borrando las dos líneas del
apartado anterior en `~/.config/hypr/hyprland.lua` y recargando con
`hyprctl reload`.

## Solución de problemas

- **Bluetooth no empareja / "acceso denegado"**: prueba con permisos de
  root (`sudo gestor-conexiones`) o desbloquea el hardware con
  `sudo rfkill unblock bluetooth`. El servicio debe estar activo:
  `sudo systemctl start bluetooth`.
- **Wi-Fi no aparece nada**: comprueba `nmcli device` (debe existir una
  interfaz `wifi`) y que no estés en modo bloqueado por rfkill. Si lanzas
  el programa por SSH, NetworkManager puede denegar la operación al no
  haber sesión de polkit: ejecuta entonces con `sudo`.
- **Error del atajo de teclado en Hyprland** (`Failed to launch child`):
  casi siempre es un nombre mal escrito o una ruta relativa; usa la ruta
  absoluta del script como en el ejemplo anterior.
- **"Terminal demasiado pequeña"**: agranda la ventana; el programa pide
  unas 16 líneas × 60 columnas.
- **Exit code / colores raros en ciertos TTY**: usa un terminal con UTF-8
  activo (`locale -s` debe mostrar `es_ES.UTF-8` o similar).

## Cómo funciona por dentro

- Un único fichero con curses (librería estándar de Python), sin dependencias
  externas.
- Escaneo y conexiones se ejecutan en **hilos separados**: la interfaz
  muestra una caja de espera con spinner y queda completamente fluida.
- **Wi-Fi**: `nmcli` en modo *terse* (`IN-USE,SIGNAL,SECURITY,SSID`) con un
  parser propio que soporta SSIDs con `:` escapados; la conexión se hace con
  `nmcli device wifi connect [password …]` (y `hidden yes` para redes
  ocultas).
- **Bluetooth**: `bluetoothctl`; listado de dispositivos conocidos con su
  estado real (`info`). Para conectar envía a una sesión de `bluetoothctl`
  el agente `NoInputNoOutput` (emparejamiento *Just Works*) seguido de
  `pair` + `trust` + `connect`.
- Estados de la interfaz (`menu → lista → contraseña → mensaje`) con un
  recinto de navegación por teclado estilo ly: caja doble centrada,
  selección con vídeo inverso y colores tenues (cian, verde, rojo).
- **Contraseñas guardadas**: JSON en `~/.config/gestor-conexiones/`
  (permisos `600`, escritura atómica). El conmutador «Guardar» ajusta
  también el perfil de NetworkManager
  (`802-11-wireless-security.psk-flags`: `0` guardada / `2` pedir cada vez).

## Licencia

Distribuido bajo licencia **MIT** (añade un fichero `LICENSE` con el texto
correspondiente antes de publicar).
