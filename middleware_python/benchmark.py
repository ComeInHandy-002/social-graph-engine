import os
import subprocess
import json
import random
import time

# 路径解析：优先环境变量，回退到相对路径
def _resolve_path(env_key, *candidates):
    val = os.environ.get(env_key)
    if val and os.path.exists(val):
        return val
    base = os.path.dirname(os.path.abspath(__file__))
    for c in candidates:
        path = os.path.normpath(os.path.join(base, c))
        if os.path.exists(path):
            return path
    return os.path.normpath(os.path.join(base, candidates[0]))


ENGINE_PATH = _resolve_path(
    "CPP_ENGINE_PATH",
    "../backend_cpp/cmake-build-release/graph_engine.exe",
    "../backend_cpp/cmake-build-debug/graph_engine.exe",
    "../backend_cpp/build/graph_engine",
    "../backend_cpp/build/graph_engine.exe",
)


def generate_dummy_data(filename, num_edges):
    print(f"🔄 正在生成 {num_edges} 条测试数据...")
    with open(filename, 'w') as f:
        for _ in range(num_edges):
            u = f"Node_{random.randint(1, int(num_edges / 5))}"
            v = f"Node_{random.randint(1, int(num_edges / 5))}"
            f.write(f"{u} {v}\n")
    print(f"✅ 数据生成完毕: {filename}")


def run_benchmark(data_file, command, *args):
    cmd = [ENGINE_PATH, data_file, command] + list(args)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        response = json.loads(result.stdout)
        if response.get("status") == "success":
            return response.get("time_ms", -1)
        else:
            return "Error"
    except Exception as e:
        print(f"  ❌ 崩溃详情: {e}")
        return "Crash"


if __name__ == "__main__":
    print("🚀 工业级图计算引擎 Benchmark 启动！\n")

    test_scales = [10000, 50000, 100000]
    algorithms = ["pagerank", "community"]

    results = {scale: {} for scale in test_scales}

    for scale in test_scales:
        test_file = f"temp_benchmark_{scale}.txt"
        generate_dummy_data(test_file, scale)

        for algo in algorithms:
            print(f"  ⚡ 压测 {algo} (数据量: {scale})...")
            time_ms = run_benchmark(test_file, algo)
            results[scale][algo] = time_ms

        os.remove(test_file)

    print("\n" + "=" * 50)
    print("📊 C++ 底层计算引擎性能基准测试报告")
    print("=" * 50 + "\n")
    print("| 数据量级 (Edges) | PageRank 耗时 (ms) | LPA 社区发现耗时 (ms) |")
    print("|------------------|--------------------|-----------------------|")

    for scale in test_scales:
        pr_time = results[scale]["pagerank"]
        lpa_time = results[scale]["community"]
        print(f"| {scale:<16} | {pr_time:<18} | {lpa_time:<21} |")

    print("\n✅ 压测完成！")
