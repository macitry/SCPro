#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `rsync --progress` 的输出压缩成“只有大文件才显示进度”

用法（由 deploy_one.sh 调用）:
    rsync -avh --progress ... | python3 rsync_progress.py <本地目录> [阈值MB]

行为:
  * 小文件的进度行直接丢弃（只保留文件名本身）；
  * 超过阈值的文件，开始时打印一行 [大文件]，之后按秒节流打印
    [进度] 文件名 百分比 速度 (已传/剩余)；
  * 100% 那一行一定打印；
  * rsync 的其它输出（文件列表、deleting、统计）原样透传。
"""

import codecs
import os
import re
import sys
import time

PROGRESS_RE = re.compile(
    r"^\s*([\d.,]+[kKMGTP]?)\s+(\d+)%\s+([\d.,]+[kKMGTP]?B/s)(?:\s+(\d+:\d+:\d+))?")
SKIP_PREFIXES = ("sending ", "receiving ", "sent ", "total ", "created ",
                 "deleting ", "file list", "bytes/sec", "speedup")


def human(size: int) -> str:
    value = float(size)
    for unit in ("B", "K", "M", "G", "T"):
        if value < 1024 or unit == "T":
            return ("%.0f%s" % (value, unit)) if unit == "B" else ("%.1f%s" % (value, unit))
        value /= 1024.0
    return ""


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    threshold_mb = float(sys.argv[2]) if len(sys.argv) > 2 else 10.0
    threshold = threshold_mb * 1024 * 1024

    current = ""
    current_size = 0
    is_big = False
    last_time = 0.0
    last_pct = -1
    announced = set()
    pending = ""
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    stream = sys.stdin.buffer
    while True:
        chunk = stream.read(4096)
        if not chunk:
            break
        pending += decoder.decode(chunk, final=False)
        pending = pending.replace("\r\n", "\n").replace("\r", "\n")
        lines = pending.split("\n")
        pending = lines.pop()
        for line in lines:
            match = PROGRESS_RE.match(line)
            if match:
                if not is_big:
                    continue
                pct = int(match.group(2))
                now = time.time()
                if pct < 100 and now - last_time < 1.0 and pct - last_pct < 10:
                    continue
                last_time, last_pct = now, pct
                extra = "  剩余 %s" % match.group(4) if (match.group(4) and pct < 100) else ""
                print("[进度] %s  %d%%  %s  已传 %s%s" % (
                    current, pct, match.group(3), match.group(1), extra), flush=True)
                continue

            text = line.strip()
            if not text:
                continue
            low = text.lower()
            if not line.startswith((" ", "\t")) and not low.startswith(SKIP_PREFIXES):
                current = text
                path = os.path.join(root, current)
                try:
                    current_size = os.path.getsize(path)
                except OSError:
                    current_size = 0
                is_big = current_size >= threshold
                if is_big and current not in announced:
                    announced.add(current)
                    print("[大文件] %s  (%s)" % (current, human(current_size)), flush=True)
            print(line, flush=True)

    pending += decoder.decode(b"", final=True)
    if pending.strip():
        print(pending.strip(), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
