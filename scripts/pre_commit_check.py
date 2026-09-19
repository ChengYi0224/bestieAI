"""
pre_commit_check.py — Git Commit 前全自動語法、靜態分析與單元測試防護腳本。
"""
import sys
import subprocess


def run_step(step_name: str, cmd: list[str]) -> bool:
    print(f"\n[Pre-commit] {step_name}...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n[Pre-commit ERROR] {step_name} 失敗！Commit 已被阻斷。")
        return False
    return True


def main() -> int:
    steps = [
        ("1/3 全專案語法編譯檢查 (compileall)", [sys.executable, "-m", "compileall", "app", "-q"]),
        ("2/3 靜態程式碼分析 (ruff select F)", ["uvx", "ruff", "check", "app", "--select", "F"]),
        ("3/3 全量單元測試 (pytest)", ["uv", "run", "pytest"]),
    ]

    for name, cmd in steps:
        if not run_step(name, cmd):
            return 1

    print("\n[Pre-commit SUCCESS] 全項檢查通過，允許 Commit！\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
