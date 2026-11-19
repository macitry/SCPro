#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按应用统计内存占用，并回收指定应用的文件缓存。

全部基于 cgroup v2（Ubuntu 22.04+ 默认）与 /proc/meminfo，不依赖第三方库：

    /sys/fs/cgroup/**/memory.current   当前占用（含该应用的文件缓存）
    /sys/fs/cgroup/**/memory.peak      历史峰值（内核 5.19+）
    /sys/fs/cgroup/**/memory.reclaim   往这里写 "512M" 即回收该 cgroup 的缓存

回收只针对**文件缓存**，不会释放应用堆内存；要真正降下来只能重启应用。
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
MB = 1024.0 * 1024.0
GB = 1024.0 * 1024.0 * 1024.0

_UNESCAPE = re.compile(r"\\x([0-9a-fA-F]{2})")
_PID_SUFFIX = re.compile(r"^(.*?)-(\d+)$")

# 应用名 → 展示名。没命中的直接用清理后的原名
_LABELS = {
    "bytedance-feishu": ("飞书", "Feishu"),
    "microsoft-edge": ("Edge", "Edge"),
    "code": ("VS Code", "VS Code"),
    "code-insiders": ("VS Code Insiders", "VS Code Insiders"),
    "chromium": ("Chromium", "Chromium"),
    "org.chromium.chromium": ("Chromium", "Chromium"),
    "google-chrome": ("Chrome", "Chrome"),
    "firefox": ("Firefox", "Firefox"),
    "gnome-shell": ("GNOME Shell", "GNOME Shell"),
    "org.gnome.shell@x11": ("GNOME Shell", "GNOME Shell"),
    "gnome-terminal-server": ("终端", "Terminal"),
    "gnome-text-editor": ("文本编辑器", "Text Editor"),
    "nautilus": ("文件管理器", "Files"),
    "gnome-system-monitor": ("系统监视器", "System Monitor"),
    "gnome-control-center": ("设置", "Settings"),
    "gnome-software": ("软件中心", "Software"),
    "dsh-desktop-next": ("DSH Desktop", "DSH Desktop"),
    "px-deploy": ("Px Deploy", "Px Deploy"),
    "lsdhelper": ("LSD Helper", "LSD Helper"),
    "lsa-gateway": ("LSA Gateway", "LSA Gateway"),
}


def _read_int(path: Path):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def _read_kv(path: Path) -> dict:
    out = {}
    try:
        for line in path.read_text().splitlines():
            key, _, value = line.partition(" ")
            if not value:
                continue
            try:
                out[key] = int(value.strip())
            except ValueError:
                continue
    except OSError:
        pass
    return out


def meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            try:
                out[key] = int(rest.split()[0]) * 1024
            except (ValueError, IndexError):
                continue
    except OSError:
        pass
    return out


def global_stats() -> dict:
    info = meminfo()
    total = info.get("MemTotal", 0)
    free = info.get("MemFree", 0)
    cache = info.get("Cached", 0) + info.get("Buffers", 0)
    available = info.get("MemAvailable", 0)
    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    used = max(0, total - free - cache)
    return {
        "total": total,
        "used": used,
        "free": free,
        "available": available,
        "cache": cache,
        "anon": info.get("AnonPages", 0),
        "slab": info.get("Slab", 0),
        "shmem": info.get("Shmem", 0),
        "mapped": info.get("Mapped", 0),
        "swap_total": swap_total,
        "swap_used": max(0, swap_total - swap_free),
        "percent": round((total - available) * 100.0 / total, 1) if total else 0.0,
    }


def _clean_name(scope_name: str):
    """app-gnome-bytedance\\x2dfeishu-708515.scope → (bytedance-feishu, 708515)"""
    name = _UNESCAPE.sub(lambda m: chr(int(m.group(1), 16)), scope_name)
    for suffix in (".scope", ".service"):
        if name.endswith(suffix):
            name = name[: -len(suffix)]
    pid = None
    match = _PID_SUFFIX.match(name)
    if match:
        name, pid = match.group(1), int(match.group(2))
    if name.startswith("app-"):
        name = name[4:]
    if name.startswith("gnome-"):
        name = name[6:]
    return name, pid


def _title(name: str):
    key = name.lower()
    if key in _LABELS:
        return _LABELS[key]
    if key.startswith("docker-"):
        short = name[7:19]
        return ("Docker %s" % short, "Docker %s" % short)
    if key.startswith("org."):
        return (name, name)
    pretty = name.replace("-", " ").replace("_", " ").strip()
    return (pretty or name, pretty or name)


def _kind(cgroup_path: Path) -> str:
    text = str(cgroup_path)
    if "/user.slice/" in text:
        return "app"
    if "/system.slice/" in text:
        return "system"
    return "other"


def _reclaimable(path: Path, stat: dict) -> int:
    """可主动回收的页缓存估算。

    cgroup 的 `file` 包含 tmpfs/shmem；drop_caches 清不掉 tmpfs，
    已映射页和脏页也回收不动，所以都减掉，得到与 inactive_file 接近的值。
    """
    file_bytes = stat.get("file", 0)
    shmem = stat.get("shmem", 0)
    mapped = stat.get("file_mapped", 0)
    dirty = stat.get("file_dirty", 0) + stat.get("file_writeback", 0)
    return max(0, file_bytes - shmem - mapped - dirty)


def scan_scope_units(min_mb: float = 1.0) -> list:
    """遍历 cgroup 树，返回叶子 cgroup 的原始占用记录。"""
    units = []
    stack = [(CGROUP_ROOT, 0)]
    exists = {}

    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                subdirs = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue

        name = path.name
        is_leaf = False
        if path != CGROUP_ROOT:
            if name.endswith(".scope"):
                is_leaf = True
            elif name.endswith(".service") and not subdirs:
                is_leaf = True

        if is_leaf:
            current = _read_int(path / "memory.current")
            if current is None or current < min_mb * MB:
                continue
            stat = _read_kv(path / "memory.stat")
            clean, pid = _clean_name(name)
            zh, en = _title(clean)
            kind = "container" if clean.lower().startswith("docker-") else _kind(path)
            units.append({
                "cgroup": str(path),
                "scope": name,
                "name": clean,
                "pid": pid,
                "kind": kind,
                "title_zh": zh,
                "title_en": en,
                "bytes": current,
                "peak": _read_int(path / "memory.peak") or 0,
                "swap": _read_int(path / "memory.swap.current") or 0,
                "reclaimable": _reclaimable(path, stat),
                "has_reclaim": (path / "memory.reclaim").exists(),
            })
            continue

        if depth < 7:
            for entry in subdirs:
                stack.append((Path(entry.path), depth + 1))

    return units


def group_units(units: list, min_mb: float = 4.0) -> list:
    """同名的多个进程（比如飞书 3 个）合并成一条。"""
    groups = {}
    for unit in units:
        key = (unit["kind"], unit["name"])
        group = groups.get(key)
        if group is None:
            group = {
                "id": "%s:%s" % (unit["kind"], unit["name"]),
                "name": unit["name"],
                "kind": unit["kind"],
                "title_zh": unit["title_zh"],
                "title_en": unit["title_en"],
                "bytes": 0,
                "peak": 0,
                "swap": 0,
                "reclaimable": 0,
                "scopes": [],
            }
            groups[key] = group
        group["bytes"] += unit["bytes"]
        group["peak"] = max(group["peak"], unit["peak"])
        group["swap"] += unit["swap"]
        group["reclaimable"] += unit["reclaimable"]
        group["scopes"].append({
            "cgroup": unit["cgroup"],
            "pid": unit["pid"],
            "bytes": unit["bytes"],
            "reclaimable": unit["reclaimable"],
            "has_reclaim": unit["has_reclaim"],
        })
    rows = [g for g in groups.values() if g["bytes"] >= min_mb * MB]
    rows.sort(key=lambda g: g["bytes"], reverse=True)
    return rows


def group_apps(min_mb: float = 4.0) -> list:
    return group_units(scan_scope_units(min_mb), min_mb)


def snapshot(min_mb: float = 4.0) -> dict:
    units = scan_scope_units(1.0)
    stats = global_stats()
    reclaimable = sum(unit["reclaimable"] for unit in units)
    return {
        "ts": time.time(),
        "global": stats,
        "apps": group_units(units, min_mb),
        "accounting": {
            # 整机缓存 = tmpfs + 可回收干净页 + 进程映射页 + 脏页/Buffers/内核
            "cache": stats["cache"],
            "reclaimable": reclaimable,
            "tmpfs": stats["shmem"],
            "mapped": stats["mapped"],
            # drop_caches 清不掉 tmpfs，也带不走仍在映射的页
            "drop_estimate": max(0, stats["cache"] - stats["shmem"] - stats["mapped"]),
        },
        "privilege": {
            "root": os.geteuid() == 0,
            "pkexec": shutil.which("pkexec") is not None,
        },
        "reclaim_supported": (CGROUP_ROOT / "memory.reclaim").exists(),
    }


def _safe_cgroup(path: str) -> Path:
    p = Path(path).resolve()
    if not str(p).startswith(str(CGROUP_ROOT.resolve()) + os.sep):
        raise ValueError("非法的 cgroup 路径: %s" % path)
    if not p.name.endswith((".scope", ".service")):
        raise ValueError("只允许回收应用/服务的 cgroup: %s" % path)
    return p


def _write_reclaim(target: Path, amount_mb: int):
    """返回 (ok, method, error)。优先直接写，失败再走 pkexec / sudo。"""
    value = "%dM" % max(1, int(amount_mb))
    try:
        with open(target, "w", encoding="ascii") as handle:
            handle.write(value)
        return True, "direct", ""
    except OSError as exc:
        direct_error = str(exc)

    command = "echo %s > %s" % (value, shlex.quote(str(target)))
    if shutil.which("pkexec"):
        try:
            proc = subprocess.run(["pkexec", "sh", "-c", command],
                                  capture_output=True, text=True, timeout=180)
            if proc.returncode == 0:
                return True, "pkexec", ""
            pkexec_error = (proc.stderr or "").strip() or "pkexec 返回 %d" % proc.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            pkexec_error = str(exc)
    else:
        pkexec_error = "没有 pkexec"

    try:
        proc = subprocess.run(["sudo", "-n", "sh", "-c", command],
                              capture_output=True, text=True, timeout=180)
        if proc.returncode == 0:
            return True, "sudo", ""
        sudo_error = (proc.stderr or "").strip() or "sudo 返回 %d" % proc.returncode
    except (OSError, subprocess.TimeoutExpired) as exc:
        sudo_error = str(exc)

    return False, "", "直接写入失败(%s)；pkexec: %s；sudo: %s" % (
        direct_error, pkexec_error, sudo_error)


def reclaim(cgroups: list, amount_mb: int) -> dict:
    """回收若干 cgroup 的缓存，总量不超过 amount_mb（按可回收量分配）。"""
    targets = []
    for item in cgroups:
        try:
            path = _safe_cgroup(str(item))
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "freed": 0}
        targets.append(path)
    if not targets:
        return {"ok": False, "error": "没有可回收的目标", "freed": 0}

    before = {}
    reclaimable = {}
    for path in targets:
        before[path] = _read_int(path / "memory.current") or 0
        reclaimable[path] = _reclaimable(path, _read_kv(path / "memory.stat")) or 0

    remaining = max(1, int(amount_mb))
    results = []
    for path in targets:
        current = before[path]
        # 按各自可回收量分配，避免给没有缓存的小进程白写一次
        share = min(remaining, max(1, int(reclaimable[path] / MB)))
        ok, method, error = _write_reclaim(path / "memory.reclaim", share)
        remaining = max(1, remaining - share)
        after = _read_int(path / "memory.current") or current
        results.append({
            "cgroup": str(path),
            "ok": ok,
            "method": method,
            "error": error,
            "freed": max(0, current - after),
        })
        if not ok:
            break

    freed = sum(item["freed"] for item in results)
    failed = next((r for r in results if not r["ok"]), None)
    return {
        "ok": failed is None,
        "freed": freed,
        "results": results,
        "method": results[0]["method"] if results else "",
        "error": failed["error"] if failed else "",
    }


def drop_caches(level: int = 3) -> dict:
    """整机清页缓存，需要 root（会通过 pkexec 弹一次授权框）。"""
    before = global_stats()
    level = min(3, max(1, int(level)))
    command = "sync; echo %d > /proc/sys/vm/drop_caches" % level

    if os.geteuid() == 0:
        try:
            subprocess.run(["sh", "-c", command], check=True, timeout=180)
            method, error = "root", ""
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": str(exc), "freed": 0}
    else:
        method, error = "", ""
        for prefix in (["pkexec"], ["sudo", "-n"]):
            if prefix[0] == "pkexec" and not shutil.which("pkexec"):
                continue
            try:
                proc = subprocess.run(prefix + ["sh", "-c", command],
                                      capture_output=True, text=True, timeout=300)
                if proc.returncode == 0:
                    method = prefix[0]
                    break
                error = (proc.stderr or "").strip() or "%s 返回 %d" % (
                    prefix[0], proc.returncode)
            except (OSError, subprocess.TimeoutExpired) as exc:
                error = str(exc)
        if not method:
            return {"ok": False, "error": error or "无法获取 root 权限", "freed": 0}

    after = global_stats()
    return {
        "ok": True,
        "freed": max(0, before["cache"] - after["cache"]),
        "method": method,
        "before": before,
        "after": after,
    }
