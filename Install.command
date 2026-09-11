#!/bin/sh
set -u

cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)" || exit 1
PATH="${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"
if [ -n "${HOME:-}" ]; then
  PATH="$HOME/.local/bin:$PATH"
fi
PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
export PATH
if (exec ./setup.sh "$@"); then
  exit 0
else
  status=$?
fi

printf '\n安装未完成（退出码 %s）。请保留此窗口中的错误信息。\n' "$status" >&2
printf '按回车关闭窗口。'
read -r _ || true
exit "$status"
