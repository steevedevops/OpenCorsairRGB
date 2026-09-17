import json
import os
import subprocess

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "opencorsairrgb")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
STATE_DIR = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "opencorsairrgb")
RUNTIME_DIR = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "opencorsairrgb")
STATUS_FILE = os.path.join(RUNTIME_DIR, "status.json")
SERVICE = "opencorsairrgb.service"
# Configuracao da versao anterior (PC RGB), migrada na primeira execucao
LEGACY_CONFIG_FILE = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")),
                                  "pc-rgb", "config.json")

ZONES = ("fans", "ram", "gpu")
# "nonce" muda quando o usuario pede para reaplicar (o servico so reage a mudancas)
ZONE_DEFAULTS = {"enabled": True, "mode": "static", "colors": ["ff00ff", "00e5ff"],
                 "speed": 50, "brightness": 100, "nonce": 0}


# Display do water cooler: alarme em graus Celsius (pisca ao atingir o limite)
DISPLAY_DEFAULTS = {"enabled": True, "unit": "C", "alarm_enabled": True, "alarm": 85}


def defaults():
    cfg = {name: dict(ZONE_DEFAULTS, colors=list(ZONE_DEFAULTS["colors"])) for name in ZONES}
    cfg.update(display=dict(DISPLAY_DEFAULTS), sync=True)
    return cfg


def load():
    cfg = defaults()
    path = CONFIG_FILE if os.path.exists(CONFIG_FILE) else LEGACY_CONFIG_FILE
    try:
        with open(path) as f:
            saved = json.load(f)
    except (OSError, ValueError):
        return cfg
    for key, value in saved.items():
        if key in ZONES and isinstance(value, dict):
            zone = cfg[key]
            zone.update({k: v for k, v in value.items() if k in ZONE_DEFAULTS})
            if "colors" not in value and "color" in value:  # config da versao 1.0
                zone["colors"] = [value["color"], zone["colors"][1]]
        elif key == "display" and isinstance(value, dict):
            cfg[key].update({k: v for k, v in value.items() if k in DISPLAY_DEFAULTS})
        elif key == "sync":
            cfg[key] = bool(value)
    return cfg


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save(cfg):
    _write_json(CONFIG_FILE, cfg)


def write_status(status):
    _write_json(STATUS_FILE, status)


def read_status():
    try:
        with open(STATUS_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _systemctl(*args):
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True)


def autostart_enabled():
    return _systemctl("is-enabled", SERVICE).stdout.strip() == "enabled"


def set_autostart(enabled):
    return _systemctl("enable" if enabled else "disable", SERVICE).returncode == 0


def daemon_active():
    return _systemctl("is-active", SERVICE).stdout.strip() == "active"


def start_daemon():
    return _systemctl("start", SERVICE).returncode == 0
