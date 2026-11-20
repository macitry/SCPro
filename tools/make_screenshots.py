#!/usr/bin/env python3
"""重新生成 README 里的主界面截图。

用无头 Chrome 渲染 web/index.html，注入一份固定的演示数据（不读取真实的
~/.ssh/config 和 projects.yaml），按 1360x820 输出到 docs/：

    docs/screenshot.png    简体中文（README.zh-CN.md）
    docs/screenshot-en.png 英文（README.md）

用法：
    python3 tools/make_screenshots.py

只依赖 google-chrome（或 chromium）和一个能跑 web 目录的本地文件系统。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - 只是截图工具，不参与运行
    sys.exit("需要 Pillow 把截图裁到目标尺寸：pip install pillow")

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DOCS = ROOT / "docs"
SIZE = (1360, 820)
PANEL_H = 210

# --- 演示场景 -------------------------------------------------------------
# 与 deploy/projects.example.yaml 的示例保持一致：*-mc / *-ai 两套规则，
# 远端基路径 /home/robot/workspace。
HOSTS = [
    {"alias": "robot-mc-01", "user": "robot", "host": "192.168.1.21",
     "port": "22", "password": True, "status": "online"},
    {"alias": "robot-mc-02", "user": "robot", "host": "192.168.1.22",
     "port": "22", "password": True, "status": "online"},
    {"alias": "robot-ai-01", "user": "robot", "host": "192.168.1.31",
     "port": "22", "password": True, "status": "offline"},
    {"alias": "robot-ai-02", "user": "robot", "host": "192.168.1.32",
     "port": "22", "password": False, "status": "unknown"},
    {"alias": "bench-mc", "user": "robot", "host": "192.168.1.41",
     "port": "60081", "password": True, "status": "online"},
    {"alias": "bench-ai", "user": "robot", "host": "192.168.1.42",
     "port": "22", "password": False, "status": "unknown"},
    {"alias": "sim-pc", "user": "dev", "host": "192.168.1.50",
     "port": "22", "password": True, "status": "offline"},
]
CURRENT_HOST = "robot-mc-01"

MC_RULE = {"match": "*-mc", "base": "/home/robot/workspace", "subdir": "."}
ROS2_EXCLUDES = [".git", ".vscode", "build", "install", "log", "__pycache__"]


def project(pid, src, remote_name, rule, excludes=None):
    rule = dict(rule) if rule else None
    remote = ""
    if rule:
        sub = rule.get("subdir") or "."
        remote = rule["base"] + ("/" + sub if sub != "." else "") + "/" + remote_name + "/"
    return {
        "id": pid,
        "local_src": src,
        "local_abs": "/home/robot/px_robot_code/" + src,
        "remote": remote,
        "error": "",
        "match": rule["match"] if rule else "",
        "remote_name": remote_name,
        "excludes": list(excludes or ROS2_EXCLUDES),
        "rule": rule,
    }


PROJECTS = [
    project("demo_repo", "demo/robot_ws", "demo_repo", MC_RULE),
    project("demo_msgs", "demo/robot_ws/src/demo_msgs", "demo_msgs", MC_RULE),
    project("demo_bringup", "demo/robot_ws/src/demo_bringup", "demo_bringup", MC_RULE),
    project("demo_tools", "demo/tools", "demo_tools", MC_RULE,
            [".git", "__pycache__", "*.pyc"]),
    # 只有 *-ai 规则：当前 Host 是 *-mc，规则一条都不命中，
    # backend 给出的就是 rule=null / remote=""，界面上这行应当是灰的
    project("demo_ai", "demo/demo_ai", "demo_ai", None),
]

WORKSPACE = ["demo_repo", "demo_msgs", "demo_bringup", "demo_ai", "demo_tools"]
ACTIVE = "demo_repo"
SELECTED = ["demo_repo", "demo_msgs"]

LOG_LINES = [
    "$ scpro deploy --host robot-mc-01 --project demo_repo --project demo_msgs",
    "=========== [开始] demo_repo ===========",
    "[INFO] 目标 robot@192.168.1.21:22  →  /home/robot/workspace/demo_repo/",
    "[进度] demo_repo 100%  12.4MB/s  完成",
    "=========== [OK] demo_repo ===========",
    "=========== [开始] demo_msgs ===========",
    "[INFO] 排除 6 项：.git .vscode build install log __pycache__",
    "[进度] demo_msgs 100%  9.8MB/s  完成",
    "=========== [OK] demo_msgs ===========",
    "[INFO] 全部结束：成功 2，失败 0，共完成 2/2 个任务",
]

# 注入脚本：伪造时间戳，再按真实调用顺序喂数据
INJECT = """
(function () {
  // 日志时间戳由前端自己取，这里按行递增，避免整屏同一秒
  var tick = 0;
  Date.prototype.toLocaleTimeString = function () {
    tick += 1;
    var base = 9 * 3600 + 41 * 60 + 7 + tick * 3;
    return [Math.floor(base / 3600) % 24, Math.floor(base / 60) % 60, base % 60]
      .map(function (n) { return String(n).padStart(2, "0"); }).join(":");
  };
  window.scproUi({
    panel_h: __PANEL_H__,
    language: "__LANG__",
    workspace: __WORKSPACE__,
    workspace_active: "__ACTIVE__",
    selected: __SELECTED__,
    delete_remote: true
  });
  window.scproState({
    current_host: "__HOST__",
    hosts: __HOSTS__,
    projects: __PROJECTS__
  });
  __LOGS__.forEach(function (line) { window.scproLog(line); });
  window.scproStatus({state: "done", done: 2, total: 2});
})();
"""

# 截图时禁用过渡和动画：无头模式下虚拟时钟不推进它们，会停在起始帧
FREEZE = """
* , *::before, *::after {
  transition: none !important;
  animation: none !important;
}
"""


def build_page(lang: str) -> str:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    inject = (INJECT
              .replace("__PANEL_H__", str(PANEL_H))
              .replace("__LANG__", lang)
              .replace("__WORKSPACE__", json.dumps(WORKSPACE))
              .replace("__ACTIVE__", ACTIVE)
              .replace("__SELECTED__", json.dumps(SELECTED))
              .replace("__HOST__", CURRENT_HOST)
              .replace("__HOSTS__", json.dumps(HOSTS, ensure_ascii=False))
              .replace("__PROJECTS__", json.dumps(PROJECTS, ensure_ascii=False))
              .replace("__LOGS__", json.dumps(LOG_LINES, ensure_ascii=False)))

    html = html.replace("<link rel=\"stylesheet\" href=\"style.css\">",
                        "<link rel=\"stylesheet\" href=\"style.css\">\n"
                        "  <style>" + FREEZE + "</style>", 1)
    # send() 会发起 scpro:// 导航，无头下会挂住
    html = html.replace('<script src="app.js"></script>',
                        '<script>window.send = function () {};</script>\n'
                        '  <script src="app.js"></script>\n'
                        '  <script>' + inject + '</script>', 1)
    assert "window.scproUi" in html and "window.send = function" in html
    return html


def find_chrome() -> str:
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        path = shutil.which(name)
        if path:
            return path
    sys.exit("找不到 google-chrome / chromium")


def viewport_offset(chrome: str, width: int, height: int) -> int:
    """新版无头 Chrome 的 --window-size 含浏览器 chrome，视口比它矮一截。"""
    probe = WEB / ".viewport-probe.html"
    probe.write_text("<script>document.title = innerHeight;</script>", encoding="utf-8")
    try:
        dom = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-sandbox",
             "--window-size=%d,%d" % (width, height), "--dump-dom", probe.as_uri()],
            capture_output=True, text=True, timeout=60).stdout
    finally:
        probe.unlink(missing_ok=True)
    match = re.search(r"<title>(\d+)</title>", dom)
    if not match:
        sys.exit("无法测量无头浏览器视口高度")
    return height - int(match.group(1))


def shoot(chrome: str, lang: str, out: Path, extra: int) -> None:
    page = WEB / (".shot-%s.html" % lang)
    page.write_text(build_page(lang), encoding="utf-8")
    try:
        cmd = [
            chrome, "--headless", "--disable-gpu", "--no-sandbox",
            "--hide-scrollbars", "--force-device-scale-factor=1",
            "--force-color-profile=srgb",
            "--window-size=%d,%d" % (SIZE[0], SIZE[1] + extra),
            "--virtual-time-budget=4000",
            "--screenshot=%s" % out,
            page.as_uri(),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            sys.exit("Chrome 退出码 %d\n%s" % (result.returncode, result.stderr[-2000:]))
    finally:
        page.unlink(missing_ok=True)
    # 窗口比视口高一个 chrome 的高度，把多出来的那条裁掉
    with Image.open(out) as shot:
        shot.crop((0, 0, SIZE[0], SIZE[1])).save(out)
    print("wrote", out.relative_to(ROOT), "%d KB" % (out.stat().st_size // 1024))


def main() -> None:
    chrome = find_chrome()
    DOCS.mkdir(exist_ok=True)
    extra = viewport_offset(chrome, *SIZE)
    print("浏览器 chrome 高度 %dpx（窗口 %dx%d → 视口 %dx%d）"
          % (extra, SIZE[0], SIZE[1] + extra, SIZE[0], SIZE[1]))
    shoot(chrome, "zh", DOCS / "screenshot.png", extra)
    shoot(chrome, "en", DOCS / "screenshot-en.png", extra)


if __name__ == "__main__":
    main()
