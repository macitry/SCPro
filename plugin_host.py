#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCPro 插件宿主。

插件就是一个目录，里面放 `plugin.json` 和一个 Python 入口：

    plugins/mem-monitor/
    ├── plugin.json     # 元数据：id / name / icon / panel ...
    ├── plugin.py       # class Plugin，实现 on_load / handle / on_unload
    └── panel.html      # 可选：webview 面板（在 iframe 里运行）

宿主负责：发现插件、加载、把 `plugin/<id>/<action>` 命令转发给插件、
把插件的事件回推给前端 webview。插件与主程序共享一个进程，
但不允许直接改前端 DOM——只能通过 context.ui() 发事件，保证隔离。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from pathlib import Path

MANIFEST_NAME = "plugin.json"


def _read_json(path: Path, default=None):
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


class PluginContext:
    """插件拿到的全部能力都从这里来，避免插件直接摸主窗口。"""

    def __init__(self, host: "PluginHost", plugin_id: str, plugin_dir: Path,
                 manifest: dict) -> None:
        self.host = host
        self.id = plugin_id
        self.dir = plugin_dir
        self.manifest = manifest
        self._settings_path = (host.data_dir / plugin_id / "settings.json")
        self._settings = _read_json(self._settings_path, {}) or {}

    # ---- 事件 / 日志 ----
    def ui(self, event: str, data=None) -> None:
        """推一条事件给插件自己的 webview（前端会转成 postMessage）。"""
        self.host.emit(self.id, event, data)

    def log(self, text: str) -> None:
        self.host.bridge.log(str(text))

    # ---- 设置 ----
    @property
    def settings(self) -> dict:
        return self._settings

    def save_settings(self, updates: dict) -> dict:
        self._settings.update(updates or {})
        try:
            self._settings_path.parent.mkdir(parents=True, exist_ok=True)
            with self._settings_path.open("w", encoding="utf-8") as handle:
                json.dump(self._settings, handle, ensure_ascii=False, indent=2)
        except OSError as exc:
            self.log("[WARN] 插件 %s 保存设置失败: %s" % (self.id, exc))
        return self._settings

    # ---- 环境 ----
    @property
    def lang(self) -> str:
        return self.host.lang()

    @property
    def app_dir(self) -> Path:
        return self.host.app_dir

    def panel_url(self) -> str:
        return self.host.panel_url(self.id)


class PluginHost:
    """插件注册表：发现 → 加载 → 分发。"""

    def __init__(self, bridge, app_dir: Path, web_dir: Path,
                 data_dir: Path, extra_dirs=()):
        self.bridge = bridge
        self.app_dir = Path(app_dir)
        self.web_dir = Path(web_dir)
        self.data_dir = Path(data_dir)
        self.search_dirs = [self.app_dir / "plugins"]
        self.search_dirs += [Path(p) for p in extra_dirs if p]
        self.manifests = {}   # id -> (dir, manifest)
        self.plugins = {}     # id -> Plugin 实例
        self.errors = {}      # id -> 错误信息

    # ---- 发现与加载 ----
    def discover(self) -> None:
        for base in self.search_dirs:
            if not base.is_dir():
                continue
            for child in sorted(base.iterdir()):
                manifest = _read_json(child / MANIFEST_NAME)
                if not isinstance(manifest, dict) or not child.is_dir():
                    continue
                plugin_id = str(manifest.get("id") or child.name).strip()
                if not plugin_id or plugin_id in self.manifests:
                    continue
                self.manifests[plugin_id] = (child, manifest)

    def load_all(self) -> None:
        self.discover()
        for plugin_id, (plugin_dir, manifest) in self.manifests.items():
            try:
                self._load_one(plugin_id, plugin_dir, manifest)
            except Exception as exc:  # 单个插件失败不影响主程序
                self.errors[plugin_id] = "%s: %s" % (type(exc).__name__, exc)
                self.bridge.log("[ERROR] 插件 %s 加载失败: %s\n%s" % (
                    plugin_id, exc, traceback.format_exc(limit=3)))

    def _load_one(self, plugin_id: str, plugin_dir: Path, manifest: dict) -> None:
        entry = plugin_dir / str(manifest.get("entry") or "plugin.py")
        if not entry.is_file():
            raise FileNotFoundError("找不到入口文件 %s" % entry)
        if str(plugin_dir) not in sys.path:
            sys.path.insert(0, str(plugin_dir))
        module_name = "scpro_plugin_%s" % plugin_id.replace("-", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(module_name, entry)
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        factory = getattr(module, "Plugin", None)
        if factory is None:
            raise AttributeError("plugin.py 里没有 class Plugin")
        context = PluginContext(self, plugin_id, plugin_dir, manifest)
        instance = factory(context)
        if hasattr(instance, "on_load"):
            instance.on_load()
        self.plugins[plugin_id] = instance
        self.bridge.log("[INFO] 已加载插件 %s v%s" % (
            manifest.get("name") or plugin_id, manifest.get("version") or "?"))

    # ---- 描述（给前端建按钮） ----
    def describe(self) -> list:
        result = []
        for plugin_id, (plugin_dir, manifest) in self.manifests.items():
            error = self.errors.get(plugin_id, "")
            result.append({
                "id": plugin_id,
                "name": manifest.get("name") or plugin_id,
                "name_en": manifest.get("name_en") or manifest.get("name") or plugin_id,
                "version": manifest.get("version") or "",
                "description": manifest.get("description") or "",
                "description_en": manifest.get("description_en") or "",
                "icon": manifest.get("icon") or "extensions",
                "url": self.panel_url(plugin_id),
                "error": error,
            })
        return result

    def panel_url(self, plugin_id: str) -> str:
        item = self.manifests.get(plugin_id)
        if not item:
            return ""
        plugin_dir, manifest = item
        panel = plugin_dir / str(manifest.get("panel") or "panel.html")
        try:
            rel = os.path.relpath(str(panel), str(self.web_dir))
        except ValueError:
            rel = str(panel)
        return rel.replace(os.sep, "/")

    # ---- 分发 ----
    def handle(self, command: str, payload: dict) -> None:
        """command 形如 plugin/<id>/<action>（前端拼在 scpro:// 的路径里）。"""
        parts = [p for p in command.split("/") if p]
        if len(parts) < 3:
            self.bridge.log("[WARN] 无效的插件命令: %s" % command)
            return
        plugin_id, action = parts[1], parts[2]
        plugin = self.plugins.get(plugin_id)
        if plugin is None:
            self.emit(plugin_id, "error", {
                "error": self.errors.get(plugin_id) or "插件未加载: %s" % plugin_id,
                "action": action,
            })
            return
        try:
            plugin.handle(action, payload or {})
        except Exception as exc:
            self.bridge.log("[ERROR] 插件 %s 处理 %s 失败: %s\n%s" % (
                plugin_id, action, exc, traceback.format_exc(limit=4)))
            self.emit(plugin_id, "error", {"action": action, "error": str(exc)})

    def emit(self, plugin_id: str, event: str, data) -> None:
        self.bridge._js("window.scproPluginEvent", {
            "plugin": plugin_id,
            "event": event,
            "data": data,
        })

    def shutdown(self) -> None:
        for plugin in self.plugins.values():
            try:
                if hasattr(plugin, "on_unload"):
                    plugin.on_unload()
            except Exception:
                pass
        self.plugins.clear()

    def lang(self) -> str:
        return str(self.bridge.app_settings.get("language", "zh"))
