"""Header ARGB da placa COLORFUL (USB 2f4c:1000, interface 2).

Protocolo (OpenRGB MR !3543): relatorio de 64 bytes sem report ID
  01 00 88 <seq> <20 triplas RGB>   seq = 0..9, depois seq = 0xFF (commit, RGB zerado)

O controlador tem 200 slots (10 janelas de 20 LEDs). Nao se sabe quais janelas
estao ligadas nesta placa, entao o mesmo padrao de 20 LEDs e enviado para todas.
"""
import glob
import os

NAME = "Fans ARGB (COLORFUL)"
VID, PID, IFACE = "2F4C", "1000", "1.2"
LEDS, PACKETS = 20, 10


class DeviceError(Exception):
    pass


def find_hidraw():
    for node in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev = os.path.realpath(os.path.join(node, "device"))
        with open(os.path.join(dev, "uevent")) as f:
            if f"0003:0000{VID}:0000{PID}" not in f.read():
                continue
        if os.path.basename(os.path.dirname(dev)).endswith(f":{IFACE}"):
            return "/dev/" + os.path.basename(node)
    return None


def status():
    path = find_hidraw()
    if not path:
        return False, "Controlador nao encontrado"
    if not os.access(path, os.W_OK):
        return False, f"Sem permissao em {path}"
    return True, path


def _packet(seq, rgb=b""):
    buf = bytearray(64)
    buf[0:4] = bytes([0x01, 0x00, 0x88, seq])
    buf[4:4 + len(rgb)] = rgb
    return bytes(buf)


class Device:
    """Mantem o hidraw aberto entre quadros; reabre depois de erro."""

    def __init__(self):
        self.fd = None

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _open(self):
        path = find_hidraw()
        if not path:
            raise DeviceError("Controlador COLORFUL 2f4c:1000 nao encontrado")
        try:
            self.fd = os.open(path, os.O_WRONLY)
        except PermissionError as e:
            raise DeviceError(f"Sem permissao em {path}") from e

    def write_frame(self, pixels):
        """pixels: LEDS tuplas RGB (padrao repetido em todas as janelas)."""
        if self.fd is None:
            self._open()
        payload = bytes(c for p in pixels[:LEDS] for c in p)
        try:
            for seq in range(PACKETS):
                os.write(self.fd, _packet(seq, payload))
            os.write(self.fd, _packet(0xFF))
        except OSError as e:
            self.close()
            raise DeviceError(f"Falha ao escrever no controlador: {e.strerror}") from e


def set_color(rgb):
    """Aplica uma cor unica (bytes de 3 elementos)."""
    dev = Device()
    try:
        dev.write_frame([tuple(rgb)] * LEDS)
    finally:
        dev.close()
