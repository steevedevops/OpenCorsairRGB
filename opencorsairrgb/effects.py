"""Efeitos de iluminacao renderizados no host (listas de tuplas RGB 0-255)."""
import colorsys

MODES = [
    ("static", "Estático"),
    ("rainbow", "Arco-íris"),
    ("spectrum", "Espectro"),
    ("gradient", "Gradiente"),
    ("cycle", "Alternar cores"),
    ("wave", "Onda de cores"),
]
MODE_IDS = [m for m, _ in MODES]
ANIMATED = {"rainbow", "spectrum", "cycle", "wave"}
MULTI_COLOR = {"gradient", "cycle", "wave"}
NO_COLOR = {"rainbow", "spectrum"}
MIN_COLORS, MAX_COLORS = 2, 6


def hex_to_rgb(hexc):
    return tuple(int(hexc[i:i + 2], 16) for i in (0, 2, 4))


def rate(speed):
    """Velocidade 1-100 -> ciclos por segundo."""
    s = max(1, min(100, int(speed))) / 100
    return 0.03 + (s ** 1.5) * 1.2


def _hue(h):
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, 1.0, 1.0)
    return (round(r * 255), round(g * 255), round(b * 255))


def _lerp(a, b, f):
    return tuple(round(x + (y - x) * f) for x, y in zip(a, b))


def _sample(colors, pos, cyclic):
    """Cor numa posicao 0..1 de uma paleta (cyclic: volta para a primeira cor)."""
    n = len(colors)
    if n == 1:
        return colors[0]
    span = n if cyclic else n - 1
    x = (pos % 1.0 if cyclic else max(0.0, min(1.0, pos))) * span
    i = int(x)
    f = x - i
    a = colors[i % n]
    b = colors[(i + 1) % n] if cyclic else colors[min(i + 1, n - 1)]
    return _lerp(a, b, f)


def scale(pixels, brightness):
    k = max(0, min(100, int(brightness))) / 100
    return [tuple(round(c * k) for c in p) for p in pixels]


def render(zone, count, t):
    """Quadro de `count` LEDs no instante `t` (segundos), com brilho aplicado."""
    if not zone.get("enabled", True):
        return [(0, 0, 0)] * count
    mode = zone.get("mode", "static")
    colors = [hex_to_rgb(c) for c in zone.get("colors") or ["ffffff"]]
    phase = t * rate(zone.get("speed", 50))

    if mode == "rainbow":
        pixels = [_hue(i / count + phase) for i in range(count)]
    elif mode == "spectrum":
        pixels = [_hue(phase)] * count
    elif mode == "gradient":
        pixels = [_sample(colors, i / max(1, count - 1), cyclic=False) for i in range(count)]
    elif mode == "cycle":
        pixels = [_sample(colors, phase / len(colors), cyclic=True)] * count
    elif mode == "wave":
        pixels = [_sample(colors, i / count - phase, cyclic=True) for i in range(count)]
    else:
        pixels = [colors[0]] * count
    return scale(pixels, zone.get("brightness", 100))
