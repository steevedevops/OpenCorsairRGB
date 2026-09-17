"""Uso:
  opencorsairrgb                       abre a interface grafica
  opencorsairrgb --daemon              servico que aplica e anima as cores
  opencorsairrgb --fans VALOR          salva o efeito dos fans
  opencorsairrgb --ram VALOR           salva o efeito da RAM
  opencorsairrgb --gpu VALOR           salva o efeito da placa de video
  opencorsairrgb --display on|off|c|f  display do water cooler (temperatura da CPU)
  opencorsairrgb --status              mostra o estado do servico

VALOR: RRGGBB | off | rainbow | spectrum
       gradient|cycle|wave:RRGGBB,RRGGBB[,...]   ex.: wave:ff00ff,00e5ff
"""
import sys

from . import config, effects

HEX = set("0123456789abcdef")


def _is_hex(value):
    return len(value) == 6 and set(value) <= HEX


def _parse(value, zone):
    value = value.lower().lstrip("#")
    if value == "off":
        zone["enabled"] = False
        return
    zone["enabled"] = True
    if _is_hex(value):
        zone["mode"], zone["colors"][0] = "static", value
        return
    mode, _, colors = value.partition(":")
    if mode not in effects.MODE_IDS:
        sys.exit(f"Valor invalido: {value}")
    zone["mode"] = mode
    if mode in effects.MULTI_COLOR:
        parts = [c.lstrip("#") for c in colors.split(",") if c]
        if not (effects.MIN_COLORS <= len(parts) <= effects.MAX_COLORS) or not all(map(_is_hex, parts)):
            sys.exit(f"{mode} precisa de {effects.MIN_COLORS} a {effects.MAX_COLORS} cores RRGGBB")
        zone["colors"] = parts


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        from .app import run
        return run()
    if argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--daemon":
        from .daemon import run
        return run()
    if argv[0] == "--status":
        print("servico:", "ativo" if config.daemon_active() else "parado")
        status = config.read_status() or {}
        for name in (*config.ZONES, "display"):
            print(f"{name}: {status.get(name, {})}")
        return 0
    if argv[0] == "--display" and len(argv) == 2 and argv[1].lower() in ("on", "off", "c", "f"):
        cfg = config.load()
        value = argv[1].lower()
        if value in ("on", "off"):
            cfg["display"]["enabled"] = value == "on"
        else:
            cfg["display"].update(enabled=True, unit=value.upper())
        config.save(cfg)
        if not config.daemon_active():
            print("Aviso: o servico opencorsairrgb esta parado (systemctl --user start opencorsairrgb)")
        return 0
    if argv[0] in ("--fans", "--ram", "--gpu") and len(argv) == 2:
        cfg = config.load()
        _parse(argv[1], cfg[argv[0][2:]])
        config.save(cfg)
        if not config.daemon_active():
            print("Aviso: o servico opencorsairrgb esta parado (systemctl --user start opencorsairrgb)")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
