"""RAM Corsair Vengeance RGB PRO SL via SMBus (/dev/i2c-0).

O OpenRGB nao detecta esses modulos porque boa parte das leituras no SMBus
desta placa falha e ele so tenta uma vez. Aqui cada operacao e repetida.

Protocolo: OpenRGB CorsairDRAMController.
- Modo direto (cores por LED): nao grava nada permanente. Os chips recusam a
  escrita em bloco no registrador 0x31, entao usa-se o fallback de escritas
  word em 0x90/0xA0.
- Efeitos de firmware (arco-iris, alternar, onda): o modulo SALVA o efeito na
  memoria permanente, entao so devem ser gravados quando mudarem.
"""
import ctypes
import fcntl
import os
import time

NAME = "Memoria RAM (Corsair)"
BUS = "/dev/i2c-0"
ADDRESSES = (0x58, 0x59, 0x5A, 0x5B)
LED_COUNT = 10
RETRIES = 30

I2C_SLAVE = 0x0703
I2C_SMBUS = 0x0720
SMBUS_READ, SMBUS_WRITE = 1, 0
SMBUS_BYTE_DATA, SMBUS_WORD_DATA, SMBUS_BLOCK_DATA = 2, 3, 5

REG_RESET_BUFFER = 0x0B
REG_SET_BINARY_DATA = 0x20
REG_BINARY_START = 0x21
REG_STATUS = 0x30
REG_COLOR_BLOCK_1 = 0x31
REG_GET_CHECKSUM = 0x42
REG_WRITE_CONFIGURATION = 0x82
ID_EFFECT_CONFIGURATION = 1

FW_COLOR_SHIFT = 0x00
FW_RAINBOW_WAVE = 0x03
FW_COLOR_WAVE = 0x04
FW_RAINBOW = 0x08
DIRECTION_DOWN = 0x01

last_failed = []  # enderecos que falharam na ultima operacao


class DeviceError(Exception):
    pass


class _SmbusData(ctypes.Union):
    _fields_ = [("byte", ctypes.c_uint8), ("block", ctypes.c_uint8 * 34)]


class _SmbusIoctl(ctypes.Structure):
    _fields_ = [("read_write", ctypes.c_uint8), ("command", ctypes.c_uint8),
                ("size", ctypes.c_uint32), ("data", ctypes.POINTER(_SmbusData))]


def crc8(data):
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


class Bus:
    def __init__(self, path=BUS):
        try:
            self.fd = os.open(path, os.O_RDWR)
        except OSError as e:
            raise DeviceError(f"Nao foi possivel abrir {path}: {e.strerror}") from e

    def close(self):
        os.close(self.fd)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _xfer(self, addr, rw, cmd, size, data):
        fcntl.ioctl(self.fd, I2C_SLAVE, addr)
        fcntl.ioctl(self.fd, I2C_SMBUS, _SmbusIoctl(rw, cmd, size, ctypes.pointer(data)))

    def _retry(self, fn):
        for attempt in range(RETRIES):
            try:
                return fn()
            except OSError:
                time.sleep(0.005 * (attempt + 1))
        raise DeviceError(f"SMBus falhou apos {RETRIES} tentativas")

    def read_byte(self, addr, reg):
        def op():
            d = _SmbusData()
            self._xfer(addr, SMBUS_READ, reg, SMBUS_BYTE_DATA, d)
            return d.byte
        return self._retry(op)

    def write_byte(self, addr, reg, value):
        def op():
            d = _SmbusData()
            d.byte = value
            self._xfer(addr, SMBUS_WRITE, reg, SMBUS_BYTE_DATA, d)
        self._retry(op)

    def write_word(self, addr, reg, value):
        def op():
            d = _SmbusData()
            d.block[0] = value & 0xFF
            d.block[1] = value >> 8
            self._xfer(addr, SMBUS_WRITE, reg, SMBUS_WORD_DATA, d)
        self._retry(op)

    def write_block(self, addr, reg, payload, attempts=3):
        d = _SmbusData()
        d.block[0] = len(payload)
        for i, b in enumerate(payload):
            d.block[i + 1] = b
        for _ in range(attempts):
            try:
                self._xfer(addr, SMBUS_WRITE, reg, SMBUS_BLOCK_DATA, d)
                return True
            except OSError:
                time.sleep(0.01)
        return False


def status():
    if not os.path.exists(BUS):
        return False, f"{BUS} nao existe"
    if not os.access(BUS, os.R_OK | os.W_OK):
        return False, f"Sem permissao em {BUS}"
    return True, f"{len(ADDRESSES)} modulos em {BUS}"


def _direct_module(bus, addr, pixels):
    packet = bytearray([LED_COUNT])
    for p in pixels[:LED_COUNT]:
        packet += bytes(p)
    packet.append(crc8(packet))
    if bus.write_block(addr, REG_COLOR_BLOCK_1, bytes(packet)):
        return

    # Fallback do OpenRGB: cada 5 bytes viram duas escritas word (0x90/0xA0 + nibble)
    for i in range(0, len(packet), 5):
        chunk = packet[i:i + 5]
        reg0, reg1, word1 = (0x90 if i == 0 else 0xA0), 0, 0
        word0 = chunk[0] | (chunk[1] << 8 if len(chunk) > 1 else 0)
        if len(chunk) > 2:
            reg0 |= chunk[2] & 0x0F
            reg1 = 0xA0 | (chunk[2] & 0xF0) >> 4
        if len(chunk) > 3:
            word1 = chunk[3] | (chunk[4] << 8 if len(chunk) > 4 else 0)
        bus.write_word(addr, reg0, word0)
        if reg1:
            bus.write_word(addr, reg1, word1)


def _effect_module(bus, addr, data):
    # Os chips recusam ~70% dos comandos; um byte repetido estraga o CRC e a
    # transferencia inteira precisa recomecar.
    for _ in range(15):
        bus.write_byte(addr, REG_RESET_BUFFER, 0x00)
        bus.write_byte(addr, REG_BINARY_START, 0x00)
        for b in data:
            bus.write_byte(addr, REG_SET_BINARY_DATA, b)
        if bus.read_byte(addr, REG_GET_CHECKSUM) != crc8(data):
            continue
        bus.write_byte(addr, REG_WRITE_CONFIGURATION, ID_EFFECT_CONFIGURATION)
        for _ in range(50):
            try:
                if not bus.read_byte(addr, REG_STATUS) & 0x08:
                    break
            except DeviceError:
                pass
            time.sleep(0.02)
        return
    raise DeviceError("CRC do efeito nao confere")


def _each_module(fn, passes=3):
    """Aplica em todos os modulos; os que falharem sao tentados de novo em outra passada."""
    remaining, errors = list(ADDRESSES), {}
    with Bus() as bus:
        for attempt in range(passes):
            failed = []
            for addr in remaining:
                try:
                    fn(bus, addr)
                    errors.pop(addr, None)
                except DeviceError as e:
                    errors[addr] = str(e)
                    failed.append(addr)
            remaining = failed
            if not remaining:
                break
            time.sleep(0.2 * (attempt + 1))
    global last_failed
    last_failed = list(remaining)
    ok = len(ADDRESSES) - len(remaining)
    if not ok:
        raise DeviceError("; ".join(f"0x{a:02X}: {m}" for a, m in errors.items()))
    return ok


def set_leds(pixels):
    """Modo direto: LED_COUNT tuplas RGB em todos os modulos. Retorna modulos ok."""
    return _each_module(lambda bus, addr: _direct_module(bus, addr, pixels))


def set_color(rgb):
    return set_leds([tuple(rgb)] * LED_COUNT)


def set_effect(fw_mode, speed, colors, brightness):
    """Efeito de firmware (salvo no modulo).

    speed: 0 lento, 1 medio, 2 rapido; colors: 2 tuplas RGB; brightness: 0-255.
    """
    (r1, g1, b1), (r2, g2, b2) = colors[0], colors[1]
    data = bytes([fw_mode, speed, 0x01, DIRECTION_DOWN,
                  r1, g1, b1, brightness, r2, g2, b2, brightness] + [0] * 8)
    return _each_module(lambda bus, addr: _effect_module(bus, addr, data), passes=4)
