# OpenCorsairRGB

**Open-source RGB lighting control for Linux** — Corsair Vengeance RGB PRO SL memory, ASUS ENE graphics cards, COLORFUL motherboard ARGB headers and the GAMDIAS CHIONE water-cooler digital display, all from one GTK4 app.

Built because the vendor tools (iCUE, Armoury Crate, iGame Center, ZEUS CAST) are Windows-only and OpenRGB does not cover some of this hardware.

> 🇧🇷 Leia em português: [README.pt-BR.md](README.pt-BR.md)

---

## Features

- 🎨 **Effects:** static, rainbow wave, spectrum cycle, gradient, color cycle and color wave, with 2–6 colors, speed and brightness
- ⚡ **Ready-made styles:** Rainbow, Spectrum, Cyberpunk, Fire, Ocean, Aurora, Sunset, Christmas
- 🔗 **Sync:** same effect on every device, or configure each one independently
- 🌡️ **Water-cooler display:** shows live CPU temperature (°C/°F) on the GAMDIAS CHIONE pump block, with an over-temperature blink alarm
- 🖥️ **Native GNOME app** (GTK 4 + libadwaita) and a **CLI**
- 🔁 **Background service** (systemd user unit) keeps animations running and restores everything at login
- 🔓 **No root at runtime** — udev rules grant access to the devices

## Supported hardware

| Device | Interface | ID / address | Notes |
|---|---|---|---|
| **Corsair Vengeance RGB PRO SL** (DDR4) | SMBus | `0x58`–`0x5B` | Direct mode + firmware effects |
| **ASUS ROG STRIX RTX 3080 White OC** and other ASUS ENE GPUs (`AUMA0-E6K5-*`, `LED-0116`) | NVIDIA i2c | `0x67` | Direct mode, host-rendered effects |
| **COLORFUL motherboard ARGB header** (e.g. CVN B550M GAMING FROZEN) | USB HID | `2f4c:1000` iface 2 | Host-rendered effects |
| **GAMDIAS CHIONE E4 digital display** | USB HID | `1b80:b53c` | CPU temperature |

Tested on **Linux Mint 22.3** (Ubuntu 24.04 base), GNOME, kernel 7.0, AMD Ryzen 9 3900X.
Other devices using the same controllers will probably work — reports and pull requests are welcome.

## Installation

### Option 1 — `.deb` package (Debian, Ubuntu, Linux Mint, Pop!_OS)

Download the latest `opencorsairrgb_<version>_all.deb` from the **Releases** page, then:

```bash
sudo apt install ./opencorsairrgb_*_all.deb
```

Log out and back in (or reboot) so the udev permissions and the background service take effect.
Then open **OpenCorsairRGB** from your application menu.

### Option 2 — build the package from source

```bash
sudo apt install git python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1
git clone https://github.com/<your-user>/OpenCorsairRGB.git
cd OpenCorsairRGB
./build-deb.sh
sudo apt install ./build/opencorsairrgb_*_all.deb
```

### Option 3 — run without installing (development)

```bash
# one-time: device permissions
sudo cp data/61-opencorsairrgb.rules /etc/udev/rules.d/
sudo modprobe i2c-dev
sudo udevadm control --reload && sudo udevadm trigger

# terminal 1: the service
python3 -m opencorsairrgb.cli --daemon
# terminal 2: the app
python3 -m opencorsairrgb.cli
```

### Requirements

- Python ≥ 3.10, PyGObject, GTK ≥ 4.10, libadwaita ≥ 1.4
- `i2c-dev` kernel module (loaded automatically by the package)
- A systemd user session

## Usage

### Graphical app

Open **OpenCorsairRGB** from the menu (or run `opencorsairrgb`). Every change is applied immediately:

- **Styles / solid colors** — one click applies to all enabled devices
- **Sync** — keep fans, memory and GPU on the same effect
- Each device has **On/Off, Effect, Colors (+/−), Speed, Brightness**
- **Memory ⟳** — re-send to modules that did not update (see *Known limitations*)
- **Water-cooler display** — on/off, unit, alarm threshold

### Command line

```bash
opencorsairrgb                         # open the app
opencorsairrgb --status                # service and device status

opencorsairrgb --fans ff00ff           # static color
opencorsairrgb --gpu rainbow           # rainbow wave
opencorsairrgb --ram spectrum          # spectrum cycle
opencorsairrgb --fans wave:ff00ff,00e5ff,ffffff   # color wave (2-6 colors)
opencorsairrgb --gpu gradient:ff3c00,6a00ff       # static gradient
opencorsairrgb --ram off

opencorsairrgb --display on|off|c|f    # water-cooler display
```

Effects: `static` (plain `RRGGBB`), `rainbow`, `spectrum`, `gradient:…`, `cycle:…`, `wave:…`, `off`.

### Service

```bash
systemctl --user status opencorsairrgb      # state
systemctl --user restart opencorsairrgb     # restart
journalctl --user -u opencorsairrgb -f      # live log
```

Settings are stored in `~/.config/opencorsairrgb/config.json`.

## Known limitations

- **Corsair memory:** on the tested board the RGB microcontroller NACKs ~70 % of SMBus commands (the SPD temperature sensor on the same bus answers 100 %), so the driver retries aggressively. Static colors take 10–30 s and sometimes only 2–3 of 4 modules update — use the ⟳ button. Firmware effects (rainbow, spectrum, cycle, wave) are **saved in the module** and take longer; *cycle* and *wave* use only the first 2 colors.
- **COLORFUL ARGB:** the controller exposes 200 LED slots in 10 windows of 20; the pattern is written to all windows because the wiring varies per board.
- **GPU:** *rainbow* and *spectrum* use the card's own ENE firmware effects (smooth, no CPU cost; brightness is not applied to them). *Cycle* and *wave* have no firmware equivalent and are drawn by the service at 4 fps — each frame is ~44 i2c transactions and the NVIDIA driver busy-waits on them, so they cost noticeable CPU. Nothing is saved to the card: until the service starts, it shows the effect stored by the vendor software.
- **Display:** fan-RPM mode is not implemented (no RPM sensor exposed on the tested board).

## Troubleshooting

| Problem | Fix |
|---|---|
| ⚠️ "Sem permissão" / permission denied | Log out and back in; check `ls -l /dev/hidraw* /dev/i2c-*` show a `+` (ACL) |
| GPU / memory not found | `sudo modprobe i2c-dev`; check `i2cdetect -l` lists the NVIDIA / PIIX4 adapters |
| "Service stopped" banner | `systemctl --user enable --now opencorsairrgb` |
| Display still shows `----` | Make sure the service is running and "Show CPU temperature" is on |
| Conflicts with OpenRGB | Don't run OpenRGB on the same devices at the same time |

## How it works

`opencorsairrgb --daemon` (systemd user service) owns the devices: it renders animations at 30 fps for USB/GPU devices, applies memory settings on a separate thread and sends the CPU temperature to the display every 250 ms. The GTK app only edits `config.json` and reads the live status from `$XDG_RUNTIME_DIR/opencorsairrgb/status.json`.

| Module | Responsibility |
|---|---|
| `opencorsairrgb/corsair_ram.py` | Corsair DRAM over SMBus (retries, direct mode, firmware effects) |
| `opencorsairrgb/asus_gpu.py` | ASUS ENE SMBus GPU over NVIDIA i2c |
| `opencorsairrgb/colorful_argb.py` | COLORFUL 2f4c:1000 USB HID |
| `opencorsairrgb/chione_display.py` | GAMDIAS CHIONE display + CPU sensor |
| `opencorsairrgb/effects.py` | Effect rendering |
| `opencorsairrgb/daemon.py` | Background service |
| `opencorsairrgb/app.py` | GTK 4 / libadwaita UI |
| `opencorsairrgb/cli.py` | Command line |

### Protocol notes

- **COLORFUL `2f4c:1000`** — 64-byte reports `01 00 88 <seq> <20×RGB>` for `seq` 0–9, then `seq=0xFF` with zero RGB to commit.
- **Corsair Vengeance RGB PRO SL** — direct packet `[10][RGB×10][CRC8]`, sent through the 0x90/0xA0 word-write fallback; firmware effects via buffer `0x0B/0x21/0x20`, CRC check `0x42`, commit `0x82=1`.
- **ASUS ENE GPU** — 16-bit register pointer written to `0x00` (byte-swapped), read `0x81`, write `0x01`, block `0x03`; direct enable `0x8020=1`, apply `0x80A0=1`, colors at `0x8100` in R,B,G order.
- **GAMDIAS CHIONE `1b80:b53c`** — 65-byte report `00 3A B5 <id> <4 digits> <dot> <unit> <cpu> <mode> <blink> <sum>`, every 250 ms (reverse-engineered from the ZEUS CAST .NET assembly).

## Uninstall

```bash
sudo apt remove opencorsairrgb
rm -rf ~/.config/opencorsairrgb ~/.local/state/opencorsairrgb   # optional: settings
```

## Contributing

Issues and pull requests are welcome — especially reports of other boards, GPUs and memory kits. Please include `opencorsairrgb --status`, `lsusb`, `i2cdetect -l` and the service log.

## Credits

- [OpenRGB](https://gitlab.com/CalcProgrammer1/OpenRGB) — Corsair DRAM and ENE SMBus protocol documentation, and [MR !3543](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3543) for the COLORFUL ARGB header
- [czw63/colorful-2f4c-openrgb](https://github.com/czw63/colorful-2f4c-openrgb) — COLORFUL reverse-engineering notes
- [innoextract](https://github.com/dscharrer/innoextract) and [ILSpy](https://github.com/icsharpcode/ILSpy) — used to study the ZEUS CAST protocol

## Disclaimer

OpenCorsairRGB is an independent community project. It is **not affiliated with, endorsed by or sponsored by** Corsair, ASUS, COLORFUL, GAMDIAS or NVIDIA. All trademarks belong to their respective owners. Writing to hardware registers is at your own risk.

## License

[GPL-2.0-or-later](LICENSE)
