#!/usr/bin/env bash
# =============================================================================
#  repo-assistant.sh — 独立 Fork 项目的上游同步助手
# -----------------------------------------------------------------------------
#  用途：
#    1. 查看本地仓库相对上游的落后情况（作者最近更新 + 社区 PR）
#    2. 在本地 main 上 rebase 上游，并在存在 dev 分支时把更新带回到 dev
#
#  核心原则：
#    - 只从上游拉取（fetch / rebase / merge），绝不执行 git push
#    - 遇到冲突绝不自动解决，仅列出冲突文件并以非零退出码停止
#    - 不引入任何需要额外安装的第三方依赖（仅 bash + git + curl + python3）
# =============================================================================

set -euo pipefail

# ---------- 可复用配置（修改此处即可适配其他 Fork） ----------
# 上游仓库的 owner/name（用于拼 GitHub API 地址）
readonly UPSTREAM_OWNER="shy3130"
readonly UPSTREAM_REPO="tick-stock-panel"
# 同步源 remote 名称（脚本会优先探测 upstream，再回退 origin）
readonly PREFERRED_REMOTE="upstream"
readonly FALLBACK_REMOTE="origin"
# 同步分支
readonly TRACK_BRANCH="main"

# ---------- 颜色 / 图标（终端可用时美化输出） ----------
if [[ -t 1 ]] && command -v tput >/dev/null 2>&1 && [[ "$(tput colors 2>/dev/null || echo 0)" -ge 8 ]]; then
    readonly C_RESET=$'\033[0m'
    readonly C_BOLD=$'\033[1m'
    readonly C_BLUE=$'\033[34m'
    readonly C_GREEN=$'\033[32m'
    readonly C_YELLOW=$'\033[33m'
    readonly C_RED=$'\033[31m'
    readonly C_GRAY=$'\033[90m'
else
    readonly C_RESET="" C_BOLD="" C_BLUE="" C_GREEN="" C_YELLOW="" C_RED="" C_GRAY=""
fi

log_info()    { printf "%s[*]%s %s\n" "${C_BLUE}"   "${C_RESET}" "$*"; }
log_ok()      { printf "%s[✓]%s %s\n" "${C_GREEN}"  "${C_RESET}" "$*"; }
log_warn()    { printf "%s[!]%s %s\n" "${C_YELLOW}" "${C_RESET}" "$*"; }
log_error()   { printf "%s[✗]%s %s\n" "${C_RED}"    "${C_RESET}" "$*" >&2; }
log_section() { printf "\n%s%s== %s ==%s\n" "${C_BOLD}${C_BLUE}" "${C_BOLD}${C_BLUE}" "$*" "${C_RESET}"; }

# ---------- 工具函数 ----------

# 强制要求必须在 git 仓库内运行
require_git_repo() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        log_error "当前目录不是 git 仓库，请在项目根目录执行本脚本。"
        exit 1
    fi
}

# 自适应确定同步源 remote：优先 upstream，回退 origin
# 输出 remote 名称到 stdout；若都找不到则返回非零
resolve_remote() {
    if git remote get-url "${PREFERRED_REMOTE}" >/dev/null 2>&1; then
        printf "%s" "${PREFERRED_REMOTE}"
        return 0
    fi
    if git remote get-url "${FALLBACK_REMOTE}" >/dev/null 2>&1; then
        printf "%s" "${FALLBACK_REMOTE}"
        return 0
    fi
    return 1
}

# 当前分支名（detached HEAD 时回退输出 HEAD 描述）
current_branch() {
    git symbolic-ref --quiet --short HEAD 2>/dev/null || git rev-parse --short HEAD
}

# 检查上游 git fetch 期间是否产生真实失败并提示
fetch_remote_main() {
    local remote="$1"
    log_info "拉取 ${remote}/${TRACK_BRANCH}（--prune 清理失效引用）..."
    # 不使用 set -e 兜底：git fetch 返回非零时给出友好提示
    if ! git fetch "${remote}" "${TRACK_BRANCH}" --prune; then
        log_error "git fetch ${remote}/${TRACK_BRANCH} 失败，请检查网络或 remote 配置。"
        exit 1
    fi
}

# 检测冲突文件并打印提示，然后以非零状态退出
abort_on_conflict() {
    local where="$1"   # 发生冲突的上下文（如 "main rebase" / "dev merge"）
    local unmerged
    unmerged="$(git diff --name-only --diff-filter=U || true)"
    if [[ -n "${unmerged}" ]]; then
        log_error "${where} 出现冲突，已停止后续操作（绝不自动解决）。"
        log_error "冲突文件列表："
        while IFS= read -r f; do
            printf "    - %s\n" "${f}"
        done <<< "${unmerged}"
        log_warn "请手动解决冲突后，重新执行 repo-assistant.sh update。"
        exit 2
    fi
    # 无 unmerged 文件但 git rebase/merge 仍然失败：典型原因是工作区未提交改动
    # 导致 git 拒绝操作。此处必须显式失败，绝不能让脚本继续往下走并误报成功。
    log_error "${where} 失败（非冲突，可能工作区有未提交改动或其他前置错误）。"
    log_warn "已停止后续操作，请检查工作区与 remote 配置后重试。"
    exit 1
}

# ---------- 子命令：view ----------

cmd_view() {
    require_git_repo

    local remote
    if ! remote="$(resolve_remote)"; then
        log_error "未找到可用的同步源 remote（需存在 upstream 或 origin）。"
        exit 1
    fi
    log_ok "当前同步源 remote: ${remote}/${TRACK_BRANCH}"

    fetch_remote_main "${remote}"

    log_section "一、作者最近更新（commit，本地落后于 ${remote}/${TRACK_BRANCH}）"

    # 列出本地 HEAD 落后于上游的所有 commit
    # 格式：短hash | ISO时间 | 作者名 | 标题
    local log_format="%h%x1f%aI%x1f%an%x1f%s"
    local ahead_raw
    ahead_raw="$(git log "HEAD..${remote}/${TRACK_BRANCH}" \
                    --pretty=format:"${log_format}" \
                    --date-order 2>/dev/null || true)"

    if [[ -z "${ahead_raw}" ]]; then
        log_ok "本地已与上游同步，无待拉取 commit。"
    else
        # 按时间倒序（最新在前）：git log 默认从新到旧，但显式排序更稳
        printf "%s%-10s  %-25s  %-25s  %s%s\n" \
            "${C_BOLD}" "短哈希" "提交时间(ISO)" "作者" "标题" "${C_RESET}"
        printf '%s\n' "-----------------------------------------------------------------------------------------------"
        printf '%s\n' "${ahead_raw}" | python3 -c '
import sys, datetime
for line in sys.stdin:
    line = line.rstrip("\n")
    if not line:
        continue
    parts = line.split("\x1f")
    if len(parts) < 4:
        continue
    h, iso, author, subject = parts[0], parts[1], parts[2], parts[3]
    try:
        dt = datetime.datetime.fromisoformat(iso)
        iso_pretty = dt.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        iso_pretty = iso
    # 标题截断避免超长
    if len(subject) > 70:
        subject = subject[:67] + "..."
    author = author[:24]
    print(f"{h:<10}  {iso_pretty:<19}  {author:<24}  {subject}")
'
        local count
        count="$(printf '%s\n' "${ahead_raw}" | grep -c . || true)"
        log_info "合计 ${count} 个待拉取 commit。"
    fi

    log_section "二、社区 PR（GitHub API，open & 按 updated 排序）"

    local api_url="https://api.github.com/repos/${UPSTREAM_OWNER}/${UPSTREAM_REPO}/pulls?state=open&sort=updated&per_page=20"
    local pr_json
    if ! pr_json="$(curl -fsSL --max-time 15 "${api_url}" 2>/dev/null)"; then
        log_warn "PR 获取失败（网络/API 限速），仅显示 commit 更新。"
        return 0
    fi

    # 用 python3 解析 JSON，避免依赖 jq
    PR_JSON="${pr_json}" python3 - <<'PY'
import os, json, datetime
raw = os.environ.get("PR_JSON", "")
try:
    data = json.loads(raw)
except Exception:
    print("[!] PR 响应不是合法 JSON，跳过展示。")
    raise SystemExit(0)

if not isinstance(data, list) or not data:
    print("[✓] 当前没有 open 状态的 PR。")
    raise SystemExit(0)

print(f"{'编号':<8}  {'更新时间(本地)':<19}  {'作者':<20}  标题")
print("-" * 100)
for pr in data:
    number = pr.get("number", "?")
    title  = (pr.get("title") or "").strip().replace("\n", " ")
    user   = (pr.get("user") or {}).get("login", "?")
    upd    = pr.get("updated_at") or ""
    try:
        upd_dt = datetime.datetime.fromisoformat(upd.replace("Z", "+00:00"))
        upd_pretty = upd_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        upd_pretty = upd
    if len(title) > 60:
        title = title[:57] + "..."
    if len(user) > 18:
        user = user[:18]
    print(f"#{number:<7}  {upd_pretty:<19}  {user:<20}  {title}")

print(f"\n[*] 合计 {len(data)} 条 open PR（API: pulls?state=open&sort=updated&per_page=20）。")
PY

    return 0
}

# ---------- 子命令：update ----------

cmd_update() {
    require_git_repo

    local remote
    if ! remote="$(resolve_remote)"; then
        log_error "未找到可用的同步源 remote（需存在 upstream 或 origin）。"
        exit 1
    fi
    log_ok "当前同步源 remote: ${remote}/${TRACK_BRANCH}"

    # 1) 检查工作区
    log_section "步骤 1/4 检查工作区状态"
    local porcelain
    porcelain="$(git status --porcelain || true)"
    if [[ -n "${porcelain}" ]]; then
        log_warn "工作区存在未提交改动（仅提示，不会自动 stash）："
        printf '%s\n' "${porcelain}" | sed 's/^/    /'
        log_warn "如需继续，请自行决定是否提交/丢弃，本脚本不会中断；冲突解决仍以你为准。"
    else
        log_ok "工作区干净。"
    fi

    local start_branch
    start_branch="$(current_branch)"
    log_info "当前分支: ${start_branch}"

    # 2) fetch
    log_section "步骤 2/4 拉取上游"
    fetch_remote_main "${remote}"

    # 3) 在 main 上 rebase 上游
    log_section "步骤 3/4 同步 ${TRACK_BRANCH}"

    local before_head after_head pulled_count start_count

    # 重新读取当前分支（fetch 不会切分支，但保持一致性）
    if [[ "${start_branch}" != "${TRACK_BRANCH}" ]]; then
        log_info "当前不在 ${TRACK_BRANCH}，先切换到 ${TRACK_BRANCH} 进行 rebase。"
        git checkout "${TRACK_BRANCH}"
    fi

    start_count="$(git rev-list --count HEAD)"
    before_head="$(git rev-parse --short HEAD)"

    log_info "执行: git rebase ${remote}/${TRACK_BRANCH}"
    if git rebase "${remote}/${TRACK_BRANCH}"; then
        log_ok "main rebase 完成。"
    else
        abort_on_conflict "main rebase"
    fi

    after_head="$(git rev-parse --short HEAD)"
    pulled_count=$(( $(git rev-list --count HEAD) - start_count ))
    if (( pulled_count < 0 )); then
        # rebase 是替换历史，理论上不会减，防御性处理
        pulled_count=0
    fi

    log_info "更新前 HEAD: ${before_head}（共 ${start_count} commit）"
    log_info "更新后 HEAD: ${after_head}（共 $(git rev-list --count HEAD) commit）"
    log_info "本次拉取/合并 ${pulled_count} 个新 commit。"

    # 4) 若存在 dev 分支，把 main 上的更新带过去
    log_section "步骤 4/4 同步 dev 分支（如存在）"
    if git show-ref --verify --quiet "refs/heads/dev"; then
        log_info "检测到 dev 分支，切到 dev 并尝试 ff 合并 main。"
        # 步骤 3 结束后当前一定在 main，无条件切到 dev
        git checkout dev

        local dev_before dev_after dev_pulled
        dev_before="$(git rev-parse --short HEAD)"

        log_info "尝试 git merge --ff-only ${TRACK_BRANCH} ..."
        if git merge --ff-only "${TRACK_BRANCH}"; then
            log_ok "dev 已快进合并 main。"
        else
            log_warn "快进失败，降级为 git rebase ${TRACK_BRANCH}（保持线性历史）。"
            if git rebase "${TRACK_BRANCH}"; then
                log_ok "dev rebase main 完成。"
            else
                abort_on_conflict "dev rebase"
            fi
        fi

        dev_after="$(git rev-parse --short HEAD)"
        dev_pulled=$(( $(git rev-list --count HEAD) - $(git rev-list --count "${dev_before}") ))
        log_info "dev HEAD: ${dev_before} -> ${dev_after}（+${dev_pulled} 个 commit）。"

        # 把用户切回原本所在分支
        if [[ "${start_branch}" != "dev" && "${start_branch}" != "${TRACK_BRANCH}" ]]; then
            log_info "切回原始分支: ${start_branch}"
            git checkout "${start_branch}"
        fi
    else
        log_info "本地无 dev 分支，跳过步骤 4。"
        if [[ "${start_branch}" != "${TRACK_BRANCH}" ]]; then
            log_info "切回原始分支: ${start_branch}"
            git checkout "${start_branch}"
        fi
    fi

    log_section "完成"
    log_ok "上游同步成功，未执行任何 push。"
    log_info "合并来源：${remote}/${TRACK_BRANCH}；分支：${TRACK_BRANCH}（+${pulled_count} commit）。"
    return 0
}

# ---------- 入口 ----------

usage() {
    cat <<EOF
用法: $(basename "$0") <子命令>

子命令:
  view    查看本地落后于上游的 commit + 社区 open PR
  update  在 main 上 rebase 上游，必要时同步到 dev 分支

示例:
  $(basename "$0") view
  $(basename "$0") update
EOF
}

main() {
    if [[ $# -lt 1 ]]; then
        usage
        exit 1
    fi
    local subcmd="$1"
    shift
    case "${subcmd}" in
        view)    cmd_view    "$@" ;;
        update)  cmd_update  "$@" ;;
        -h|--help|help) usage; exit 0 ;;
        *)
            log_error "未知子命令: ${subcmd}"
            usage
            exit 1
            ;;
    esac
}

main "$@"
