#!/usr/bin/env bash
# Gera o pacote .deb do OpenCorsairRGB em build/.
set -euo pipefail

cd "$(dirname "$0")"
VERSION=$(python3 -c 'import opencorsairrgb; print(opencorsairrgb.VERSION)')
PKG=opencorsairrgb_${VERSION}_all
ROOT=build/$PKG

rm -rf "$ROOT"
install -d "$ROOT/DEBIAN" "$ROOT/usr/bin" "$ROOT/usr/lib/opencorsairrgb/opencorsairrgb" \
           "$ROOT/usr/share/applications" "$ROOT/usr/share/icons/hicolor/scalable/apps" \
           "$ROOT/usr/lib/systemd/user" "$ROOT/usr/lib/udev/rules.d" "$ROOT/usr/lib/modules-load.d"

install -m 644 opencorsairrgb/*.py "$ROOT/usr/lib/opencorsairrgb/opencorsairrgb/"
install -m 644 data/com.steeve.OpenCorsairRGB.desktop "$ROOT/usr/share/applications/"
install -m 644 data/com.steeve.OpenCorsairRGB.svg "$ROOT/usr/share/icons/hicolor/scalable/apps/"
install -m 644 data/opencorsairrgb.service "$ROOT/usr/lib/systemd/user/"
install -m 644 data/61-opencorsairrgb.rules "$ROOT/usr/lib/udev/rules.d/"
echo i2c-dev > "$ROOT/usr/lib/modules-load.d/opencorsairrgb.conf"
chmod 644 "$ROOT/usr/lib/modules-load.d/opencorsairrgb.conf"

cat > "$ROOT/usr/bin/opencorsairrgb" <<'EOF'
#!/usr/bin/python3
import sys
sys.path.insert(0, "/usr/lib/opencorsairrgb")
from opencorsairrgb.cli import main
sys.exit(main())
EOF
chmod 755 "$ROOT/usr/bin/opencorsairrgb"

cat > "$ROOT/DEBIAN/control" <<EOF
Package: opencorsairrgb
Version: $VERSION
Section: utils
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1 (>= 1.4)
Conflicts: pc-rgb
Replaces: pc-rgb
Maintainer: Steeve <steevedevops@gmail.com>
Description: Open-source RGB lighting control for Linux
 GTK4 app and background service to control Corsair Vengeance RGB PRO SL
 memory, ASUS ENE graphics cards, COLORFUL motherboard ARGB headers and the
 GAMDIAS CHIONE water-cooler digital display (CPU temperature).
EOF

cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "configure" ]; then
    modprobe i2c-dev 2>/dev/null || true
    udevadm control --reload 2>/dev/null || true
    udevadm trigger --subsystem-match=hidraw --subsystem-match=i2c-dev 2>/dev/null || true
    # Limpa os servicos do projeto antigo (PC RGB)
    rm -f /etc/systemd/user/default.target.wants/pc-rgb.service \
          /etc/systemd/user/default.target.wants/pc-rgb-apply.service
    systemctl --global enable opencorsairrgb.service 2>/dev/null || true
    gtk-update-icon-cache -q -t /usr/share/icons/hicolor 2>/dev/null || true
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi
EOF

cat > "$ROOT/DEBIAN/prerm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    systemctl --global disable opencorsairrgb.service 2>/dev/null || true
fi
EOF

cat > "$ROOT/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
    udevadm control --reload 2>/dev/null || true
    update-desktop-database -q /usr/share/applications 2>/dev/null || true
fi
EOF
chmod 755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/prerm" "$ROOT/DEBIAN/postrm"

dpkg-deb --root-owner-group --build "$ROOT" "build/$PKG.deb"
echo "Pacote gerado: $(pwd)/build/$PKG.deb"
