#!/usr/bin/env python3
"""
模块 0：WebBridge 守护进程健康检查与自愈辅助（v5.6.6 新增）

用途：探测 127.0.0.1:10086 守护进程是否在线；若离线，清理残留 daemon.pid 并打印启动命令。
职责范围：消除「守护进程误报不可达 / 残留 pid 阻塞启动 / 跨调用被清理」三类环境故障（复盘 K2/K3）。
      本脚本只做探测 + 清理 + 提示；真正起守护进程由 Agent 用 run_in_background 托管
      `kimi-webbridge start --foreground` 以跨调用保活（本环境 Bash 工具会在普通命令结束时清理后台子进程）。
关联模块：webbridge_client.health_check（已修，改探 /command 而非 GET /）
维护状态：v5.6.6 新增

用法：
    python scripts/ensure_webbridge.py        # 探测并打印状态
    python scripts/ensure_webbridge.py --fix  # 额外清理残留 pid（若守护进程确实离线）
"""

import os
import sys
import json
import argparse
import urllib.request
import urllib.error
import subprocess

HOST, PORT, SESSION = "127.0.0.1", 10086, "boss-main"
PID_FILE = os.path.expanduser("~/.kimi-webbridge/daemon.pid")
BIN = os.path.expanduser("~/.kimi-webbridge/bin/kimi-webbridge.exe")


def health():
    body = json.dumps({"action": "list_tabs", "args": {}, "session": SESSION}).encode("utf-8")
    req = urllib.request.Request(
        "http://%s:%d/command" % (HOST, PORT), data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return bool(json.loads(r.read().decode("utf-8")).get("ok"))
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="离线时额外清理残留 daemon.pid")
    a = ap.parse_args()

    up = health()
    print(f"WebBridge 守护进程: {'在线' if up else '离线'}")
    if up:
        print("无需操作；可直接运行 serial_loop / batch_deliver。")
        return

    print("离线。推荐：Agent 用 run_in_background 托管启动以跨调用保活：")
    print(f'  "{BIN}" start --foreground')
    if a.fix:
        if os.path.exists(PID_FILE):
            try:
                os.remove(PID_FILE)
                print(f"已清理残留 pid 文件: {PID_FILE}")
            except Exception as e:
                print("清 pid 失败:", e)
        try:
            subprocess.run([BIN, "stop"], timeout=5, capture_output=True)
        except Exception:
            pass
        print("可重新运行 start --foreground（经 run_in_background 托管）。")


if __name__ == "__main__":
    main()
