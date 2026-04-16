import subprocess
import json
import os

def run_graph_engine(command, *args):
    # 你的绝对路径
    exe_path = r"D:\claudecode_workspace\backend_cpp\cmake-build-debug\graph_engine.exe"
    data_path = r"D:\claudecode_workspace\backend_cpp\facebook_combined.txt"
    
    # 🌟 核心魔法：我们在 D 盘建一个临时文件，当作 C++ 和 Python 交接数据的“中转站”
    temp_output_file = r"D:\claudecode_workspace\temp_graph_output.json"
    
    cmd = [exe_path, data_path, command] + list(args)
    
    try:
        # 1. 打开这个临时文件，让 C++ 的海量输出直接灌进去，绕过脆弱的系统管道！
        with open(temp_output_file, "w", encoding="utf-8") as f_out:
            # 注意：这里 stdout=f_out，就是你在终端里敲的 `>` 的代码版
            result = subprocess.run(cmd, stdout=f_out, stderr=subprocess.PIPE, text=True, timeout=30)
        
        if result.returncode != 0:
            return {"status": "error", "message": f"引擎崩溃: {result.stderr}"}
            
        # 2. C++ 写完退出了，Python 再安全地从文件里把这 300 万字符一口气读出来
        with open(temp_output_file, "r", encoding="utf-8") as f_in:
            out_text = f_in.read().strip()
            
        if not out_text:
            return {"status": "error", "message": "C++ 引擎生成了空数据！"}
            
        # 3. 解析 JSON 并返回给前端
        return json.loads(out_text)
        
    except json.JSONDecodeError:
        return {"status": "error", "message": "JSON解析失败，C++吐出的格式有问题！"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        # 清理战场：如果你想看看 C++ 到底输出了啥，可以把下面两行注释掉
        if os.path.exists(temp_output_file):
            os.remove(temp_output_file)