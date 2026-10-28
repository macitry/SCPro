#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SCPro 的配置后端（无 Qt 依赖）

随 SCPro 一起分发，所有路径都相对 app 自身，不读上级目录：
  deploy/  部署引擎与配置（deploy_one.sh + *.yaml + ssh_config）
负责：配置读写、Host 发现、项目模型、排除规则、密码表、排序与 CRUD。
"""

from __future__ import annotations

import datetime
import fnmatch
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import yaml

APP_ROOT = Path(__file__).resolve().parent
DEPLOY_DIR = APP_ROOT / "deploy"          # 引擎与配置模板（安装后只读）
TEMPLATE_DIR = DEPLOY_DIR


def _env_path(name: str, default: str) -> Path:
    return Path(os.environ.get(name) or default).expanduser()


def _is_portable() -> bool:
    """程序目录可写就用便携模式（配置放在程序目录内），否则用 XDG 目录。

    安装到 /usr/share 后普通用户不可写，自动落到 ~/.config/scpro 等位置。
    可用 SCPRO_PORTABLE=0/1 强制指定。
    """
    flag = os.environ.get("SCPRO_PORTABLE", "").strip().lower()
    if flag in ("0", "false", "no"):
        return False
    if flag in ("1", "true", "yes"):
        return True
    return os.access(APP_ROOT, os.W_OK)


PORTABLE = _is_portable()

# 可写目录：配置 / 状态 / 缓存
CONFIG_DIR = DEPLOY_DIR if PORTABLE else _env_path("XDG_CONFIG_HOME", "~/.config") / "scpro"
STATE_DIR = (APP_ROOT / "logs") if PORTABLE else (
    _env_path("XDG_STATE_HOME", "~/.local/state") / "scpro" / "logs")
CACHE_DIR = (APP_ROOT / "upload_tmp") if PORTABLE else (
    _env_path("XDG_CACHE_HOME", "~/.cache") / "scpro")
UPLOAD_DIR = (APP_ROOT / "upload_tmp") if PORTABLE else (CACHE_DIR / "upload_tmp")
ASSET_DIR = (APP_ROOT / "web" / "assets") if PORTABLE else (CACHE_DIR / "assets")
LOCK_FILE = (APP_ROOT / ".instance.lock") if PORTABLE else (CACHE_DIR / "instance.lock")

CONFIG_YAML = CONFIG_DIR / "deploy_config.yaml"
CONNECTIONS_YAML = CONFIG_DIR / "robot_connections.yaml"
SSH_CONFIG = CONFIG_DIR / "ssh_config"
SECRETS_YAML = CONFIG_DIR / "deploy_secrets.yaml"
PROJECTS_YAML = CONFIG_DIR / "projects.yaml"
SETTINGS_JSON = CONFIG_DIR / "settings.json"
SSH_SOURCE_CONFIG = Path.home() / ".ssh" / "config"
DEPLOY_ONE_SH = DEPLOY_DIR / "deploy_one.sh"

# 本地私有配置 <- 仓库内模板。首次运行时自动补齐，真实文件不进仓库。
LOCAL_CONFIG_FILES = (
    ("projects.yaml", "projects.example.yaml"),
    ("deploy_config.yaml", "deploy_config.example.yaml"),
    ("ssh_config", "ssh_config.example"),
    ("deploy_secrets.yaml", "deploy_secrets.example.yaml"),
    ("robot_connections.yaml", "robot_connections.example.yaml"),
)

NO_SUFFIX_WORDS = ("-", "none", "null", "off", "no", "无", "不加", "无后缀")


class ConfigError(Exception):
    pass


# ==========================================================================
# 项目模型
# ==========================================================================
@dataclass(frozen=True)
class Action:
    no: int
    group: str
    title: str
    remote_name: str
    local_src: str
    targets: tuple = ()
    excludes: tuple = ()
    error: str = ""

    def rule_for(self, host: str) -> Optional[dict]:
        for rule in self.targets:
            match = str(rule.get("match") or "")
            if match and fnmatch.fnmatchcase(host, match):
                return rule
        return None


# ==========================================================================
# 基础 YAML 读写
# ==========================================================================
def load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as exc:
        raise ConfigError("%s 解析失败: %s" % (path.name, exc))
    return data if isinstance(data, dict) else {}


def _backup(path: Path) -> None:
    if path.exists():
        try:
            shutil.copy2(path, path.parent / (path.name + ".bak"))
        except OSError:
            pass


def _atomic_write(path: Path, text: str) -> None:
    mode = (path.stat().st_mode & 0o777) if path.exists() else None
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    if mode is not None:
        tmp.chmod(mode)
    tmp.replace(path)


def ensure_local_configs() -> List[str]:
    """首次运行：用仓库里的 *.example.* 生成本地私有配置。

    返回本次实际创建的文件名列表；已存在的文件一律不动。
    """
    created: List[str] = []
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for name, example in LOCAL_CONFIG_FILES:
        target = CONFIG_DIR / name
        source = TEMPLATE_DIR / example
        if target.exists() or not source.exists():
            continue
        try:
            shutil.copy2(source, target)
            if name == "deploy_secrets.yaml":
                os.chmod(target, 0o600)
        except OSError as exc:
            raise ConfigError("生成本地配置 %s 失败: %s" % (name, exc))
        created.append(name)
    return created


# ==========================================================================
# 工作区根目录 / 当前 Host / 目录后缀 / 本地源码
# ==========================================================================
def workspace_root() -> Path:
    """projects.yaml 里 local_src 写相对路径时的基准目录。

    优先级：环境变量 DEPLOY_WORKSPACE_ROOT > deploy_config.yaml 的
    workspace_root > app 目录的上一级。支持 ~ 与绝对路径。
    与 deploy/local_src.sh 的 resolve_workspace_root 保持同一规则。
    """
    raw = os.environ.get("DEPLOY_WORKSPACE_ROOT", "").strip()
    if not raw:
        raw = str(load_yaml(CONFIG_YAML).get("workspace_root") or "").strip()
    if not raw:
        return APP_ROOT.parent if PORTABLE else Path.home()
    if raw == "~":
        return Path.home()
    if raw.startswith("~/"):
        return Path.home() / raw[2:]
    path = Path(raw)
    return path if path.is_absolute() else (APP_ROOT / path).resolve()


def read_current_host() -> str:
    cfg = load_yaml(CONFIG_YAML)
    return str(cfg.get("current_host") or cfg.get("current_robot") or "").strip()


def write_current_host(host: str) -> None:
    text = CONFIG_YAML.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r"(?m)^(current_host:[ \t]*)\"?[^\"\n#]*\"?",
        lambda m: '%s"%s"' % (m.group(1), host),
        text, count=1)
    if count == 0:
        new_text, count = re.subn(
            r"(?m)^current_robot:[ \t]*\"?[^\"\n#]*\"?",
            'current_host: "%s"' % host, text, count=1)
    if count == 0:
        raise ConfigError("deploy_config.yaml 中未找到 current_host 行")
    _backup(CONFIG_YAML)
    _atomic_write(CONFIG_YAML, new_text)


def config_name_suffix() -> str:
    value = load_yaml(CONFIG_YAML).get("name_suffix")
    return str(value if value is not None else "").strip()


def resolve_name_suffix(raw: str = "") -> str:
    value = (raw or "").strip()
    if not value:
        value = os.environ.get("DEPLOY_NAME_SUFFIX", "").strip()
    if not value:
        value = config_name_suffix()
    if not value:
        return "_" + datetime.date.today().strftime("%Y%m%d")
    if value.lower() in NO_SUFFIX_WORDS:
        return ""
    return value if value.startswith("_") else "_" + value


def write_name_suffix(value: str) -> None:
    if "\n" in value or "\r" in value:
        raise ConfigError("后缀不能包含换行")
    text = CONFIG_YAML.read_text(encoding="utf-8")
    new_text, count = re.subn(
        r'(?m)^(name_suffix:[ \t]*)"?[^"\n#]*"?',
        lambda m: '%s"%s"' % (m.group(1), value),
        text, count=1)
    if count == 0:
        new_text = text.rstrip("\n") + '\nname_suffix: "%s"\n' % value
    _backup(CONFIG_YAML)
    _atomic_write(CONFIG_YAML, new_text)


def resolve_local_src(raw: str) -> str:
    value = (raw or "").strip().strip('"').strip("'")
    if not value:
        return ""
    if value == "~":
        return str(Path.home())
    if value.startswith("~/"):
        return str(Path.home() / value[2:])
    path = Path(value)
    if not path.is_absolute():
        path = workspace_root() / path
    return str(path)


def compact_local_src(abs_path: str) -> str:
    try:
        return str(Path(abs_path).resolve().relative_to(workspace_root().resolve()))
    except (ValueError, OSError):
        return abs_path


# ==========================================================================
# 项目清单
# ==========================================================================
def resolve_excludes(raw, profiles: dict):
    if isinstance(raw, str):
        if raw not in profiles:
            return [], "引用了不存在的排除模板: %s" % raw
        return [str(x) for x in (profiles.get(raw) or [])], ""
    if isinstance(raw, dict):
        items: List[str] = []
        use = raw.get("use")
        if use:
            if use not in profiles:
                return [], "引用了不存在的排除模板: %s" % use
            items = [str(x) for x in (profiles.get(use) or [])]
        for extra in (raw.get("add") or []):
            if str(extra) not in items:
                items.append(str(extra))
        for drop in (raw.get("remove") or []):
            if str(drop) in items:
                items.remove(str(drop))
        return items, ""
    if isinstance(raw, list):
        return [str(x) for x in raw], ""
    return [], ""


def load_projects() -> List[Action]:
    data = load_yaml(PROJECTS_YAML)
    projects = data.get("projects") or {}
    profiles = data.get("exclude_profiles") or {}
    rows: List[Action] = []
    for index, name in enumerate(projects, start=1):
        cfg = projects.get(name) or {}
        error = ""
        local_src = str(cfg.get("local_src") or "").strip()
        if not local_src:
            error = "缺少 local_src（不知道该打包哪个本地目录）"
        rules = []
        for item in cfg.get("targets") or []:
            if not isinstance(item, dict) or not item.get("match"):
                error = error or "targets 里有无效规则（每条都要有 match）"
                continue
            rules.append({
                "match": str(item.get("match") or ""),
                "base": str(item.get("base") or ""),
                "subdir": str(item.get("subdir") or "."),
            })
        if not rules and not error:
            error = "没有配置 targets（不知道发到哪个 Host）"
        remote_name = str(cfg.get("remote_name") or "").strip() or local_src.rstrip(
            "/").rsplit("/", 1)[-1]
        excludes, exclude_error = resolve_excludes(cfg.get("excludes"), profiles)
        error = error or exclude_error
        rows.append(Action(
            no=index, group="project", title=str(name),
            remote_name=remote_name, local_src=local_src,
            targets=tuple(rules), excludes=tuple(excludes), error=error))
    return rows


def _yaml_quote(value: str) -> str:
    return '"%s"' % value.replace("\\", "\\\\").replace('"', '\\"')


def project_block(name: str, values: dict) -> List[str]:
    rules = [r for r in (values.get("targets") or []) if isinstance(r, dict) and r.get("match")]
    if not rules:
        raise ConfigError("至少要配置一条 Host 匹配规则")
    local_src = str(values.get("local_src") or "").strip()
    remote_name = str(values.get("remote_name") or "").strip() or local_src.rstrip("/").rsplit("/", 1)[-1]
    block = ["  %s:" % name,
             "    local_src: %s" % _yaml_quote(local_src),
             "    remote_name: %s" % _yaml_quote(remote_name),
             "    targets:"]
    for rule in rules:
        block.append("      - match: %s" % _yaml_quote(str(rule.get("match") or "")))
        block.append("        base: %s" % _yaml_quote(str(rule.get("base") or "")))
        block.append("        subdir: %s" % _yaml_quote(str(rule.get("subdir") or ".")))
    excludes = values.get("excludes")
    if isinstance(excludes, str) and excludes:
        block += ["    excludes:", "      use: %s" % excludes]
    elif isinstance(excludes, dict) and excludes.get("use"):
        block.append("    excludes:")
        block.append("      use: %s" % excludes["use"])
        for key in ("add", "remove"):
            items = excludes.get(key) or []
            if items:
                block.append("      %s:" % key)
                block += ["        - %s" % _yaml_quote(str(x)) for x in items]
    elif isinstance(excludes, list) and excludes:
        block.append("    excludes:")
        block += ["      - %s" % _yaml_quote(str(x)) for x in excludes]
    return block


def _check_project_name(name: str, existing: List[str]) -> None:
    if not name:
        raise ConfigError("项目名不能为空")
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", name):
        raise ConfigError("项目名只能用字母、数字、下划线、点和减号: %s" % name)
    if name in existing:
        raise ConfigError("项目名已被占用: %s" % name)


def _find_project_lines(lines: List[str], name: str):
    pattern = re.compile(r"^(\s+)([A-Za-z0-9_.\-]+)\s*:\s*$")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match and match.group(2) == name:
            indent = len(match.group(1))
            end = len(lines)
            for cursor in range(index + 1, len(lines)):
                row = lines[cursor]
                if not row.strip():
                    continue
                if len(row) - len(row.lstrip()) <= indent:
                    end = cursor
                    break
            return index, end, indent
    return None, None, 0


def write_new_project(values: dict) -> None:
    name = str(values.get("name") or "").strip()
    data = load_yaml(PROJECTS_YAML)
    _check_project_name(name, list(data.get("projects") or {}))
    block = project_block(name, values) + [""]
    lines = PROJECTS_YAML.read_text(encoding="utf-8").splitlines()
    insert_at = len(lines)
    for index, line in enumerate(lines):
        if "新增项目就照下面这段改" in line:
            marker = index
            while marker > 0 and not lines[marker].strip().startswith("# ===="):
                marker -= 1
            insert_at = marker
            break
    lines[insert_at:insert_at] = block
    _backup(PROJECTS_YAML)
    _atomic_write(PROJECTS_YAML, "\n".join(lines) + "\n")


def write_project(values: dict, old_name: str) -> None:
    name = str(values.get("name") or "").strip()
    data = load_yaml(PROJECTS_YAML)
    others = [n for n in (data.get("projects") or {}) if n != old_name]
    _check_project_name(name, others)
    lines = PROJECTS_YAML.read_text(encoding="utf-8").splitlines()
    start, end, _indent = _find_project_lines(lines, old_name)
    if start is None:
        raise ConfigError("projects.yaml 里找不到项目: %s" % old_name)
    lines[start:end] = project_block(name, values) + [""]
    _backup(PROJECTS_YAML)
    _atomic_write(PROJECTS_YAML, "\n".join(lines) + "\n")


def delete_project(name: str) -> None:
    lines = PROJECTS_YAML.read_text(encoding="utf-8").splitlines()
    start, end, _indent = _find_project_lines(lines, name)
    if start is None:
        raise ValueError("项目不存在: %s" % name)
    _backup(PROJECTS_YAML)
    _atomic_write(PROJECTS_YAML, "\n".join(lines[:start] + lines[end:]) + "\n")


def reorder_projects(order: List[str]) -> None:
    data = load_yaml(PROJECTS_YAML)
    projects = data.get("projects") or {}
    if set(order) != set(projects):
        raise ConfigError("项目列表与 projects.yaml 不一致，请先重新加载项目")
    lines = PROJECTS_YAML.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^projects:\s*$", line):
            start = index
            break
    if start is None:
        raise ConfigError("projects.yaml 里找不到 projects: 段")
    last_name = list(projects.keys())[-1]
    _start, end, _indent = _find_project_lines(lines, last_name)
    if end is None:
        end = len(lines)
    blocks: List[str] = []
    for name in order:
        cfg = projects.get(name) or {}
        blocks += project_block(name, {
            "local_src": cfg.get("local_src"),
            "remote_name": cfg.get("remote_name"),
            "targets": cfg.get("targets"),
            "excludes": cfg.get("excludes"),
        }) + [""]
    _backup(PROJECTS_YAML)
    _atomic_write(PROJECTS_YAML, "\n".join(lines[:start + 1] + blocks + lines[end:]) + "\n")


# ==========================================================================
# Host
# ==========================================================================
def ssh_config_source() -> Path:
    """当前生效的 SSH 配置：系统 ~/.ssh/config 优先，缺失时用项目自带副本。"""
    return SSH_SOURCE_CONFIG if SSH_SOURCE_CONFIG.exists() else SSH_CONFIG


def read_hosts_config() -> dict:
    data = load_yaml(PROJECTS_YAML).get("hosts") or {}
    return {
        "ignore": [str(x) for x in (data.get("ignore") or [])],
        "ports": {str(k): str(v) for k, v in (data.get("ports") or {}).items()},
    }


def write_hosts_config(ignore: list, ports: dict) -> None:
    lines = PROJECTS_YAML.read_text(encoding="utf-8").splitlines()
    start = None
    for index, line in enumerate(lines):
        if re.match(r"^hosts:\s*$", line):
            start = index
            break
    if start is None:
        raise ValueError("projects.yaml 里没有 hosts: 段")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line and not line[0].isspace() and not line.lstrip().startswith("#"):
            end = index
            break
    block = ["hosts:", "  # 不参与部署的 Host（按名字通配）", "  ignore:"]
    for pattern in ignore:
        pattern = str(pattern).strip()
        if pattern:
            block.append('    - "%s"' % pattern.replace('"', '\\"'))
    block.append("  # 端口覆盖（不写就用 ssh_config 的 Port）")
    if ports:
        block.append("  ports:")
        for alias, port in ports.items():
            block.append('    "%s": %d' % (str(alias).replace('"', '\\"'), int(port)))
    else:
        block.append("  ports: {}")
    block.append("")
    _backup(PROJECTS_YAML)
    _atomic_write(PROJECTS_YAML, "\n".join(lines[:start] + block + lines[end:]) + "\n")


def load_hosts(path: Path | None = None) -> Dict[str, dict]:
    """解析 Host 列表；path 为空时用当前生效来源（系统优先，项目副本兜底）。"""
    data = load_yaml(PROJECTS_YAML)
    host_cfg = data.get("hosts") or {}
    ignore = [str(x) for x in (host_cfg.get("ignore") or [])]
    ports = {str(k): str(v) for k, v in (host_cfg.get("ports") or {}).items()}
    conns = load_yaml(CONNECTIONS_YAML).get("connections") or {}
    secrets = load_yaml(SECRETS_YAML).get("secrets") or {}
    try:
        lines = (path or ssh_config_source()).read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return {}
    raw_hosts: Dict[str, dict] = {}
    current: List[str] = []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        key, val = parts[0].lower(), parts[1].strip()
        if key == "host":
            current = val.split()
            for alias in current:
                raw_hosts.setdefault(alias, {})
        elif key in ("hostname", "user", "port") and current:
            for alias in current:
                raw_hosts[alias].setdefault(key, val)
    result = {}
    for alias, opts in raw_hosts.items():
        if any(fnmatch.fnmatchcase(alias, pat) for pat in ignore):
            continue
        ssh_port = str(opts.get("port") or "22")
        if alias in ports:
            opts["port"] = ports[alias]
        secret_key = alias
        for key, val in conns.items():
            if isinstance(val, dict) and str(val.get("ssh_host") or "") == alias:
                secret_key = key
                break
        result[alias] = {
            "alias": alias,
            "user": str(opts.get("user") or ""),
            "host": str(opts.get("hostname") or ""),
            "port": str(opts.get("port") or "22"),
            "ssh_port": ssh_port,
            "secret_key": secret_key,
            "has_password": bool(str(secrets.get(secret_key) or "").strip()),
        }
    return dict(sorted(result.items()))


def remote_dir(host_info: dict, action: Action, suffix: str = "") -> str:
    rule = action.rule_for(host_info.get("alias", ""))
    if rule is None:
        return ""
    sub = str(rule.get("subdir") or ".")
    sub = "" if sub in (".", "./") else sub
    parts = [p for p in (str(rule.get("base") or "").rstrip("/"), sub,
                         action.remote_name + suffix) if p]
    return "/".join(parts) + "/"


def _install_bundled_ssh_config() -> None:
    """系统没有 ~/.ssh/config 时，用项目自带副本初始化一份。"""
    target_dir = SSH_SOURCE_CONFIG.parent
    created_dir = not target_dir.exists()
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        if created_dir:
            os.chmod(target_dir, 0o700)
        shutil.copy2(SSH_CONFIG, SSH_SOURCE_CONFIG)
        os.chmod(SSH_SOURCE_CONFIG, 0o600)
    except OSError as exc:
        raise ConfigError("写入 %s 失败: %s" % (SSH_SOURCE_CONFIG, exc))


def sync_hosts() -> dict:
    """刷新 Host 列表，并在系统配置与项目副本之间同步。

    - ~/.ssh/config 存在  -> 以它为准，覆盖项目内 deploy/ssh_config（新机器进来后
      能同步回项目，随项目分发）；
    - ~/.ssh/config 不存在 -> 用项目自带副本初始化 ~/.ssh/config（权限 600）。
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # 以“上次同步后的项目副本”为基线，才能算出本次新增/移除了哪些 Host
    old = set(load_hosts(SSH_CONFIG))
    if SSH_SOURCE_CONFIG.exists():
        try:
            shutil.copy2(SSH_SOURCE_CONFIG, SSH_CONFIG)
        except OSError as exc:
            raise ConfigError("更新项目内 ssh_config 副本失败: %s" % exc)
        direction = "system-to-bundled"
        source = SSH_SOURCE_CONFIG
    elif SSH_CONFIG.exists():
        _install_bundled_ssh_config()
        direction = "bundled-to-system"
        source = SSH_CONFIG
    else:
        raise ConfigError("找不到 SSH 配置: %s 与 %s 都不存在"
                          % (SSH_SOURCE_CONFIG, SSH_CONFIG))
    new = set(load_hosts())
    if not new:
        raise ConfigError("%s 中没有找到可用的 Host" % source)
    return {
        "added": sorted(new - old),
        "removed": sorted(old - new),
        "hosts": sorted(new),
        "source": str(source),
        "direction": direction,
    }


# ==========================================================================
# Host 增删（直接改 ~/.ssh/config，改动前备份）
# ==========================================================================
_ALIAS_BAD_CHARS = set("*?!#")


def _alias_in_config(text: str, alias: str) -> bool:
    for line in text.splitlines():
        entry = line.strip()
        if entry.lower().startswith("host "):
            if alias in entry.split()[1:]:
                return True
    return False


def _ssh_edit_target() -> Path:
    """增删操作的目标文件：系统配置优先，缺失时改项目内的副本。"""
    return SSH_SOURCE_CONFIG if SSH_SOURCE_CONFIG.exists() else SSH_CONFIG


def _check_alias(alias: str) -> str:
    alias = (alias or "").strip()
    if not alias:
        raise ConfigError("别名不能为空")
    if any(ch.isspace() for ch in alias) or any(ch in alias for ch in _ALIAS_BAD_CHARS):
        raise ConfigError("别名不能包含空格或 * ? ! #")
    if alias.startswith("-"):
        raise ConfigError("别名不能以 - 开头")
    return alias


def add_host(alias: str, hostname: str, user: str, port="22") -> None:
    """在 ~/.ssh/config 末尾追加一个 Host，首次创建时沿用现有配置内容。"""
    alias = _check_alias(alias)
    hostname = (hostname or "").strip()
    user = (user or "").strip()
    port = str(port or "22").strip() or "22"
    if not hostname or any(ch.isspace() for ch in hostname):
        raise ConfigError("地址不能为空，且不能包含空格")
    if not user or any(ch.isspace() for ch in user):
        raise ConfigError("用户不能为空，且不能包含空格")
    try:
        port_no = int(port)
    except ValueError:
        raise ConfigError("端口必须是数字")
    if not 1 <= port_no <= 65535:
        raise ConfigError("端口必须在 1-65535 之间")

    created = not SSH_SOURCE_CONFIG.exists()
    if created:
        base = SSH_CONFIG.read_text(encoding="utf-8") if SSH_CONFIG.exists() else ""
    else:
        base = SSH_SOURCE_CONFIG.read_text(encoding="utf-8")
    if _alias_in_config(base, alias):
        raise ConfigError("Host 已存在: %s" % alias)

    block = "\n".join([
        "# Added by SCPro",
        "Host %s" % alias,
        "  HostName %s" % hostname,
        "  User %s" % user,
        "  Port %d" % port_no,
    ])
    new_text = ((base.rstrip("\n") + "\n\n" + block) if base.strip() else block) + "\n"
    try:
        SSH_SOURCE_CONFIG.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if created:
            os.chmod(SSH_SOURCE_CONFIG.parent, 0o700)
        _backup(SSH_SOURCE_CONFIG)
        _atomic_write(SSH_SOURCE_CONFIG, new_text)
        if created:
            os.chmod(SSH_SOURCE_CONFIG, 0o600)
    except OSError as exc:
        raise ConfigError("写入 %s 失败: %s" % (SSH_SOURCE_CONFIG, exc))


def delete_host(alias: str) -> None:
    """从 ssh 配置里删除一个 Host（多别名行只去掉该别名）。"""
    alias = (alias or "").strip()
    if not alias:
        raise ConfigError("Host 别名不能为空")
    if any(ch in alias for ch in "*?!"):
        raise ConfigError("通配 Host 不能在这里删除")

    path = _ssh_edit_target()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ConfigError("读取 %s 失败: %s" % (path, exc))

    start = end = None
    tokens: List[str] = []
    indent = ""
    for index, line in enumerate(lines):
        entry = line.strip()
        if entry.lower().startswith("host "):
            parts = entry.split()[1:]
            if alias in parts:
                start, tokens = index, parts
                indent = line[:len(line) - len(line.lstrip())]
                break
    if start is None:
        raise ConfigError("SSH 配置里没有这个 Host: %s" % alias)

    for cursor in range(start + 1, len(lines)):
        entry = lines[cursor].strip().lower()
        if entry.startswith("host ") or entry.startswith("match "):
            end = cursor
            break
    if end is None:
        end = len(lines)

    if len(tokens) > 1:
        lines[start] = indent + "Host " + " ".join(t for t in tokens if t != alias)
    else:
        if end < len(lines) and not lines[end].strip():
            end += 1
        del lines[start:end]

    try:
        _backup(path)
        _atomic_write(path, "\n".join(lines).rstrip("\n") + "\n")
    except OSError as exc:
        raise ConfigError("写入 %s 失败: %s" % (path, exc))


# ==========================================================================
# 密码
# ==========================================================================
def read_secrets() -> Dict[str, str]:
    secrets = load_yaml(SECRETS_YAML).get("secrets") or {}
    return {str(key): str(val if val is not None else "") for key, val in secrets.items()}


def write_secrets(updates: Dict[str, str]) -> None:
    for key, value in updates.items():
        if "\n" in value or "\r" in value:
            raise ConfigError("%s 的密码不能包含换行" % key)
    if SECRETS_YAML.exists():
        _backup(SECRETS_YAML)
        lines = SECRETS_YAML.read_text(encoding="utf-8").splitlines()
    else:
        lines = ["secrets:"]

    def dump(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"')

    pending = dict(updates)
    out: List[str] = []
    for line in lines:
        match = re.match(r"^(\s+)([A-Za-z0-9_.\-]+)(\s*):\s*.*$", line)
        if match and match.group(2) in pending:
            key = match.group(2)
            out.append('%s%s: "%s"' % (match.group(1), key, dump(pending.pop(key))))
        else:
            out.append(line)
    if pending:
        if not any(entry.strip() == "secrets:" for entry in out):
            out.append("secrets:")
        for key in sorted(pending):
            out.append('  %s: "%s"' % (key, dump(pending[key])))
    _atomic_write(SECRETS_YAML, "\n".join(out) + "\n")
