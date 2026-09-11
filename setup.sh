#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
cd "$ROOT"

die() {
  printf '安装失败：%s\n' "$*" >&2
  exit 1
}

if [ "$(uname -s)" != 'Darwin' ]; then
  die '本发布包要求 macOS 15+ Apple Silicon（M1 及以后）；当前系统不是 macOS。'
fi
if [ "$(uname -m)" != 'arm64' ]; then
  die '本发布包要求 Apple Silicon（arm64，M1 及以后）；当前架构不受支持。'
fi
MACOS_VERSION=$(sw_vers -productVersion 2>/dev/null || true)
MACOS_MAJOR=${MACOS_VERSION%%.*}
case "$MACOS_MAJOR" in
  ''|*[!0-9]*) die '无法确认 macOS 版本；请在 macOS 15+ Apple Silicon 上重试。' ;;
esac
if [ "$MACOS_MAJOR" -lt 15 ]; then
  die "本发布包要求 macOS 15+ Apple Silicon；当前 macOS 为 $MACOS_VERSION。"
fi

build_frontend=0
if [ "$#" -gt 1 ]; then
  die '用法：./setup.sh [--build-frontend]'
fi
if [ "$#" -eq 1 ]; then
  if [ "$1" != '--build-frontend' ]; then
    die "未知参数：$1；用法：./setup.sh [--build-frontend]"
  fi
  build_frontend=1
fi

# A release archive already contains the production frontend. Do not invoke
# Node/npm unless a developer explicitly asks for a fresh frontend build.
if [ "$build_frontend" -eq 0 ] && [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  die '未找到 frontend/dist/index.html；发布包必须包含前端构建产物。源码开发请显式运行 ./setup.sh --build-frontend。'
fi
if [ "$build_frontend" -eq 1 ] && ! command -v npm >/dev/null 2>&1; then
  die '已请求 --build-frontend，但找不到 npm；请安装 Node.js 20+ 后重试。'
fi

validate_venv() {
  venv_path=$1
  venv_python="$venv_path/bin/python"
  if [ ! -x "$venv_python" ]; then
    die "已有虚拟环境缺少可执行文件 $venv_python；未修改该环境。"
  fi

  if ! venv_version=$("$venv_python" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null); then
    die "无法运行已有虚拟环境 $venv_python；未修改该环境。"
  fi
  if [ "$venv_version" != '3.12' ]; then
    die "已有 .venv 是 Python $venv_version，需要 Python 3.12；未删除或覆盖旧环境。"
  fi

  if ! expected_prefix=$(CDPATH= cd -- "$venv_path" && pwd -P); then
    die "无法解析虚拟环境位置 $venv_path；未修改该环境。"
  fi
  if ! actual_prefix=$("$venv_python" -c 'import pathlib, sys; print(pathlib.Path(sys.prefix).resolve())' 2>/dev/null); then
    die "无法确认已有虚拟环境的运行位置；未修改该环境。"
  fi
  if [ "$actual_prefix" != "$expected_prefix" ]; then
    die "已有 .venv 的运行位置是 $actual_prefix，不是 $expected_prefix；未删除或覆盖旧环境。"
  fi
}

PYTHON312=''
FOUND_PYTHON=''
find_python312() {
  PYTHON312=''
  FOUND_PYTHON=''
  for candidate_name in python3.12 python3; do
    if candidate_path=$(command -v "$candidate_name" 2>/dev/null); then
      if candidate_version=$("$candidate_path" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null); then
        FOUND_PYTHON="$FOUND_PYTHON $candidate_name=$candidate_version"
        if [ "$candidate_version" = '3.12' ]; then
          PYTHON312=$candidate_path
          return 0
        fi
      else
        FOUND_PYTHON="$FOUND_PYTHON $candidate_name=unusable"
      fi
    fi
  done
  return 1
}

VENV_CREATED=0
cleanup_new_venv() {
  if [ "$VENV_CREATED" -eq 1 ] && [ -d "$ROOT/.venv" ] && [ ! -L "$ROOT/.venv" ]; then
    rm -rf "$ROOT/.venv"
  fi
}
trap cleanup_new_venv EXIT HUP INT TERM

create_venv() {
  VENV_CREATED=1
  if command -v uv >/dev/null 2>&1; then
    if uv venv --python 3.12 "$ROOT/.venv"; then
      return 0
    fi
    printf '提示：uv 创建 Python 3.12 环境失败，尝试本机 python3.12/python3。\n' >&2
    cleanup_new_venv
    if [ -e "$ROOT/.venv" ] || [ -L "$ROOT/.venv" ]; then
      die 'uv 失败后 .venv 未能安全清理；为保护现有路径，未继续覆盖。'
    fi
  fi

  if ! find_python312; then
    if [ -n "$FOUND_PYTHON" ]; then
      die "需要 Python 3.12；已发现的 Python：$FOUND_PYTHON。请安装 uv 或 Python 3.12 后重试。"
    fi
    die '需要 Python 3.12；未找到 python3.12 或 python3。请安装 uv 或 Python 3.12 后重试。'
  fi
  if ! "$PYTHON312" -m venv "$ROOT/.venv"; then
    die "无法用 $PYTHON312 创建 Python 3.12 虚拟环境。"
  fi
}

if [ -e "$ROOT/.venv" ] || [ -L "$ROOT/.venv" ]; then
  if [ -L "$ROOT/.venv" ] || [ ! -d "$ROOT/.venv" ]; then
    die '已有 .venv 不是普通目录；为保护旧环境，未覆盖它。'
  fi
  validate_venv "$ROOT/.venv"
else
  create_venv
  validate_venv "$ROOT/.venv"
  VENV_CREATED=0
fi

VENV_PYTHON="$ROOT/.venv/bin/python"
REQUIREMENTS_FILE="$ROOT/backend/requirements.txt"
if [ -f "$ROOT/backend/requirements-lock.txt" ]; then
  REQUIREMENTS_FILE="$ROOT/backend/requirements-lock.txt"
else
  printf '提示：未找到 backend/requirements-lock.txt，回退到 backend/requirements.txt。\n' >&2
fi

if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$VENV_PYTHON" -r "$REQUIREMENTS_FILE"
else
  "$VENV_PYTHON" -m pip install -r "$REQUIREMENTS_FILE"
fi

if [ "$build_frontend" -eq 1 ]; then
  (cd "$ROOT/frontend" && npm ci && npm run build)
else
  printf '已找到 frontend/dist，跳过 Node/npm。\n'
fi

printf '\n安装完成。运行 ./start.sh，然后打开 http://127.0.0.1:8710\n'
