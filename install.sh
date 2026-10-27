#!/bin/bash
# ==============================================================================
# 安装 SCPro 到应用菜单
#   ./install.sh                安装菜单启动器
#   ./install.sh --autostart    同时开启开机自启
#   ./install.sh --no-autostart 关闭开机自启
#   ./install.sh --uninstall    卸载
# ==============================================================================
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_PY="${APP_DIR}/main.py"
ICON_SRC="${APP_DIR}/scpro.svg"
PYTHON="$(command -v python3)"

APPS_DIR="${HOME}/.local/share/applications"
ICONS_DIR="${HOME}/.local/share/icons/hicolor/scalable/apps"
AUTOSTART_FILE="${HOME}/.config/autostart/scpro.desktop"
DESKTOP_FILE="${APPS_DIR}/scpro.desktop"
LAUNCHER="${HOME}/.local/bin/scpro"

# 旧名字（Px Deploy v2）留下的启动器/菜单项，安装时顺手清掉，避免菜单里出现两份
LEGACY_AUTOSTART="${HOME}/.config/autostart/px-deploy-v2.desktop"
LEGACY_DESKTOP="${APPS_DIR}/px-deploy-v2.desktop"
LEGACY_LAUNCHER="${HOME}/.local/bin/px-deploy-v2"
LEGACY_ICON="${ICONS_DIR}/px-deploy-v2.svg"

cleanup_legacy() {
    rm -f "$LEGACY_AUTOSTART" "$LEGACY_DESKTOP" "$LEGACY_LAUNCHER" "$LEGACY_ICON"
}

write_launcher() {
    mkdir -p "$(dirname "$LAUNCHER")"
    cat > "$LAUNCHER" <<EOF
#!/bin/bash
exec "${PYTHON}" "${APP_PY}" "\$@"
EOF
    chmod +x "$LAUNCHER"
}

write_desktop() {
    local dest="$1" autostart="$2"
    mkdir -p "$(dirname "$dest")"
    rm -f "$dest"
    {
        echo "[Desktop Entry]"
        echo "Type=Application"
        echo "Name=SCPro"
        echo "Comment=VS Code 风格的机器人部署工具"
        echo "Exec=${LAUNCHER}"
        echo "Icon=scpro"
        echo "Terminal=false"
        echo "Categories=Development;Utility;"
        [[ "$autostart" == "yes" ]] && echo "X-GNOME-Autostart-enabled=true"
    } > "$dest"
    chmod 644 "$dest"
}

case "${1:-}" in
    --uninstall)
        rm -f "$DESKTOP_FILE" "$AUTOSTART_FILE" "$LAUNCHER"
        cleanup_legacy
        echo "[INFO] 已卸载 SCPro"
        exit 0
        ;;
    --no-autostart)
        rm -f "$AUTOSTART_FILE" "$LEGACY_AUTOSTART"
        echo "[INFO] 已关闭开机自启"
        exit 0
        ;;
    --autostart)
        cleanup_legacy
        write_launcher
        write_desktop "$DESKTOP_FILE" no
        write_desktop "$AUTOSTART_FILE" yes
        echo "[INFO] 已安装并开启开机自启"
        ;;
    *)
        cleanup_legacy
        write_launcher
        write_desktop "$DESKTOP_FILE" no
        echo "[INFO] 已安装菜单启动器（未开启开机自启）"
        ;;
esac

mkdir -p "$ICONS_DIR"
install -m 644 "$ICON_SRC" "${ICONS_DIR}/scpro.svg"
chmod +x "$APP_PY"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true
echo "[INFO] 运行: ${LAUNCHER}"
