import os
import subprocess
import json
import random
import time

# ⚠️ 注意：如果你在 Windows 下运行，请把这里改成你的 exe 实际路径！
# 例如：ENGINE_PATH = "./backend_cpp/build/Release/graph_engine.exe"
# 如果在 Linux/Mac 下，通常是：ENGINE_PATH = "./backend_cpp/build/graph_engine"
ENGINE_PATH = r"D:\claudecode_workspace\backend_cpp\cmake-build-debug\graph_engine.exe"

def generate_dummy_data(filename, num_edges):
    """生成用于压测的随机图数据"""
    print(f"🔄 正在生成 {num_edges} 条测试数据...")
    with open(filename, 'w') as f:
        for _ in range(num_edges):
            u = f"Node_{random.randint(1, int(num_edges/5))}"
            v = f"Node_{random.randint(1, int(num_edges/5))}"
            f.write(f"{u} {v}\n")
    print(f"✅ 数据生成完毕: {filename}")

def run_benchmark(data_file, command, *args):
    """调用 C++ 引擎并提取耗时"""
    cmd = [ENGINE_PATH, data_file, command] + list(args)
    try:
        # 只捕获 stdout (JSON数据)，忽略 stderr (日志)
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # 解析 C++ 吐出的 JSON
        response = json.loads(result.stdout)
        if response.get("status") == "success":
            return response.get("time_ms", -1)
        else:
            return "Error"
    except Exception as e:
        # 把具体的死因打印出来！
        print(f"  ❌ 崩溃详情: {e}") 
        return "Crash"

if __name__ == "__main__":
    print("🚀 工业级图计算引擎 Benchmark 启动！\n")
    
    # 我们测试三个量级：1万条边，5万条边，10万条边
    test_scales = [10000, 50000, 100000]
    algorithms = ["pagerank", "community"]
    
    results = {scale: {} for scale in test_scales}

    # 1. 跑测试
    for scale in test_scales:
        test_file = f"temp_benchmark_{scale}.txt"
        generate_dummy_data(test_file, scale)
        
        for algo in algorithms:
            print(f"  ⚡ 压测 {algo} (数据量: {scale})...")
            time_ms = run_benchmark(test_file, algo)
            results[scale][algo] = time_ms
            
        # 清理临时文件
        os.remove(test_file)

    # 2. 生成极具震撼力的 Markdown 报告
    print("\n" + "="*50)
    print("📊 C++ 底层计算引擎性能基准测试报告")
    print("="*50 + "\n")
    print("| 数据量级 (Edges) | PageRank 耗时 (ms) | LPA 社区发现耗时 (ms) |")
    print("|------------------|--------------------|-----------------------|")
    
    for scale in test_scales:
        pr_time = results[scale]["pagerank"]
        lpa_time = results[scale]["community"]
        print(f"| {scale:<16} | {pr_time:<18} | {lpa_time:<21} |")
    
    print("\n✅ 压测完成！你可以直接把这个表格贴进你的 GitHub README 里了！")