#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_one.sh 与 Python 后端之间的解析适配层。

规则（Host 解析、ignore 过滤、端口覆盖、排除模板展开、后缀、源码路径）
只有 deploy_core.py 一份实现；本脚本只负责把结果换成 shell 能 eval 的格式。
不要再往这里加规则——要改规则，改 deploy_core.py。

用法（deploy_one.sh 内部调用，也可单独调试）：
    resolve.py --list-hosts                    alias|user@host:port
    resolve.py --list-tasks <host>             name|base|subdir|remote_name
    resolve.py <project> <host> [--src DIR]    KEY=value（shell 可 eval）

退出码：
    0  成功
    1  参数错误 / 读配置失败
    3  未知项目、未知或已忽略的 Host、项目配置有错
    4  项目没有匹配该 Host 的 targets 规则
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import deploy_core as core  # noqa: E402 - 先注册 app 目录


def _fail(message: str, code: int = 3) -> int:
    sys.stderr.write(message if message.endswith("\n") else message + "\n")
    return code


def list_hosts() -> int:
    for alias, info in core.load_hosts().items():
        print("%s|%s@%s:%s" % (alias, info.get("user", ""),
                               info.get("host", ""), info.get("port", "22")))
    return 0


def list_tasks(host: str) -> int:
    hosts = core.load_hosts()
    if host not in hosts:
        return _fail("[ERROR] 未知或已忽略的 Host: %s\n[提示]  可用 Host: %s"
                     % (host, ", ".join(hosts) or "（无）"))
    for action in core.load_projects():
        rule = action.rule_for(host)
        if rule is None:
            print("%s||||" % action.title)
            continue
        print("%s|%s|%s|%s" % (action.title, rule.get("base") or "",
                               rule.get("subdir") or ".", action.remote_name))
    return 0


def resolve(project: str, host: str, src_override: str = "") -> int:
    actions = {action.title: action for action in core.load_projects()}
    action = actions.get(project)
    if action is None:
        return _fail("[ERROR] 未知项目: %s\n[提示]  可用项目: %s"
                     % (project, ", ".join(actions) or "（无）"))
    hosts = core.load_hosts()
    info = hosts.get(host)
    if info is None:
        return _fail("[ERROR] 未知或已忽略的 Host: %s\n[提示]  可用 Host: %s"
                     % (host, ", ".join(hosts) or "（无）"))
    if action.error:
        return _fail("[ERROR] %s" % action.error)
    rule = action.rule_for(host)
    if rule is None:
        return _fail("[ERROR] 项目 %s 没有匹配 Host %s 的 targets 规则"
                     % (project, host), 4)

    secret = str(core.read_secrets().get(info.get("secret_key") or host) or "")
    raw_src = (src_override or os.environ.get("DEPLOY_LOCAL_SRC", "").strip()
               or action.local_src)
    values = [
        ("P_LOCAL_SRC", action.local_src),
        ("P_REMOTE_NAME", action.remote_name),
        ("P_EXCLUDES", " ".join(shlex.quote(x) for x in action.excludes)),
        ("P_SRC_DIR", core.resolve_local_src(raw_src)),
        ("P_NAME_SUFFIX", core.resolve_name_suffix()),
        ("P_WORKSPACE_DIR", str(core.workspace_root())),
        ("H_ALIAS", host),
        ("H_USER", info.get("user", "")),
        ("H_HOSTNAME", info.get("host", "")),
        ("H_PORT", info.get("port", "22")),
        ("H_SECRET", secret),
        ("R_BASE", str(rule.get("base") or "")),
        ("R_SUBDIR", str(rule.get("subdir") or ".")),
        ("R_MATCH", str(rule.get("match") or "")),
    ]
    # 逐项 shlex.quote：值里可能有空格、中文或引号，shell 侧靠 eval 还原
    for key, value in values:
        print("%s=%s" % (key, shlex.quote(value)))
    return 0


def main(argv: list) -> int:
    project = argv[1] if len(argv) > 1 else ""
    host = argv[2] if len(argv) > 2 else ""
    src = ""
    if "--src" in argv[3:]:
        index = argv.index("--src", 3)
        src = argv[index + 1] if len(argv) > index + 1 else ""

    if project == "--list-hosts" or (not project and host == "--list-hosts"):
        return list_hosts()
    if project == "--list-tasks":
        return list_tasks(host)
    if not project:
        return _fail(__doc__.strip(), 1)
    try:
        return resolve(project, host, src)
    except core.ConfigError as exc:
        return _fail("[ERROR] %s" % exc, 3)
    except OSError as exc:
        return _fail("[ERROR] 读取配置失败: %s" % exc, 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
