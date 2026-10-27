#!/bin/bash
#===============================================================================
# 部署目录后缀 —— 全流程统一规则
#
# 被 run.sh / deploy_one.sh / deploy_config.sh 与图形界面共同引用，
# 保证「本地打包目录 upload_tmp/<名字>」与「远端落地目录 <remote_base>/<名字>」
# 用的是同一个后缀。
#
# 取值优先级:
#   1) 环境变量 (或命令行 --suffix/--no-suffix)  DEPLOY_NAME_SUFFIX
#   2) deploy_config.yaml 顶级的 name_suffix
#   3) 当天日期
#
# 取值含义:
#   空 / 未设置            -> _$(date +%Y%m%d)，例如 _20260917
#   - | none | 无 | 不加    -> 不加后缀（返回空串）
#   其它                   -> 原样使用，缺前导下划线会自动补（wcz -> _wcz）
#
# 用法:
#   source ".../deploy/name_suffix.sh"
#   suffix="$(resolve_name_suffix)"          # 按上面优先级
#   suffix="$(resolve_name_suffix "_wcz")"   # 强制指定
#===============================================================================

NAME_SUFFIX_YAML="${SCPRO_CONFIG_DIR:-$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)}/deploy_config.yaml"

# 内部: 去掉首尾空白
_name_suffix_trim() {
    local s="${1-}"
    s="${s#"${s%%[![:space:]]*}"}"
    s="${s%"${s##*[![:space:]]}"}"
    printf '%s' "$s"
}

# 从 deploy_config.yaml 读顶级 name_suffix（不依赖 python/yaml）
name_suffix_from_config() {
    local yaml="${NAME_SUFFIX_YAML:-}"
    [[ -f "$yaml" ]] || { printf ''; return 0; }
    sed -n 's/^name_suffix:[[:space:]]*"\{0,1\}\([^"#]*\)"\{0,1\}.*/\1/p' "$yaml" | head -1 | xargs
}

# 归一化 -> 输出生效后缀（空串 = 不加后缀）
resolve_name_suffix() {
    local raw="$(_name_suffix_trim "${1:-}")"
    [[ -z "$raw" ]] && raw="$(_name_suffix_trim "${DEPLOY_NAME_SUFFIX:-}")"
    [[ -z "$raw" ]] && raw="$(_name_suffix_trim "$(name_suffix_from_config)")"

    if [[ -z "$raw" ]]; then
        # 默认: 当天日期
        printf '_%s\n' "$(date +%Y%m%d)"
        return 0
    fi

    case "${raw,,}" in
        -|none|null|off|no|无|不加|无后缀) printf '\n' ;;
        _*)                                printf '%s\n' "$raw" ;;
        *)                                 printf '_%s\n' "$raw" ;;
    esac
}
