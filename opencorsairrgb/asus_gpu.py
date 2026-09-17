"""Placa de video ASUS com controlador ENE SMBus (ex.: ROG STRIX RTX 3080 White OC).

Protocolo (OpenRGB ENESMBusController), no barramento i2c da propria GPU:
  - registrador ENE de 16 bits selecionado com write_word(0x00, reg com bytes trocados)
  - leitura em 0x81, escrita de byte em 0x01, bloco (ate 3 bytes) em 0x03
  - 0x1000: nome do firmware (16 bytes); 0x1C00: tabela de configuracao
  - 0x8020 = 1 liga o modo direto; 0x80A0 = 1 aplica (0xAA salvaria na placa)
  - cores diretas em 0x8000 (v1) ou 0x8100 (v2), 3 bytes por LED na ordem R, B, G
O modo direto nao grava nada na placa: ao reiniciar, ela volta ao efeito salvo.
"""
import ctypes
import fcntl
import glob
import os
import time

from .corsair_ram import (I2C_SLAVE, I2C_SMBUS, SMBUS_BLOCK_DATA, SMBUS_BYTE_DATA, SMBUS_READ,
                          SMBUS_WORD_DATA, SMBUS_WRITE, _SmbusData, _SmbusIoctl)

NAME = "Placa de vídeo (ASUS ENE)"
ADDRESS = 0x67
RETRIES = 5

REG_DEVICE_NAME = 0x1000
REG_CONFIG_TABLE = 0x1C00
REG_COLORS_DIRECT_V1 = 0x8000
REG_COLORS_DIRECT_V2 = 0x8100
REG_DIRECT = 0x8020
REG_MODE = 0x8021
REG_SPEED = 0x8022
REG_DIRECTION = 0x8023
REG_APPLY = 0x80A0
APPLY_VAL = 0x01

# Efeitos do firmware ENE (animam na propria placa, sem custo de CPU)
FW_SPECTRUM_CYCLE = 4
FW_RAINBOW = 5
SPEED_FASTEST, SPEED_SLOWEST = 0x00, 0x04

# Firmwares que usam os registradores v2 e o contador de LEDs no offset 0x03 da tabela
V2_COUNT_AT_03 = {"AUMA0-E6K5-0107", "AUMA0-E6K5-1110", "AUMA0-E6K5-1111", "AUMA0-E6K5-1107",
                  "AUMA0-E6K5-0008", "AUMA0-E6K5-1113", "AUMA0-E6K5-1114"}
V2_COUNT_AT_02 = {"AUDA0-E6K5-0101", "AUMA0-E6K5-0106", "AUMA0-E6K5-0105", "AUMA0-E6K5-0104"}


class DeviceError(Exception):
    pass


class _Bus:
    def __init__(self, path):
        try:
            self.fd = os.open(path, os.O_RDWR)
        except OSError as e:
            raise DeviceError(f"Não foi possível abrir {path}: {e.strerror}") from e
        fcntl.ioctl(self.fd, I2C_SLAVE, ADDRESS)

    def close(self):
        os.close(self.fd)

    def _xfer(self, rw, cmd, size, data):
        for attempt in range(RETRIES):
            try:
                fcntl.ioctl(self.fd, I2C_SMBUS, _SmbusIoctl(rw, cmd, size, ctypes.pointer(data)))
                return
            except OSError as e:
                if attempt == RETRIES - 1:
                    raise DeviceError(f"i2c falhou: {e.strerror}") from e
                time.sleep(0.002 * (attempt + 1))

    def read_byte(self, cmd):
        d = _SmbusData()
        self._xfer(SMBUS_READ, cmd, SMBUS_BYTE_DATA, d)
        return d.byte

    def write_byte(self, cmd, value):
        d = _SmbusData()
        d.byte = value
        self._xfer(SMBUS_WRITE, cmd, SMBUS_BYTE_DATA, d)

    def write_word(self, cmd, value):
        d = _SmbusData()
        d.block[0], d.block[1] = value & 0xFF, value >> 8
        self._xfer(SMBUS_WRITE, cmd, SMBUS_WORD_DATA, d)

    def write_block(self, cmd, payload):
        d = _SmbusData()
        d.block[0] = len(payload)
        for i, b in enumerate(payload):
            d.block[i + 1] = b
        self._xfer(SMBUS_WRITE, cmd, SMBUS_BLOCK_DATA, d)

    # --- registradores ENE -------------------------------------------------------
    def _select(self, reg):
        self.write_word(0x00, ((reg << 8) & 0xFF00) | ((reg >> 8) & 0x00FF))

    def ene_read(self, reg):
        self._select(reg)
        return self.read_byte(0x81)

    def ene_write(self, reg, value):
        self._select(reg)
        self.write_byte(0x01, value)

    def ene_write_block(self, reg, payload):
        self._select(reg)
        try:
            self.write_block(0x03, payload)
        except DeviceError:
            for b in payload:
                self.write_byte(0x01, b)


def _is_ene(path):
    """Mesmo teste do OpenRGB: registradores 0xA0..0xAF devolvem 0..15 (so leitura)."""
    try:
        bus = _Bus(path)
    except (DeviceError, OSError):
        return False
    try:
        return all(bus.read_byte(0xA0 + i) == i for i in range(16))
    except (DeviceError, OSError):
        return False
    finally:
        bus.close()


def find_bus():
    for node in sorted(glob.glob("/sys/class/i2c-dev/i2c-*"), key=lambda p: int(p.rsplit("-", 1)[1])):
        try:
            with open(os.path.join(node, "name")) as f:
                name = f.read().strip()
        except OSError:
            continue
        if name.startswith("NVIDIA i2c adapter"):
            path = "/dev/" + os.path.basename(node)
            if os.access(path, os.R_OK | os.W_OK) and _is_ene(path):
                return path
    return None


def status():
    path = find_bus()
    if not path:
        return False, "Controlador ENE da GPU não encontrado"
    return True, f"{path}, endereço 0x{ADDRESS:02X}"


class Device:
    """Mantem o barramento aberto entre quadros; reabre depois de erro."""

    def __init__(self):
        self.bus = None
        self.firmware = None
        self.led_count = 0
        self.direct_reg = REG_COLORS_DIRECT_V1
        self.direct = False
        self.firmware_mode = None

    def close(self):
        if self.bus is not None:
            self.bus.close()
            self.bus = None
        self.direct = False
        self.firmware_mode = None

    def open(self):
        path = find_bus()
        if not path:
            raise DeviceError("Controlador ENE da GPU não encontrado")
        self.bus = _Bus(path)
        try:
            raw = bytes(self.bus.ene_read(REG_DEVICE_NAME + i) for i in range(16))
            self.firmware = raw.split(b"\0")[0].decode("ascii", "replace")
            table = [self.bus.ene_read(REG_CONFIG_TABLE + i) for i in range(4)]
        except DeviceError:
            self.close()
            raise
        if self.firmware in V2_COUNT_AT_03:
            self.direct_reg, self.led_count = REG_COLORS_DIRECT_V2, table[0x03]
        elif self.firmware in V2_COUNT_AT_02:
            self.direct_reg, self.led_count = REG_COLORS_DIRECT_V2, table[0x02]
        else:
            self.direct_reg, self.led_count = REG_COLORS_DIRECT_V1, table[0x02]
        if not 0 < self.led_count <= 64:
            self.close()
            raise DeviceError(f"Quantidade de LEDs inválida ({self.led_count}) no firmware {self.firmware}")

    def write_frame(self, pixels):
        """pixels: tuplas RGB; a lista e repetida/cortada para led_count."""
        if self.bus is None:
            self.open()
        try:
            if not self.direct:
                self.bus.ene_write(REG_DIRECT, 1)
                self.bus.ene_write(REG_APPLY, APPLY_VAL)
                self.direct, self.firmware_mode = True, None
            buf = bytearray()
            for i in range(self.led_count):
                r, g, b = pixels[i % len(pixels)]
                buf += bytes((r, b, g))  # ordem ENE: R, B, G
            for offset in range(0, len(buf), 3):
                self.bus.ene_write_block(self.direct_reg + offset, bytes(buf[offset:offset + 3]))
        except DeviceError:
            self.close()
            raise

    def set_firmware_effect(self, mode, speed):
        """Efeito animado pelo firmware (nao salvo na placa). speed: 0 mais rapido .. 4 mais lento."""
        if self.bus is None:
            self.open()
        speed = max(SPEED_FASTEST, min(SPEED_SLOWEST, speed))
        if self.firmware_mode == (mode, speed):
            return
        try:
            self.bus.ene_write(REG_DIRECT, 0)
            self.bus.ene_write(REG_MODE, mode)
            self.bus.ene_write(REG_SPEED, speed)
            self.bus.ene_write(REG_DIRECTION, 0)
            self.bus.ene_write(REG_APPLY, APPLY_VAL)
        except DeviceError:
            self.close()
            raise
        self.direct, self.firmware_mode = False, (mode, speed)
