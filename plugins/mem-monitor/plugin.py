#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""内存监控插件：定时采样 → 推给 webview；接收回收/清理命令。

宿主约定：
    Plugin(context)
        on_load()            加载完成
        handle(action, p)    前端 plugin/mem-monitor/<action> 命令
        on_unload()          退出时收尾

耗时操作（写 memory.reclaim / 等 polkit 授权）放到子线程，
结果通过 Qt 信号回到主线程再推给前端，避免界面卡住。
"""

from __future__ import annotations

import threading
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

import mem_core as core

DEFAULT_INTERVAL = 3
MIN_MB = 4.0


class Plugin(QObject):
    sampled = pyqtSignal(dict)
    finished = pyqtSignal(dict)

    def __init__(self, context) -> None:
        super().__init__()
        self.ctx = context
        try:
            self.interval = int(context.settings.get("interval", DEFAULT_INTERVAL))
        except (TypeError, ValueError):
            self.interval = DEFAULT_INTERVAL
        self.interval = max(1, min(60, self.interval))
        self.active = False
        self.busy = False
        self.last_snapshot = {}
        self.timer = QTimer(self)
        self.timer.setInterval(self.interval * 1000)
        self.timer.timeout.connect(self._tick)
        self.sampled.connect(self._push_snapshot)
        self.finished.connect(self._on_finished)

    # ---- 生命周期 ----
    def on_load(self) -> None:
        self.ctx.log("[INFO] 内存监控插件已就绪（cgroup v2: %s）"
                     % ("可用" if (core.CGROUP_ROOT / "memory.reclaim").exists()
                        else "缺少 memory.reclaim"))

    def on_unload(self) -> None:
        self.timer.stop()

    # ---- 命令入口 ----
    def handle(self, action: str, payload: dict) -> None:
        if action == "activate":
            self.active = True
            self.timer.start()
            self._tick()
        elif action == "deactivate":
            self.active = False
            self.timer.stop()
        elif action == "snapshot":
            self._tick()
        elif action == "reclaim":
            cgroups = payload.get("cgroups") or []
            amount = int(payload.get("mbytes") or 512)
            self._spawn("reclaim", core.reclaim, cgroups, amount)
        elif action == "drop":
            level = int(payload.get("level") or 3)
            self._spawn("drop", core.drop_caches, level)
        elif action == "set-interval":
            try:
                seconds = int(payload.get("seconds") or DEFAULT_INTERVAL)
            except (TypeError, ValueError):
                seconds = DEFAULT_INTERVAL
            self.interval = max(1, min(60, seconds))
            self.timer.setInterval(self.interval * 1000)
            self.ctx.save_settings({"interval": self.interval})
            self._tick()
        elif action == "ping":
            self.ctx.ui("pong", {"ts": time.time()})

    # ---- 采样 ----
    def _tick(self) -> None:
        if self.busy:
            return
        try:
            data = core.snapshot(MIN_MB)
        except Exception as exc:  # 采样失败也要让前端看到原因
            self.ctx.ui("error", {"action": "snapshot", "error": str(exc)})
            return
        data["interval"] = self.interval
        data["busy"] = self.busy
        self.last_snapshot = data
        self.sampled.emit(data)

    def _push_snapshot(self, data: dict) -> None:
        self.ctx.ui("snapshot", data)

    # ---- 清理（子线程） ----
    def _spawn(self, action: str, func, *args) -> None:
        if self.busy:
            self.ctx.ui("busy", {"busy": True})
            return
        self.busy = True
        self.ctx.ui("busy", {"busy": True, "action": action})

        def worker():
            try:
                result = func(*args)
            except Exception as exc:
                result = {"ok": False, "error": "%s: %s" % (type(exc).__name__, exc)}
            result = dict(result or {})
            result["action"] = action
            result["ts"] = time.time()
            self.finished.emit(result)

        threading.Thread(target=worker, daemon=True).start()

    def _on_finished(self, result: dict) -> None:
        self.busy = False
        self.ctx.ui("clean", result)
        self._tick()
