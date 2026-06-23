#!/usr/bin/env python3
"""Smart IPTV Sources — 每日刷新脚本

每 24 小时自动执行：
1. python3 generate.py --check-streams
2. python3 validate.py
3. git commit + push → Cloudflare Pages 自动部署

用法:
  python3 scripts/refresh.py
  python3 scripts/refresh.py --dry-run    # 只生成不提交
  python3 scripts/refresh.py --no-push    # 不 git push
"""

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 600) -> subprocess.CompletedProcess:
    print(f"  ⏳ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        for line in result.stdout.strip().split("\n")[:20]:
            print(f"     {line}")
    if result.returncode != 0:
        print(f"  ❌ 失败 (exit {result.returncode})", flush=True)
        if result.stderr.strip():
            for line in result.stderr.strip().split("\n")[:5]:
                print(f"     {line}")
    else:
        print(f"  ✅ 完成", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="Smart IPTV Sources 每日刷新")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-push", action="store_true")
    args = parser.parse_args()

    print(f"🔄 Smart IPTV Sources 刷新 — {datetime.now(timezone.utc).isoformat()}", flush=True)

    # Step 1: 生成
    print("\n📡 生成 + 流探测...", flush=True)
    if run(["python3", "generate.py", "--check-streams"], timeout=900).returncode != 0:
        sys.exit(1)

    # Step 2: 验证
    print("\n✅ 验证...", flush=True)
    if run(["python3", "validate.py"], timeout=60).returncode != 0:
        sys.exit(1)

    if args.dry_run:
        print("\n🔍 --dry-run 跳过提交", flush=True)
        return

    # Step 3: Git → CF 自动部署
    print("\n📦 Git 提交...", flush=True)
    status = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True)
    if not status.stdout.strip():
        print("    无变更", flush=True)
        return

    run(["git", "add", "public/"])
    if run(["git", "commit", "-m", f"chore: auto-refresh {datetime.now().strftime('%Y-%m-%d %H:%M')}"]).returncode != 0:
        print("  ⚠️  Git commit 失败", flush=True)
        sys.exit(1)
    if not args.no_push:
        if run(["git", "push"], timeout=120).returncode != 0:
            print("  ⚠️  Git push 失败", flush=True)
            sys.exit(1)
        print("\n☁️  Git push 完成 → Cloudflare Pages 自动部署中...", flush=True)

    print(f"\n🎉 刷新完成 — {datetime.now(timezone.utc).isoformat()}", flush=True)


if __name__ == "__main__":
    main()
