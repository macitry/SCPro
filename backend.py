#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""界面与部署核心之间的适配层（全部路径都在 app 目录内）。"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DEPLOY_DIR = APP_DIR / "deploy"
UPLOAD_DIR = APP_DIR / "upload_tmp"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import deploy_core as core  # noqa: E402 - 先注册 app 目录


def snapshot() -> dict:
    """返回界面一次刷新所需的完整 Host、项目与路径状态。"""
    hosts = core.load_hosts()
    current = core.read_current_host()
    if current not in hosts:
        current = next(iter(hosts), "")
    suffix = core.resolve_name_suffix()
    host_info = hosts.get(current, {})
    projects = []
    for project in core.load_projects():
        rule = project.rule_for(current) if current else None
        projects.append({
            "id": project.title,
            "local_src": project.local_src,
            "local_abs": core.resolve_local_src(project.local_src),
            "remote": (core.remote_dir(host_info, project, suffix)
                       if host_info else ""),
            "error": project.error,
            "match": (rule or {}).get("match", ""),
        })
    return {
        "current_host": current,
        "suffix": suffix,
        "hosts": [{
            "alias": alias,
            "user": info.get("user", ""),
            "host": info.get("host", ""),
            "port": info.get("port", ""),
            "ssh_port": info.get("ssh_port", info.get("port", "")),
            "password": bool(info.get("has_password")),
        } for alias, info in hosts.items()],
        "projects": projects,
    }


def set_host(alias: str) -> None:
    core.write_current_host(alias)


def refresh_hosts() -> dict:
    return core.sync_hosts()


def deploy_args(project: str, host: str, delete_remote: bool = False) -> list[str]:
    """构造与命令行完全一致的部署参数。"""
    args = ["bash", str(core.DEPLOY_ONE_SH), project, "--host", host]
    suffix = core.resolve_name_suffix()
    args += ["--suffix", suffix] if suffix else ["--no-suffix"]
    if delete_remote:
        args.append("--delete-remote")
    args.append("--yes")
    return args


def host_secret_key(alias: str) -> str:
    info = core.load_hosts().get(alias) or {}
    return str(info.get("secret_key") or alias)


def write_name_suffix(value: str) -> None:
    core.write_name_suffix(value)


def read_name_suffix() -> str:
    return str(core.load_yaml(core.CONFIG_YAML).get("name_suffix") or "")


def read_hosts_config() -> dict:
    return core.read_hosts_config()


def write_hosts_config(ignore: list, ports: dict) -> None:
    core.write_hosts_config(ignore, ports)


def delete_project(name: str) -> None:
    core.delete_project(name)
