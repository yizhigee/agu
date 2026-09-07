#!/usr/bin/env bash
# tick-stock-panel — 一键关闭（双击/Finder 或终端均可使用）
#
# 用法：
#   Finder 双击本文件    → 弹终端窗口显示关闭过程
#   终端 ./stop.command  → 等价于 ./stop.sh
#   BACKEND_PORT=8000 ./stop.command  # 与 start 的端口保持一致
#
# 说明：
#   - 先按 PID 文件停止主进程, 再按端口清理残留子进程
#     （uv run / pnpm dev 会派生子进程，只杀父进程会留下占端口的孤儿）

set -uo pipefail

# 切到脚本所在目录（双击时 cwd 是 $HOME，必须切过来）
cd "$(dirname "$0")" || exit 1

ROOT="$(pwd)"
RUN_DIR="$ROOT/.dev-run"

BACKEND_PORT="${BACKEND_PORT:-3018}"
FRONTEND_PORT="${FRONTEND_PORT:-3011}"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; GRAY='\033[0;90m'; NC='\033[0m'

info() { echo -e "${GRAY}[stop]${NC} $*"; }
ok()   { echo -e "${GREEN}[stop]${NC} $*"; }
warn() { echo -e "${YELLOW}[stop]${NC} $*"; }

# 双击场景的开头提示
echo "================================================================"
echo "  agu (tick-stock-panel) — 关闭服务"
echo "================================================================"
echo ""
echo "  [i] 正在停止后端 / 前端进程..."
echo "  [i] 如果服务没在运行，会直接提示已空闲"
echo ""
echo "----------------------------------------------------------------"

# ---------- 1. 按 PID 文件停止主进程 ----------
stop_by_pidfile() {
  local name="$1" pidfile="$2"
  if [[ ! -f "$pidfile" ]]; then
    return 0
  fi

  local pid
  pid="$(cat "$pidfile" 2>/dev/null || true)"
  if [[ -z "$pid" ]]; then
    rm -f "$pidfile"
    return 0
  fi

  if ! kill -0 "$pid" 2>/dev/null; then
    info "$name 进程已不存在 (PID $pid), 跳过"
    rm -f "$pidfile"
    return 0
  fi

  kill "$pid" 2>/dev/null || true

  # 最多等 10 秒优雅退出
  local i=0
  while [[ $i -lt 10 ]]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      break
    fi
    sleep 1
    i=$((i + 1))
  done

  # 仍存活则强制杀
  if kill -0 "$pid" 2>/dev/null; then
    warn "$name 未响应 TERM, 强制 KILL (PID $pid)"
    kill -9 "$pid" 2>/dev/null || true
    sleep 1
  fi

  ok "$name 已停止 (PID $pid)"
  rm -f "$pidfile"
}

stop_by_pidfile "后端" "$RUN_DIR/backend.pid"
stop_by_pidfile "前端" "$RUN_DIR/frontend.pid"

# ---------- 2. 按端口清理残留子进程 ----------
kill_port() {
  local port="$1" name="$2" pids

  pids=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -z "$pids" ]]; then
    ok "端口 $port ($name) 已空闲"
    return 0
  fi

  info "端口 $port ($name) 仍有残留进程, 清理中..."
  echo "$pids" | xargs kill 2>/dev/null || true
  sleep 1

  pids=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -9 2>/dev/null || true
    sleep 1
  fi

  pids=$(lsof -nP -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)
  if [[ -n "$pids" ]]; then
    warn "端口 $port 仍被占用, 请手动处理: lsof -i :$port"
  else
    ok "端口 $port ($name) 已释放"
  fi
}

kill_port "$BACKEND_PORT" backend
kill_port "$FRONTEND_PORT" frontend

echo
ok "全部服务已关闭"
echo

# 双击场景下的结尾：按回车 / 超时后自动关闭窗口
echo "----------------------------------------------------------------"
echo ""
echo "按回车立即关闭本窗口；不管它的话 15 秒后自动关闭。"

if [[ "${TERM_PROGRAM:-}" == "Apple_Terminal" ]]; then
  read -t 15 -r _ || true
  echo "正在关闭窗口…（若没自动关闭，按 ⌘W 手动关即可）"
  # 放到后台再退出：万一系统弹确认框，也不会把脚本卡死
  nohup bash -c 'sleep 0.3; osascript -e "tell application \"Terminal\" to close front window"' \
    >/dev/null 2>&1 &
  exit 0
fi

read -r _ || true
