"""
SocialGraph Pro — 一键执行全部 6 个负载测试场景

用法:
  python tests/load/run_all_scenarios.py [--host http://127.0.0.1:8000]

前置条件:
  - API 服务已启动 (python server.py)
  - Redis 运行中
  - Neo4j 运行中
  - MySQL 运行中
  - C++ 引擎可执行

输出:
  reports/ 目录下生成每个场景的 CSV + HTML 报告
"""

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime

# ────────────────────────────────────────────────────────────────────
# 配置
# ────────────────────────────────────────────────────────────────────

REPORTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reports")
LOCUSTFILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "locustfile.py")

SCENARIOS = [
    {
        "name": "NormalLoad",
        "description": "正常负载 (50 并发, 30 分钟)",
        "users": 50,
        "spawn_rate": 5,
        "run_time": "30m",
        "tags": ["NormalLoad"],
        "pre_cmd": None,
        "post_cmd": None,
    },
    {
        "name": "PeakLoad",
        "description": "峰值负载 (10→200 并发, 60s 爬坡, 10 分钟)",
        "users": 200,
        "spawn_rate": 3,
        "run_time": "10m",
        "tags": ["PeakLoad"],
        "pre_cmd": None,
        "post_cmd": None,
    },
    {
        "name": "SustainedLoad",
        "description": "持续负载 (100 并发, 2 小时)",
        "users": 100,
        "spawn_rate": 10,
        "run_time": "2h",
        "tags": ["SustainedLoad"],
        "pre_cmd": None,
        "post_cmd": None,
    },
    {
        "name": "CacheFailure",
        "description": "Redis 缓存故障 (30 并发, 10 分钟)",
        "users": 30,
        "spawn_rate": 5,
        "run_time": "10m",
        "tags": ["CacheFailure"],
        "pre_cmd": 'redis-cli shutdown 2>/dev/null; echo "Redis 已停止 (用于故障测试)"',
        "post_cmd": 'redis-server --daemonize yes 2>/dev/null; echo "Redis 已重启"',
    },
    {
        "name": "DatabaseFailure",
        "description": "Neo4j 数据库故障 (30 并发, 10 分钟)",
        "users": 30,
        "spawn_rate": 5,
        "run_time": "10m",
        "tags": ["DatabaseFailure"],
        "pre_cmd": 'neo4j stop 2>/dev/null; echo "Neo4j 已停止 (用于故障测试)"',
        "post_cmd": 'neo4j start 2>/dev/null; echo "Neo4j 已重启"',
    },
    {
        "name": "MixedWorkload",
        "description": "混合工作负载 (80 并发, 20 分钟)",
        "users": 80,
        "spawn_rate": 5,
        "run_time": "20m",
        "tags": ["MixedWorkload"],
        "pre_cmd": None,
        "post_cmd": None,
    },
]


def run_scenario(scenario: dict, host: str, fail_fast: bool = False) -> bool:
    """执行单个测试场景。

    Args:
        scenario: 场景配置字典
        host:     目标主机 URL
        fail_fast: 遇到失败是否立即停止

    Returns:
        是否全部通过
    """
    name = scenario["name"]
    description = scenario["description"]

    print(f"\n{'=' * 70}")
    print(f"开始执行: {name}")
    print(f"描述: {description}")
    print(f"{'=' * 70}")

    # 执行前置命令
    if scenario["pre_cmd"]:
        print(f"\n[前置操作] {scenario['pre_cmd']}")
        subprocess.run(scenario["pre_cmd"], shell=True, timeout=30)
        time.sleep(2)  # 等待服务完全停止

    # 构建 Locust 命令
    os.makedirs(REPORTS_DIR, exist_ok=True)
    prefix = os.path.join(REPORTS_DIR, name.lower())

    cmd = [
        sys.executable, "-m", "locust",
        "-f", LOCUSTFILE,
        "--host", host,
        "--headless",
        "-u", str(scenario["users"]),
        "-r", str(scenario["spawn_rate"]),
        "--run-time", scenario["run_time"],
        "--csv", prefix,
        "--html", f"{prefix}.html",
    ]
    for tag in scenario["tags"]:
        cmd.extend(["--tags", tag])

    # 排除不需要的用户类标签（只让对应的 User 类生效）
    # Locust 中 --tags 作用于 @task 级别，还需要确保对应的 User 类存在
    # 这里使用环境变量 LOCUST_USER_CLASS 来指定
    env = os.environ.copy()
    env["LOCUST_USER_CLASS"] = {
        "NormalLoad": "NormalLoadUser",
        "PeakLoad": "PeakLoadUser",
        "SustainedLoad": "SustainedLoadUser",
        "CacheFailure": "CacheFailureUser",
        "DatabaseFailure": "DatabaseFailureUser",
        "MixedWorkload": "MixedWorkloadUser",
    }.get(name, "")

    print(f"\n[执行命令] {' '.join(cmd)}")
    print(f"[时间] {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # 执行
    start = time.time()
    result = subprocess.run(cmd, env=env, timeout=None)
    elapsed = time.time() - start

    print(f"\n[完成] {name} — 耗时: {elapsed:.0f}s, 退出码: {result.returncode}")

    # 执行后置命令
    if scenario["post_cmd"]:
        print(f"\n[后置操作] {scenario['post_cmd']}")
        subprocess.run(scenario["post_cmd"], shell=True, timeout=30)
        time.sleep(3)  # 等待服务完全启动

    # 检查结果
    if result.returncode != 0:
        print(f"[结果] FAIL — {name} 未通过性能断言")
        return False
    else:
        print(f"[结果] PASS — {name} 通过性能断言")
        return True


def health_check(host: str) -> bool:
    """检查 API 服务是否可达。"""
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"{host}/api/v1/health", timeout=10)
        return resp.status == 200
    except Exception as e:
        print(f"健康检查失败: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="SocialGraph Pro — 一键负载测试"
    )
    parser.add_argument(
        "--host", default="http://127.0.0.1:8000",
        help="API 服务器地址 (默认: http://127.0.0.1:8000)"
    )
    parser.add_argument(
        "--scenarios", nargs="+",
        choices=[s["name"] for s in SCENARIOS] + ["all"],
        default=["all"],
        help="要执行的场景 (默认: all)"
    )
    parser.add_argument(
        "--fail-fast", action="store_true",
        help="遇到第一个失败就停止"
    )
    parser.add_argument(
        "--skip-health-check", action="store_true",
        help="跳过启动前健康检查"
    )
    args = parser.parse_args()

    print("=" * 70)
    print("SocialGraph Pro — 负载测试套件")
    print(f"目标: {args.host}")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 健康检查
    if not args.skip_health_check:
        print("\n[健康检查]")
        if health_check(args.host):
            print("  PASS — API 服务可达")
        else:
            print("  FAIL — API 服务不可达! 请先启动服务: python server.py")
            sys.exit(1)

    # 筛选要执行的场景
    if "all" in args.scenarios:
        to_run = SCENARIOS
    else:
        to_run = [s for s in SCENARIOS if s["name"] in args.scenarios]

    print(f"\n将执行 {len(to_run)} 个场景:\n")
    for s in to_run:
        print(f"  - {s['name']}: {s['description']}")
    print()

    # 执行
    results = {}
    total_start = time.time()

    for i, scenario in enumerate(to_run, 1):
        print(f"\n{'#' * 70}")
        print(f"# 场景 {i}/{len(to_run)}")
        print(f"{'#' * 70}")

        passed = run_scenario(scenario, args.host, fail_fast=args.fail_fast)
        results[scenario["name"]] = passed

        if not passed and args.fail_fast:
            print("\n[fail-fast] 遇到失败，停止后续场景")
            break

        # 场景间冷却 (非最后一个)
        if i < len(to_run):
            cooldown = 60  # 60 秒冷却
            print(f"\n[冷却] 等待 {cooldown} 秒后开始下一个场景...")
            time.sleep(cooldown)

    total_elapsed = time.time() - total_start

    # 汇总报告
    print("\n" + "=" * 70)
    print("全部场景执行完毕")
    print(f"总耗时: {total_elapsed:.0f}s ({total_elapsed/60:.1f} 分钟) ")
    print("=" * 70)
    print(f"\n{'场景':<25} {'结果':<8}")
    print("-" * 35)
    all_passed = True
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False
        print(f"{name:<25} {status:<8}")
    print("-" * 35)
    print(f"\n总体结果: {'全部通过' if all_passed else '存在失败场景'}")
    print(f"报告目录: {os.path.abspath(REPORTS_DIR)}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
