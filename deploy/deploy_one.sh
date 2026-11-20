#!/bin/bash
#===============================================================================
# 脚本: deploy_one.sh —— 通用部署引擎（Host + Project）
#
# 没有 AI/MC 角色概念：目标是 ~/.ssh/config 里的一个 Host 别名，
# 项目按 Host 名字的通配规则（projects.yaml 的 targets）决定远端路径。
#
# 用法:
#   ./deploy_one.sh <项目名> --host <Host别名> [选项]
#   ./deploy_one.sh --list-hosts               列出可用 Host
#   ./deploy_one.sh <项目> --host X --plan     只打印解析结果
#
# 选项:
#   --host <别名>     目标 Host（不写则取 deploy_config.yaml 的 current_host）
#   --pack-only       只做本地打包，不上传
#   --skip-copy       跳过打包，直接上传已有的本地包
#   --suffix <值>     目录后缀（本地与远端目录名同时跟随）
#   --no-suffix       不加后缀
#   --src <目录>      覆盖 projects.yaml 里的 local_src
#   --dst <目录>      覆盖本地打包目录
#   --delete-remote   删除远端目录中本地包不存在的文件（默认保留）
#   --keep-package    上传完成后保留本地打包目录
#   --dry-run         预演：只列出会发生的变化，不写本地、不改远端
#   --plan            只打印解析结果（源码/打包目录/远端路径），什么都不做
#   --yes             自动应答确认（图形界面 / 脚本调用用）
#   -h|--help         帮助
#
# SSH 配置来源: ~/.ssh/config 优先，缺失时用本目录的 ssh_config；
#               环境变量 DEPLOY_SSH_CONFIG 可显式指定。
#
# 解析规则（Host / 端口覆盖 / 排除模板 / 后缀 / 源码路径）只在 ../deploy_core.py
# 实现一次，本脚本通过 resolve.py 复用，请勿在 shell 里再写一份。
#===============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # 引擎与模板（安装后只读）
APP_DIR="$(dirname "$SCRIPT_DIR")"                            # 程序根目录
TEMPLATE_DIR="$SCRIPT_DIR"

# 配置目录：GUI 会传 SCPRO_CONFIG_DIR；命令行独立运行时自动判断便携 / XDG
if [[ -n "${SCPRO_CONFIG_DIR:-}" ]]; then
    CONFIG_DIR="$SCPRO_CONFIG_DIR"
    PORTABLE="${SCPRO_PORTABLE:-0}"
elif [[ "${SCPRO_PORTABLE:-auto}" == "0" ]]; then
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/scpro"
    PORTABLE=0
elif [[ -f "${SCRIPT_DIR}/projects.yaml" ]]; then
    CONFIG_DIR="$SCRIPT_DIR"
    PORTABLE=1
else
    CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/scpro"
    PORTABLE=0
fi
mkdir -p "$CONFIG_DIR"

PROJECTS_YAML="${CONFIG_DIR}/projects.yaml"
DEPLOY_YAML="${CONFIG_DIR}/deploy_config.yaml"

# 本地打包缓存
if [[ -n "${SCPRO_UPLOAD_DIR:-}" ]]; then
    UPLOAD_TMP_DIR="$SCPRO_UPLOAD_DIR"
elif [[ "$PORTABLE" == "1" ]]; then
    UPLOAD_TMP_DIR="${APP_DIR}/upload_tmp"
else
    UPLOAD_TMP_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/scpro/upload_tmp"
fi

# 首次运行：缺少本地私有配置时，从模板目录生成（真实配置不进仓库）
for _pair in \
    "projects.yaml:projects.example.yaml" \
    "deploy_config.yaml:deploy_config.example.yaml" \
    "ssh_config:ssh_config.example" \
    "deploy_secrets.yaml:deploy_secrets.example.yaml" \
    "robot_connections.yaml:robot_connections.example.yaml"
do
    _name="${_pair%%:*}"
    _example="${_pair##*:}"
    if [[ ! -f "${CONFIG_DIR}/${_name}" && -f "${TEMPLATE_DIR}/${_example}" ]]; then
        cp -p "${TEMPLATE_DIR}/${_example}" "${CONFIG_DIR}/${_name}"
        if [[ "$_name" == "deploy_secrets.yaml" ]]; then
            chmod 600 "${CONFIG_DIR}/${_name}"
        fi
        echo "[INFO] 已从 ${_example} 生成本地配置 ${_name}"
    fi
done
unset _pair _name _example

export SCPRO_CONFIG_DIR="$CONFIG_DIR"
export SCPRO_PORTABLE="$PORTABLE"

# 解析规则（Host / 端口覆盖 / 排除模板 / 后缀 / 源码路径）只在 deploy_core.py
# 里实现一次；resolve.py 把结果转成 shell 能 eval 的 KEY=value，不重复规则。
RESOLVE_PY="${SCRIPT_DIR}/resolve.py"

_yaml_guard() {
    if [[ ! -f "$PROJECTS_YAML" ]]; then
        echo "[ERROR] 项目清单不存在: $PROJECTS_YAML" >&2
        return 1
    fi
    if ! command -v python3 &>/dev/null || ! python3 -c "import yaml" &>/dev/null; then
        echo "[ERROR] 需要 python3 + PyYAML（sudo apt install python3-yaml）" >&2
        return 1
    fi
}

#===============================================================================
# Host 发现 + 项目规则解析
#   规则只在 deploy_core.py 里实现一次，这里只转调 resolve.py。
#===============================================================================
_hosts_and_project() {
    _yaml_guard || return 1
    # 后缀规则也只在 deploy_core 里，用环境变量把它交给子进程
    export DEPLOY_NAME_SUFFIX="${DEPLOY_NAME_SUFFIX:-}"
    python3 "$RESOLVE_PY" "$@"
}

print_help() {
    sed -n '2,27p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    echo ""
    echo "可用 Host:"
    _hosts_and_project --list-hosts | sed 's/^/  - /'
}

#===============================================================================
# 参数
#===============================================================================
PROJECT=""
HOST=""
PACK_ONLY=false
SKIP_COPY=false
DELETE_REMOTE=false
KEEP_PACKAGE=false
DRY_RUN=false
PLAN_ONLY=false
ASSUME_YES=false
SRC_ARG=""
DST_ARG=""
LIST_HOSTS=false
LIST_TASKS=false
TASKS_HOST=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)   print_help; exit 0 ;;
        --list-hosts) LIST_HOSTS=true; shift ;;
        --list-tasks)
            LIST_TASKS=true
            shift
            if [[ $# -gt 0 && "$1" != -* ]]; then TASKS_HOST="$1"; shift; fi
            ;;
        --host)      HOST="${2:-}"; shift 2 ;;
        --host=*)    HOST="${1#*=}"; shift ;;
        --pack-only) PACK_ONLY=true; shift ;;
        --skip-copy) SKIP_COPY=true; shift ;;
        --delete-remote) DELETE_REMOTE=true; shift ;;
        --keep-package) KEEP_PACKAGE=true; shift ;;
        --suffix)    DEPLOY_NAME_SUFFIX="${2:-}"; shift 2 ;;
        --suffix=*)  DEPLOY_NAME_SUFFIX="${1#*=}"; shift ;;
        --no-suffix) DEPLOY_NAME_SUFFIX="-"; shift ;;
        --src)       SRC_ARG="${2:-}"; shift 2 ;;
        --src=*)     SRC_ARG="${1#*=}"; shift ;;
        --dst)       DST_ARG="${2:-}"; shift 2 ;;
        --dst=*)     DST_ARG="${1#*=}"; shift ;;
        --dry-run)   DRY_RUN=true; shift ;;
        --plan)      PLAN_ONLY=true; shift ;;
        --yes|-y)    ASSUME_YES=true; shift ;;
        -*)          echo "[ERROR] 未知参数: $1（用 --help 查看用法）" >&2; exit 1 ;;
        *)           PROJECT="$1"; shift ;;
    esac
done

if [[ "$LIST_HOSTS" == true ]]; then
    _hosts_and_project --list-hosts
    exit 0
fi

CURRENT_HOST="$(sed -n 's/^current_host:[[:space:]]*"\{0,1\}\([^"#]*\)"\{0,1\}.*/\1/p' "$DEPLOY_YAML" | head -1 | xargs)"
if [[ "$LIST_TASKS" == true ]]; then
    _hosts_and_project --list-tasks "${TASKS_HOST:-$CURRENT_HOST}"
    exit $?
fi

if [[ -z "$PROJECT" ]]; then
    echo "[ERROR] 缺少项目名（--help 查看用法）" >&2
    exit 1
fi
if [[ "$PACK_ONLY" == true && "$SKIP_COPY" == true ]]; then
    echo "[ERROR] --pack-only 与 --skip-copy 不能同时使用" >&2
    exit 1
fi

if [[ -z "$HOST" ]]; then
    HOST="$CURRENT_HOST"
fi
if [[ -z "$HOST" ]]; then
    echo "[ERROR] 没有指定 --host，且 deploy_config.yaml 里没有 current_host" >&2
    exit 1
fi

RESOLVE_ARGS=("$PROJECT" "$HOST")
if [[ -n "$SRC_ARG" ]]; then
    RESOLVE_ARGS+=(--src "$SRC_ARG")
fi
VARS="$(_hosts_and_project "${RESOLVE_ARGS[@]}")" || exit $?
unset RESOLVE_ARGS
eval "$VARS"

NAME_SUFFIX="$P_NAME_SUFFIX"
SRC_DIR="$P_SRC_DIR"
WORKSPACE_DIR="$P_WORKSPACE_DIR"
LOCAL_PKG_DIR="${DST_ARG:-${UPLOAD_TMP_DIR}/${P_REMOTE_NAME}${NAME_SUFFIX}}"
[[ -n "$SRC_DIR" ]] || { echo "[ERROR] 无法解析本地源码目录: ${P_LOCAL_SRC}" >&2; exit 1; }

EXCLUDES=()
[[ -n "${P_EXCLUDES:-}" ]] && eval "EXCLUDES=( ${P_EXCLUDES} )"

SUB_DIR="${R_SUBDIR}"
[[ "$SUB_DIR" == "." || "$SUB_DIR" == "./" ]] && SUB_DIR=""
REMOTE_DIR="${R_BASE%/}"
[[ -n "$SUB_DIR" ]] && REMOTE_DIR="${REMOTE_DIR}/${SUB_DIR}"
REMOTE_DIR="${REMOTE_DIR}/${P_REMOTE_NAME}${NAME_SUFFIX}"

_assert_safe_local_pkg() {
    local target source critical depth
    target="$(realpath -m -- "$LOCAL_PKG_DIR")"
    source="$(realpath -m -- "$SRC_DIR")"
    if [[ -z "$target" || "$target" == "/" ]]; then
        echo "[ERROR] 拒绝使用根目录作为本地打包目录" >&2
        return 1
    fi
    for critical in "$HOME" "$WORKSPACE_DIR" "$APP_DIR" \
                    "$TEMPLATE_DIR" "$CONFIG_DIR" "$UPLOAD_TMP_DIR" "$source"; do
        if [[ "$target" == "$critical" ]]; then
            echo "[ERROR] 拒绝将受保护目录作为打包缓存: $target" >&2
            return 1
        fi
    done
    if [[ "$source" == "$target/"* || "$target" == "$source/"* ]]; then
        echo "[ERROR] 打包目录不能与源码目录重叠: $target" >&2
        return 1
    fi
    depth="$(awk -F/ '{print NF - 1}' <<< "$target")"
    if (( depth < 3 )); then
        echo "[ERROR] 打包目录层级过浅，拒绝清理: $target" >&2
        return 1
    fi
}

_safe_remove_local_pkg() {
    _assert_safe_local_pkg || return 1
    rm -rf -- "$(realpath -m -- "$LOCAL_PKG_DIR")"
}

command -v rsync &>/dev/null || { echo "[ERROR] rsync 未安装" >&2; exit 1; }
if [[ "$SKIP_COPY" == false && ! -d "$SRC_DIR" ]]; then
    echo "[ERROR] 本地源码目录不存在: $SRC_DIR" >&2
    exit 1
fi
if [[ "$SKIP_COPY" == true && ! -d "$LOCAL_PKG_DIR" ]]; then
    echo "[ERROR] 本地部署包不存在: $LOCAL_PKG_DIR（先不带 --skip-copy 跑一次）" >&2
    exit 1
fi

TAG=""
[[ "$DRY_RUN" == true ]] && TAG="[预演] "

echo "============================================"
echo "  ${TAG}部署项目: ${PROJECT}"
echo "============================================"
echo "  目标 Host: ${H_ALIAS}   ${H_USER}@${H_HOSTNAME}:${H_PORT}"
echo "  匹配规则:  ${R_MATCH}"
echo "  远端路径:  ${REMOTE_DIR}/"
echo "  本地源码:  ${SRC_DIR}"
echo "  本地打包:  ${LOCAL_PKG_DIR}"
echo "  目录后缀:  ${NAME_SUFFIX:-（不加后缀）}"
if [[ "$DELETE_REMOTE" == true ]]; then
    echo "  远端清理:  开启（删除本地包中不存在的远端文件）"
else
    echo "  远端清理:  关闭（保留远端多余文件）"
fi
echo "============================================"

if [[ "$PLAN_ONLY" == true ]]; then
    echo "  排除项:    ${EXCLUDES[*]:-（无）}"
    echo "============================================"
    exit 0
fi

_assert_safe_local_pkg || exit 1
RSYNC_DELETE_ARGS=()
[[ "$DELETE_REMOTE" == true ]] && RSYNC_DELETE_ARGS=(--delete)

# -- pack (unless --skip-copy)
if [[ "$SKIP_COPY" == false ]]; then
    if [[ "$DRY_RUN" == false && -d "$LOCAL_PKG_DIR" ]]; then
        if [[ "$ASSUME_YES" == true ]]; then
            _safe_remove_local_pkg
        else
            read -rp "  本地包已存在，删除并重新生成? (y/N): " _ok
            [[ "${_ok:-}" =~ ^[Yy]$ ]] || { echo "[INFO] 已取消。"; exit 1; }
            _safe_remove_local_pkg
        fi
    fi
    mkdir -p "$(dirname "$LOCAL_PKG_DIR")"
    ex_args=()
    for pattern in "${EXCLUDES[@]}"; do
        ex_args+=("--exclude=${pattern}")
    done
    if [[ "$DRY_RUN" == true ]]; then
        rsync -avhn "${ex_args[@]}" "${SRC_DIR}/" "${LOCAL_PKG_DIR}/"
    else
        rsync -avh "${ex_args[@]}" "${SRC_DIR}/" "${LOCAL_PKG_DIR}/"
        echo ""
        echo "[INFO] 打包完成  原始 $(du -sh "$SRC_DIR" | cut -f1) → 精简 $(du -sh "$LOCAL_PKG_DIR" | cut -f1)"
    fi
else
    echo "[INFO] 跳过打包 (--skip-copy)"
fi

if [[ "$PACK_ONLY" == true ]]; then
    echo "[INFO] 仅本地打包，不上传"
    [[ "$DRY_RUN" == true ]] && echo "[DONE] 预演结束，没有改动任何文件"
    exit 0
fi

# -- upload
SSH_E="ssh -p ${H_PORT}"
if [[ -n "${H_SECRET:-}" ]] && command -v sshpass &>/dev/null; then
    export SSHPASS="$H_SECRET"
    SSH_E="sshpass -e ssh -p ${H_PORT}"
fi

if [[ "$DRY_RUN" == false && "$ASSUME_YES" != true ]]; then
    read -rp "  上传到 ${H_USER}@${H_HOSTNAME}:${H_PORT}:${REMOTE_DIR}/ ? (y/N): " _ok
    [[ "${_ok:-}" =~ ^[Yy]$ ]] || { echo "[INFO] 已取消上传"; exit 0; }
fi

if [[ "$DRY_RUN" == true ]]; then
    echo "[预演] 用 rsync -n 检查远端差异（只读）:"
    rsync -avhzn -i "${RSYNC_DELETE_ARGS[@]}" -e "$SSH_E" "${LOCAL_PKG_DIR}/" \
        "${H_USER}@${H_HOSTNAME}:${REMOTE_DIR}/" || true
    echo "[DONE] 预演结束，没有改动任何文件"
    exit 0
fi

echo "[INFO] 检查 SSH 连通性..."
if ! $SSH_E -o ConnectTimeout=5 -o BatchMode=no "${H_USER}@${H_HOSTNAME}" "echo ok" &>/dev/null; then
    echo "[ERROR] SSH 连接失败或需要交互，已停止上传" >&2
    exit 6
fi

REMOTE_DIR_Q="$(printf '%q' "$REMOTE_DIR")"
if ! $SSH_E "${H_USER}@${H_HOSTNAME}" "mkdir -p -- $REMOTE_DIR_Q"; then
    echo "[ERROR] 无法创建远端目录: ${REMOTE_DIR}" >&2
    exit 6
fi

# rsync needs write access to every destination directory, including existing
# children. Check before transfer so a permission problem cannot look like a
# partially successful deployment.
UNWRITABLE_DIR="$($SSH_E "${H_USER}@${H_HOSTNAME}" \
    "find -- $REMOTE_DIR_Q -type d ! -writable -print -quit" 2>/dev/null || true)"
if [[ -n "$UNWRITABLE_DIR" ]]; then
    UNWRITABLE_DIR_Q="$(printf '%q' "$UNWRITABLE_DIR")"
    REMOTE_META="$($SSH_E "${H_USER}@${H_HOSTNAME}" \
        "stat -c '%U:%G %A' -- $UNWRITABLE_DIR_Q" 2>/dev/null || true)"
    echo "[ERROR] 远端目录不可写: ${UNWRITABLE_DIR}" >&2
    [[ -n "$REMOTE_META" ]] && echo "[INFO] 当前所有者/权限: ${REMOTE_META}" >&2
    echo "[HINT] SSH 用户 ${H_USER} 需要拥有该目录及子目录的写权限" >&2
    echo "[HINT] 请在 ${H_ALIAS} 上执行: sudo chown -R ${H_USER}:${H_USER} ${REMOTE_DIR_Q}" >&2
    exit 6
fi

PROGRESS_THRESHOLD_MB="$(sed -n 's/^progress_threshold_mb:[[:space:]]*\([0-9][0-9]*\).*/\1/p' "$DEPLOY_YAML" | head -1)"
PROGRESS_THRESHOLD_MB="${PROGRESS_THRESHOLD_MB:-10}"
BIG_COUNT="$(find "$LOCAL_PKG_DIR" -type f -size +"${PROGRESS_THRESHOLD_MB}"M 2>/dev/null | wc -l)"
if [[ "$BIG_COUNT" -gt 0 ]]; then
    echo "[INFO] 有大文件（>${PROGRESS_THRESHOLD_MB}M）${BIG_COUNT} 个，传输中显示进度与网速"
    rsync -avhz --progress "${RSYNC_DELETE_ARGS[@]}" -e "$SSH_E" "${LOCAL_PKG_DIR}/" \
        "${H_USER}@${H_HOSTNAME}:${REMOTE_DIR}/" \
        | python3 "${SCRIPT_DIR}/rsync_progress.py" "$LOCAL_PKG_DIR" "$PROGRESS_THRESHOLD_MB"
else
    rsync -avhz "${RSYNC_DELETE_ARGS[@]}" -e "$SSH_E" "${LOCAL_PKG_DIR}/" \
        "${H_USER}@${H_HOSTNAME}:${REMOTE_DIR}/"
fi

if [[ "$KEEP_PACKAGE" == false ]]; then
    _safe_remove_local_pkg
    echo "[INFO] 已清理本地打包缓存（--keep-package 可保留）"
fi

echo ""
echo "============================================"
echo "  [DONE] 上传完成"
echo "  远程路径: ${H_USER}@${H_HOSTNAME}:${REMOTE_DIR}/"
echo "============================================"
