"""Display digital do water cooler GAMDIAS CHIONE (USB 1b80:b53c).

Protocolo extraido do ZEUS CAST 3.3.1.4 (classe HIDB53CII):
  relatorio de 65 bytes (report ID 0 + 64 bytes)
  [1]=0x3A [2]=0xB5 [3]=id (0xFF consulta firmware, 0x01 dados)
  [4..7]=digitos (0-9, 32 = apagado) [8]=ponto decimal [9]=unidade (1 C, 0 F)
  [10]=icone CPU [11]=modo (0 temperatura, 1 RPM) [12]=piscar
  [13]=soma dos bytes 0..12 & 0xFF
O ZEUS CAST reenvia os dados a cada 250 ms.
"""
import glob
import os
import select

NAME = "Display CHIONE"
MATCH = "0003:00001B80:0000B53C"
BLANK = 32
HEADER = (0x3A, 0xB5)
ID_QUERY, ID_DATA = 0xFF, 0x01
MODE_TEMP, MODE_RPM = 0, 1


class DeviceError(Exception):
    pass


def find_hidraw():
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        with open(os.path.join(node, "device", "uevent")) as f:
            if MATCH in f.read():
                return "/dev/" + os.path.basename(node)
    return None


def status():
    path = find_hidraw()
    if not path:
        return False, "Display não encontrado"
    if not os.access(path, os.R_OK | os.W_OK):
        return False, f"Sem permissão em {path}"
    return True, path


def _report(dev_id, digits, dot, celsius, cpu_icon, mode, flashing):
    buf = bytearray(65)
    buf[1], buf[2], buf[3] = HEADER[0], HEADER[1], dev_id
    buf[4:8] = bytes(digits)
    buf[8], buf[9], buf[10], buf[11], buf[12] = dot, celsius, cpu_icon, mode, flashing
    buf[13] = sum(buf[0:13]) & 0xFF
    return bytes(buf)


def temp_digits(temp_c, fahrenheit=False):
    """Como o ZEUS CAST: 4 digitos com uma casa decimal (45.3 -> ' 453')."""
    value = temp_c * 1.8 + 32 if fahrenheit else temp_c
    tenths = max(0, min(9999, round(value * 10)))
    digits = [tenths // 1000, tenths // 100 % 10, tenths // 10 % 10, tenths % 10]
    if digits[0] == 0:
        digits[0] = BLANK
    return digits


def rpm_digits(rpm):
    rpm = max(0, min(9999, int(rpm)))
    return [rpm // 1000, rpm // 100 % 10, rpm // 10 % 10, rpm % 10]


class Device:
    def __init__(self):
        self.fd = None
        self.firmware = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _read(self, timeout=0.5):
        if select.select([self.fd], [], [], timeout)[0]:
            return os.read(self.fd, 65)
        return b""

    def open(self):
        path = find_hidraw()
        if not path:
            raise DeviceError("Display CHIONE 1b80:b53c não encontrado")
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        except PermissionError as e:
            raise DeviceError(f"Sem permissão em {path}") from e
        # Mesmo pacote inicial do ZEUS CAST: consulta de firmware
        self._write(_report(ID_QUERY, [BLANK] * 4, 0, 1, 1, 0, 0))
        reply = self._read()
        if len(reply) >= 5:
            self.firmware = {"version": f"{reply[3]:X}.{reply[4]:X}", "raw": reply[:8].hex(" ")}

    def _write(self, data):
        try:
            os.write(self.fd, data)
        except OSError as e:
            self.close()
            raise DeviceError(f"Falha ao escrever no display: {e.strerror}") from e

    def show_temperature(self, temp_c, fahrenheit=False, flashing=False):
        self._send(temp_digits(temp_c, fahrenheit), dot=1, celsius=0 if fahrenheit else 1,
                   cpu_icon=1, mode=MODE_TEMP, flashing=flashing)

    def show_rpm(self, rpm, flashing=False):
        self._send(rpm_digits(rpm), dot=0, celsius=0, cpu_icon=0, mode=MODE_RPM, flashing=flashing)

    def _send(self, digits, dot, celsius, cpu_icon, mode, flashing):
        if self.fd is None:
            self.open()
        self._write(_report(ID_DATA, digits, dot, celsius, cpu_icon, mode, 1 if flashing else 0))
        self._read(timeout=0.05)  # o firmware responde a cada relatorio; descarta


# --- sensores -------------------------------------------------------------------
CPU_SENSORS = (("k10temp", ("Tctl", "Tdie")), ("zenpower", ("Tdie", "Tctl")),
               ("coretemp", ("Package id 0",)))


def cpu_temp_path():
    """Caminho temp*_input do sensor de temperatura da CPU."""
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(hwmon, "name")) as f:
                name = f.read().strip()
        except OSError:
            continue
        for driver, labels in CPU_SENSORS:
            if name != driver:
                continue
            inputs = sorted(glob.glob(os.path.join(hwmon, "temp*_input")))
            for label in labels:
                for inp in inputs:
                    try:
                        with open(inp.replace("_input", "_label")) as f:
                            if f.read().strip() == label:
                                return inp
                    except OSError:
                        pass
            if inputs:
                return inputs[0]
    return None


def fan_rpm_sensors():
    """[(rotulo, caminho fan*_input)] de todos os fans com leitura."""
    result = []
    for hwmon in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        try:
            with open(os.path.join(hwmon, "name")) as f:
                chip = f.read().strip()
        except OSError:
            continue
        for inp in sorted(glob.glob(os.path.join(hwmon, "fan*_input"))):
            label = os.path.basename(inp).replace("_input", "")
            try:
                with open(inp.replace("_input", "_label")) as f:
                    label = f.read().strip()
            except OSError:
                pass
            result.append((f"{chip} {label}", inp))
    return result


def read_sensor(path, scale=1000.0):
    with open(path) as f:
        return int(f.read().strip()) / scale
