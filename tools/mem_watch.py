#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""mem_watch.py —— 看清"整机内存越占越大"到底是谁在长。

原理：直接读 cgroup v2 的 memory.current，按应用（systemd scope）统计，
和 /proc/meminfo 的全局数据一起采样。不依赖 root，不需要装任何包。

用法：
    ./mem_watch.py top                  # 当前内存占用排行（含历史峰值/swap）
    ./mem_watch.py watch                # 每 60s 采一次，Ctrl-C 结束并输出增长排行
    ./mem_watch.py watch -i 30 --csv ~/mem.csv
    ./mem_watch.py report ~/mem.csv     # 事后分析：哪个应用涨得最快（MB/h）

说明：memory.current 含该应用自己的页缓存，所以几项相加会略大于 free 的 used。
"""

import argparse
import csv
import os
import re
import sys
import time
from pathlib import Path

CGROUP_ROOT = Path("/sys/fs/cgroup")
MB = 1024.0 * 1024.0
GB = 1024.0 * 1024.0 * 1024.0
UNESC = re.compile(r"\\x([0-9a-fA-F]{2})")


def unescape(name: str) -> str:
    return UNESC.sub(lambda m: chr(int(m.group(1), 16)), name)


def pretty(scope: str) -> str:
    n = unescape(scope)
    for suf in (".scope", ".service"):
        if n.endswith(suf):
            n = n[: -len(suf)]
    n = n.replace("app-gnome-", "").replace("app-", "")
    return n


def read_int(path: Path):
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def meminfo() -> dict:
    out = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            out[k] = int(v.split()[0]) * 1024
    except OSError:
        pass
    return out


def scan(min_mb: float = 8.0, limit=None):
    """返回 [(name, current, peak, swap), ...]，按 current 降序。"""
    rows = []

    def record(p: Path, name: str):
        cur = read_int(p / "memory.current")
        if cur is None or cur < min_mb * MB:
            return
        rows.append((
            pretty(name),
            cur,
            read_int(p / "memory.peak") or 0,
            read_int(p / "memory.swap.current") or 0,
        ))

    stack = [(CGROUP_ROOT, 0)]
    while stack:
        path, depth = stack.pop()
        try:
            with os.scandir(path) as it:
                subdirs = [e for e in it if e.is_dir(follow_symlinks=False)]
        except OSError:
            continue

        name = path.name
        if path != CGROUP_ROOT:
            # .scope 是叶子，直接记账，不再下钻
            if name.endswith(".scope"):
                record(path, name)
                continue
            # .service 只有在自己没有子 cgroup 时才是独立单元，
            # 否则会重复统计（例如 user@1000.service 包含所有 app.slice）
            if name.endswith(".service") and not subdirs:
                record(path, name)
                continue

        if depth < 7:
            for e in subdirs:
                stack.append((Path(e.path), depth + 1))
    rows.sort(key=lambda r: r[1], reverse=True)
    return rows[:limit] if limit else rows


def global_line(mi: dict) -> str:
    total = mi.get("MemTotal", 0)
    free = mi.get("MemFree", 0)
    cache = mi.get("Cached", 0) + mi.get("Buffers", 0)
    avail = mi.get("MemAvailable", 0)
    anon = mi.get("AnonPages", 0)
    used = total - free - cache
    st, sf = mi.get("SwapTotal", 0), mi.get("SwapFree", 0)
    return (
        f"已用 {used / GB:5.1f}G  可用 {avail / GB:5.1f}G  "
        f"缓存 {cache / GB:5.1f}G  匿名 {anon / GB:5.1f}G  "
        f"swap {(st - sf) / GB:4.1f}/{st / GB:4.1f}G"
    )


def cmd_top(args):
    mi = meminfo()
    print(f"整机：{global_line(mi)}")
    print()
    print(f"{'应用 / 服务':<34}{'当前MB':>9}{'峰值MB':>9}{'swapMB':>8}")
    print("-" * 62)
    for name, cur, peak, swap in scan(args.min_mb, args.limit):
        print(f"{name[:34]:<34}{cur / MB:9.0f}{peak / MB:9.0f}{swap / MB:8.0f}")
    print()
    print("提示：峰值远大于当前 = 曾经吃满过；swap 不为 0 = 被换出过（会卡顿）。")


def cmd_watch(args):
    csv_file = None
    writer = None
    if args.csv:
        path = Path(os.path.expanduser(args.csv))
        new = not path.exists()
        csv_file = path.open("a", newline="", encoding="utf-8")
        writer = csv.writer(csv_file)
        if new:
            writer.writerow(["ts", "scope", "current_bytes", "swap_bytes"])

    t0 = time.time()
    first, last = {}, {}
    print(f"每 {args.interval}s 采样一次，Ctrl-C 结束并汇总。CSV: {args.csv or '(不写)'}")
    try:
        while True:
            rows = scan()
            mi = meminfo()
            for name, cur, peak, swap in rows:
                first.setdefault(name, cur)
                last[name] = cur
                if writer:
                    writer.writerow([f"{time.time():.0f}", name, cur, swap])
            if csv_file:
                csv_file.flush()
            print(f"{time.strftime('%H:%M:%S')}  {global_line(mi)}  应用数 {len(rows)}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass
    finally:
        if csv_file:
            csv_file.close()

    hours = max((time.time() - t0) / 3600.0, 1e-6)
    print(f"\n=== 增长排行（窗口 {hours * 60:.1f} 分钟）===")
    deltas = []
    for name, v0 in first.items():
        v1 = last.get(name, v0)
        d = v1 - v0
        if abs(d) >= 16 * MB:
            deltas.append((d, name, v0, v1))
    deltas.sort(reverse=True)
    if not deltas:
        print("窗口内没有明显增长（<16MB）。拉长采样时间再看。")
    else:
        print(f"{'应用 / 服务':<34}{'增加MB':>9}{'GB/h':>8}   首 → 末(MB)")
        for d, name, v0, v1 in deltas[: args.limit or 15]:
            print(f"{name[:34]:<34}{d / MB:9.0f}{d / GB / hours:8.2f}   "
                  f"{v0 / MB:.0f} → {v1 / MB:.0f}")
        print("\nGB/h 持续 > 1 且不回落 → 该应用疑似泄漏，重启它或上报。")


def cmd_report(args):
    path = Path(os.path.expanduser(args.csv))
    series = {}
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                ts = float(row["ts"])
                cur = int(row["current_bytes"])
            except (KeyError, ValueError):
                continue
            series.setdefault(row["scope"], []).append((ts, cur))
    if not series:
        print("CSV 里没有数据。")
        return
    print(f"{'应用 / 服务':<34}{'首MB':>8}{'末MB':>8}{'增加MB':>9}{'GB/h':>8}{'峰值MB':>9}")
    out = []
    for name, pts in series.items():
        pts.sort()
        t0, v0 = pts[0]
        t1, v1 = pts[-1]
        hours = max((t1 - t0) / 3600.0, 1e-6)
        peak = max(v for _, v in pts)
        out.append((v1 - v0, name, v0, v1, (v1 - v0) / GB / hours, peak))
    out.sort(reverse=True)
    for d, name, v0, v1, rate, peak in out[: args.limit or 20]:
        print(f"{name[:34]:<34}{v0 / MB:8.0f}{v1 / MB:8.0f}{d / MB:9.0f}"
              f"{rate:8.2f}{peak / MB:9.0f}")
    print("\n注：窗口内的自然抖动也会计入；看 GB/h 和是否单调上升更可靠。")


def main():
    ap = argparse.ArgumentParser(description="按应用统计内存占用与增长")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("top", help="当前占用排行")
    p.add_argument("-n", "--limit", type=int, default=15)
    p.add_argument("--min-mb", type=float, default=8.0)
    p.set_defaults(func=cmd_top)

    p = sub.add_parser("watch", help="持续采样并在退出时给出增长排行")
    p.add_argument("-i", "--interval", type=int, default=60)
    p.add_argument("--csv", default="")
    p.add_argument("-n", "--limit", type=int, default=15)
    p.set_defaults(func=cmd_watch)

    p = sub.add_parser("report", help="分析 watch 生成的 CSV")
    p.add_argument("csv")
    p.add_argument("-n", "--limit", type=int, default=20)
    p.set_defaults(func=cmd_report)

    args = ap.parse_args()
    try:
        args.func(args)
    except BrokenPipeError:
        sys.exit(0)


if __name__ == "__main__":
    main()
