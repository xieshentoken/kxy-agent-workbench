#!/usr/bin/env python3
"""Verify the immutable source files listed by package-manifest.json."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MANIFEST_PATH = ROOT / "package-manifest.json"


def fail(message: str) -> int:
    print(f"包校验失败：{message}", file=sys.stderr)
    return 1


def listed_path(raw_path: object) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError("files 含有空或非字符串路径")
    relative = Path(raw_path)
    if relative.is_absolute() or relative == Path(".") or ".." in relative.parts:
        raise ValueError(f"路径必须是包根目录内的相对路径：{raw_path!r}")

    candidate = ROOT
    for part in relative.parts:
        candidate /= part
        if candidate.is_symlink():
            raise ValueError(f"清单路径不能经过 symlink：{raw_path!r}")

    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(ROOT)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"路径逃逸包根目录：{raw_path!r}") from exc
    return candidate


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    if MANIFEST_PATH.is_symlink() or not MANIFEST_PATH.is_file():
        return fail("缺少包根目录/package-manifest.json")
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return fail(f"无法读取 package-manifest.json：{exc}")

    if not isinstance(manifest, dict) or not isinstance(manifest.get("files"), dict):
        return fail("manifest.files 必须是‘相对路径 => sha256’对象")

    checked = 0
    for raw_path, expected in manifest["files"].items():
        try:
            path = listed_path(raw_path)
        except ValueError as exc:
            return fail(str(exc))
        if not isinstance(expected, str) or len(expected) != 64:
            return fail(f"{raw_path!r} 的 sha256 格式无效")
        try:
            int(expected, 16)
        except ValueError:
            return fail(f"{raw_path!r} 的 sha256 不是十六进制")
        if path.is_symlink() or not path.is_file():
            return fail(f"清单文件不存在或不是普通文件：{raw_path!r}")
        try:
            actual = sha256(path)
        except OSError as exc:
            return fail(f"无法读取 {raw_path!r}：{exc}")
        if actual.lower() != expected.lower():
            return fail(f"sha256 不匹配：{raw_path!r}")
        checked += 1

    print(f"包校验通过：{checked} 个清单文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
