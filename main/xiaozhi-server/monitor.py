import subprocess
import time
import psutil
import os
import csv
from datetime import datetime

def get_memory_usage(pid):
    try:
        process = psutil.Process(pid)
        mem_info = process.memory_info()
        return mem_info.rss / (1024 * 1024) # 以 MB 为单位返回
    except psutil.NoSuchProcess:
        return None

if __name__ == "__main__":
    command = ["python", "app.py"] # 替换为你的应用启动命令
    log_file = "memory_log.csv"
    sample_interval = 5 # 每隔 5 秒采样一次

    with open(log_file, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["timestamp", "pid", "memory_mb"])

        process = subprocess.Popen(command)
        pid = process.pid
        print(f"应用 (PID: {pid}) 已启动，开始记录内存使用情况...")

        try:
            while process.poll() is None:  # 当进程仍在运行时
                memory_usage = get_memory_usage(pid)
                if memory_usage is not None:
                    timestamp = datetime.now().isoformat()
                    writer.writerow([timestamp, pid, f"{memory_usage:.2f}"])
                else:
                    print(f"进程 (PID: {pid}) 未找到。")
                    break
                time.sleep(sample_interval)
        except KeyboardInterrupt:
            print("监控已停止。")
        finally:
            process.terminate()
            process.wait()
            print(f"内存使用日志已保存到 {log_file}")