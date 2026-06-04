#!/bin/bash
# SocialGraph Pro — 一键启动演示脚本
# 自动检测 Docker 容器端口/凭据，无需手动配置环境变量。
# 支持: Git Bash (Windows) / Linux / macOS
# 用法: bash start_demo.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ── 处理 --stop 参数 ─────────────────────────────────────────────
if [ "$1" = "--stop" ]; then
    echo "正在停止 SocialGraph Pro..."
    API_PID=$(netstat -ano 2>/dev/null | grep ":8000" | grep "LISTENING" | awk '{print $NF}' | head -1)
    FRONT_PID=$(netstat -ano 2>/dev/null | grep ":8080" | grep "LISTENING" | awk '{print $NF}' | head -1)
    [ -n "$API_PID" ] && [ "$API_PID" != "0" ] && taskkill //PID "$API_PID" //F >/dev/null 2>&1 && echo "  ✅ API 网关已停止 (PID: $API_PID)" || echo "  API 网关未运行"
    [ -n "$FRONT_PID" ] && [ "$FRONT_PID" != "0" ] && taskkill //PID "$FRONT_PID" //F >/dev/null 2>&1 && echo "  ✅ 前端已停止 (PID: $FRONT_PID)" || echo "  前端未运行"
    echo "已停止。"
    exit 0
fi

# ── 正常启动 ──────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║     SocialGraph Pro — 演示环境启动               ║${NC}"
echo -e "${CYAN}║     社交网络可视分析平台                          ║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# ================================================================
# 工具函数
# ================================================================

docker_env() {
    local container="$1" key="$2"
    docker inspect "$container" --format "{{range .Config.Env}}{{.}}{{\"\n\"}}{{end}}" 2>/dev/null \
        | grep "^${key}=" | head -1 | cut -d= -f2-
}

docker_port() {
    local container="$1" cport="$2"
    docker port "$container" "$cport" 2>/dev/null | head -1 | sed 's/.*://'
}

port_open() {
    local host="$1" port="$2"
    (echo >/dev/tcp/"$host"/"$port") 2>/dev/null && return 0
    return 1
}

find_container() {
    local image_pattern="$1" name img result
    result=""
    for name in $(docker ps --format "{{.Names}}" 2>/dev/null); do
        img=$(docker inspect "$name" --format "{{.Config.Image}}" 2>/dev/null)
        case "$img" in
            ${image_pattern} | ${image_pattern}:*) result="$name"; break ;;
        esac
    done
    echo "$result"
}

# ================================================================
# 第1步: 检测 Docker 服务
# ================================================================
echo -e "${CYAN}>>> [1/6] 检测 Docker 服务...${NC}"

DOCKER_AVAILABLE=false
if docker ps >/dev/null 2>&1; then DOCKER_AVAILABLE=true; fi

# ── Redis ──
REDIS_CONTAINER=""; REDIS_HOST="127.0.0.1"; REDIS_PORT=6379; REDIS_PASS=""
if $DOCKER_AVAILABLE; then REDIS_CONTAINER=$(find_container "redis"); fi
if [ -n "$REDIS_CONTAINER" ]; then
    REDIS_PORT=$(docker_port "$REDIS_CONTAINER" 6379)
    REDIS_PORT=${REDIS_PORT:-6379}
    echo -e "  ${GREEN}✅ Redis${NC}     — ${REDIS_HOST}:${REDIS_PORT} (容器: ${REDIS_CONTAINER})"
elif port_open "$REDIS_HOST" "$REDIS_PORT"; then
    echo -e "  ${GREEN}✅ Redis${NC}     — ${REDIS_HOST}:${REDIS_PORT} (本地)"
else
    echo -e "  ${YELLOW}⚠️  Redis${NC}     — 未运行，将降级"
fi

# ── MySQL ──
MYSQL_CONTAINER=""; MYSQL_HOST="127.0.0.1"; MYSQL_PORT=3306
MYSQL_USER="socialgraph"; MYSQL_PASS="sgpass123"; MYSQL_DB="socialgraph"
if $DOCKER_AVAILABLE; then MYSQL_CONTAINER=$(find_container "mysql"); fi
if [ -n "$MYSQL_CONTAINER" ]; then
    MYSQL_PORT=$(docker_port "$MYSQL_CONTAINER" 3306)
    MYSQL_PORT=${MYSQL_PORT:-3306}
    MYSQL_USER=$(docker_env "$MYSQL_CONTAINER" "MYSQL_USER"); MYSQL_USER=${MYSQL_USER:-socialgraph}
    MYSQL_PASS=$(docker_env "$MYSQL_CONTAINER" "MYSQL_PASSWORD"); MYSQL_PASS=${MYSQL_PASS:-sgpass123}
    MYSQL_DB=$(docker_env "$MYSQL_CONTAINER" "MYSQL_DATABASE"); MYSQL_DB=${MYSQL_DB:-socialgraph}
    echo -e "  ${GREEN}✅ MySQL${NC}     — ${MYSQL_HOST}:${MYSQL_PORT} (数据库: ${MYSQL_DB})"
elif port_open "$MYSQL_HOST" "$MYSQL_PORT"; then
    echo -e "  ${GREEN}✅ MySQL${NC}     — ${MYSQL_HOST}:${MYSQL_PORT} (本地)"
else
    echo -e "  ${YELLOW}⚠️  MySQL${NC}     — 未运行，将降级"
fi

# ── MongoDB ──
MONGO_CONTAINER=""; MONGO_HOST="127.0.0.1"; MONGO_PORT=27017
MONGO_URI="mongodb://admin:mongopass@127.0.0.1:27017/"; MONGO_DB="socialgraph_analytics"
if $DOCKER_AVAILABLE; then MONGO_CONTAINER=$(find_container "mongo"); fi
if [ -n "$MONGO_CONTAINER" ]; then
    MONGO_PORT=$(docker_port "$MONGO_CONTAINER" 27017); MONGO_PORT=${MONGO_PORT:-27017}
    MONGO_ROOT_USER=$(docker_env "$MONGO_CONTAINER" "MONGO_INITDB_ROOT_USERNAME"); MONGO_ROOT_USER=${MONGO_ROOT_USER:-admin}
    MONGO_ROOT_PASS=$(docker_env "$MONGO_CONTAINER" "MONGO_INITDB_ROOT_PASSWORD"); MONGO_ROOT_PASS=${MONGO_ROOT_PASS:-mongopass}
    MONGO_DB=$(docker_env "$MONGO_CONTAINER" "MONGO_INITDB_DATABASE"); MONGO_DB=${MONGO_DB:-socialgraph_analytics}
    MONGO_URI="mongodb://${MONGO_ROOT_USER}:${MONGO_ROOT_PASS}@${MONGO_HOST}:${MONGO_PORT}/"
    echo -e "  ${GREEN}✅ MongoDB${NC}   — ${MONGO_HOST}:${MONGO_PORT} (数据库: ${MONGO_DB})"
elif port_open "$MONGO_HOST" "$MONGO_PORT"; then
    echo -e "  ${GREEN}✅ MongoDB${NC}   — ${MONGO_HOST}:${MONGO_PORT} (本地)"
else
    echo -e "  ${YELLOW}⚠️  MongoDB${NC}   — 未运行，将降级"
fi

# ── Neo4j ──
NEO4J_CONTAINER=""; NEO4J_HOST="127.0.0.1"; NEO4J_PORT=7687
NEO4J_USER="neo4j"; NEO4J_PASS="password123"
if $DOCKER_AVAILABLE; then NEO4J_CONTAINER=$(find_container "neo4j"); fi
if [ -n "$NEO4J_CONTAINER" ]; then
    NEO4J_PORT=$(docker_port "$NEO4J_CONTAINER" 7687); NEO4J_PORT=${NEO4J_PORT:-7687}
    NEO4J_AUTH=$(docker_env "$NEO4J_CONTAINER" "NEO4J_AUTH")
    NEO4J_USER=$(echo "${NEO4J_AUTH:-neo4j/password123}" | cut -d/ -f1)
    NEO4J_PASS=$(echo "${NEO4J_AUTH:-neo4j/password123}" | cut -d/ -f2)
    echo -e "  ${GREEN}✅ Neo4j${NC}     — bolt://${NEO4J_HOST}:${NEO4J_PORT} (用户: ${NEO4J_USER})"
elif port_open "$NEO4J_HOST" 7474; then
    echo -e "  ${GREEN}✅ Neo4j${NC}     — bolt://${NEO4J_HOST}:${NEO4J_PORT} (本地)"
else
    echo -e "  ${YELLOW}⚠️  Neo4j${NC}     — 未运行，将降级"
fi

echo ""

# ================================================================
# 第2步: C++ 引擎验证
# ================================================================
echo -e "${CYAN}>>> [2/6] 验证 C++ 引擎...${NC}"

ENGINE_PATH=""; ENGINE_REL=""
for candidate in \
    "backend_cpp/cmake-build-debug/graph_engine.exe" \
    "backend_cpp/cmake-build-release/graph_engine.exe" \
    "backend_cpp/build/graph_engine" \
    "backend_cpp/build/graph_engine.exe"; do
    if [ -f "$SCRIPT_DIR/$candidate" ]; then
        ENGINE_PATH="$SCRIPT_DIR/$candidate"
        ENGINE_REL="$candidate"
        break
    fi
done

if [ -z "$ENGINE_PATH" ]; then
    echo -e "  ${RED}❌ 未找到 C++ 引擎二进制！${NC}"
    echo "     请先编译: cd backend_cpp && cmake -B build && cmake --build build"
    exit 1
fi

GRAPH_DATA="$SCRIPT_DIR/backend_cpp/facebook_combined.txt"
if [ ! -f "$GRAPH_DATA" ]; then
    echo -e "  ${RED}❌ 数据文件缺失: ${GRAPH_DATA}${NC}"
    exit 1
fi

cd "$SCRIPT_DIR"
"$ENGINE_REL" "backend_cpp/facebook_combined.txt" run_test 2>/dev/null && \
    echo -e "  ${GREEN}✅ C++ 引擎测试通过${NC}" || {
    echo -e "  ${RED}❌ C++ 引擎测试失败${NC}"
    exit 1
}

# ================================================================
# 第3步: Python 依赖
# ================================================================
echo -e "${CYAN}>>> [3/6] 检查 Python 依赖...${NC}"

PYTHON=""

# 优先级1: 已知的真实安装路径 (最快, 不依赖 PATH, 避开 WindowsApps 假货)
for exe in \
    "$HOME/AppData/Local/Python/pythoncore-3.14-64/python.exe" \
    "$HOME/AppData/Local/Python/pythoncore-3.14-64/python3.exe" \
    "$HOME/AppData/Local/Python/pythoncore-3.13"*"/python.exe" \
    "$HOME/AppData/Local/Python/pythoncore-3.12"*"/python.exe" \
    "$HOME/AppData/Local/Python/pythoncore-3.11"*"/python.exe" \
    "$HOME/AppData/Local/Programs/Python/Python3"*"/python.exe" \
    "/usr/bin/python3" \
    "/usr/bin/python"; do
    if [ -f "$exe" ] && "$exe" -c "import fastapi, uvicorn" 2>/dev/null; then
        PYTHON="$exe"; break
    fi
done

# 优先级2: PATH 搜索，跳过 WindowsApps
if [ -z "$PYTHON" ]; then
    IFS=':'
    for dir in $PATH; do
        case "$dir" in *WindowsApps*|*Microsoft*|*windowsapps*) continue ;; esac
        for name in python3 python; do
            full="$dir/$name"
            [ ! -f "$full" ] && full="$dir/$name.exe"
            if [ -f "$full" ] && "$full" -c "import fastapi, uvicorn" 2>/dev/null; then
                PYTHON="$full"; break 2
            fi
        done
    done
    IFS=' '
fi

# 优先级3: 任何能跑 --version 的 Python (之后 pip install)
if [ -z "$PYTHON" ]; then
    for exe in \
        "$HOME/AppData/Local/Python/pythoncore-3.14-64/python.exe" \
        "$HOME/AppData/Local/Python/pythoncore-3.13"*"/python.exe" \
        "$HOME/AppData/Local/Python/pythoncore-3.12"*"/python.exe"; do
        if [ -f "$exe" ] && timeout 3 "$exe" --version >/dev/null 2>&1; then
            PYTHON="$exe"; break
        fi
    done
fi

if [ -z "$PYTHON" ]; then
    echo -e "  ${RED}❌ 未找到可用的 Python${NC}"
    exit 1
fi

cd "$SCRIPT_DIR/middleware_python"

if $PYTHON -c "import fastapi, uvicorn" 2>/dev/null; then
    echo -e "  ${CYAN}📍 Python:${NC} $($PYTHON --version 2>&1) — 依赖已就绪"
else
    echo -e "  ${CYAN}📍 Python:${NC} $($PYTHON --version 2>&1)"
    echo "  安装依赖中..."
    $PYTHON -m pip install -q -r requirements.txt 2>&1 | tail -3
    if $PYTHON -c "import fastapi, uvicorn" 2>/dev/null; then
        echo -e "  ${GREEN}✅ Python 依赖安装完成${NC}"
    else
        echo -e "  ${RED}❌ 依赖安装失败${NC}"
        exit 1
    fi
fi
echo ""

# ================================================================
# 第4步: 停止旧进程
# ================================================================
echo -e "${CYAN}>>> [4/6] 停止旧进程...${NC}"

OLD_PID=$(netstat -ano 2>/dev/null | grep ":8000" | grep "LISTENING" | awk '{print $NF}' | head -1)
if [ -n "$OLD_PID" ] && [ "$OLD_PID" != "0" ]; then
    taskkill //PID "$OLD_PID" //F >/dev/null 2>&1 || true
    echo -e "  ${YELLOW}已停止旧 API 进程 (PID: $OLD_PID)${NC}"
else
    echo "  无需清理"
fi
echo ""

# ================================================================
# 第5步: 启动 API 网关
# ================================================================
echo -e "${CYAN}>>> [5/6] 启动 API 网关...${NC}"

cd "$SCRIPT_DIR/middleware_python"

export CPP_ENGINE_PATH="$SCRIPT_DIR/$ENGINE_REL"
export GRAPH_DATA_PATH="$SCRIPT_DIR/backend_cpp/facebook_combined.txt"
export REDIS_HOST="$REDIS_HOST"
export REDIS_PORT="$REDIS_PORT"
export NEO4J_URI="bolt://${NEO4J_HOST}:${NEO4J_PORT}"
export NEO4J_USER="$NEO4J_USER"
export NEO4J_PASSWORD="$NEO4J_PASS"
export MYSQL_HOST="$MYSQL_HOST"
export MYSQL_PORT="$MYSQL_PORT"
export MYSQL_USER="$MYSQL_USER"
export MYSQL_PASSWORD="$MYSQL_PASS"
export MYSQL_DATABASE="$MYSQL_DB"
export MONGODB_URI="$MONGO_URI"
export MONGODB_DATABASE="$MONGO_DB"
export SGP_JWT_SECRET_KEY="demo-jwt-secret-key-2026"

$PYTHON -m uvicorn server:app --host 0.0.0.0 --port 8000 --ws none \
    > /tmp/socialgraph-server.log 2>&1 &

API_READY=false
for i in 1 2 3 4 5; do
    sleep 3
    if curl -s -o /dev/null http://127.0.0.1:8000/api/v1/health 2>/dev/null; then
        API_READY=true; break
    fi
    echo "  等待 API 就绪... ($i/5)"
done

if $API_READY; then
    echo -e "  ${GREEN}✅ API 网关已启动${NC}"
else
    echo -e "  ${RED}❌ API 网关启动失败${NC}"
    echo "     tail /tmp/socialgraph-server.log"
    exit 1
fi

echo ""
echo -e "  ${CYAN}健康检查:${NC}"
HEALTH=$(curl -s http://127.0.0.1:8000/api/v1/health 2>/dev/null)
echo "$HEALTH" | $PYTHON -c "
import json, sys
d = json.load(sys.stdin)
overall = d.get('status','?')
icon = '✅' if overall == 'healthy' else '⚠️'
print(f'  整体: {icon} {overall}')
for name, comp in d.get('components',{}).items():
    s = comp.get('status','?')
    icon = '✅' if s == 'healthy' else '⚠️' if s == 'degraded' else '❌'
    lat = comp.get('latency_ms')
    lat_str = f' {lat}ms' if lat else ''
    msg = comp.get('message','')
    detail = f' — {msg}' if msg else ''
    print(f'  {icon} {name}: {s}{lat_str}{detail}')
" 2>/dev/null || echo "$HEALTH"
echo ""

# ================================================================
# 第6步: 启动前端
# ================================================================
echo -e "${CYAN}>>> [6/6] 启动前端...${NC}"

OLD_FRONT=$(netstat -ano 2>/dev/null | grep ":8080" | grep "LISTENING" | awk '{print $NF}' | head -1)
if [ -n "$OLD_FRONT" ] && [ "$OLD_FRONT" != "0" ]; then
    taskkill //PID "$OLD_FRONT" //F >/dev/null 2>&1 || true
fi

cd "$SCRIPT_DIR/frontend_web"
$PYTHON -m http.server 8080 --bind 127.0.0.1 \
    > /tmp/socialgraph-frontend.log 2>&1 &

sleep 2

if curl -s -o /dev/null http://127.0.0.1:8080 2>/dev/null; then
    echo -e "  ${GREEN}✅ 前端已启动${NC}"
else
    echo -e "  ${RED}❌ 前端启动失败${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  🎉 SocialGraph Pro 演示环境就绪！                ║${NC}"
echo -e "${GREEN}╠══════════════════════════════════════════════════╣${NC}"
echo -e "${GREEN}║                                                    ║${NC}"
echo -e "${GREEN}║  🌐 前端可视化:   http://127.0.0.1:8080              ║${NC}"
echo -e "${GREEN}║  📡 API 网关:     http://127.0.0.1:8000              ║${NC}"
echo -e "${GREEN}║  📖 API 文档:     http://127.0.0.1:8000/docs         ║${NC}"
echo -e "${GREEN}║  ❤️  健康检查:     http://127.0.0.1:8000/api/v1/health║${NC}"
echo -e "${GREEN}║                                                    ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "日志文件:"
echo -e "  API:  tail -f /tmp/socialgraph-server.log"
echo -e "  前端: tail -f /tmp/socialgraph-frontend.log"
echo ""
echo -e "停止服务: bash start_demo.sh --stop"
echo ""
