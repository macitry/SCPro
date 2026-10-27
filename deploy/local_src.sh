#!/bin/bash
#===============================================================================
# local_src.sh —— 本地源仓库路径规则（唯一实现）
#
# 取值来源（优先级从高到低）:
#   1. 命令行 --src <目录>
#   2. deploy_config.yaml 目标段的 local_src
#   3. 各脚本内置的默认目录（相对工作区）
#
# 值的写法:
#   /home/xxx/yyy        绝对路径 -> 原样使用
#   ~/yyy  或  ~         以 ~ 开头 -> 展开为 $HOME
#   其它相对路径          -> 相对「工作区根目录」（见 resolve_workspace_root）
#   例: local_src: "demo/robot_ws"
#
# 用法（在脚本里）:
#   # shellcheck source=deploy/local_src.sh
#   source "${SCRIPT_DIR}/local_src.sh"
#   SRC_DIR="$(resolve_local_src "${SRC_ARG:-${DEPLOY_LOCAL_SRC:-demo/robot_ws}}")"
#===============================================================================

# 本文件所在目录 = app 的 deploy/；app 目录 = 它的上一级
if [[ -z "${LOCAL_SRC_SCRIPT_DIR:-}" ]]; then
    LOCAL_SRC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
LOCAL_SRC_APP_DIR="$(dirname "$LOCAL_SRC_SCRIPT_DIR")"

#===============================================================================
# resolve_workspace_root
#   本地源码相对路径的基准目录。优先级：
#     1) 环境变量 DEPLOY_WORKSPACE_ROOT
#     2) deploy_config.yaml 的 workspace_root（支持 ~ 与绝对路径）
#     3) app 目录的上一级
#   与 deploy_core.py 的 workspace_root() 保持同一规则。
#===============================================================================
workspace_root_from_config() {
    local yaml="${LOCAL_SRC_SCRIPT_DIR}/deploy_config.yaml"
    [[ -f "$yaml" ]] || return 0
    sed -n 's/^workspace_root:[[:space:]]*"\{0,1\}\([^"#]*\)"\{0,1\}.*/\1/p' "$yaml" | head -1 | xargs
}

resolve_workspace_root() {
    local raw="${DEPLOY_WORKSPACE_ROOT:-}"
    [[ -z "$raw" ]] && raw="$(workspace_root_from_config)"
    if [[ -z "$raw" ]]; then
        printf '%s' "$(dirname "$LOCAL_SRC_APP_DIR")"
        return 0
    fi
    case "$raw" in
        "~")   printf '%s' "$HOME" ;;
        "~"/*) printf '%s' "${HOME}/${raw:2}" ;;
        *)     printf '%s' "$raw" ;;
    esac
}

#===============================================================================
# resolve_local_src <值>
#   归一化为绝对路径（去掉首尾引号与结尾多余的 /），空值返回 1
#===============================================================================
resolve_local_src() {
    local raw="${1:-}"

    if [[ -z "$raw" ]]; then
        return 1
    fi

    # 兼容从 YAML 里读到的带引号写法
    raw="${raw#\"}"; raw="${raw%\"}"
    raw="${raw#\'}"; raw="${raw%\'}"

    # 去掉结尾多余的 /（保留单独的 "/"）
    if [[ "$raw" != "/" ]]; then
        raw="${raw%/}"
    fi

    case "$raw" in
        "~")    printf '%s' "$HOME" ;;
        "~"/*)  printf '%s' "${HOME}/${raw:2}" ;;
        /*)     printf '%s' "$raw" ;;
        *)      printf '%s' "$(resolve_workspace_root)/${raw}" ;;
    esac
}

#===============================================================================
# local_src_from_config <段名>
#   从 deploy_config.yaml 指定段读 local_src（带引号/不带引号都可以）
#   不依赖 deploy_config.sh，供 copy / 打包等不需要连接信息的场景使用
#   未配置时无输出并返回 1
#   例: local_src_from_config "demo_repo"   ->  demo/robot_ws
#===============================================================================
local_src_from_config() {
    local section="${1:-}"
    local yaml="${LOCAL_SRC_SCRIPT_DIR}/deploy_config.yaml"

    if [[ -z "$section" || ! -f "$yaml" ]]; then
        return 1
    fi

    awk -v sec="$section" '
        /^[[:space:]]*#/ { next }                  # 注释行
        /^[^[:space:]]/ {                          # 顶级行（段名或顶级标量）
            key = $0
            sub(/:.*$/, "", key)
            inside = (key == sec) ? 1 : 0
            next
        }
        inside {
            key = $1
            sub(/:$/, "", key)
            if (key == "local_src") {
                value = $0
                sub(/^[^:]*:[[:space:]]*/, "", value)
                gsub(/["\047]/, "", value)
                sub(/[[:space:]]+$/, "", value)
                print value
                exit
            }
        }
    ' "$yaml"
}
