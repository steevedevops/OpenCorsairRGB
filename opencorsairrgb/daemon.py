"""Servico que controla os dispositivos: anima fans e GPU, aplica a RAM e alimenta o display.

A interface grafica so edita ~/.config/opencorsairrgb/config.json; este processo
percebe a mudanca e aplica. O estado vai para $XDG_RUNTIME_DIR/opencorsairrgb/status.json.
"""
import json
import os
import signal
import threading
import time

from . import asus_gpu, chione_display, colorful_argb, config, corsair_ram, effects

FPS = 30
CONFIG_POLL = 0.25
RAM_DEBOUNCE = 1.5
FW_STATE_FILE = os.path.join(config.STATE_DIR, "ram-firmware.json")

RAM_FIRMWARE = {
    "rainbow": corsair_ram.FW_RAINBOW_WAVE,
    "spectrum": corsair_ram.FW_RAINBOW,
    "cycle": corsair_ram.FW_COLOR_SHIFT,
    "wave": corsair_ram.FW_COLOR_WAVE,
}


def log(msg):
    print(msg, flush=True)


class Status:
    def __init__(self):
        self.lock = threading.Lock()
        self.data = {"pid": os.getpid(), "fans": {"ok": None, "msg": "", "busy": False},
                     "ram": {"ok": None, "msg": "", "busy": False},
                     "gpu": {"ok": None, "msg": "", "busy": False},
                     "display": {"ok": None, "msg": "", "busy": False, "temp": None}}

    def set(self, zone, **fields):
        with self.lock:
            if all(self.data[zone].get(k) == v for k, v in fields.items()):
                return
            self.data[zone].update(fields)
            config.write_status(self.data)


class RamWorker(threading.Thread):
    """Aplica a RAM fora do loop dos fans (cada escrita leva segundos)."""

    def __init__(self, status):
        super().__init__(daemon=True)
        self.status = status
        self.cond = threading.Condition()
        self.pending = None
        self.first = True

    def request(self, zone):
        with self.cond:
            self.pending = (dict(zone), time.monotonic() + RAM_DEBOUNCE)
            self.cond.notify()

    def run(self):
        while True:
            with self.cond:
                while self.pending is None:
                    self.cond.wait()
                zone, due = self.pending
                if time.monotonic() < due:
                    self.cond.wait(due - time.monotonic())
                    continue
                self.pending = None
            self.apply(zone)

    def apply(self, zone):
        self.status.set("ram", busy=True)
        try:
            mode = zone["mode"] if zone.get("enabled", True) else "static"
            if mode in RAM_FIRMWARE:
                msg = self._firmware(zone, mode)
            else:
                n = corsair_ram.set_leds(effects.render(zone, corsair_ram.LED_COUNT, 0))
                msg = f"Aplicado em {n} de {len(corsair_ram.ADDRESSES)} módulos" + _failed_suffix()
                _save_fw_state(None)
            self.status.set("ram", ok=True, msg=msg, busy=False)
            log(f"ram: {msg}")
        except (corsair_ram.DeviceError, OSError) as e:
            self.status.set("ram", ok=False, msg=str(e), busy=False)
            log(f"ram: erro: {e}")
        self.first = False

    def _firmware(self, zone, mode):
        colors = [effects.hex_to_rgb(c) for c in zone.get("colors", [])][:2]
        while len(colors) < 2:
            colors.append(colors[0] if colors else (255, 255, 255))
        pct = int(zone.get("speed", 50))
        speed = 0 if pct < 34 else 1 if pct < 67 else 2
        brightness = round(max(0, min(100, int(zone.get("brightness", 100)))) * 2.55)
        signature = [RAM_FIRMWARE[mode], speed, colors, brightness, zone.get("nonce", 0)]
        # O efeito fica salvo no modulo: nao regravar o mesmo efeito (ex.: a cada boot)
        if self.first and _load_fw_state() == json.loads(json.dumps(signature)):
            return "Efeito já estava salvo nos módulos"
        n = corsair_ram.set_effect(RAM_FIRMWARE[mode], speed, colors, brightness)
        if n == len(corsair_ram.ADDRESSES):
            _save_fw_state(signature)
        return f"Efeito salvo em {n} de {len(corsair_ram.ADDRESSES)} módulos" + _failed_suffix()


def _failed_suffix():
    failed = corsair_ram.last_failed
    return f" (falharam: {', '.join(f'0x{a:02X}' for a in failed)})" if failed else ""


class DisplayWorker(threading.Thread):
    """Envia a temperatura da CPU ao display do CHIONE, como o ZEUS CAST (a cada 250 ms)."""

    INTERVAL = 0.25

    def __init__(self, status, settings):
        super().__init__(daemon=True)
        self.status = status
        self.settings = settings  # substituido pelo loop principal quando a config muda
        self.stop_event = threading.Event()

    def run(self):
        dev = chione_display.Device()
        sensor, active = None, False
        while not self.stop_event.is_set():
            s = self.settings
            if not s.get("enabled", True):
                if active:
                    dev.close()
                    active = False
                self.status.set("display", ok=None, msg="Desligado", temp=None)
                self.stop_event.wait(0.5)
                continue
            try:
                sensor = sensor or chione_display.cpu_temp_path()
                if not sensor:
                    raise chione_display.DeviceError("Sensor de temperatura da CPU não encontrado")
                temp = chione_display.read_sensor(sensor)
                fahrenheit = s.get("unit", "C") == "F"
                flashing = bool(s.get("alarm_enabled", True)) and temp >= float(s.get("alarm", 85))
                dev.show_temperature(temp, fahrenheit=fahrenheit, flashing=flashing)
                if not active:
                    log(f"display: enviando temperatura (firmware {(dev.firmware or {}).get('version', '?')})")
                active = True
                shown = temp * 1.8 + 32 if fahrenheit else temp
                self.status.set("display", ok=True, temp=round(temp, 1),
                                msg=f"{shown:.1f} °{'F' if fahrenheit else 'C'}" + (" · alarme" if flashing else ""))
                self.stop_event.wait(self.INTERVAL)
            except (chione_display.DeviceError, OSError) as e:
                dev.close()
                sensor, active = None, False
                self.status.set("display", ok=False, msg=str(e), temp=None)
                self.stop_event.wait(2.0)
        dev.close()


class GpuWorker(threading.Thread):
    """Controla a GPU em thread propria.

    Cada quadro desenhado no host sao ~44 transacoes i2c (~90 ms na RTX 3080) e o driver
    NVIDIA gasta CPU esperando cada uma. Por isso arco-iris e espectro usam os efeitos do
    firmware ENE; so "alternar" e "onda" (que o firmware nao tem) sao desenhados aqui, a 4 fps.
    """

    FPS = 4
    FIRMWARE = {"rainbow": asus_gpu.FW_RAINBOW, "spectrum": asus_gpu.FW_SPECTRUM_CYCLE}

    def __init__(self, status, zone):
        super().__init__(daemon=True)
        self.status = status
        self.zone = zone          # substituido pelo loop principal quando a config muda
        self.dirty = True
        self.stop_event = threading.Event()

    def update(self, zone):
        self.zone, self.dirty = zone, True

    def run(self):
        dev = asus_gpu.Device()
        start = time.monotonic()
        while not self.stop_event.is_set():
            zone = self.zone
            enabled = zone.get("enabled", True)
            if enabled and zone.get("mode") in self.FIRMWARE:
                if self.dirty:
                    try:
                        self.dirty = False
                        # velocidade 1-100 -> 4 (lento) .. 0 (rapido)
                        speed = 4 - min(4, int(zone.get("speed", 50)) * 5 // 101)
                        dev.set_firmware_effect(self.FIRMWARE[zone["mode"]], speed)
                        self.status.set("gpu", ok=True, msg=f"Efeito da placa · {dev.led_count} LEDs · {dev.firmware}")
                    except asus_gpu.DeviceError as e:
                        self.dirty = True
                        self.status.set("gpu", ok=False, msg=str(e))
                        self.stop_event.wait(3.0)
                        continue
                self.stop_event.wait(0.1)
                continue
            animated = enabled and zone.get("mode") in effects.ANIMATED
            if not (animated or self.dirty):
                self.stop_event.wait(0.1)
                continue
            began = time.monotonic()
            try:
                self.dirty = False
                count = dev.led_count or 1
                dev.write_frame(effects.render(zone, count if dev.bus else 1, began - start))
                if count != dev.led_count:  # primeiro quadro abriu o dispositivo: redesenha certo
                    dev.write_frame(effects.render(zone, dev.led_count, began - start))
                self.status.set("gpu", ok=True, msg=f"{'Animando' if animated else 'Aplicado'} · "
                                                    f"{dev.led_count} LEDs · {dev.firmware}")
            except asus_gpu.DeviceError as e:
                self.dirty = True
                self.status.set("gpu", ok=False, msg=str(e))
                self.stop_event.wait(3.0)
                continue
            if animated:
                self.stop_event.wait(max(0.0, 1 / self.FPS - (time.monotonic() - began)))
        dev.close()


def _load_fw_state():
    try:
        with open(FW_STATE_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save_fw_state(signature):
    os.makedirs(config.STATE_DIR, exist_ok=True)
    with open(FW_STATE_FILE, "w") as f:
        json.dump(signature, f)


def _config_mtime():
    try:
        return os.stat(config.CONFIG_FILE).st_mtime_ns
    except OSError:
        return None


def run():
    status = Status()
    config.write_status(status.data)
    running = True

    def stop(*_args):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    fans = colorful_argb.Device()
    ram = RamWorker(status)
    ram.start()

    cfg, mtime = config.load(), _config_mtime()
    ram.request(cfg["ram"])
    display = DisplayWorker(status, cfg["display"])
    display.start()
    gpu = GpuWorker(status, cfg["gpu"])
    gpu.start()
    fans_dirty, last_poll, last_ram = True, 0.0, json.dumps(cfg["ram"], sort_keys=True)
    start, frame, retry_at = time.monotonic(), 0, 0.0
    log("opencorsairrgb: servico iniciado")

    while running:
        now = time.monotonic()
        if now - last_poll >= CONFIG_POLL:
            last_poll = now
            new_mtime = _config_mtime()
            if new_mtime != mtime:
                mtime, cfg = new_mtime, config.load()
                display.settings = cfg["display"]
                gpu.update(cfg["gpu"])
                fans_dirty = True
                ram_sig = json.dumps(cfg["ram"], sort_keys=True)
                if ram_sig != last_ram:
                    last_ram = ram_sig
                    ram.request(cfg["ram"])

        zone = cfg["fans"]
        animated = zone.get("enabled", True) and zone.get("mode") in effects.ANIMATED
        if (animated or fans_dirty) and now >= retry_at:
            try:
                fans.write_frame(effects.render(zone, colorful_argb.LEDS, now - start))
                fans_dirty = False
                status.set("fans", ok=True, msg="Animando" if animated else "Aplicado")
            except colorful_argb.DeviceError as e:
                status.set("fans", ok=False, msg=str(e))
                retry_at = now + 2.0

        frame += 1
        next_frame = start + frame / FPS
        delay = next_frame - time.monotonic()
        if delay > 0:
            time.sleep(delay if animated else min(delay * 3, CONFIG_POLL))
        else:
            frame = int((time.monotonic() - start) * FPS)

    for worker in (display, gpu):
        worker.stop_event.set()
    for worker in (display, gpu):
        worker.join(timeout=1.0)
    fans.close()
    log("opencorsairrgb: servico encerrado")
    return 0
