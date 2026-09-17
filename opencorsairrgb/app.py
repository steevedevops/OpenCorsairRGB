"""Interface grafica do OpenCorsairRGB (GTK 4 + libadwaita).

A interface so edita a configuracao; o servico opencorsairrgb aplica e anima.
"""
import math
import os
import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gdk, Gio, GLib, GObject, Gtk  # noqa: E402

from . import APP_ID, APP_NAME, VERSION, config, effects  # noqa: E402

SOLIDS = [
    ("Magenta", "ff00ff"), ("Roxo", "8a2be2"), ("Azul", "0050ff"), ("Ciano", "00e5ff"),
    ("Verde", "00ff40"), ("Amarelo", "ffd000"), ("Laranja", "ff6000"), ("Vermelho", "ff0000"),
    ("Rosa", "ff4fa0"), ("Branco", "ffffff"),
]

STYLES = [
    ("Arco-íris", "rainbow", []),
    ("Espectro", "spectrum", []),
    ("Cyberpunk", "wave", ["ff00ff", "00e5ff"]),
    ("Fogo", "wave", ["ff0000", "ff7000", "ffd000"]),
    ("Oceano", "wave", ["0030ff", "00e5ff", "00ffa0"]),
    ("Aurora", "cycle", ["00ff80", "8a2be2", "00b0ff"]),
    ("Pôr do sol", "gradient", ["ff3c00", "ff00aa", "6a00ff"]),
    ("Natal", "cycle", ["ff0000", "00ff40"]),
]
RAINBOW = ["ff0000", "ffd000", "00ff40", "00e5ff", "0050ff", "ff00ff", "ff0000"]

CSS = """
button.swatch { padding: 3px; border-radius: 999px; min-width: 0; min-height: 0; }
button.style-btn { padding: 4px 4px 2px 4px; min-width: 0; min-height: 0; }
.style-label { font-size: 0.8em; }
.brightness-scale { min-width: 160px; }
"""


# --- desenho (cairo, imune ao tema GTK) ----------------------------------------
def _rgb(hexc):
    return tuple(int(hexc[i:i + 2], 16) / 255 for i in (0, 2, 4))


def draw_circle(_area, cr, width, height, hexc):
    radius = min(width, height) / 2
    cr.arc(width / 2, height / 2, radius - 1, 0, 2 * math.pi)
    cr.set_source_rgb(*_rgb(hexc))
    cr.fill_preserve()
    cr.set_source_rgba(1, 1, 1, 0.35)
    cr.set_line_width(1.5)
    cr.stroke()


def draw_pill(_area, cr, width, height, colors):
    import cairo
    r = height / 2
    cr.new_sub_path()
    cr.arc(width - r, r, r - 1, -math.pi / 2, math.pi / 2)
    cr.arc(r, r, r - 1, math.pi / 2, 3 * math.pi / 2)
    cr.close_path()
    grad = cairo.LinearGradient(0, 0, width, 0)
    for i, hexc in enumerate(colors):
        grad.add_color_stop_rgb(i / max(1, len(colors) - 1), *_rgb(hexc))
    cr.set_source(grad)
    cr.fill_preserve()
    cr.set_source_rgba(1, 1, 1, 0.3)
    cr.set_line_width(1.5)
    cr.stroke()


def rgba_to_hex(rgba):
    return "".join(f"{round(max(0.0, min(1.0, c)) * 255):02x}" for c in (rgba.red, rgba.green, rgba.blue))


def hex_to_rgba(hexc):
    rgba = Gdk.RGBA()
    rgba.parse("#" + hexc)
    return rgba


# --- grupo de uma zona ------------------------------------------------------------
class ZoneGroup(Adw.PreferencesGroup):
    def __init__(self, window, name, title, description, ram=False):
        super().__init__(title=title, description=description)
        self.window, self.name, self.ram = window, name, ram
        self._loading = False

        self.status_icon = Gtk.Image(icon_name="content-loading-symbolic")
        self.spinner = Gtk.Spinner(visible=False)
        header = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        header.append(self.spinner)
        header.append(self.status_icon)
        if ram:
            retry = Gtk.Button(icon_name="view-refresh-symbolic", valign=Gtk.Align.CENTER,
                               tooltip_text="Reaplicar nos módulos (use se algum pente não mudou)")
            retry.add_css_class("flat")
            retry.connect("clicked", self._reapply)
            header.append(retry)
        self.set_header_suffix(header)

        self.enabled_row = Adw.SwitchRow(title="Ligado")
        self.enabled_row.connect("notify::active", self._changed)
        self.add(self.enabled_row)

        self.mode_row = Adw.ComboRow(title="Efeito",
                                     model=Gtk.StringList.new([label for _, label in effects.MODES]))
        self.mode_row.connect("notify::selected", self._mode_changed)
        self.add(self.mode_row)

        self.colors_row = Adw.ActionRow(title="Cores")
        self.colors_box = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.remove_btn = Gtk.Button(icon_name="list-remove-symbolic", tooltip_text="Remover cor",
                                     valign=Gtk.Align.CENTER)
        self.add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="Adicionar cor",
                                  valign=Gtk.Align.CENTER)
        for btn in (self.remove_btn, self.add_btn):
            btn.add_css_class("flat")
        self.remove_btn.connect("clicked", self._remove_color)
        self.add_btn.connect("clicked", self._add_color)
        self.colors_row.add_suffix(self.colors_box)
        self.colors_row.add_suffix(self.remove_btn)
        self.colors_row.add_suffix(self.add_btn)
        self.add(self.colors_row)
        self.color_buttons = []

        self.speed = self._scale(1, 100, 1)
        self.speed_row = Adw.ActionRow(title="Velocidade")
        self.speed_row.add_suffix(self.speed)
        self.add(self.speed_row)

        self.brightness = self._scale(0, 100, 5)
        self.brightness_row = Adw.ActionRow(title="Brilho")
        self.brightness_row.add_suffix(self.brightness)
        self.add(self.brightness_row)

        for row in (self.mode_row, self.colors_row, self.speed_row, self.brightness_row):
            self.enabled_row.bind_property("active", row, "sensitive", GObject.BindingFlags.SYNC_CREATE)

        self.load(window.cfg[name])

    def _scale(self, lo, hi, step):
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.LEFT)
        scale.set_format_value_func(lambda _s, v: f"{v:.0f}%")
        scale.set_hexpand(True)
        scale.add_css_class("brightness-scale")
        scale.connect("value-changed", self._changed)
        return scale

    # --- config <-> widgets -------------------------------------------------------
    def load(self, zone):
        self._loading = True
        self.enabled_row.set_active(zone["enabled"])
        self.mode_row.set_selected(effects.MODE_IDS.index(zone["mode"])
                                   if zone["mode"] in effects.MODE_IDS else 0)
        self.speed.set_value(zone["speed"])
        self.brightness.set_value(zone["brightness"])
        self._build_colors(zone["colors"])
        self._update_visibility()
        self._loading = False

    def _mode(self):
        return effects.MODE_IDS[self.mode_row.get_selected()]

    def _colors(self):
        return [rgba_to_hex(b.get_rgba()) for b in self.color_buttons]

    def _build_colors(self, colors):
        while (child := self.colors_box.get_first_child()) is not None:
            self.colors_box.remove(child)
        self.color_buttons = []
        for hexc in colors:
            btn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False),
                                        rgba=hex_to_rgba(hexc), valign=Gtk.Align.CENTER)
            btn.connect("notify::rgba", self._changed)
            self.colors_box.append(btn)
            self.color_buttons.append(btn)

    def _update_visibility(self):
        mode = self._mode()
        multi = mode in effects.MULTI_COLOR
        self.colors_row.set_visible(mode not in effects.NO_COLOR)
        self.speed_row.set_visible(mode in effects.ANIMATED)
        # Estatico mostra so a primeira cor; multicor mostra 2..6
        shown = len(self.color_buttons) if multi else 1
        for i, btn in enumerate(self.color_buttons):
            btn.set_visible(i < shown)
        self.add_btn.set_visible(multi and len(self.color_buttons) < effects.MAX_COLORS)
        self.remove_btn.set_visible(multi and len(self.color_buttons) > effects.MIN_COLORS)
        subtitle = ""
        if self.ram and mode in ("cycle", "wave"):
            subtitle = "A RAM usa só as 2 primeiras cores neste efeito"
        self.colors_row.set_subtitle(subtitle)

    def to_zone(self):
        mode = self._mode()
        colors = self._colors()
        if mode not in effects.MULTI_COLOR:
            # Preserva as outras cores da paleta ao alternar para estatico
            colors = colors[:1] + self.window.cfg[self.name]["colors"][1:]
        return {"enabled": self.enabled_row.get_active(), "mode": mode, "colors": colors,
                "speed": int(self.speed.get_value()), "brightness": int(self.brightness.get_value()),
                "nonce": self.window.cfg[self.name].get("nonce", 0)}

    def _reapply(self, _btn):
        import time
        # So a RAM: nao passa por zone_changed para nao reaplicar os fans via sincronizacao
        self.window.cfg[self.name] = dict(self.window.cfg[self.name], nonce=int(time.time()))
        self.window.schedule_save()

    # --- sinais ------------------------------------------------------------------
    def _mode_changed(self, *_args):
        if not self._loading:
            self._update_visibility()
        self._changed()

    def _add_color(self, _btn):
        colors = self._colors()
        palette = [h for _, h in SOLIDS]
        nxt = next((h for h in palette if h not in colors), "ffffff")
        self._build_colors(colors + [nxt])
        self._update_visibility()
        self._changed()

    def _remove_color(self, _btn):
        self._build_colors(self._colors()[:-1])
        self._update_visibility()
        self._changed()

    def _changed(self, *_args):
        if self._loading:
            return
        self.window.zone_changed(self.name, self.to_zone())

    # --- estado vindo do servico ---------------------------------------------------
    def show_status(self, st):
        busy = bool(st and st.get("busy"))
        self.spinner.set_visible(busy)
        self.spinner.set_spinning(busy)
        self.status_icon.set_visible(not busy)
        if not st or st.get("ok") is None:
            icon, css, tip = "content-loading-symbolic", None, "Aguardando o serviço"
        elif st["ok"]:
            icon, css, tip = "emblem-ok-symbolic", "success", st.get("msg", "")
        else:
            icon, css, tip = "dialog-warning-symbolic", "warning", st.get("msg", "")
        self.status_icon.set_from_icon_name(icon)
        for c in ("success", "warning"):
            self.status_icon.remove_css_class(c)
        if css:
            self.status_icon.add_css_class(css)
        self.status_icon.set_tooltip_text(tip)
        self.spinner.set_tooltip_text(st.get("msg", "Aplicando…") if st else None)


# --- janela --------------------------------------------------------------------------
class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title=APP_NAME, default_width=560, default_height=820)
        self.cfg = config.load()
        self._save_timeout = 0
        self._last_errors = {}

        self.toasts = Adw.ToastOverlay()
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        menu = Gtk.MenuButton(icon_name="open-menu-symbolic", tooltip_text="Menu")
        menu.set_menu_model(app.menu)
        header.pack_end(menu)
        toolbar.add_top_bar(header)

        self.banner = Adw.Banner(title="O serviço de iluminação está parado", button_label="Iniciar")
        self.banner.connect("button-clicked", self._start_daemon)
        toolbar.add_top_bar(self.banner)

        page = Adw.PreferencesPage()

        styles = Adw.PreferencesGroup(title="Estilos",
                                      description="Arco-íris e combinações de várias cores")
        styles_flow = self._flow(4)
        for label, mode, colors in STYLES:
            area = Gtk.DrawingArea(content_width=96, content_height=28)
            area.set_draw_func(draw_pill, RAINBOW if not colors else colors)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.append(area)
            text = Gtk.Label(label=label)
            text.add_css_class("style-label")
            box.append(text)
            btn = Gtk.Button(child=box, tooltip_text=f"{label} — {dict(effects.MODES)[mode]}")
            btn.add_css_class("flat")
            btn.add_css_class("style-btn")
            btn.connect("clicked", self._style_clicked, mode, colors)
            styles_flow.append(btn)
        styles.add(styles_flow)
        page.add(styles)

        solids = Adw.PreferencesGroup(title="Cores sólidas")
        solids_flow = self._flow(10)
        for label, hexc in SOLIDS:
            dot = Gtk.DrawingArea(content_width=32, content_height=32)
            dot.set_draw_func(draw_circle, hexc)
            btn = Gtk.Button(child=dot, tooltip_text=label,
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            btn.add_css_class("flat")
            btn.add_css_class("swatch")
            btn.connect("clicked", self._solid_clicked, hexc)
            solids_flow.append(btn)
        solids.add(solids_flow)
        self.sync_row = Adw.SwitchRow(title="Sincronizar", active=self.cfg["sync"],
                                      subtitle="Fans e RAM usam sempre o mesmo efeito e cores")
        self.sync_row.connect("notify::active", self._sync_toggled)
        solids.add(self.sync_row)
        page.add(solids)

        self.zones = {
            "fans": ZoneGroup(self, "fans", "Fans ARGB", "Header ARGB da placa-mãe COLORFUL"),
            "ram": ZoneGroup(self, "ram", "Memória RAM",
                             "Corsair Vengeance RGB PRO SL · leva alguns segundos para aplicar",
                             ram=True),
            "gpu": ZoneGroup(self, "gpu", "Placa de vídeo", "ASUS ROG STRIX (controlador ENE)"),
        }
        for group in self.zones.values():
            page.add(group)
        page.add(self._display_group())

        startup = Adw.PreferencesGroup(title="Inicialização")
        self.autostart_row = Adw.SwitchRow(title="Iniciar o serviço ao entrar na sessão",
                                           subtitle="Necessário para as animações e para restaurar as cores",
                                           active=config.autostart_enabled())
        self.autostart_row.connect("notify::active", self._autostart_toggled)
        startup.add(self.autostart_row)
        page.add(startup)

        toolbar.set_content(page)
        self.toasts.set_child(toolbar)
        self.set_content(self.toasts)

        self._poll_status()
        GLib.timeout_add(700, self._poll_status)

    def _display_group(self):
        disp = self.cfg["display"]
        group = Adw.PreferencesGroup(title="Display do water cooler",
                                     description="GAMDIAS CHIONE · temperatura da CPU no bloco da bomba")
        self.display_temp = Gtk.Label(label="—", valign=Gtk.Align.CENTER)
        self.display_temp.add_css_class("title-4")
        self.display_temp.add_css_class("numeric")
        self.display_icon = Gtk.Image(icon_name="content-loading-symbolic", valign=Gtk.Align.CENTER)
        header = Gtk.Box(spacing=8, valign=Gtk.Align.CENTER)
        header.append(self.display_temp)
        header.append(self.display_icon)
        group.set_header_suffix(header)

        self.display_enabled = Adw.SwitchRow(title="Mostrar temperatura da CPU", active=disp["enabled"])
        self.display_unit = Adw.ComboRow(title="Unidade", model=Gtk.StringList.new(["Celsius (°C)", "Fahrenheit (°F)"]),
                                         selected=1 if disp["unit"] == "F" else 0)
        self.display_alarm_on = Adw.SwitchRow(title="Piscar em temperatura alta", active=disp["alarm_enabled"])
        self.display_alarm = Adw.SpinRow.new_with_range(50, 100, 1)
        self.display_alarm.set_title("Limite do alarme (°C)")
        self.display_alarm.set_value(disp["alarm"])

        for row in (self.display_enabled, self.display_unit, self.display_alarm_on, self.display_alarm):
            group.add(row)
        for row in (self.display_unit, self.display_alarm_on, self.display_alarm):
            self.display_enabled.bind_property("active", row, "sensitive", GObject.BindingFlags.SYNC_CREATE)
        self.display_alarm_on.bind_property("active", self.display_alarm, "sensitive", GObject.BindingFlags.SYNC_CREATE)

        self.display_enabled.connect("notify::active", self._display_changed)
        self.display_unit.connect("notify::selected", self._display_changed)
        self.display_alarm_on.connect("notify::active", self._display_changed)
        self.display_alarm.connect("notify::value", self._display_changed)
        return group

    def _display_changed(self, *_args):
        self.cfg["display"] = {
            "enabled": self.display_enabled.get_active(),
            "unit": "F" if self.display_unit.get_selected() == 1 else "C",
            "alarm_enabled": self.display_alarm_on.get_active(),
            "alarm": int(self.display_alarm.get_value()),
        }
        self.schedule_save()

    def _show_display_status(self, st):
        if not st or st.get("ok") is None:
            self.display_temp.set_label("—" if not st else st.get("msg") or "—")
            icon, css = "content-loading-symbolic", None
        elif st["ok"]:
            self.display_temp.set_label(st.get("msg", "").split(" · ")[0])
            alarm = "alarme" in st.get("msg", "")
            icon, css = ("dialog-warning-symbolic", "error") if alarm else ("emblem-ok-symbolic", "success")
        else:
            self.display_temp.set_label("—")
            icon, css = "dialog-warning-symbolic", "warning"
        self.display_icon.set_from_icon_name(icon)
        for c in ("success", "warning", "error"):
            self.display_icon.remove_css_class(c)
        if css:
            self.display_icon.add_css_class(css)
        self.display_icon.set_tooltip_text(st.get("msg") if st else "Aguardando o serviço")

    def _flow(self, per_line):
        return Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, max_children_per_line=per_line,
                           min_children_per_line=min(per_line, 4), column_spacing=8, row_spacing=8,
                           homogeneous=True, margin_top=6, margin_bottom=6)

    # --- edicao -------------------------------------------------------------------
    def zone_changed(self, name, zone):
        self.cfg[name] = zone
        if self.cfg["sync"]:
            for other in self.zones:
                if other == name:
                    continue
                # nonce e so da RAM: sincronizar nao deve disparar reaplicacao
                self.cfg[other] = dict(zone, colors=list(zone["colors"]),
                                       nonce=self.cfg[other].get("nonce", 0))
                self.zones[other].load(self.cfg[other])
        self.schedule_save()

    def _apply_to_zones(self, **fields):
        for name, group in self.zones.items():
            zone = dict(self.cfg[name], enabled=True, **fields)
            self.cfg[name] = zone
            group.load(zone)
        self.schedule_save()

    def _style_clicked(self, _btn, mode, colors):
        fields = {"mode": mode}
        if colors:
            fields["colors"] = list(colors)
        self._apply_to_zones(**fields)

    def _solid_clicked(self, _btn, hexc):
        for name in self.zones:
            colors = list(self.cfg[name]["colors"])
            colors[0] = hexc
            self.cfg[name] = dict(self.cfg[name], mode="static", enabled=True, colors=colors)
            self.zones[name].load(self.cfg[name])
        self.schedule_save()

    def _sync_toggled(self, row, _pspec):
        self.cfg["sync"] = row.get_active()
        if self.cfg["sync"]:
            self.zone_changed("fans", self.cfg["fans"])
        self.schedule_save()

    def _autostart_toggled(self, row, _pspec):
        if not config.set_autostart(row.get_active()):
            self.toast("Não foi possível alterar a inicialização do serviço")

    # --- servico --------------------------------------------------------------------
    def _start_daemon(self, _banner):
        if config.start_daemon():
            self.toast("Serviço iniciado")
        else:
            self.toast("Não foi possível iniciar o serviço")

    def _poll_status(self):
        status = config.read_status()
        alive = False
        if status and status.get("pid"):
            try:
                os.kill(status["pid"], 0)
                alive = True
            except OSError:
                pass
        self.banner.set_revealed(not alive)
        for name, group in self.zones.items():
            st = status.get(name) if (alive and status) else None
            group.show_status(st)
            if st and st.get("ok") is False and self._last_errors.get(name) != st.get("msg"):
                self.toast(f"{group.get_title()}: {st.get('msg')}", timeout=6)
            self._last_errors[name] = st.get("msg") if st and st.get("ok") is False else None
        self._show_display_status(status.get("display") if (alive and status) else None)
        return GLib.SOURCE_CONTINUE

    def toast(self, text, timeout=3):
        self.toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=timeout))

    # --- persistencia -----------------------------------------------------------------
    def schedule_save(self):
        if self._save_timeout:
            GLib.source_remove(self._save_timeout)
        self._save_timeout = GLib.timeout_add(200, self._save)

    def _save(self):
        self._save_timeout = 0
        config.save(self.cfg)
        return GLib.SOURCE_REMOVE


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        GLib.set_application_name(APP_NAME)
        self.menu = Gio.Menu()
        self.menu.append("Sobre o OpenCorsairRGB", "app.about")
        about = Gio.SimpleAction(name="about")
        about.connect("activate", self._about)
        self.add_action(about)
        self.set_accels_for_action("window.close", ["<Ctrl>w", "<Ctrl>q"])

    def do_startup(self):
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)

    def do_activate(self):
        if not config.daemon_active():
            config.start_daemon()
        win = self.get_active_window() or MainWindow(self)
        win.present()

    def _about(self, *_args):
        Adw.AboutWindow(
            transient_for=self.get_active_window(), application_name=APP_NAME,
            application_icon=APP_ID, version=VERSION, developer_name="Steeve",
            comments="Controle dos fans ARGB (COLORFUL) e da RAM Corsair RGB no Linux",
            license_type=Gtk.License.GPL_2_0,
        ).present()


def run():
    return App().run([sys.argv[0]])
