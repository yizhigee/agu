#!/usr/bin/env bash
# tick-stock-panel — 一键启动（双击/Finder 或终端均可使用）
#
# 用法：
#   Finder 双击本文件    → 弹终端窗口显示启动日志
#   终端 ./start.command → 等价于 ./start.sh
#   BACKEND_PORT=8000 ./start.command  # 改后端端口
#   FRONTEND_PORT=5173 ./start.command # 改前端端口
#
# 关闭：双击 stop.command 或 ./stop.command

set -uo pipefail

# 切到脚本所在目录（双击时 cwd 是 $HOME，必须切过来）
cd "$(dirname "$0")" || exit 1

ROOT="$(pwd)"
BACKEND_DIR="$ROOT/backend"
FRONTEND_DIR="$ROOT/frontend"
RUN_DIR="$ROOT/.dev-run"

BACKEND_PORT="${BACKEND_PORT:-3018}"
FRONTEND_PORT="${FRONTEND_PORT:-3011}"

GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[0;33m'
RED='\033[0;31m'; GRAY='\033[0;90m'; NC='\033[0m'

info() { echo -e "${GRAY}[start]${NC} $*"; }
ok()   { echo -e "${GREEN}[start]${NC} $*"; }
warn() { echo -e "${YELLOW}[start]${NC} $*"; }
err()  { echo -e "${RED}[start]${NC} $*" >&2; }

# 双击场景的开头提示
echo "================================================================"
echo "  agu (tick-stock-panel) — 启动服务"
echo "================================================================"
echo ""
echo "  [i] 启动日志会显示在后端/前端就绪之后"
echo "  [i] 关闭窗口不会关闭服务（服务已在后台运行）"
echo "  [i] 关闭服务请双击 stop.command，或在终端跑 ./stop.command"
echo ""
echo "----------------------------------------------------------------"

mkdir -p "$RUN_DIR"

# ---------- 1. 依赖检查 ----------
require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    err "$1 未安装。安装方式: $2"
    exit 1
  fi
}
require_cmd uv   "curl -LsSf https://astral.sh/uv/install.sh | sh"
require_cmd pnpm "npm i -g pnpm"

# ---------- 2. 是否已在运行 ----------
if [[ -f "$RUN_DIR/backend.pid" ]]; then
  old_pid="$(cat "$RUN_DIR/backend.pid" 2>/dev/null || true)"
  if [[ -n "$old_pid" ]] && kill -0 "$old_pid" 2>/dev/null; then
    warn "后端似乎已在运行 (PID $old_pid)。如需重启, 请先执行 ./stop.command"
    exit 0
  fi
fi

# ---------- 3. 端口占用检查 ----------
check_port() {
  local port="$1" name="$2" pids
  pids=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    err "端口 $port ($name) 已被占用, PID: $pids"
    echo "       请先执行 ./stop.command, 或手动处理: lsof -i :$port"
    exit 1
  fi
}
check_port "$BACKEND_PORT" backend
check_port "$FRONTEND_PORT" frontend

# ---------- 4. 首次启动装依赖 ----------
if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  info "首次启动: 安装后端 Python 依赖 (约 1-2 分钟)..."
  ( cd "$BACKEND_DIR" && uv sync --frozen )
  ok "后端依赖就绪"
fi

if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  info "首次启动: 安装前端 Node 依赖..."
  ( cd "$FRONTEND_DIR" && pnpm install )
  ok "前端依赖就绪"
fi

# ---------- 5. 启动后端 ----------
info "启动后端  http://localhost:$BACKEND_PORT"
(
  cd "$BACKEND_DIR"
  nohup uv run --no-sync python -m uvicorn app.main:app \
    --host 0.0.0.0 --port "$BACKEND_PORT" \
    > "$RUN_DIR/backend.log" 2>&1 &
  echo $! > "$RUN_DIR/backend.pid"
)

# ---------- 6. 启动前端 ----------
info "启动前端  http://localhost:$FRONTEND_PORT"
(
  cd "$FRONTEND_DIR"
  nohup pnpm dev --host 0.0.0.0 --port "$FRONTEND_PORT" \
    > "$RUN_DIR/frontend.log" 2>&1 &
  echo $! > "$RUN_DIR/frontend.pid"
)

# ---------- 7. 等待就绪 ----------
info "等待服务就绪 (最多 60 秒)..."

backend_ok=0
i=0
while [[ $i -lt 60 ]]; do
  # --noproxy '*' : 必加。本机配了系统代理, 不加此参数健康检查永远失败。
  if curl -sf --noproxy '*' --max-time 5 "http://127.0.0.1:$BACKEND_PORT/health" >/dev/null 2>&1; then
    backend_ok=1
    break
  fi
  sleep 1
  i=$((i + 1))
done

frontend_ok=0
i=0
while [[ $i -lt 60 ]]; do
  if lsof -nP -tiTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    frontend_ok=1
    break
  fi
  sleep 1
  i=$((i + 1))
done

# ---------- 8. 汇报 ----------
echo
failed=0
if [[ $backend_ok -eq 1 ]]; then
  ok "后端已就绪"
else
  err "后端启动超时。查看日志: tail -f .dev-run/backend.log"
  failed=1
fi

if [[ $frontend_ok -eq 1 ]]; then
  ok "前端已就绪"
else
  err "前端启动超时。查看日志: tail -f .dev-run/frontend.log"
  failed=1
fi

echo
echo -e "${BLUE}╭──────────────────────────────────────────────╮${NC}"
echo -e "${BLUE}│${NC}  前端界面   ${YELLOW}http://localhost:$FRONTEND_PORT${NC}"
echo -e "${BLUE}│${NC}  后端接口   ${YELLOW}http://localhost:$BACKEND_PORT${NC}"
echo -e "${BLUE}│${NC}  关闭服务   ${YELLOW}./stop.command${NC}"
echo -e "${BLUE}╰──────────────────────────────────────────────╯${NC}"
echo

# 若有任一服务启动失败，给出非零退出码，调用方能感知
if [[ $failed -ne 0 ]]; then
  echo -e "${RED}启动未完全成功，请检查上方错误后重试。${NC}"
  echo
  # 双击场景：仍允许用户回车关窗 / 超时自动关窗；非交互终端直接退出
  if [[ "${TERM_PROGRAM:-}" == "Apple_Terminal" ]]; then
    echo "按回车立即关闭本窗口；不管它的话 30 秒后自动关闭。"
    read -t 30 -r _ || true
    nohup bash -c 'sleep 0.3; osascript -e "tell application \"Terminal\" to close front window"' \
      >/dev/null 2>&1 &
  fi
  exit 1
fi

# ---------- 9. 双击场景结尾：按回车 / 超时后自动关闭窗口 ----------
# 说明：服务已经在后台跑起来了，关掉这个窗口不会影响服务。
echo "----------------------------------------------------------------"
echo ""
echo "服务已在后台运行，关掉这个窗口不会关闭服务。"
echo "按回车立即关闭本窗口；不管它的话 30 秒后自动关闭。"
read -t 30 -r _ || true

# 只在「终端 Terminal.app」里自动关窗；iTerm / VS Code 等不干预
if [[ "${TERM_PROGRAM:-}" == "Apple_Terminal" ]]; then
  echo "正在关闭窗口…（若没自动关闭，按 ⌘W 手动关即可，不影响服务）"
  # 放到后台再退出：万一系统弹确认框，也不会把脚本卡死
  nohup bash -c 'sleep 0.3; osascript -e "tell application \"Terminal\" to close front window"' \
    >/dev/null 2>&1 &
  exit 0
fi
