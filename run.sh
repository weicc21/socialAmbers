#!/bin/bash
set -uo pipefail

ROOT=$(cd "$(dirname "$0")" && pwd)
if [ -f "$ROOT/.env" ]; then
  set -a
  # Values must be unquoted in .env; the shell strips quotes but naive parsers do not.
  . "$ROOT/.env"
  set +a
fi
PY=${PY:-$ROOT/.venv/bin/python}
STREAMLIT=${STREAMLIT:-$ROOT/.venv/bin/streamlit}
BACKEND_PORT=${BACKEND_PORT:-5000}
UI_PORT=${UI_PORT:-8501}
THRESHOLD=${THRESHOLD:-3}
INGEST_MODE=${INGEST_MODE:-manual}
PACE=${PACE:-0.25}
ENGINE_PACE=${ENGINE_PACE:-0.3}
COMPONENTS=${COMPONENTS:-"backend ingest ui"}
KEY_STATE=MISSING; [ -n "${GREPTILE_API_KEY:-}" ] && KEY_STATE=set
RUNTIME="$ROOT/runtime"; PIDS="$RUNTIME/pids"; LOGS="$RUNTIME/logs"

if [ -z "${ACME_SHOP_PATH:-}" ]; then
  [ -d "${TARGET_REPO:-}/.git" ] && ACME_SHOP_PATH="$TARGET_REPO"
  [ -d "$ROOT/acme-shop" ] && ACME_SHOP_PATH="$ROOT/acme-shop"
  [ -z "${ACME_SHOP_PATH:-}" ] && [ -d "$ROOT/../acme-shop" ] && ACME_SHOP_PATH="$ROOT/../acme-shop"
  [ -z "${ACME_SHOP_PATH:-}" ] && [ -d "/Users/william_chen/acme-shop/.git" ] && ACME_SHOP_PATH="/Users/william_chen/acme-shop"
  export ACME_SHOP_PATH
fi

usage() {
  echo "SocialClues — GREPTILE_API_KEY=$KEY_STATE"
  echo "usage: ./run.sh {start [backend|ingest|ui...]|stop [component...]|status|logs NAME [-f]|seed|post TEXT|run|fix [SIGNAL]|reset-shop|actor [--emit]|test|clean|restart [component]}"
}

port_for() { case "$1" in backend) echo "$BACKEND_PORT";; ui) echo "$UI_PORT";; *) echo "";; esac; }
pattern_for() { case "$1" in backend) echo "flask --app backend.app.*--port $BACKEND_PORT";; ingest) echo "ingest.py --watch";; ui) echo "streamlit run frontend/app.py.*server.port $UI_PORT";; esac; }
listens() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }
pid_up() { [ -f "$PIDS/$1.pid" ] && kill -0 "$(cat "$PIDS/$1.pid")" 2>/dev/null; }

command_for() {
  case "$1" in
    backend) echo "$PY -m flask --app backend.app run --host 127.0.0.1 --port $BACKEND_PORT";;
    ingest) if [ "$INGEST_MODE" = manual ]; then echo "$PY ingest.py --watch --threshold $THRESHOLD --manual --pace $PACE --engine-pace $ENGINE_PACE"; else echo "$PY ingest.py --watch --threshold $THRESHOLD --pace $PACE --engine-pace $ENGINE_PACE"; fi;;
    ui) echo "$STREAMLIT run frontend/app.py --server.port $UI_PORT --server.headless true";;
    *) return 1;;
  esac
}

wait_for_port() { i=0; while [ "$i" -lt 40 ]; do listens "$1" && return 0; sleep .25; i=$((i+1)); done; return 1; }

start_one() {
  name=$1; port=$(port_for "$name"); mkdir -p "$PIDS" "$LOGS"
  if pid_up "$name"; then echo "$name already running"; return 0; fi
  if [ -n "$port" ] && listens "$port"; then echo "$name: port $port is busy; inspect with: lsof -nP -iTCP:$port -sTCP:LISTEN"; return 1; fi
  cmd=$(command_for "$name") || { echo "unknown component: $name"; return 1; }
  (cd "$ROOT" && nohup /bin/bash -c "$cmd" >"$LOGS/$name.log" 2>&1 & echo $! >"$PIDS/$name.pid")
  sleep .5
  if ! pid_up "$name"; then echo "$name died during startup"; tail -6 "$LOGS/$name.log"; return 1; fi
  if [ -n "$port" ] && ! wait_for_port "$port"; then echo "$name is alive but did not listen on $port"; tail -6 "$LOGS/$name.log"; return 1; fi
  echo "$name started"
}

sweep_pattern() {
  pattern=$(pattern_for "$1"); [ -z "$pattern" ] && return
  pgrep -f "$pattern" 2>/dev/null | while read orphan; do [ "$orphan" = "$$" ] || kill "$orphan" 2>/dev/null || true; done
}

stop_one() {
  name=$1; port=$(port_for "$name")
  if pid_up "$name"; then
    pid=$(cat "$PIDS/$name.pid"); kill "$pid" 2>/dev/null || true; i=0
    while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 12 ]; do sleep .25; i=$((i+1)); done
    if kill -0 "$pid" 2>/dev/null; then echo "$name ignored TERM; sending KILL"; kill -9 "$pid" 2>/dev/null || true; fi
  fi
  rm -f "$PIDS/$name.pid"; sweep_pattern "$name"; sleep .2
  if [ -n "$port" ] && listens "$port"; then
    echo "$name orphan still holds $port; reaping listener"
    lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | while read orphan; do kill "$orphan" 2>/dev/null || true; done
    sleep .5
    if listens "$port"; then
      echo "$name listener ignored TERM; sending KILL"
      lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | while read orphan; do kill -9 "$orphan" 2>/dev/null || true; done
    fi
  fi
  echo "$name stopped"
}

start_all() { rc=0; for name in "$@"; do start_one "$name" || rc=1; done; return "$rc"; }
stop_all() { rc=0; for name in "$@"; do stop_one "$name" || rc=1; done; return "$rc"; }

status_cmd() {
  printf '%-10s %-10s %-6s\n' COMPONENT STATE PORT
  for name in backend ingest ui; do
    port=$(port_for "$name"); state=down
    if pid_up "$name"; then state=up; [ -n "$port" ] && ! listens "$port" && state=no-port; fi
    printf '%-10s %-10s %-6s\n' "$name" "$state" "${port:--}"
  done
  "$PY" - "$RUNTIME" <<'PY'
import json, pathlib, sys
root=pathlib.Path(sys.argv[1])
def load(name):
    try: return json.loads((root/name).read_text())
    except (OSError, json.JSONDecodeError): return {}
control=load("control.json")
print(f'gate: {control.get("mode", "unavailable")} · {control.get("queued", 0)} queued')
for signal in load("state.json").get("signals", []):
    n=int(signal.get("distinct_authors",0)); bar="▓"*min(n,3)+"░"*max(0,3-n)
    print(f'{signal.get("feature")}: {n}/3 voices {bar} · {signal.get("status")}')
PY
}

reset_shop() {
  [ -d "${ACME_SHOP_PATH:-}/.git" ] || { echo "ACME_SHOP_PATH not found"; return 1; }
  branch=$(git -C "$ACME_SHOP_PATH" branch --show-current)
  case "$branch" in fix/socialclues/*) git -C "$ACME_SHOP_PATH" checkout -- . && git -C "$ACME_SHOP_PATH" clean -fd && git -C "$ACME_SHOP_PATH" checkout main || return 1;; main|master) :;; *) echo "refusing to reset unrelated branch: $branch"; return 1;; esac
  git -C "$ACME_SHOP_PATH" for-each-ref --format='%(refname:short)' refs/heads/fix/socialclues/ | while read fix_branch; do git -C "$ACME_SHOP_PATH" branch -D "$fix_branch" || exit 1; done
  git -C "$ACME_SHOP_PATH" status --short
}

case "${1:-help}" in
  start) shift; if [ "$#" -gt 0 ]; then start_all "$@"; else start_all $COMPONENTS; fi;;
  stop) shift; if [ "$#" -gt 0 ]; then stop_all "$@"; else stop_all ui ingest backend; fi;;
  status) status_cmd;;
  logs) [ "$#" -ge 2 ] || { usage; exit 1; }; if [ "${3:-}" = -f ]; then tail -f "$LOGS/$2.log"; else cat "$LOGS/$2.log"; fi;;
  seed) (cd "$ROOT" && "$PY" ingest.py --seed);;
  post) shift; [ "$#" -gt 0 ] || { echo "post requires text"; exit 1; }; (cd "$ROOT" && "$PY" -c 'import sys; from frontend.runtime_bridge import post_complaint; print(post_complaint(" ".join(sys.argv[1:])))' "$@");;
  run) pid_up ingest || { echo "ingest is not running; refusing to queue an unread run"; exit 1; }; (cd "$ROOT" && "$PY" -c 'from frontend.runtime_bridge import request_run; print("run requested" if request_run() else "request failed")');;
  fix|agent) (cd "$ROOT" && "$PY" agent.py "${2:-sig-0001}" --fixture-replay);;
  reset-shop) reset_shop;;
  actor) shift; (cd "$ROOT" && "$PY" agent.py "${1:-sig-0001}" --fixture-replay "${2:-}");;
  test) rc=0; (cd "$ROOT" && "$PY" -m pyflakes backend engine frontend agent.py ingest.py) || rc=1; (cd "$ROOT" && "$PY" -m compileall -q backend engine frontend agent.py ingest.py) || rc=1; exit "$rc";;
  clean) stop_all ui ingest backend; rm -rf "$RUNTIME";;
  restart)
    if [ -n "${2:-}" ]; then stop_one "$2" && start_one "$2"; # A component bounce preserves the active runtime bus.
    else stop_all ui ingest backend && reset_shop && rm -rf "$RUNTIME" && start_all backend ingest ui && (cd "$ROOT" && "$PY" ingest.py --seed); fi;;
  help|-h|--help) usage;;
  *) echo "unknown command: $1"; usage; exit 1;;
esac
