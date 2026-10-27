#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""读取当前 VS Code 主题与文件图标主题，供 SCPro 复用。

- 颜色：解析 workbench.colorTheme 指向的主题 JSON（支持 JSONC 与 include）
- 图标：复制 VS Code 自带 codicon 字体，以及当前图标主题的 folder/file 图标
- 资源写到 SCPro/web/assets/，CSS 通过变量消费
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

HOME = Path.home()
SETTINGS = HOME / ".config" / "Code" / "User" / "settings.json"
BUILTIN_EXT = Path("/usr/share/code/resources/app/extensions")
USER_EXT = HOME / ".vscode" / "extensions"
CODICON = Path("/usr/share/code/resources/app/node_modules/@vscode/codicons/dist")

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
ASSET_DIR = WEB_DIR / "assets"

FALLBACK = {
    "bg": "#fdf6e3",
    "text": "#657b83",
    "sidebar": "#eee8d5",
    "activity": "#ddd6c1",
    "activity_fg": "#584c27",
    "status_bg": "#eee8d5",
    "status_fg": "#586e75",
    "panel": "#fdf6e3",
    "border": "#ddd6c1",
    "hover": "#dfca88",
    "selection": "#dfca88",
    "input_bg": "#ddd6c1",
    "input_fg": "#586e75",
    "button_bg": "#ac9d57",
    "button_fg": "#fdf6e3",
    "accent": "#b49471",
    "muted": "#93a1a1",
    "danger": "#dc322f",
}

DARK_FALLBACK = {
    "bg": "#1e1e1e",
    "text": "#d4d4d4",
    "sidebar": "#252526",
    "activity": "#333333",
    "activity_fg": "#cccccc",
    "status_bg": "#007acc",
    "status_fg": "#ffffff",
    "panel": "#1e1e1e",
    "border": "#3c3c3c",
    "hover": "#2a2d2e",
    "selection": "#094771",
    "input_bg": "#3c3c3c",
    "input_fg": "#cccccc",
    "button_bg": "#0e639c",
    "button_fg": "#ffffff",
    "accent": "#007acc",
    "muted": "#9d9d9d",
    "danger": "#f14c4c",
}

LIGHT_FALLBACK = {
    "bg": "#ffffff",
    "text": "#1f1f1f",
    "sidebar": "#f3f3f3",
    "activity": "#f8f8f8",
    "activity_fg": "#424242",
    "status_bg": "#007acc",
    "status_fg": "#ffffff",
    "panel": "#ffffff",
    "border": "#cecece",
    "hover": "#f0f0f0",
    "selection": "#d6ebff",
    "input_bg": "#ffffff",
    "input_fg": "#1f1f1f",
    "button_bg": "#007acc",
    "button_fg": "#ffffff",
    "accent": "#007acc",
    "muted": "#6b6b6b",
    "danger": "#a1260d",
}


def _strip_jsonc(text: str) -> str:
    """去掉 // 与 /* */ 注释和尾逗号（字符串内部的符号不动）"""
    out, i, in_str, esc = [], 0, False, False
    while i < len(text):
        ch = text[i]
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            i += 1
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
            i += 1
            continue
        if text.startswith("//", i):
            while i < len(text) and text[i] != "\n":
                i += 1
            continue
        if text.startswith("/*", i):
            i += 2
            while i < len(text) and not text.startswith("*/", i):
                i += 1
            i += 2
            continue
        out.append(ch)
        i += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _load_jsonc(path: Path) -> dict:
    try:
        return json.loads(_strip_jsonc(path.read_text(encoding="utf-8", errors="replace")))
    except Exception:
        return {}


def _settings() -> dict:
    return _load_jsonc(SETTINGS) if SETTINGS.exists() else {}


def _iter_extensions():
    for root in (BUILTIN_EXT, USER_EXT):
        if not root.is_dir():
            continue
        for item in root.iterdir():
            pkg = item / "package.json"
            if pkg.is_file():
                data = _load_jsonc(pkg)
                if data:
                    yield item, data


def _theme_label(ext_dir: Path, package: dict, raw_label) -> str:
    label = str(raw_label or "").strip()
    if not (label.startswith("%") and label.endswith("%")):
        return label
    key = label[1:-1]
    package_name = str(package.get("name") or "")
    for nls_name in ("package.nls.zh-cn.json", "package.nls.zh.json",
                     "package.nls.json"):
        data = _load_jsonc(ext_dir / nls_name)
        value = data.get(key)
        if value:
            return str(value)
    return package_name or key


def _iter_themes():
    for ext_dir, pkg in _iter_extensions():
        for theme in (pkg.get("contributes", {}) or {}).get("themes", []) or []:
            path = (ext_dir / str(theme.get("path", ""))).resolve()
            if not path.is_file():
                continue
            raw_id = str(theme.get("id") or "").strip()
            raw_label = str(theme.get("label") or "").strip()
            label = _theme_label(ext_dir, pkg, raw_label)
            theme_id = raw_id or label
            yield {
                "id": theme_id,
                "label": label or theme_id,
                "raw_id": raw_id,
                "raw_label": raw_label,
                "path": path,
                "uiTheme": str(theme.get("uiTheme") or ""),
            }


def available_themes() -> list:
    """返回 VS Code 当前安装的可用颜色主题。"""
    themes = {}
    for item in _iter_themes():
        themes.setdefault(item["id"], {
            "id": item["id"],
            "label": item["label"],
            "uiTheme": item["uiTheme"],
        })
    return sorted(themes.values(), key=lambda item: item["label"].casefold())


def _find_theme_entry(theme_id: str):
    theme_id = str(theme_id or "").strip()
    if not theme_id:
        return None
    for item in _iter_themes():
        if theme_id in (item["id"], item["label"], item["raw_id"], item["raw_label"]):
            return item
    return None


def _theme_colors(path: Path, seen=None) -> dict:
    seen = seen or set()
    if path in seen or not path.is_file():
        return {}
    seen.add(path)
    data = _load_jsonc(path)
    colors = {}
    include = data.get("include")
    if include:
        colors.update(_theme_colors((path.parent / include).resolve(), seen))
    colors.update(data.get("colors") or {})
    return colors


def _pick(colors: dict, *keys, default=""):
    for key in keys:
        value = colors.get(key)
        if value:
            return str(value)
    return default


def _luminance(color: str) -> float:
    rgb = _parse_color(color)
    if rgb is None:
        return 1.0
    channels = []
    for value in rgb:
        channel = value / 255.0
        channels.append(channel / 12.92 if channel <= 0.04045
                        else ((channel + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _parse_color(color: str):
    value = str(color or "").strip().lstrip("#")
    if len(value) in (3, 4):
        value = "".join(ch * 2 for ch in value[:3])
    if len(value) == 8:
        if value[6:8].lower() == "00":
            return None
        value = value[:6]
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return None


def _solid(color: str, fallback: str) -> str:
    rgb = _parse_color(color)
    if rgb is None:
        rgb = _parse_color(fallback)
    if rgb is None:
        return fallback
    return "#%02x%02x%02x" % rgb


def _mix(first: str, second: str, amount: float) -> str:
    one = _parse_color(first)
    two = _parse_color(second)
    if one is None or two is None:
        return _solid(first, second)
    amount = max(0.0, min(1.0, amount))
    rgb = tuple(round(a * (1.0 - amount) + b * amount) for a, b in zip(one, two))
    return "#%02x%02x%02x" % rgb


def _contrast(first: str, second: str) -> float:
    one = _luminance(first)
    two = _luminance(second)
    return (max(one, two) + 0.05) / (min(one, two) + 0.05)


def _readable(background: str, preferred: str, fallback: str) -> str:
    candidate = _solid(preferred, fallback)
    if _contrast(candidate, background) >= 4.5:
        return candidate
    light = "#ffffff" if _contrast("#ffffff", background) >= _contrast("#000000", background) else "#000000"
    return light


def _find_icon_theme(icon_id: str):
    for ext_dir, pkg in _iter_extensions():
        for theme in (pkg.get("contributes", {}) or {}).get("iconThemes", []) or []:
            if icon_id in (theme.get("id"), theme.get("label")):
                path = (ext_dir / str(theme.get("path", ""))).resolve()
                if path.is_file():
                    return path
    return None


def _copy_icon(theme_json: Path, definition: str, dest_name: str, icons: dict) -> str:
    node = (icons.get("iconDefinitions") or {}).get(definition) or {}
    rel = node.get("iconPath")
    if not rel:
        return ""
    src = (theme_json.parent / rel).resolve()
    if not src.is_file():
        return ""
    dest = ASSET_DIR / dest_name
    shutil.copy2(src, dest)
    return "assets/" + dest_name


def load(theme_id: str = "") -> dict:
    """返回 {id, name, dark, colors, icons}，并同步 web/assets。

    theme_id 为空时跟随 VS Code；否则优先使用指定的已安装 VS Code 主题。
    """
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    settings = _settings()
    configured_theme = str(settings.get("workbench.colorTheme") or "")
    icon_id = str(settings.get("workbench.iconTheme") or "")

    selected = _find_theme_entry(theme_id)
    if selected is None:
        selected = _find_theme_entry(configured_theme)
    theme_path = selected["path"] if selected else None
    raw = _theme_colors(theme_path) if theme_path else {}

    ui_theme = selected["uiTheme"] if selected else ""
    dark = ui_theme in ("vs-dark", "hc-black") or (
        not ui_theme and _luminance(str(raw.get("editor.background") or "")) < 0.45)
    defaults = (DARK_FALLBACK if dark else LIGHT_FALLBACK) if selected else FALLBACK

    bg = _solid(_pick(raw, "editor.background"), defaults["bg"])
    text = _readable(bg, _pick(raw, "editor.foreground", "foreground"), defaults["text"])
    sidebar = _solid(
        _pick(raw, "sideBar.background", "editorGroupHeader.tabsBackground"),
        _mix(bg, text, 0.05))
    activity = _solid(
        _pick(raw, "activityBar.background", "titleBar.activeBackground"),
        _mix(bg, text, 0.08))
    activity_fg = _readable(
        activity,
        _pick(raw, "activityBar.foreground", "activityBar.inactiveForeground"),
        text)
    status_bg = _solid(
        _pick(raw, "statusBar.background", "titleBar.activeBackground"),
        _mix(activity, text, 0.10))
    status_fg = _readable(
        status_bg,
        _pick(raw, "statusBar.foreground"),
        text)
    panel = _solid(
        _pick(raw, "panel.background", "editor.background"),
        bg)
    border = _solid(
        _pick(raw, "panel.border", "sideBar.border", "editorGroup.border",
              "contrastBorder"),
        _mix(bg, text, 0.20))
    hover = _solid(
        _pick(raw, "list.hoverBackground", "toolbar.hoverBackground"),
        _mix(bg, text, 0.10))
    selection = _solid(
        _pick(raw, "list.activeSelectionBackground",
              "list.inactiveSelectionBackground",
              "editor.selectionBackground"),
        _mix(bg, text, 0.20))
    selection_fg = _readable(
        selection,
        _pick(raw, "list.activeSelectionForeground",
              "list.inactiveSelectionForeground"),
        text)
    input_bg = _solid(
        _pick(raw, "input.background", "dropdown.background"),
        _mix(bg, text, 0.07))
    input_fg = _readable(
        input_bg,
        _pick(raw, "input.foreground", "dropdown.foreground"),
        text)
    accent = _solid(
        _pick(raw, "focusBorder", "activityBarBadge.background",
              "badge.background", "textLink.foreground"),
        defaults["accent"])
    button_bg = _solid(_pick(raw, "button.background"), accent)
    button_fg = _readable(
        button_bg,
        _pick(raw, "button.foreground"),
        defaults["button_fg"])
    muted_preferred = _solid(
        _pick(raw, "editorLineNumber.foreground", "descriptionForeground",
              "disabledForeground"),
        _mix(text, bg, 0.35))
    muted = muted_preferred if _contrast(muted_preferred, bg) >= 3.0 else _mix(text, bg, 0.20)
    danger = _readable(
        bg,
        _pick(raw, "errorForeground", "terminal.ansiRed"),
        defaults["danger"])

    if ui_theme in ("hc-black", "hc-light"):
        hc_bg = "#000000" if ui_theme == "hc-black" else "#ffffff"
        hc_fg = "#ffffff" if ui_theme == "hc-black" else "#000000"
        bg = hc_bg
        text = hc_fg
        sidebar = hc_bg
        activity = hc_bg
        activity_fg = hc_fg
        status_bg = hc_bg
        status_fg = hc_fg
        panel = hc_bg
        border = hc_fg
        accent = hc_fg
        selection = hc_fg
        selection_fg = hc_bg
        input_bg = hc_bg
        input_fg = hc_fg
        muted = hc_fg

    colors = {
        "bg": bg,
        "text": text,
        "sidebar": sidebar,
        "activity": activity,
        "activity_fg": activity_fg,
        "status_bg": status_bg,
        "status_fg": status_fg,
        "panel": panel,
        "border": border,
        "subtle_border": _mix(bg, border, 0.55),
        "hover": hover,
        "selection": selection,
        "selection_fg": selection_fg,
        "input_bg": input_bg,
        "input_fg": input_fg,
        "placeholder": _mix(input_fg, input_bg, 0.38),
        "button_bg": button_bg,
        "button_fg": button_fg,
        "accent": accent,
        "muted": muted,
        "danger": danger,
    }
    # 日志与状态使用固定语义色，只随明暗主题调整亮度，避免终端 ANSI 色
    # 因对比度不足而全部退化成黑色。
    if dark:
        log_colors = {"info": "#75beff", "ok": "#73c991", "warn": "#d7ba7d",
                      "err": "#f14c4c", "prog": "#4fc1ff"}
        status_colors = {"status_online": "#4ade80", "status_warning": "#facc15",
                         "status_unknown": "#a3a3a3", "status_error": "#f87171"}
    else:
        log_colors = {"info": "#005a9c", "ok": "#2e7d32", "warn": "#8a6200",
                      "err": "#c62828", "prog": "#00778f"}
        status_colors = {"status_online": "#16825d", "status_warning": "#f2b84b",
                         "status_unknown": "#777d86", "status_error": "#c62828"}
    colors.update(log_colors)
    colors.update(status_colors)

    icons = {}
    icon_json_path = _find_icon_theme(icon_id) if icon_id else None
    if icon_json_path:
        icon_data = _load_jsonc(icon_json_path)
        icons["folder"] = _copy_icon(icon_json_path, icon_data.get("folder", ""),
                                     "folder.svg", icon_data)
        icons["folderOpen"] = _copy_icon(icon_json_path, icon_data.get("folderExpanded", ""),
                                         "folder-open.svg", icon_data)
        icons["file"] = _copy_icon(icon_json_path, icon_data.get("file", ""),
                                   "file.svg", icon_data)
    icons = {k: v for k, v in icons.items() if v}

    # VS Code 自带 codicon 字体
    for name in ("codicon.css", "codicon.ttf"):
        src = CODICON / name
        if src.is_file():
            shutil.copy2(src, ASSET_DIR / name)

    return {
        "id": selected["id"] if selected else "",
        "name": selected["label"] if selected else "fallback",
        "dark": dark,
        "colors": colors,
        "icons": icons,
    }


if __name__ == "__main__":
    print(json.dumps(load(), ensure_ascii=False, indent=2))
