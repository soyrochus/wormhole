#!/usr/bin/env bash
# Save as packaging/install-linux.sh
set -euo pipefail
PREFIX="${HOME}/.local"
APPDIR="${PREFIX}/wormhole"
DESKTOP_DIR="${HOME}/.local/share/applications"

mkdir -p "${APPDIR}" "${DESKTOP_DIR}"

# copy built app folder shipped inside the makeself bundle
cp -r dist/wormhole "${APPDIR}/"

# optional icon (if present)
ICON_SRC="$(dirname "$0")/../packaging/icon.png"
if [ -f "$ICON_SRC" ]; then
  ICON_PATH="${HOME}/.local/share/icons/wormhole.png"
  mkdir -p "$(dirname "$ICON_PATH")"
  cp "$ICON_SRC" "$ICON_PATH"
fi

# desktop entry
cat > "${DESKTOP_DIR}/wormhole.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Wormhole
Exec=${APPDIR}/wormhole/wormhole --gui
Icon=${HOME}/.local/share/icons/wormhole.png
Terminal=false
Categories=Utility;
EOF

echo "Installed Wormhole to ${APPDIR}"
echo "Launcher installed to ${DESKTOP_DIR}/wormhole.desktop"
