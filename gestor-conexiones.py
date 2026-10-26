#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gestor-conexiones — Gestor Wi-Fi / Bluetooth a pantalla completa, por teclado,
con una estética inspirada en ly-greeter (caja centrada sobre fondo oscuro,
navegación con flechas, mensajes de error en rojo).

Backends
  Wi-Fi      : NetworkManager  (nmcli)
  Bluetooth  : BlueZ           (bluetoothctl)

Ejecución
  python3 gestor-conexiones.py     ·     ./gestor-conexiones.py

Teclas
  ↑/↓ · j/k    moverse               Enter    elegir / conectar / aceptar
  r            reescanear            n        añadir red oculta (solo Wi-Fi)
  e            registrar/cambiar la contraseña de una red (Wi-Fi)
  d            borrar la contraseña guardada de una red (Wi-Fi)
  g            guardar o no la contraseña que se está escribiendo
  Tab          mostrar/ocultar la contraseña
  Esc / q      atrás (en el menú, Esc sale)
  Ctrl+C       salir

Las contraseñas guardadas se almacenan en
~/.config/gestor-conexiones/contrasenas.json (permisos 600).
"""
from __future__ import annotations

import curses
import json
import locale
import os
import shutil
import subprocess
import threading
import time

# ----------------------------------------------------------------------------
# Constantes de presentación
# ----------------------------------------------------------------------------
CP_NORM, CP_ACC, CP_OK, CP_ERR, CP_WARN = 1, 2, 3, 4, 5
MIN_ROWS, MIN_COLS = 16, 62
SPIN = "|/-\\"
BARS = ((70, "█"), (45, "▆"), (20, "▄"), (0, "▂"))

# Almacén local de contraseñas guardadas (chmod 600)
CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".config", "gestor-conexiones")
PW_FILE = os.path.join(CONFIG_DIR, "contrasenas.json")


def load_passwords():
    """Lee el diccionario ssid → contraseña ({}, si no existe)."""
    try:
        with open(PW_FILE, "r", encoding="utf-8") as fh:
            data = json.load(fh)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items()}
    except (OSError, ValueError):
        pass
    return {}


def save_passwords(pw):
    """Escribe el almacén de contraseñas con permisos 600 (atómico)."""
    try:
        os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
        tmp = PW_FILE + ".tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(pw, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, PW_FILE)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Utilidades de sistema
# ----------------------------------------------------------------------------
def run(cmd, timeout=20, input_text=None):
    """Ejecuta un comando y devuelve (rc, salida combinada stdout+stderr)."""
    try:
        p = subprocess.run(cmd, input=input_text, capture_output=True,
                           text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, f"{cmd[0]}: no se encontró el comando"
    except subprocess.TimeoutExpired:
        return 124, f"{cmd[0]}: tiempo agotado"


def split_terse(line):
    """Divide una línea terse de nmcli respetando ':' escapados con '\\\\'."""
    parts, cur, esc = [], [], False
    for ch in line:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return parts


def trunc(s, n):
    return s if len(s) <= n else s[: max(n - 1, 1)] + "…"


def tail(text, n=3):
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    q = " · ".join(lines[-n:]).strip()
    return trunc(q, 90)


def wrap(text, w, limit=4):
    """Ajusta un texto a un ancho, devolviendo como mucho `limit` líneas."""
    lines, cur = [], ""
    for word in str(text).split():
        cand = (cur + " " + word).strip()
        if len(cand) <= w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = trunc(word, w)
    if cur:
        lines.append(cur)
    if len(lines) > limit:
        lines = lines[:limit]
        lines[-1] = trunc(lines[-1], w - 1) + "…"
    return lines or [""]


def sig_bar(sig):
    for minimo, ch in BARS:
        if sig >= minimo:
            return ch
    return " "


def A(color, extra=0):
    return curses.color_pair(color) | extra


# ----------------------------------------------------------------------------
# Backend Wi-Fi (NetworkManager / nmcli)
# ----------------------------------------------------------------------------
class WiFiBackend:
    name = "Wi-Fi"

    def __init__(self):
        self.available = shutil.which("nmcli") is not None

    def scan(self):
        """Reescanea y devuelve ([redes], error)."""
        run(["nmcli", "device", "wifi", "rescan"], timeout=10)
        time.sleep(1.5)
        return self.list()

    def list(self):
        entries, err = [], ""
        rc, out = run(["nmcli", "-t", "-f",
                       "IN-USE,SIGNAL,SECURITY,SSID", "device", "wifi"],
                      timeout=20)
        if rc != 0:
            err = tail(out, 2)
        seen = {}
        for line in out.splitlines():
            f = split_terse(line)
            if len(f) < 4:
                continue
            try:
                signal = int(f[1])
            except ValueError:
                signal = 0
            ssid, security = f[3], f[2].strip()
            if not ssid:
                continue
            e = {"ssid": ssid, "signal": max(0, min(100, signal)),
                 "secured": security not in ("", "--"),
                 "in_use": f[0] == "*", "hidden": False}
            prev = seen.get(ssid)
            if prev is None or (not prev["in_use"]
                                and (e["in_use"] or e["signal"] > prev["signal"])):
                seen[ssid] = e
        entries = sorted(seen.values(),
                         key=lambda e: (not e["in_use"], -e["signal"],
                                        e["ssid"].lower()))
        return entries, err

    def connect(self, ssid, password=None, hidden=False):
        cmd = ["nmcli", "--wait", "45", "device", "wifi", "connect", ssid]
        if password:
            cmd += ["password", password]
        if hidden:
            cmd += ["hidden", "yes"]
        rc, out = run(cmd, timeout=70)
        if rc == 0:
            return {"ok": True, "msg": f"Conectado a «{ssid}»", "need_secret": False}
        err = tail(out, 3) or "No se pudo conectar"
        # P. ej.: "(7) Secrets were required, but not provided."
        necesita = "secret" in out.lower()
        return {"ok": False, "msg": err, "need_secret": necesita}


# ----------------------------------------------------------------------------
# Backend Bluetooth (BlueZ / bluetoothctl)
# ----------------------------------------------------------------------------
class BluetoothBackend:
    name = "Bluetooth"

    def __init__(self):
        self.available = shutil.which("bluetoothctl") is not None

    def _ctl(self, *args, timeout=15):
        return run(["bluetoothctl", *args], timeout=timeout)

    def _power_on(self):
        _, out = self._ctl("show")
        if "Powered: no" in out:
            self._ctl("power", "on")

    def _parse_devices(self, out):
        devs, seen = [], set()
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("Device "):
                rest = line[7:]
                mac, _, name = rest.partition(" ")
                mac = mac.strip()
                if mac and mac not in seen:
                    seen.add(mac)
                    devs.append((mac, name.strip() or mac))
        return devs

    def scan(self):
        self._power_on()
        self._ctl("--timeout", "6", "scan", "on", timeout=12)
        return self.list()

    def list(self):
        _, out = self._ctl("devices")
        if "No default controller" in out:
            return [], "Sin adaptador Bluetooth disponible (revisa hardware o permisos)"
        entries = []
        for mac, name in self._parse_devices(out):
            info = self._ctl("info", mac)[1]
            paired = "Paired: yes" in info
            connected = "Connected: yes" in info
            state = "conectado" if connected else (
                "emparejado" if paired else "descubierto")
            entries.append({"mac": mac, "name": name, "paired": paired,
                            "connected": connected, "state": state})
        entries.sort(key=lambda d: (not d["connected"], not d["paired"],
                                    d["name"].lower()))
        return entries, ""

    def connect(self, d):
        self._power_on()
        mac = d["mac"]
        script = "agent NoInputNoOutput\ndefault-agent\n"
        if not d["paired"]:
            script += f"pair {mac}\n"
        script += f"trust {mac}\nconnect {mac}\nexit\n"
        rc, out = run(["bluetoothctl"], timeout=50, input_text=script)
        if "Connection successful" in out:
            return {"ok": True, "msg": f"Conectado a «{d['name']}»"}
        msg = tail(out, 2)
        if "Failed to connect:" in msg:
            msg = "Fallo al conectar: " + msg.split("Failed to connect:")[-1]
        elif "Failed to pair" in msg:
            msg = "Fallo al emparejar: " + msg.split("Failed to pair")[-1].lstrip(": ")
        return {"ok": False, "msg": msg or "No se pudo conectar"}

    def disconnect(self, d):
        rc, out = self._ctl("disconnect", d["mac"], timeout=20)
        if "Successfully disconnected" in out:
            return {"ok": True, "msg": f"Desconectado «{d['name']}»"}
        return {"ok": False, "msg": tail(out, 2) or "No se pudo desconectar"}


# ----------------------------------------------------------------------------
# Interfaz (curses, estilo ly)
# ----------------------------------------------------------------------------
class App:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.backends = {"wifi": WiFiBackend(), "bt": BluetoothBackend()}
        self.state = "menu"
        self.done = False
        self.menu_sel = 0
        self.menu_items = ({"kind": "wifi", "label": "Wi-Fi"},
                           {"kind": "bt", "label": "Bluetooth"},
                           {"kind": "quit", "label": "Salir"})
        self.kind = "wifi"
        self.entries, self.list_err, self.sel = [], "", 0
        self.job, self.on_done, self.frame = None, None, 0
        self.msg, self.msg_back = None, "menu"
        self.input_mode, self.buffer, self.hidden = "password", "", True
        self.target = None
        self.passwords = load_passwords()
        self.save_pw = True
        self.pw_lock = threading.Lock()
        self._init_colors()
        stdscr.keypad(True)
        stdscr.timeout(100)
        curses.noecho()
        try:
            curses.curs_set(0)
        except curses.error:
            pass

    def _init_colors(self):
        curses.start_color()
        try:
            curses.use_default_colors()
            bg = -1
        except curses.error:
            bg = curses.COLOR_BLACK
        for pair, fg in ((CP_NORM, curses.COLOR_WHITE),
                         (CP_ACC, curses.COLOR_CYAN),
                         (CP_OK, curses.COLOR_GREEN),
                         (CP_ERR, curses.COLOR_RED),
                         (CP_WARN, curses.COLOR_YELLOW)):
            curses.init_pair(pair, fg, bg)

    # ------------------------------------------------------------------ bucle
    def run(self):
        while not self.done:
            self.pump()
            self.draw()
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                break
            if key == curses.KEY_RESIZE:
                self.stdscr.erase()
                continue
            if self.job:
                continue  # ignorar teclado mientras hay trabajo en curso
            self.dispatch(key)

    def dispatch(self, key):
        if self.state == "menu":
            self.key_menu(key)
        elif self.state in ("wifi", "bt"):
            self.key_list(key)
        elif self.state == "input":
            self.key_input(key)
        elif self.state == "msg":
            self.key_msg(key)

    # ------------------------------------------------- trabajo en 2º plano
    def start_job(self, text, fn, on_done):
        self.on_done = on_done
        self.job = {"text": text, "result": None, "done": False}

        def worker():
            try:
                res = fn()
            except Exception as ex:               # por si algo explota
                res = {"ok": False, "msg": str(ex), "need_secret": False,
                       "entries": [], "err": str(ex)}
            self.job["result"] = res
            self.job["done"] = True

        threading.Thread(target=worker, daemon=True).start()

    def pump(self):
        if self.job and self.job["done"]:
            res, cb = self.job["result"], self.on_done
            self.job = None
            self.on_done = None
            if cb:
                cb(res)

    # ------------------------------------------------------------ acciones
    def menu_pick(self):
        kind = self.menu_items[self.menu_sel]["kind"]
        if kind == "quit":
            self.done = True
        else:
            self.open_list(kind)

    def open_list(self, kind):
        b = self.backends[kind]
        if not b.available:
            falta = "nmcli (NetworkManager)" if kind == "wifi" else "bluetoothctl (BlueZ)"
            self.show("err", f"{b.name} no está disponible: falta {falta}.")
            return
        self.kind = self.state = kind
        self.entries, self.list_err, self.sel = [], "", 0
        self.refresh(kind)

    def refresh(self, kind):
        b = self.backends[kind]

        def fn():
            entries, err = b.scan()
            return {"entries": entries, "err": err}

        self.start_job(f"Escaneando {b.name} …", fn, self.after_scan)

    def after_scan(self, res):
        self.entries = res["entries"]
        self.list_err = res["err"]
        if self.sel >= len(self.entries):
            self.sel = max(0, len(self.entries) - 1)

    def pick_entry(self):
        if not self.entries:
            return
        e = self.entries[self.sel]
        if self.kind == "wifi":
            if e["in_use"]:
                self.show("ok", f"Ya estás conectado a «{e['ssid']}»")
            else:
                # Primer intento sin pedir contraseña: si NM ya conserva el
                # PSK conectará directamente; si no, saltará la contraseña.
                self.start_wifi_connect(e)
        else:
            self.start_bt_action(e, disconnect=e["connected"])

    def start_wifi_connect(self, e, password=None):
        ssid = e["ssid"]
        guardar = self.save_pw and bool(password)

        def fn():
            res = self.backends["wifi"].connect(ssid, password,
                                                e.get("hidden", False))
            if res["ok"] and password:
                with self.pw_lock:
                    self.passwords.pop(ssid, None)
                    if guardar:
                        self.passwords[ssid] = password
                    save_passwords(self.passwords)
                self.apply_nm_psk_policy(ssid, keep=guardar)
            return res

        def done(res):
            if res["ok"]:
                extra = ""
                if password:
                    extra = (" · contraseña guardada" if guardar
                             else " · sin guardar contraseña")
                self.show("ok", res["msg"] + extra, refresh=True)
            elif res["need_secret"] and password is None:
                self.open_input("password",
                                {"ssid": ssid, "hidden": e.get("hidden", False)})
            else:
                self.show("err", res["msg"], retry=True)

        self.start_job(f"Conectando a «{ssid}» …", fn, done)

    def forget_password(self, e):
        ssid = e["ssid"]

        def fn():
            with self.pw_lock:
                self.passwords.pop(ssid, None)
                save_passwords(self.passwords)
            self.apply_nm_psk_policy(ssid, keep=False)
            return {"ok": True, "msg": f"Se borró la contraseña guardada de «{ssid}»"}

        self.start_job(f"Borrando la contraseña de «{ssid}»…", fn,
                       lambda r: self.show("ok" if r["ok"] else "err", r["msg"]))

    def apply_nm_psk_policy(self, ssid, keep):
        """Mejor esfuerzo: el perfil de NM conserva (flags 0) o no (flags 2) el PSK."""
        rc, out = run(["nmcli", "-t", "-f", "NAME,SSID", "connection", "show"],
                      timeout=10)
        if rc != 0:
            return
        for line in out.splitlines():
            parts = split_terse(line)
            if len(parts) == 2 and parts[1] == ssid:
                run(["nmcli", "connection", "modify", parts[0],
                     "802-11-wireless-security.psk-flags",
                     "0" if keep else "2"], timeout=10)
                return

    def start_bt_action(self, e, disconnect=False):
        b = self.backends["bt"]
        fn = (lambda: b.disconnect(e)) if disconnect else (lambda: b.connect(e))
        verbo = "Desconectando" if disconnect else "Conectando"

        def done(res):
            self.show("ok" if res["ok"] else "err", res["msg"], refresh=True)

        self.start_job(f"{verbo} «{e['name']}» …", fn, done)

    def open_input(self, mode, target=None):
        self.input_mode = mode
        if target is not None:
            self.target = target
        self.buffer = ""
        self.hidden = mode == "password"
        self.state = "input"

    def show(self, kind, text, retry=False, refresh=False):
        if self.state in ("wifi", "bt"):
            back = self.state
        elif self.state == "input" and self.kind in ("wifi", "bt"):
            back = self.kind
        elif self.state == "menu":
            back = "menu"
        else:
            back = self.msg_back
        self.msg_back = back
        self.msg = {"kind": kind, "text": text, "retry": retry, "refresh": refresh}
        self.state = "msg"

    # --------------------------------------------------------------- teclas
    def key_menu(self, key):
        n = len(self.menu_items)
        if key in (curses.KEY_UP, curses.KEY_BTAB, ord("k")):
            self.menu_sel = (self.menu_sel - 1) % n
        elif key in (curses.KEY_DOWN, ord("j")):
            self.menu_sel = (self.menu_sel + 1) % n
        elif key in (curses.KEY_ENTER, 10, 13):
            self.menu_pick()
        elif key in (27, ord("q"), 4):            # Esc, q, Ctrl-D
            self.done = True

    def key_list(self, key):
        n = len(self.entries)
        if key in (curses.KEY_UP, ord("k")):
            self.sel = (self.sel - 1) % n if n else 0
        elif key in (curses.KEY_DOWN, ord("j")):
            self.sel = (self.sel + 1) % n if n else 0
        elif key in (curses.KEY_ENTER, 10, 13):
            self.pick_entry()
        elif key == ord("r"):
            self.refresh(self.kind)
        elif key == ord("n") and self.kind == "wifi":
            self.open_input("ssid")
        elif key == ord("e") and self.kind == "wifi" and self.entries:
            e = self.entries[self.sel]
            self.open_input("password", {"ssid": e["ssid"],
                                         "hidden": e.get("hidden", False)})
        elif key == ord("d") and self.kind == "wifi" and self.entries:
            e = self.entries[self.sel]
            if self.passwords.get(e["ssid"]):
                self.forget_password(e)
            else:
                self.show("ok", f"«{e['ssid']}» no tiene contraseña guardada aquí")
        elif key in (27, curses.KEY_LEFT, ord("q")):
            self.state = "menu"

    def key_input(self, key):
        if key in (curses.KEY_ENTER, 10, 13):
            if self.input_mode == "ssid":
                if self.buffer.strip():
                    self.open_input("password",
                                    {"ssid": self.buffer.strip(), "hidden": True})
            else:
                self.start_wifi_connect(self.target, self.buffer)
        elif key == ord("g") and self.input_mode == "password":
            self.save_pw = not self.save_pw
        elif key in (curses.KEY_BACKSPACE, 263, 8, 127):
            self.buffer = self.buffer[:-1]
        elif key == 9:                            # Tab: mostrar/ocultar
            self.hidden = not self.hidden
        elif key == 21:                           # Ctrl-U: borra todo
            self.buffer = ""
        elif key in (27,):                        # Esc
            self.state = self.kind if self.kind in ("wifi", "bt") else "menu"
        elif 32 <= key < 256:
            if len(self.buffer) < 128:
                self.buffer += chr(key)

    def key_msg(self, key):
        m = self.msg
        if key in (curses.KEY_ENTER, 10, 13):
            if m["retry"]:
                self.open_input("password", self.target)
            else:
                self.state = self.msg_back
                if self.state in ("wifi", "bt") and m["refresh"]:
                    self.refresh(self.state)
        elif key in (27, ord("q")):
            self.state = self.msg_back
            if self.state in ("wifi", "bt") and m["refresh"]:
                self.refresh(self.state)

    #                                                                dibujo
    def draw(self):
        s = self.stdscr
        rows, cols = s.getmaxyx()
        s.erase()
        if self.job:
            self.frame += 1
        if rows < MIN_ROWS or cols < MIN_COLS:
            msg = "Terminal demasiado pequeña…"
            try:
                s.addstr(max(0, rows // 2), max(0, (cols - len(msg)) // 2), msg,
                         A(CP_ERR, curses.A_BOLD))
            except curses.error:
                pass
        else:
            {
                "menu": self.draw_menu,
                "wifi": self.draw_list,
                "bt": self.draw_list,
                "input": self.draw_input,
                "msg": self.draw_msg,
            }[self.state](rows, cols)
            if self.job:
                self.draw_busy(rows, cols)
        s.refresh()

    def put(self, y, x, text, a=0):
        try:
            self.stdscr.addstr(y, x, text, a)
        except curses.error:
            pass

    def centre(self, r, text, w, x, a=0):
        self.put(r, x + max(0, (w - len(text)) // 2), text, a)

    def box(self, y, x, h, w, title="", col=CP_ACC):
        s = self.stdscr
        a = A(col, curses.A_BOLD)
        s.addch(y, x, curses.ACS_ULCORNER, a)
        s.addch(y, x + w - 1, curses.ACS_URCORNER, a)
        s.addch(y + h - 1, x, curses.ACS_LLCORNER, a)
        s.addch(y + h - 1, x + w - 1, curses.ACS_LRCORNER, a)
        s.hline(y, x + 1, curses.ACS_HLINE, w - 2, a)
        s.hline(y + h - 1, x + 1, curses.ACS_HLINE, w - 2, a)
        for i in range(1, h - 1):
            s.addch(y + i, x, curses.ACS_VLINE, a)
            s.addch(y + i, x + w - 1, curses.ACS_VLINE, a)
        if title:
            t = trunc(title, w - 6)
            self.put(y, max(x + 1, x + (w - len(t)) // 2), t, a)

    def draw_menu(self, rows, cols):
        bw, bh = 52, 12
        y, x = (rows - bh) // 2, (cols - bw) // 2
        self.box(y, x, bh, bw, " Gestor de conexiones ")
        self.centre(y + 2, "Selecciona una opción:", bw, x, A(CP_NORM, curses.A_BOLD))
        r = y + 4
        for i, it in enumerate(self.menu_items):
            marca = "▸ " if i == self.menu_sel else "  "
            if i == self.menu_sel:
                self.put(r, x + 2, marca + it["label"],
                         A(CP_ACC, curses.A_BOLD | curses.A_REVERSE))
            else:
                self.put(r, x + 2, marca + it["label"], A(CP_NORM))
            b = self.backends.get(it["kind"])
            if b:
                if b.available:
                    sub = "mediante nmcli" if it["kind"] == "wifi" else "mediante bluetoothctl"
                    self.put(r + 1, x + 4, trunc(sub, bw - 8), A(CP_NORM, curses.A_DIM))
                else:
                    sub = "no disponible en este sistema"
                    self.put(r + 1, x + 4, trunc(sub, bw - 8), A(CP_ERR))
            r += 2
        self.put(y + bh - 2, x + 2, trunc("↑/↓ Elegir · Enter Seleccionar · Esc Salir", bw - 4),
                 A(CP_NORM, curses.A_DIM))

    def draw_list(self, rows, cols):
        s = self.stdscr
        wifi = self.state == "wifi"
        bw = min(cols - 4, 64)
        count = len(self.entries)
        bh = max(7, min(rows - 2, count + 5))
        visible = max(0, min(count, bh - 5))
        start = 0 if self.sel < visible else min(self.sel - visible + 1,
                                                 max(0, count - visible))
        y, x = (rows - bh) // 2, (cols - bw) // 2
        self.box(y, x, bh, bw, " Redes Wi-Fi " if wifi else " Dispositivos Bluetooth ")
        innerw = bw - 4
        if wifi:
            pie = "Enter · e Contraseña · d Olvidar · r Reescanear · Esc Menú"
        else:
            pie = "Enter Conectar/Desconectar · r Reescanear · Esc Menú"
        sub = (f"{count} red{'es' if count != 1 else ''}"
               if wifi else f"{count} dispositivo{'s' if count != 1 else ''}")
        self.put(y + 1, x + 2, trunc(sub + "   (r reescanea)", innerw),
                 A(CP_NORM, curses.A_DIM))
        if not self.entries:
            self.centre(y + 2 + max(0, (bh - 6) // 2),
                        "Sin resultados — pulsa r para escanear", innerw, x,
                        A(CP_NORM, curses.A_DIM))
        for i in range(start, min(count, start + visible)):
            e = self.entries[i]
            r = y + 2 + (i - start)
            rev = curses.A_REVERSE if i == self.sel else 0
            self.put(r, x + 1, " " * (bw - 2), A(CP_NORM, rev))
            if wifi:
                nameW = innerw - 12
                self.put(r, x + 2, ("▸ " if e["in_use"] else "  "),
                         A(CP_OK, rev if e["in_use"] else 0))
                self.put(r, x + 4, ("●" if e["secured"] else " "),
                         A(CP_WARN, rev))
                if self.passwords.get(e["ssid"]):
                    self.put(r, x + 5, "✓", A(CP_OK, rev))
                self.put(r, x + 6, f"{trunc(e['ssid'], nameW):<{nameW}}",
                         A(CP_NORM, rev))
                self.put(r, x + 7 + nameW, sig_bar(e["signal"]),
                         A(CP_ACC, rev))
                self.put(r, x + 9 + nameW, f"{e['signal']:>3}%",
                         A(CP_NORM, curses.A_DIM | rev))
            else:
                nameW = innerw - 15
                self.put(r, x + 2, f"{trunc(e['name'], nameW):<{nameW}}",
                         A(CP_NORM, rev))
                color = CP_OK if e["connected"] else CP_NORM
                extra = curses.A_DIM if not e["connected"] else curses.A_BOLD
                self.put(r, x + 4 + nameW, f"{e['state']:>11}",
                         A(color, extra | rev))
        if self.list_err:
            self.put(y + bh - 3, x + 2, trunc(self.list_err, innerw), A(CP_ERR))
        self.put(y + bh - 2, x + 2, trunc(pie, innerw), A(CP_NORM, curses.A_DIM))

    def draw_input(self, rows, cols):
        bw = min(cols - 4, 58)
        bh = 9
        y, x = (rows - bh) // 2, (cols - bw) // 2
        es_clave = self.input_mode == "password"
        self.box(y, x, bh, bw, " Contraseña " if es_clave else " Red oculta ")
        if es_clave:
            label = f"Contraseña para «{trunc(self.target.get('ssid', ''), bw - 30)}»:"
        else:
            label = "Nombre de red (SSID):"
        self.centre(y + 3, trunc(label, bw - 4), bw, x, A(CP_NORM, curses.A_BOLD))
        fw = bw - 10
        self.put(y + 5, x + 4, "_" * fw, A(CP_NORM, curses.A_DIM))
        texto = self.buffer if not self.hidden else "*" * len(self.buffer)
        self.put(y + 5, x + 4, trunc(texto, fw - 1), A(CP_NORM, curses.A_BOLD))
        if es_clave:
            pista = ("[Enter] Conectar · [g] Guardar: "
                     + ("Sí" if self.save_pw else "No")
                     + " · [Esc] Cancelar")
        else:
            pista = "[Enter] Conectar · [Esc] Cancelar"
        self.put(y + bh - 2, x + 2, trunc(pista, bw - 4), A(CP_NORM, curses.A_DIM))

    def draw_msg(self, rows, cols):
        m = self.msg
        err = m["kind"] == "err"
        bw = min(cols - 4, 62)
        lineas = wrap(m["text"], bw - 8)
        bh = max(6, len(lineas) + 4)
        y, x = (rows - bh) // 2, (cols - bw) // 2
        col = CP_ERR if err else CP_OK
        self.box(y, x, bh, bw, " Error " if err else " Listo ", col=col)
        for i, ln in enumerate(lineas):
            self.put(y + 2 + i, x + 4, trunc(ln, bw - 8), A(col, curses.A_BOLD))
        extra = " · Enter reintenta" if m["retry"] else ""
        self.put(y + bh - 2, x + 2,
                 trunc(f"[Enter] Aceptar{extra} · [Esc] Volver", bw - 4),
                 A(CP_NORM, curses.A_DIM))

    def draw_busy(self, rows, cols):
        texto = self.job["text"]
        bw = min(cols - 6, max(48, len(texto) + 12))
        bh = 5
        y, x = (rows - bh) // 2, (cols - bw) // 2
        self.box(y, x, bh, bw, " Espere ", col=CP_ACC)
        spin = SPIN[self.frame % len(SPIN)]
        self.put(y + 2, x + 2, trunc(f"{spin}  {texto}", bw - 4),
                 A(CP_ACC, curses.A_BOLD))


def _run(stdscr):
    App(stdscr).run()


# ----------------------------------------------------------------------------
def main():
    os.environ.setdefault("ESCDELAY", "30")
    try:
        locale.setlocale(locale.LC_ALL, "")
    except locale.Error:
        pass
    try:
        curses.wrapper(_run)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
