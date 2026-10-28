#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCPro —— QtWebEngine + HTML/CSS 的 VS Code 风格界面

与命令行共用同一套配置和 deploy_one.sh，不依赖旧版图形界面。
JS -> Python 用自定义协议 scpro://，Python -> JS 用 runJavaScript，
不依赖 QWebChannel。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import fcntl
import datetime
import codecs
from pathlib import Path
from urllib.parse import parse_qsl

from PyQt5.QtCore import (QEvent, QPoint, QProcess, QProcessEnvironment, QRect,
                          Qt, QTimer, QUrl)
from PyQt5.QtGui import QColor, QDesktopServices, QIcon, QPalette
from PyQt5.QtWebEngineWidgets import (QWebEnginePage, QWebEngineSettings,
                                      QWebEngineView)
from PyQt5.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow,
                             QMenu, QMessageBox, QPushButton, QSystemTrayIcon,
                             QVBoxLayout, QWidget)

import backend
import vscode_theme

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
ICON_SVG = APP_DIR / "scpro.svg"
VERSION = "2.1.0"
APP_SETTINGS = backend.core.SETTINGS_JSON
AUTOSTART_FILE = Path.home() / ".config" / "autostart" / "scpro.desktop"
LOG_DIR = backend.core.STATE_DIR
LOG_KEEP_FILES = 30
MAX_TASK_OUTPUT = 1_000_000
TASK_IDLE_TIMEOUT_MS = 10 * 60 * 1000
STOP_GRACE_MS = 5_000
CONNECTION_FAILURE_RE = re.compile(
    r"Connection refused|No route to host|Connection timed out|"
    r"Network is unreachable|Could not resolve|Host key verification failed|"
    r"Too many authentication failures|"
    r"Permission denied \([^)]*(publickey|password|keyboard-interactive)[^)]*\)",
    re.I,
)
_INSTANCE_LOCK = None


def load_app_settings() -> dict:
    defaults = {
        "notify": True,
        "window": [1280, 820],
        "panel_h": 228,
        "language": "zh",
        "delete_remote": False,
        "theme_id": "",
    }
    try:
        data = json.loads(APP_SETTINGS.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            defaults.update(data)
    except Exception:
        pass
    return defaults


def save_app_settings(updates: dict) -> None:
    data = load_app_settings()
    data.update(updates)
    try:
        APP_SETTINGS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
    except OSError:
        pass


def prune_old_logs(keep: int = LOG_KEEP_FILES) -> None:
    """只保留最近若干次运行的日志，避免长期使用后无限堆积。"""
    try:
        logs = sorted(
            LOG_DIR.glob("scpro_*.log"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        for path in logs[keep:]:
            path.unlink(missing_ok=True)
    except OSError:
        pass


def title_style(colors: dict) -> str:
    """标题栏跟着 VS Code 主题走（Qt 不支持 #RRGGBBAA，hover 用 6 位色）"""
    return """
QWidget#titleBar {{ background: {activity}; border-bottom: 1px solid {border}; }}
QLabel#titleText {{ color: {text}; font-size: 12px; }}
QPushButton#winBtn {{
    color: {fg}; background: transparent; border: none;
    font-size: 13px; min-width: 34px; max-width: 34px;
}}
QPushButton#winBtn:hover {{ background: {hover}; }}
QPushButton#closeBtn {{
    color: {fg}; background: transparent; border: none;
    font-size: 13px; min-width: 34px; max-width: 34px;
}}
QPushButton#closeBtn:hover {{ background: {danger}; color: white; }}
""".format(activity=colors["activity"], border=colors["border"],
           text=colors["text"], fg=colors["activity_fg"],
           hover=colors["selection"], danger=colors["danger"])


class TitleBar(QWidget):
    """VS Code 风深色标题栏：拖动 / 最大化 / 关闭"""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__(window)
        self.window_ref = window
        self.setObjectName("titleBar")
        self.setFixedHeight(34)
        self.setMouseTracking(True)
        self._drag_offset = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 0, 0)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(QIcon(str(ICON_SVG)).pixmap(16, 16))
        icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(icon)
        title = QLabel("SCPro")
        title.setObjectName("titleText")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(title)
        layout.addStretch(1)
        for text, slot, name in (("─", window.showMinimized, "winBtn"),
                                 ("□", window.toggle_maximized, "winBtn"),
                                 ("✕", window.close, "closeBtn")):
            button = QPushButton(text)
            button.setObjectName(name)
            button.setCursor(Qt.ArrowCursor)
            button.clicked.connect(slot)
            layout.addWidget(button)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            if self.window_ref._start_resize_if_edge(event):
                return
            if self.window_ref.isMaximized():
                self.window_ref.showNormal()
                self._drag_offset = QPoint(self.window_ref.width() // 2, 16)
            else:
                self._drag_offset = (event.globalPos()
                                     - self.window_ref.frameGeometry().topLeft())
            # X11 下 startSystemMove 不一定被 WM 响应，直接手动移动更可靠
            if not QApplication.platformName().startswith("xcb"):
                handle = self.window_ref.windowHandle()
                if handle is not None:
                    handle.startSystemMove()
                self._drag_offset = None
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.window_ref._resize_edges and event.buttons() & Qt.LeftButton:
            self.window_ref._perform_resize(event)
            event.accept()
            return
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.window_ref.move(event.globalPos() - self._drag_offset)
            event.accept()
            return
        self.window_ref._update_cursor_for_edge(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._drag_offset = None
        self.window_ref._end_resize()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.window_ref.toggle_maximized()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class Bridge:
    """处理前端命令，并把结果/日志推回页面"""

    def __init__(self, window: "MainWindow") -> None:
        self.window_ref = window
        self.queue: list[str] = []
        self.proc: QProcess | None = None
        self.test_proc: QProcess | None = None
        self.total = 0
        self.done = 0
        self.current = ""
        self.buffer = ""
        self.queue_host = ""
        self.task_output = ""
        self.host_status = {}
        self.failed_projects = []
        self.cancelled_projects = []
        self.app_settings = load_app_settings()
        self.fail_count = 0
        self.success_count = 0
        self.log_path = None
        self.stopping = False
        self.stop_reason = ""
        self.decoder = None
        self.idle_timer = QTimer(self.window_ref)
        self.idle_timer.setSingleShot(True)
        self.idle_timer.timeout.connect(self._on_idle_timeout)
        self.stop_timer = QTimer(self.window_ref)
        self.stop_timer.setSingleShot(True)
        self.stop_timer.timeout.connect(self._force_stop)

    # ---- 推送 ----
    def _js(self, fn: str, payload) -> None:
        page = self.window_ref.page
        if page is None:
            return
        page.runJavaScript("%s(%s);" % (fn, json.dumps(payload, ensure_ascii=False)))

    def log(self, text: str) -> None:
        for line in str(text).split("\n"):
            self._js("window.scproLog", line)
            try:
                if self.log_path is None:
                    LOG_DIR.mkdir(parents=True, exist_ok=True)
                    prune_old_logs()
                    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                    self.log_path = LOG_DIR / ("scpro_%s.log" % stamp)
                with open(self.log_path, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass

    def push_state(self) -> None:
        try:
            state = backend.snapshot()
        except Exception as exc:
            self.log("[ERROR] 读取配置失败: %s" % exc)
            return
        for host in state.get("hosts", []):
            host["status"] = self.host_status.get(host["alias"], "unknown")
        self._js("window.scproState", state)
        if hasattr(self.window_ref, "build_tray_menu"):
            try:
                self.window_ref.build_tray_menu(state)
            except Exception:
                pass

    def push_status(self, state: str, done: int = 0, total: int = 0) -> None:
        self._js("window.scproStatus", {"state": state, "done": done, "total": total})
        if getattr(self.window_ref, "tray", None) is not None:
            self.window_ref.tray.setToolTip(
                "SCPro — 执行中…" if state == "running"
                else "SCPro — %s" % (self.queue_host or "no host"))

    # ---- 接收 ----
    def handle(self, command: str, params: dict) -> None:
        data = params.get("data", "")
        try:
            payload = json.loads(data) if data else {}
        except ValueError:
            payload = {}

        if command == "get-state":
            self.push_state()
        elif command == "set-host":
            self._set_host(str(payload.get("host", "")))
        elif command == "refresh":
            self._refresh()
        elif command == "run":
            self._run(payload.get("projects") or [])
        elif command == "stop":
            self.stop()
        elif command == "test":
            self._test_connection()
        elif command == "new-project":
            self._project_data("")
        elif command == "edit-project":
            self._project_data(str(payload.get("name", "")))
        elif command == "passwords":
            QTimer.singleShot(0, self._secrets_data)
        elif command == "save-secrets":
            self._save_secrets(payload.get("values") or {})
        elif command == "move-project":
            self._move_project(str(payload.get("name", "")), int(payload.get("delta", 0)))
        elif command == "settings":
            self._settings_data()
        elif command == "save-settings":
            self._save_settings(payload)
        elif command == "hosts-data":
            self._hosts_data()
        elif command == "save-hosts":
            self._save_hosts(payload)
        elif command == "add-host":
            self._add_host(payload)
        elif command == "delete-host":
            self._delete_host(str(payload.get("alias", "")))
        elif command == "copy-project":
            self._copy_project(str(payload.get("name", "")))
        elif command == "delete-project":
            self._delete_project(str(payload.get("name", "")))
        elif command == "preflight":
            self._preflight(payload.get("projects") or [])
        elif command == "save-ui":
            self._save_ui(payload)
        elif command == "open-log-dir":
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_DIR)))
        elif command == "clear-cache":
            self._clear_upload_cache()
        elif command == "reorder-projects":
            self._reorder_projects(payload.get("order") or [])
        elif command == "update-host-key":
            self._update_host_key(str(payload.get("alias", "")))
        elif command == "reload-theme":
            self.window_ref.reload_theme()
        elif command == "project-data":
            self._project_data(str(payload.get("name", "")))
        elif command == "list-dir":
            self._list_dir(str(payload.get("path", "")))
        elif command == "choose-dir":
            current = str(payload.get("current", ""))
            QTimer.singleShot(0, lambda c=current: self._choose_dir(c))
        elif command == "save-project":
            self._save_project(payload)

    def _set_host(self, alias: str) -> None:
        if not alias:
            return
        if self.proc is not None:
            self.log("[WARN] 任务执行中，暂不能切换 Host")
            self.push_state()
            return
        try:
            backend.set_host(alias)
            self.log("[INFO] 目标 Host 已切换为 %s" % alias)
        except Exception as exc:
            self.log("[ERROR] 切换 Host 失败: %s" % exc)
        self.push_state()

    def _refresh(self) -> None:
        try:
            info = backend.refresh_hosts()
            if info.get("direction") == "bundled-to-system":
                self.log("[INFO] 未找到 ~/.ssh/config，已用项目自带配置初始化")
            else:
                self.log("[INFO] 已从 ~/.ssh/config 同步 Host 列表，并更新项目内副本")
            if info.get("added"):
                self.log("[INFO] 新增 Host: %s" % ", ".join(info["added"]))
            if info.get("removed"):
                self.log("[WARN] 移除 Host: %s" % ", ".join(info["removed"]))
        except Exception as exc:
            self.log("[ERROR] 刷新失败: %s" % exc)
        self.push_state()

    # ---- 部署队列 ----
    def _run(self, projects: list) -> None:
        if self.proc is not None:
            self.log("[WARN] 已有任务在执行中")
            return
        state = backend.snapshot()
        host = state.get("current_host", "")
        allowed = {p["id"] for p in state.get("projects", []) if p.get("remote")}
        self.queue = [p for p in projects if p in allowed]
        if not self.queue:
            self.log("[WARN] 没有可上传的项目")
            return
        self.total, self.done = len(self.queue), 0
        self.fail_count = 0
        self.success_count = 0
        self.failed_projects = []
        self.cancelled_projects = []
        self.stopping = False
        self.stop_reason = ""
        self.queue_host = host
        self.push_status("running", 0, self.total)
        self._start_next()

    def _start_next(self) -> None:
        if not self.queue:
            self.push_status("done", self.done, self.total)
            self.log("[INFO] 全部结束：成功 %d，失败 %d，共完成 %d/%d 个任务"
                     % (self.success_count, self.fail_count, self.done, self.total))
            self._js("window.scproSummary", {
                "ok": self.success_count,
                "fail": len(self.failed_projects),
                "failed": list(self.failed_projects),
                "cancelled": 0,
                "total": self.total,
            })
            if self.app_settings.get("notify", True):
                self.window_ref.tray.showMessage(
                    "SCPro",
                    "完成：成功 %d，失败 %d" % (self.success_count, self.fail_count),
                    QSystemTrayIcon.Information if self.fail_count == 0
                    else QSystemTrayIcon.Warning, 4000)
            return
        project = self.queue.pop(0)
        self.current = project
        host = self.queue_host or backend.snapshot().get("current_host", "")
        args = backend.deploy_args(
            project, host, bool(self.app_settings.get("delete_remote", False)))
        cmd = (["setsid"] if shutil.which("setsid") else []) + args
        self.log("")
        self.log("=========== [开始] %s ===========" % project)
        self.log("$ " + " ".join(cmd))
        self.buffer = ""
        self.task_output = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

        self.proc = QProcess(self.window_ref)
        self.proc.setWorkingDirectory(str(backend.APP_DIR))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        # 让部署引擎与界面使用同一套配置/缓存目录（XDG 或便携模式）
        env.insert("SCPRO_CONFIG_DIR", str(backend.core.CONFIG_DIR))
        env.insert("SCPRO_UPLOAD_DIR", str(backend.core.UPLOAD_DIR))
        env.insert("SCPRO_PORTABLE", "1" if backend.core.PORTABLE else "0")
        self.proc.setProcessEnvironment(env)
        self.proc.readyReadStandardOutput.connect(self._read_output)
        self.proc.errorOccurred.connect(self._on_process_error)
        self.proc.finished.connect(self._on_finished)
        self.proc.start(cmd[0], cmd[1:])
        self.idle_timer.start(TASK_IDLE_TIMEOUT_MS)

    def _feed_output(self, text: str) -> None:
        if not text:
            return
        self.task_output = (self.task_output + text)[-MAX_TASK_OUTPUT:]
        self.buffer += text
        lines = self.buffer.split("\n")
        self.buffer = lines.pop()
        for line in lines:
            if line.strip():
                self.log(line)

    def _read_output(self) -> None:
        if self.proc is None:
            return
        raw = bytes(self.proc.readAllStandardOutput())
        text = self.decoder.decode(raw, final=False) if self.decoder else raw.decode(
            "utf-8", errors="replace")
        self._feed_output(text.replace("\r\n", "\n").replace("\r", "\n"))
        self.idle_timer.start(TASK_IDLE_TIMEOUT_MS)

    def _on_finished(self, code: int, _status) -> None:
        if self.proc is None:
            return
        process = self.proc
        self.proc = None
        if self.decoder is not None:
            self._feed_output(self.decoder.decode(b"", final=True))
            self.decoder = None
        if self.buffer.strip():
            self.log(self.buffer.strip())
        self.buffer = ""
        self.idle_timer.stop()
        self.stop_timer.stop()
        cancelled = self.stopping
        if cancelled:
            self.cancelled_projects = [self.current] + list(self.queue)
            self.queue = []
            self.log("[WARN] [取消] %s：%s" %
                     (self.current, self.stop_reason or "用户停止"))
        ok = code == 0
        if not cancelled and ok:
            self.success_count += 1
        elif not cancelled:
            self.fail_count += 1
            self.failed_projects.append(self.current)
        if not cancelled:
            if ok:
                self.host_status[self.queue_host] = "online"
            elif CONNECTION_FAILURE_RE.search(self.task_output):
                self.host_status[self.queue_host] = "offline"
        result = "取消" if cancelled else ("完成" if ok else "失败")
        self.log("=========== [%s] %s ===========" % (result, self.current))
        if not ok and not cancelled and "HOST IDENTIFICATION HAS CHANGED" in self.task_output.upper():
            found = re.search(r"SHA256:[A-Za-z0-9+/=]+", self.task_output)
            self._js("window.scproHostKey", {
                "alias": self.queue_host,
                "fingerprint": found.group(0) if found else "",
            })
        process.deleteLater()
        self.done += 1
        self.push_state()
        if cancelled:
            reason = self.stop_reason or "用户停止"
            self.stopping = False
            self.stop_reason = ""
            self.push_status("cancelled", self.done, self.total)
            self.log("[INFO] 已取消：已处理 %d/%d，取消 %d 个任务"
                     % (self.done, self.total, len(self.cancelled_projects)))
            self._js("window.scproSummary", {
                "ok": self.success_count,
                "fail": len(self.failed_projects),
                "failed": list(self.failed_projects),
                "cancelled": len(self.cancelled_projects),
                "total": self.total,
            })
            if self.app_settings.get("notify", True):
                self.window_ref.tray.showMessage(
                    "SCPro", "任务已取消：%s" % reason,
                    QSystemTrayIcon.Warning, 4000)
            return
        self.push_status("running", self.done, self.total)
        QTimer.singleShot(150, self._start_next)

    def stop(self) -> None:
        self._request_stop("用户停止")

    def _request_stop(self, reason: str) -> None:
        if self.proc is None:
            return
        if self.stopping:
            return
        self.stopping = True
        self.stop_reason = reason
        pid = int(self.proc.processId())
        try:
            if pid <= 0:
                raise OSError("无效进程号")
            os.killpg(os.getpgid(pid), 15)
        except OSError:
            self.proc.terminate()
        self.stop_timer.start(STOP_GRACE_MS)
        self.log("[WARN] 已请求停止当前任务：%s" % reason)

    def _on_idle_timeout(self) -> None:
        minutes = TASK_IDLE_TIMEOUT_MS // 60000
        self._request_stop("超过 %d 分钟没有新输出" % minutes)

    def _on_process_error(self, error) -> None:
        if self.proc is None:
            return
        if error == QProcess.FailedToStart:
            self.log("[ERROR] 无法启动部署进程，请检查 Python、Bash 和部署脚本")
            self._on_finished(-1, QProcess.CrashExit)

    def _force_stop(self) -> None:
        if self.proc is None:
            return
        self.log("[WARN] 任务未在宽限期内退出，正在强制结束")
        pid = int(self.proc.processId())
        try:
            if pid <= 0:
                raise OSError("无效进程号")
            os.killpg(os.getpgid(pid), 9)
        except OSError:
            self.proc.kill()

    # ---- 连接测试 ----
    def _test_connection(self) -> None:
        if self.test_proc is not None:
            self.log("[WARN] 正在测试中")
            return
        state = backend.snapshot()
        alias = state.get("current_host", "")
        info = next((h for h in state.get("hosts", []) if h["alias"] == alias), None)
        if not info:
            self.log("[ERROR] 当前没有可选 Host")
            return
        secret_key = backend.host_secret_key(alias)
        secret = str(backend.core.read_secrets().get(secret_key) or "")
        auth = (["-o", "NumberOfPasswordPrompts=1"] if secret
                else ["-o", "BatchMode=yes"])
        args = (["-p", str(info["port"]), "-o", "ConnectTimeout=5",
                 "-o", "StrictHostKeyChecking=accept-new"] + auth
                + ["%s@%s" % (info["user"], info["host"]), "echo ok"])
        env = QProcessEnvironment.systemEnvironment()
        if secret and shutil.which("sshpass"):
            env.insert("SSHPASS", secret)
            program, args = "sshpass", ["-e", "ssh"] + args
        else:
            program = "ssh"
        self.log("[INFO] 测试连接: %s  %s@%s:%s" %
                 (alias, info["user"], info["host"], info["port"]))
        self.log("$ %s %s" % (program, " ".join(args)))

        self.test_proc = QProcess(self.window_ref)
        self.test_proc.setProcessEnvironment(env)
        self.test_proc.setProcessChannelMode(QProcess.MergedChannels)

        def done(code, _status):
            out = bytes(self.test_proc.readAllStandardOutput()).decode(
                "utf-8", errors="replace").strip()
            for line in out.splitlines():
                if line.strip():
                    self.log(line)
            if code == 0 and "ok" in out:
                self.log("[OK]   %s 连接正常" % alias)
                self.host_status[alias] = "online"
            else:
                self.log("[失败] %s 连接失败（退出码 %d）" % (alias, code))
                self.host_status[alias] = "offline"
                if "HOST IDENTIFICATION HAS CHANGED" in out.upper():
                    found = re.search(r"SHA256:[A-Za-z0-9+/=]+", out)
                    self._js("window.scproHostKey", {
                        "alias": alias,
                        "fingerprint": found.group(0) if found else "",
                    })
            self.test_proc.deleteLater()
            self.test_proc = None
            self.push_state()

        self.test_proc.finished.connect(done)
        self.test_proc.start(program, args)

    def _move_project(self, name: str, delta: int) -> None:
        if self.proc is not None or not name or not delta:
            return
        order = [p.title for p in backend.core.load_projects()]
        if name not in order:
            return
        index = order.index(name)
        target = index + delta
        if not 0 <= target < len(order):
            return
        order[index], order[target] = order[target], order[index]
        try:
            backend.core.reorder_projects(order)
            self.log("[INFO] 项目顺序：%s 移到第 %d 位" % (name, target + 1))
        except Exception as exc:
            self.log("[ERROR] 调整顺序失败: %s" % exc)
        self.push_state()

    def _reorder_projects(self, order: list) -> None:
        if self.proc is not None or not order:
            return
        names = [p.title for p in backend.core.load_projects()]
        if sorted(str(x) for x in order) != sorted(names):
            self.log("[ERROR] 排序失败：项目列表已变化，请重试")
            return
        try:
            backend.core.reorder_projects([str(x) for x in order])
            self.log("[INFO] 已按拖拽结果更新项目顺序")
        except Exception as exc:
            self.log("[ERROR] 排序失败: %s" % exc)
        self.push_state()

    def _update_host_key(self, alias: str) -> None:
        state = backend.snapshot()
        info = next((h for h in state.get("hosts", []) if h["alias"] == alias), None)
        if not info:
            return
        targets = [info["host"]]
        if str(info["port"]) != "22":
            targets.insert(0, "[%s]:%s" % (info["host"], info["port"]))
        for target in targets:
            try:
                result = subprocess.run(["ssh-keygen", "-R", target],
                                        capture_output=True, text=True, timeout=15)
            except Exception as exc:
                self.log("[ERROR] 删除旧主机记录失败: %s" % exc)
                return
            if result.returncode != 0:
                self.log("[ERROR] 删除旧主机记录失败: %s" % (result.stderr or result.stdout))
                return
            self.log("[INFO] 已移除旧主机记录: %s" % target)

        secret = str(backend.core.read_secrets().get(backend.host_secret_key(alias)) or "")
        cmd = ["ssh", "-p", str(info["port"]), "-o", "ConnectTimeout=5",
               "-o", "StrictHostKeyChecking=accept-new", "-o", "BatchMode=yes",
               "%s@%s" % (info["user"], info["host"]), "true"]
        env = os.environ.copy()
        if secret and shutil.which("sshpass"):
            env["SSHPASS"] = secret
            cmd = ["sshpass", "-e"] + cmd
        try:
            result = subprocess.run(cmd, capture_output=True, text=True,
                                    timeout=20, env=env)
        except Exception as exc:
            self.log("[ERROR] 接受新主机密钥失败: %s" % exc)
            return
        output = (result.stdout + result.stderr).strip()
        if "Host key verification failed" in output:
            self.log("[ERROR] 新主机密钥未被接受: %s" % output)
        else:
            self.log("[OK] 已接受 %s 的新主机密钥，可重新测试连接" % alias)

    # ---- 项目编辑（HTML 弹层）----
    def _project_data(self, name: str) -> None:
        core = backend.core
        data = core.load_yaml(core.PROJECTS_YAML)
        profiles = data.get("exclude_profiles") or {}
        projects = data.get("projects") or {}
        result = {
            "name": "",
            "local_src": "",
            "remote_name": "",
            "targets": [
                {"match": "*-mc", "base": "/home/robot/workspace", "subdir": "."},
                {"match": "*-ai", "base": "/home/robot/workspace", "subdir": "."},
            ],
            "template": "ros2_pkg" if "ros2_pkg" in profiles else next(iter(profiles), ""),
            "patterns": [],
            "profiles": list(profiles),
            "profile_items": profiles,
            "editing": False,
        }
        if name and name in projects:
            cfg = projects[name]
            raw = cfg.get("excludes")
            template = ""
            if isinstance(raw, str):
                template = raw
            elif isinstance(raw, dict):
                template = str(raw.get("use") or "")
            action = next((p for p in core.load_projects() if p.title == name), None)
            result.update({
                "name": name,
                "local_src": str(cfg.get("local_src") or ""),
                "remote_name": str(cfg.get("remote_name") or ""),
                "targets": [dict(x) for x in (cfg.get("targets") or [])],
                "template": template,
                "patterns": list(action.excludes) if action else [],
                "editing": True,
            })
        elif not result["patterns"]:
            result["patterns"] = [str(x) for x in (profiles.get(result["template"]) or [])]
        self._js("window.scproProjectData", result)

    def _list_dir(self, path: str) -> None:
        root = backend.core.resolve_local_src(path)
        entries = []
        error = ""
        try:
            items = sorted(os.scandir(root),
                           key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.lower()))
            for entry in items:
                is_dir = entry.is_dir(follow_symlinks=False)
                try:
                    size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                except OSError:
                    size = 0
                entries.append({"name": entry.name, "dir": is_dir, "size": size})
        except OSError as exc:
            error = "读取目录失败: %s" % exc
            self.log("[ERROR] %s（%s）" % (error, root))
        self._js("window.scproDirEntries",
                 {"path": path, "entries": entries, "error": error})

    def _choose_dir(self, current: str) -> None:
        from PyQt5.QtWidgets import QFileDialog
        start = backend.core.resolve_local_src(current) or str(backend.core.workspace_root())
        chosen = QFileDialog.getExistingDirectory(self.window_ref, "选择本地源码目录", start)
        path = backend.core.compact_local_src(chosen) if chosen else ""
        self._js("window.scproDirChosen", {"path": path})

    def _save_project(self, payload: dict) -> None:
        core = backend.core
        values = {
            "name": str(payload.get("name", "")).strip(),
            "local_src": str(payload.get("local_src", "")).strip(),
            "remote_name": str(payload.get("remote_name", "")).strip(),
            "targets": payload.get("targets") or [],
            "excludes": payload.get("excludes") or [],
        }
        old_name = str(payload.get("old_name", ""))
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", values["name"] or ""):
            self._js("window.scproSaveResult",
                     {"ok": False, "error": "项目名只能包含字母、数字、_ . -"})
            return
        src = core.resolve_local_src(values["local_src"])
        if not src or not os.path.isdir(src):
            self._js("window.scproSaveResult", {"ok": False, "error": "本地源码目录不存在"})
            return
        if not values["targets"]:
            self._js("window.scproSaveResult", {"ok": False, "error": "至少要有一条 Host 规则"})
            return
        try:
            if old_name:
                core.write_project(values, old_name)
            else:
                core.write_new_project(values)
        except Exception as exc:
            self._js("window.scproSaveResult", {"ok": False, "error": str(exc)})
            return
        self._js("window.scproSaveResult", {"ok": True})
        self.log("[INFO] 已保存项目: %s" % values["name"])
        self.push_state()

    # ---- 密码（HTML 弹层）----
    def _secrets_data(self) -> None:
        hosts = backend.core.load_hosts()
        secrets = backend.core.read_secrets()
        rows = []
        for alias, info in hosts.items():
            key = str(info.get("secret_key") or alias)
            rows.append({
                "alias": alias,
                "user": info.get("user", ""),
                "host": info.get("host", ""),
                "port": info.get("port", ""),
                "key": key,
                "value": str(secrets.get(key) or ""),
            })
        self._js("window.scproSecretsData", {"hosts": rows})

    def _save_secrets(self, values: dict) -> None:
        before = backend.core.read_secrets()
        changed = {str(k): str(v) for k, v in values.items()
                   if str(v) != str(before.get(k, ""))}
        if changed:
            try:
                backend.core.write_secrets(changed)
            except Exception as exc:
                self._js("window.scproSecretsSaved", {"ok": False, "error": str(exc)})
                return
            self.log("[INFO] 已保存 %d 项 SSH 密码" % len(changed))
        self._js("window.scproSecretsSaved", {"ok": True})
        self.push_state()

    # ---- 应用设置 ----
    def _settings_data(self) -> None:
        self._js("window.scproSettingsData", {
            "autostart": AUTOSTART_FILE.exists(),
            "notify": bool(self.app_settings.get("notify", True)),
            "suffix": backend.read_name_suffix(),
            "theme": self.window_ref.theme.get("name", ""),
            "theme_id": self.app_settings.get("theme_id", ""),
            "themes": vscode_theme.available_themes(),
            "language": self.app_settings.get("language", "zh"),
            "delete_remote": bool(self.app_settings.get("delete_remote", False)),
            "version": VERSION,
        })

    def _save_settings(self, payload: dict) -> None:
        notify = bool(payload.get("notify", True))
        suffix = str(payload.get("suffix", ""))
        autostart = bool(payload.get("autostart", False))
        delete_remote = bool(payload.get("delete_remote", False))
        theme_id = str(payload.get("theme_id", "")).strip()
        language = str(payload.get("language", "zh") or "zh")
        if language not in ("zh", "en"):
            language = "zh"
        try:
            if suffix != backend.read_name_suffix():
                backend.write_name_suffix(suffix)
            if autostart and not AUTOSTART_FILE.exists():
                AUTOSTART_FILE.parent.mkdir(parents=True, exist_ok=True)
                launcher = Path.home() / ".local" / "bin" / "scpro"
                exec_cmd = (str(launcher) if launcher.exists()
                            else "%s %s" % (sys.executable, APP_DIR / "main.py"))
                AUTOSTART_FILE.write_text(
                    "[Desktop Entry]\nType=Application\nName=SCPro\n"
                    "Exec=%s\nIcon=scpro\nTerminal=false\n"
                    "X-GNOME-Autostart-enabled=true\n" % exec_cmd,
                    encoding="utf-8")
            elif not autostart and AUTOSTART_FILE.exists():
                AUTOSTART_FILE.unlink()
            save_app_settings({
                "notify": notify,
                "language": language,
                "delete_remote": delete_remote,
                "theme_id": theme_id,
            })
            self.app_settings = load_app_settings()
        except Exception as exc:
            self._js("window.scproSettingsSaved", {"ok": False, "error": str(exc)})
            return
        self._js("window.scproSettingsSaved", {
            "ok": True,
            "language": language,
            "delete_remote": delete_remote,
            "theme_id": theme_id,
        })
        self.window_ref.reload_theme()
        self.log("[INFO] 设置已保存")
        self.push_state()

    # ---- Host 管理 ----
    def _hosts_data(self) -> None:
        cfg = backend.read_hosts_config()
        rows = []
        for alias, info in backend.core.load_hosts().items():
            rows.append({
                "alias": alias,
                "user": info.get("user", ""),
                "host": info.get("host", ""),
                "port": info.get("port", ""),
                "ssh_port": info.get("ssh_port", info.get("port", "")),
                "override": cfg["ports"].get(alias, ""),
            })
        self._js("window.scproHostsData", {
            "ignore": cfg["ignore"],
            "hosts": rows,
        })

    def _save_hosts(self, payload: dict) -> None:
        ignore = [str(x).strip() for x in (payload.get("ignore") or []) if str(x).strip()]
        ports = dict(backend.read_hosts_config()["ports"])
        try:
            for alias, port in (payload.get("ports") or {}).items():
                value = int(port)
                if not 1 <= value <= 65535:
                    raise ValueError("端口超出范围: %s" % alias)
                ports[str(alias)] = value
            for alias in payload.get("remove_ports") or []:
                ports.pop(str(alias), None)
            ports = {alias: int(port) for alias, port in ports.items()}
        except (TypeError, ValueError) as exc:
            self._js("window.scproHostsSaved", {"ok": False, "error": str(exc)})
            return
        try:
            backend.write_hosts_config(ignore, ports)
        except Exception as exc:
            self._js("window.scproHostsSaved", {"ok": False, "error": str(exc)})
            return
        self._js("window.scproHostsSaved", {"ok": True})
        self.log("[INFO] 已更新 Host 设置（忽略 %d 条，端口覆盖 %d 条）"
                 % (len(ignore), len(ports)))
        self.push_state()

    def _add_host(self, payload: dict) -> None:
        if self.proc is not None:
            self._js("window.scproHostAddResult",
                     {"ok": False, "error": "任务执行中，暂不能添加 Host"})
            return
        alias = str(payload.get("alias", "")).strip()
        try:
            backend.add_host(alias, str(payload.get("host", "")),
                             str(payload.get("user", "")),
                             str(payload.get("port", "22")))
        except Exception as exc:
            self._js("window.scproHostAddResult", {"ok": False, "error": str(exc)})
            return
        try:
            backend.core.sync_hosts()
        except Exception as exc:
            self.log("[WARN] 同步 ssh_config 副本失败: %s" % exc)
        try:
            backend.set_host(alias)
        except Exception as exc:
            self.log("[WARN] 切换当前 Host 失败: %s" % exc)
        self.log("[INFO] 已添加 Host: %s" % alias)
        self._js("window.scproHostAddResult", {"ok": True})
        self.push_state()

    def _delete_host(self, alias: str) -> None:
        if self.proc is not None:
            self._js("window.scproHostDeleted",
                     {"ok": False, "error": "任务执行中，暂不能删除 Host"})
            return
        try:
            backend.delete_host(alias)
        except Exception as exc:
            self._js("window.scproHostDeleted", {"ok": False, "error": str(exc)})
            return
        try:
            backend.core.sync_hosts()
        except Exception as exc:
            self.log("[WARN] 同步 ssh_config 副本失败: %s" % exc)
        if backend.core.read_current_host() == alias:
            remaining = [h["alias"] for h in backend.snapshot().get("hosts", [])]
            try:
                backend.set_host(remaining[0] if remaining else "")
            except Exception:
                pass
        self.log("[INFO] 已删除 Host: %s" % alias)
        self._js("window.scproHostDeleted", {"ok": True})
        self.push_state()

    def _copy_project(self, name: str) -> None:
        if self.proc is not None:
            return
        core = backend.core
        data = core.load_yaml(core.PROJECTS_YAML)
        projects = data.get("projects") or {}
        if name not in projects:
            return
        candidate = name + "_copy"
        index = 2
        while candidate in projects:
            candidate = "%s_copy%d" % (name, index)
            index += 1
        cfg = projects.get(name) or {}
        try:
            core.write_new_project({
                "name": candidate,
                "local_src": cfg.get("local_src"),
                "remote_name": cfg.get("remote_name"),
                "targets": cfg.get("targets"),
                "excludes": cfg.get("excludes"),
            })
            self.log("[INFO] 已复制项目 %s → %s" % (name, candidate))
        except Exception as exc:
            self.log("[ERROR] 复制项目失败: %s" % exc)
        self.push_state()

    def _delete_project(self, name: str) -> None:
        if self.proc is not None:
            return
        try:
            backend.delete_project(name)
            self.log("[INFO] 已删除项目: %s" % name)
        except Exception as exc:
            self.log("[ERROR] 删除项目失败: %s" % exc)
        self.push_state()

    def _preflight(self, projects: list) -> None:
        state = backend.snapshot()
        errors, warnings = [], []
        for tool, label in (("rsync", "rsync"), ("ssh", "ssh")):
            if not shutil.which(tool):
                errors.append("缺少命令: %s" % label)
        if not shutil.which("sshpass"):
            warnings.append("未安装 sshpass：使用密码认证的 Host 可能连接失败")
        by_id = {p["id"]: p for p in state.get("projects", [])}
        for project in projects:
            item = by_id.get(project)
            if item is None:
                errors.append("项目不存在: %s" % project)
            elif item.get("error"):
                errors.append("%s: %s" % (project, item["error"]))
            elif not item.get("remote"):
                errors.append("%s: 当前 Host 没有匹配规则" % project)
            elif not os.path.isdir(item.get("local_abs", "")):
                errors.append("%s: 源码目录不存在 %s" % (project, item.get("local_src", "")))
        self._js("window.scproPreflight", {
            "ok": not errors,
            "errors": errors,
            "warnings": warnings,
            "projects": projects,
        })

    def _save_ui(self, payload: dict) -> None:
        updates = {}
        try:
            height = int(payload.get("panel_h", 0))
            if 80 <= height <= 1200 and height != self.app_settings.get("panel_h"):
                updates["panel_h"] = height
        except (TypeError, ValueError):
            pass
        selected = payload.get("selected")
        if isinstance(selected, list):
            cleaned = [str(x) for x in selected][:200]
            if cleaned != self.app_settings.get("selected"):
                updates["selected"] = cleaned
        if updates:
            save_app_settings(updates)
            self.app_settings = load_app_settings()

    def _clear_upload_cache(self) -> None:
        if self.proc is not None:
            self._js("window.scproToast", "任务执行中，暂不能清理打包缓存")
            return
        cache_dir = backend.UPLOAD_DIR
        removed = 0
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            for child in list(cache_dir.iterdir()):
                if child.is_symlink() or child.is_file():
                    child.unlink()
                elif child.is_dir():
                    shutil.rmtree(child)
                removed += 1
        except OSError as exc:
            self.log("[ERROR] 清理打包缓存失败: %s" % exc)
            self._js("window.scproToast", "清理打包缓存失败: %s" % exc)
            return
        self.log("[INFO] 已清理本地打包缓存，共 %d 项" % removed)
        self._js("window.scproToast", "打包缓存已清理")


class AppPage(QWebEnginePage):
    """拦截 scpro:// 命令（JS -> Python）"""

    def __init__(self, bridge: Bridge, parent=None) -> None:
        super().__init__(parent)
        self.bridge = bridge

    def acceptNavigationRequest(self, url, nav_type, is_main_frame) -> bool:
        if url.scheme() == "scpro":
            self.bridge.handle(url.host(), dict(parse_qsl(url.query())))
            return False
        return super().acceptNavigationRequest(url, nav_type, is_main_frame)


class WindowBody(QWidget):
    """窗口内容区：四周的细边用来拉伸/换光标"""

    def __init__(self, window: "MainWindow") -> None:
        super().__init__()
        self.window_ref = window
        # 普通 QWidget 子类默认不绘制 QSS 背景，必须显式开启；否则边带会露出浅色父背景
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor("#1e1e1e"))
        self.setPalette(palette)
        self.setMouseTracking(True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.window_ref._start_resize_if_edge(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.window_ref._resize_edges and event.buttons() & Qt.LeftButton:
            self.window_ref._perform_resize(event)
            event.accept()
            return
        self.window_ref._update_cursor_for_edge(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.window_ref._end_resize()
        super().mouseReleaseEvent(event)


class ResizeHandle(QWidget):
    """悬浮在窗口最外层的透明拉伸手柄：不占布局、不内缩界面"""

    def __init__(self, window: "MainWindow", edges, cursor) -> None:
        super().__init__(window)
        self.window_ref = window
        self.edges = edges
        self.setCursor(cursor)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.window_ref._begin_resize(self.edges, event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.window_ref._resize_edges and event.buttons() & Qt.LeftButton:
            self.window_ref._perform_resize(event)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.window_ref._end_resize()
        super().mouseReleaseEvent(event)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        startup_settings = load_app_settings()
        self.theme = vscode_theme.load(str(startup_settings.get("theme_id", "")))
        colors = self.theme["colors"]
        self.setWindowTitle("SCPro")
        self.setWindowIcon(QIcon(str(ICON_SVG)))
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        size = startup_settings.get("window") or [1280, 820]
        try:
            self.resize(int(size[0]), int(size[1]))
        except (TypeError, ValueError, IndexError):
            self.resize(1280, 820)
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(colors["bg"]))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        self.resize_margin = 5
        self.setMouseTracking(True)
        self._resize_edges = Qt.Edges()
        self._resize_start_geo = None
        self._resize_start_pos = None

        self.bridge = Bridge(self)
        central = WindowBody(self)
        central.setObjectName("windowBody")
        central.setStyleSheet("#windowBody { background:%s; }" % colors["bg"])
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        # 不内缩：拉伸热区用悬浮手柄叠在最外层
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.title_bar = TitleBar(self)
        self.title_bar.setStyleSheet(title_style(colors))
        layout.addWidget(self.title_bar)

        self.view = QWebEngineView()
        self.page = AppPage(self.bridge, self.view)
        self.page.setBackgroundColor(QColor(colors["bg"]))
        self.view.setPage(self.page)
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
        layout.addWidget(self.view, 1)

        self.page.loadFinished.connect(self._on_load)
        self.view.load(QUrl.fromLocalFile(str(WEB_DIR / "index.html")))

        self._handles = []
        for name, edges, cursor in (
                ("left", Qt.LeftEdge, Qt.SizeHorCursor),
                ("right", Qt.RightEdge, Qt.SizeHorCursor),
                ("top", Qt.TopEdge, Qt.SizeVerCursor),
                ("bottom", Qt.BottomEdge, Qt.SizeVerCursor),
                ("tl", Qt.LeftEdge | Qt.TopEdge, Qt.SizeFDiagCursor),
                ("tr", Qt.RightEdge | Qt.TopEdge, Qt.SizeBDiagCursor),
                ("bl", Qt.LeftEdge | Qt.BottomEdge, Qt.SizeBDiagCursor),
                ("br", Qt.RightEdge | Qt.BottomEdge, Qt.SizeFDiagCursor)):
            handle = ResizeHandle(self, edges, cursor)
            handle.setObjectName("resize_" + name)
            self._handles.append((name, handle))
        self._layout_handles()

        self.tray = QSystemTrayIcon(QIcon(str(ICON_SVG)), self)
        self.tray.setToolTip("SCPro")
        self.tray_menu = QMenu()
        self.tray.setContextMenu(self.tray_menu)
        self.tray.activated.connect(self._on_tray)
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
        try:
            self.build_tray_menu(backend.snapshot())
        except Exception:
            pass

    def build_tray_menu(self, state: dict) -> None:
        host = state.get("current_host", "")
        self.tray_menu.clear()
        self.tray_menu.addAction("显示主窗口", self._show_window)
        upload = self.tray_menu.addMenu("上传到 %s" % (host or "（未选择 Host）"))
        matched = 0
        for project in state.get("projects", []):
            if not project.get("remote"):
                continue
            matched += 1
            action = upload.addAction(project["id"])
            action.triggered.connect(
                lambda _checked=False, name=project["id"]: self._tray_upload(name))
        if not matched:
            upload.setEnabled(False)
        self.tray_menu.addAction("测试连接", self.bridge._test_connection)
        self.tray_menu.addSeparator()
        self.tray_menu.addAction("退出", self.close)
        self.tray.setToolTip("SCPro — %s" % (host or "no host"))

    def _tray_upload(self, name: str) -> None:
        state = backend.snapshot()
        host = state.get("current_host", "")
        item = next((p for p in state.get("projects", []) if p["id"] == name), None)
        if not item or not item.get("remote"):
            QMessageBox.warning(self, "无法上传", "当前 Host 没有该项目的规则")
            return
        if not os.path.isdir(item.get("local_abs", "")):
            QMessageBox.warning(self, "无法上传", "源码目录不存在:\n%s" % item.get("local_src", ""))
            return
        if QMessageBox.question(self, "上传确认",
                                "将 %s 上传到 %s？" % (name, host)) != QMessageBox.Yes:
            return
        self.bridge._run([name])

    def _on_load(self, ok: bool) -> None:
        if ok:
            self.bridge._js("window.scproTheme",
                            {"colors": self.theme["colors"], "dark": self.theme["dark"]})
            self.bridge._js("window.scproAssets", self.theme["icons"])
            self.bridge._js("window.scproUi",
                            {"panel_h": self.bridge.app_settings.get("panel_h", 228),
                             "language": self.bridge.app_settings.get("language", "zh"),
                             "selected": self.bridge.app_settings.get("selected", []),
                             "delete_remote": bool(
                                 self.bridge.app_settings.get("delete_remote", False))})
            self.bridge.push_state()
            self.bridge.log("[INFO] SCPro 已就绪")
            for name in getattr(self, "startup_configs", []):
                self.bridge.log("[INFO] 首次运行，已从模板生成 %s" % name)

    def _show_window(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible():
                self.hide()
            else:
                self._show_window()

    def toggle_maximized(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def _layout_handles(self) -> None:
        """把手柄贴在窗口四边/四角（叠在 WebView 之上，不占布局）"""
        if self.isMaximized() or self.isFullScreen():
            for _name, handle in self._handles:
                handle.hide()
            return
        m = self.resize_margin
        w, h = self.width(), self.height()
        geo = {
            "left": (0, m, m, max(0, h - 2 * m)),
            "right": (w - m, m, m, max(0, h - 2 * m)),
            "top": (m, 0, max(0, w - 2 * m), m),
            "bottom": (m, h - m, max(0, w - 2 * m), m),
            "tl": (0, 0, m, m),
            "tr": (w - m, 0, m, m),
            "bl": (0, h - m, m, m),
            "br": (w - m, h - m, m, m),
        }
        for name, handle in self._handles:
            handle.setGeometry(*geo[name])
            handle.raise_()
            handle.show()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._layout_handles()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._layout_handles()

    def _begin_resize(self, edges, event) -> None:
        self._resize_edges = edges
        if QApplication.platformName().startswith("xcb"):
            self._resize_start_geo = QRect(self.geometry())
            self._resize_start_pos = event.globalPos()
        else:
            handle = self.windowHandle()
            if handle is not None:
                handle.startSystemResize(edges)
        event.accept()

    # ---- 边界拉伸（无边框窗口自己处理）----
    def _resize_edges_at(self, global_pos) -> Qt.Edges:
        edges = Qt.Edges()
        if self.isMaximized() or self.isFullScreen():
            return edges
        point = self.mapFromGlobal(global_pos)
        if point.x() <= self.resize_margin:
            edges |= Qt.LeftEdge
        elif point.x() >= self.width() - self.resize_margin:
            edges |= Qt.RightEdge
        if point.y() <= self.resize_margin:
            edges |= Qt.TopEdge
        elif point.y() >= self.height() - self.resize_margin:
            edges |= Qt.BottomEdge
        return edges

    def _start_resize_if_edge(self, event) -> bool:
        edges = self._resize_edges_at(event.globalPos())
        if not edges:
            return False
        self._begin_resize(edges, event)
        return True

    def _perform_resize(self, event) -> None:
        if not self._resize_edges or self._resize_start_geo is None:
            return
        delta = event.globalPos() - self._resize_start_pos
        geo = QRect(self._resize_start_geo)
        min_w, min_h = 900, 520
        if self._resize_edges & Qt.LeftEdge:
            geo.setLeft(min(geo.right() - min_w, geo.left() + delta.x()))
        if self._resize_edges & Qt.RightEdge:
            geo.setRight(max(geo.left() + min_w, geo.right() + delta.x()))
        if self._resize_edges & Qt.TopEdge:
            geo.setTop(min(geo.bottom() - min_h, geo.top() + delta.y()))
        if self._resize_edges & Qt.BottomEdge:
            geo.setBottom(max(geo.top() + min_h, geo.bottom() + delta.y()))
        self.setGeometry(geo)

    def _end_resize(self) -> None:
        self._resize_edges = Qt.Edges()
        self._resize_start_geo = None
        self._resize_start_pos = None

    def _update_cursor_for_edge(self, event) -> None:
        edges = self._resize_edges_at(event.globalPos())
        if edges in (Qt.LeftEdge | Qt.TopEdge, Qt.RightEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeFDiagCursor)
        elif edges in (Qt.RightEdge | Qt.TopEdge, Qt.LeftEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeBDiagCursor)
        elif edges & (Qt.LeftEdge | Qt.RightEdge):
            self.setCursor(Qt.SizeHorCursor)
        elif edges & (Qt.TopEdge | Qt.BottomEdge):
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.unsetCursor()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self._start_resize_if_edge(event):
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._resize_edges and event.buttons() & Qt.LeftButton:
            self._perform_resize(event)
            event.accept()
            return
        self._update_cursor_for_edge(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self._end_resize()
        super().mouseReleaseEvent(event)

    def reload_theme(self) -> None:
        theme_id = str(self.bridge.app_settings.get("theme_id", ""))
        self.theme = vscode_theme.load(theme_id)
        colors = self.theme["colors"]
        self.title_bar.setStyleSheet(title_style(colors))
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(colors["bg"]))
        self.setPalette(palette)
        central = self.centralWidget()
        if central is not None:
            central.setStyleSheet("#windowBody { background:%s; }" % colors["bg"])
        self.page.setBackgroundColor(QColor(colors["bg"]))
        self.bridge._js("window.scproTheme",
                        {"colors": colors, "dark": self.theme["dark"]})
        self.bridge._js("window.scproAssets", self.theme["icons"])
        self.bridge.log("[INFO] 已重新加载 VS Code 主题: %s" % self.theme["name"])

    def closeEvent(self, event) -> None:
        self.tray.hide()
        save_app_settings({"window": [self.width(), self.height()]})
        event.accept()
        QApplication.instance().quit()


def main() -> int:
    global _INSTANCE_LOCK
    # 首次运行：用仓库内模板生成本地私有配置（真实配置已被 .gitignore 排除）
    try:
        created_configs = backend.core.ensure_local_configs()
    except Exception as exc:
        created_configs = []
        print("[WARN] 生成本地配置失败: %s" % exc, file=sys.stderr)
    if "--check" in sys.argv:
        state = backend.snapshot()
        print("SCPro v%s" % VERSION)
        print("当前 Host: %s" % state.get("current_host", ""))
        print("Host 数  : %d" % len(state.get("hosts", [])))
        print("项目数   : %d" % len(state.get("projects", [])))
        ssh_source = backend.core.ssh_config_source()
        print("SSH 配置 : %s%s" % (
            ssh_source,
            "" if ssh_source == backend.core.SSH_SOURCE_CONFIG else "（本地副本）"))
        if created_configs:
            print("本地配置 : 已由模板生成 %s" % ", ".join(created_configs))
        for project in state.get("projects", []):
            if project.get("error"):
                print("  [ERROR] %-24s %s" % (project["id"], project["error"]))
            elif not project.get("remote"):
                print("  [--]    %-24s 当前 Host 无规则" % project["id"])
            else:
                print("  [OK]    %-24s %s" % (project["id"], project["remote"]))
        return 0
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    lock_path = backend.core.LOCK_FILE
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _INSTANCE_LOCK = open(lock_path, "w")
    try:
        fcntl.flock(_INSTANCE_LOCK, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        QMessageBox.warning(None, "SCPro", "已经有一个 SCPro 实例在运行。")
        return 0
    app.setApplicationName("SCPro")
    app.setQuitOnLastWindowClosed(False)
    window = MainWindow()
    window.startup_configs = created_configs
    window.show()
    return app.exec_()


if __name__ == "__main__":
    sys.exit(main())
