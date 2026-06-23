#!/usr/bin/env python3
"""Smart IPTV Sources — 每日刷新脚本

每 24 小时自动执行，流程：
1. python3 generate.py --check-streams  （拉源 → 筛选 → 测流 → 生成）
2. python3 validate.py                  （验证输出完整性）
3. git commit + push                    （推送更新）
4. (可选) wrangler pages deploy          （Cloudflare Pages 部署）

用法:
  python3 scripts/refresh.py           # 完整流程
  python3 scripts/refresh.py --dry-run  # 只生成和验证，不 git/cf
  python3 scripts/refresh.py --no-push  # 不 git push
"""

import argparse
import subprocess
import sys
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path = ROOT, timeout: int = 600) -> subprocess.CompletedProcess:
    """运行命令，打印输出，遇错退出"""
    print(f"  ⏳ {' '.join(cmd)}", flush=True)
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            print(f"     {line}")
    if result.stderr.strip():
        for line in result.stderr.strip().split("\n")[:10]:
            print(f"     [stderr] {line}", flush=True)
    if result.returncode != 0:
        print(f"  ❌ 失败 (exit {result.returncode})", flush=True)
    else:
        print(f"  ✅ 完成", flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description="Smart IPTV Sources 每日刷新")
    parser.add_argument("--dry-run", action="store_true", help="只生成和验证，不提交 git")
    parser.add_argument("--no-push", action="store_true", help="不 git push")
    parser.add_argument("--deploy-cf", action="store_true", help="同时部署到 Cloudflare Pages")
    args = parser.parse_args()

    print(f"🔄 Smart IPTV Sources 刷新 — {datetime.now(timezone.utc).isoformat()}", flush=True)
    print()

    # Step 1: 生成（含流探测）
    print("📡 Step 1/4: 拉取上游源并生成...", flush=True)
    result = run(["python3", "generate.py", "--check-streams"], timeout=900)
    if result.returncode != 0:
        print("❌ 生成失败，中止", flush=True)
        sys.exit(1)

    # Step 2: 验证
    print("\n✅ Step 2/4: 验证输出...", flush=True)
    result = run(["python3", "validate.py"], timeout=60)
    if result.returncode != 0:
        print("❌ 验证失败，中止", flush=True)
        sys.exit(1)

    if args.dry_run:
        print("\n🔍 --dry-run 模式，跳过 git 和部署", flush=True)
        return

    # Step 3: Git 提交
    print("\n📦 Step 3/4: Git 提交...", flush=True)
    git_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True
    )
    if not git_status.stdout.strip():
        print("    无变更，跳过提交", flush=True)
    else:
        run(["git", "add", "public/"])
        run(["git", "commit", "-m", f"chore: auto-refresh {datetime.now().strftime('%Y-%m-%d %H:%M')}"])
        if not args.no_push:
            run(["git", "push"], timeout=120)

    # Step 4: Cloudflare Pages（可选）
    if args.deploy_cf:
        print("\n☁️  Step 4/4: 部署到 Cloudflare Pages...", flush=True)
        result = run(["wrangler", "pages", "deploy", "public/"], timeout=180)
        if result.returncode != 0:
            print("⚠️  Cloudflare 部署失败（不影响主流程）", flush=True)

    print(f"\n🎉 刷新完成 — {datetime.now(timezone.utc).isoformat()}", flush=True)


if __name__ == "__main__":
    main()
