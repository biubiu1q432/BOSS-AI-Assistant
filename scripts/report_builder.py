#!/usr/bin/env python3
"""
模块 G：投递汇总 HTML 生成（Skill v5.6.1，2026-10-12）

职责：读取 stream_progress.json，输出包含累计快照和本次调用结果的 HTML 报告。
每次 finish 默认写入时间戳文件 投递汇总_YYYYMMDD_HHMMSS.html，不覆盖历史报告；
可选同步最新副本 投递汇总.html。标题包含生成时间和 run_id。

统计卡片拆开显示 success、blocked、fail、unknown、legacy_unknown，
并展示重复合并数、唯一岗位数、空行业成功数。失败明细按状态分组，
不把 unknown 和 blocked 合并到“失败”。
"""

import base64
import json
import os
import shutil
import sys
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(SKILL_DIR, "assets")


def _esc(text):
    """HTML 转义"""
    if not text:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def _load_qr_base64(filename):
    """从 assets 目录读取二维码图片，返回 data:image 格式的 base64 字符串。读取失败返回空字符串。"""
    filepath = os.path.join(ASSETS_DIR, filename)
    if not os.path.exists(filepath):
        print(f"警告: 二维码图片不存在: {filepath}")
        return ""
    try:
        with open(filepath, "rb") as f:
            raw = f.read()
        ext = os.path.splitext(filename)[1].lstrip(".").lower()
        mime_map = {"jpg": "jpeg", "jpeg": "jpeg", "png": "png", "gif": "gif", "webp": "webp"}
        mime = mime_map.get(ext, "jpeg")
        return f"data:image/{mime};base64,{base64.b64encode(raw).decode()}"
    except Exception as e:
        print(f"警告: 读取二维码图片失败: {filepath} ({e})")
        return ""


def _status_of(job):
    return job.get("result") or job.get("status") or "fail"


def _table(rows, headers, empty_text):
    if not rows:
        return f'    <div class="empty">{_esc(empty_text)}</div>\n'
    html = "    <table>\n      <thead><tr>" + "".join(f"<th>{_esc(h)}</th>" for h in headers) + "</tr></thead>\n      <tbody>\n"
    for i, row in enumerate(rows, 1):
        html += "      <tr>" + "".join(f"<td>{cell}</td>" for cell in [str(i)] + row) + "</tr>\n"
    html += "      </tbody>\n    </table>\n"
    return html


def build_report(progress_file="stream_progress.json", output_path="投递汇总.html", run_id=None, latest_copy=None, current_stats=None):
    """生成投递汇报 HTML 页。

    参数:
        progress_file: 投递进度 JSON 文件路径
        output_path: 输出 HTML 文件路径（应为时间戳文件）
        run_id: 本次调用标识
        latest_copy: 可选的最新报告副本路径
        current_stats: 本次调用统计；缺省时按 run_id 从进度文件计算
    """
    if not os.path.exists(progress_file):
        print(f"进度文件不存在: {progress_file}")
        return None

    sys.path.insert(0, SKILL_DIR)
    from scripts.webbridge_client import ProgressManager
    pm = ProgressManager(progress_file)
    pm.load()
    delivered = pm.data.get("delivered", [])
    failed = pm.data.get("failed", [])
    stats = pm.stats()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if current_stats is None:
        records = list(delivered) + list(failed)
        current_records = [r for r in records if run_id and r.get("run_id") == run_id]
        def _count(items, status):
            return sum(1 for item in items if pm.classify_status(item) == status)
        current_industries = sorted({j.get("industry") for j in current_records if pm.classify_status(j) == "success" and j.get("industry")})
        current_stats = {
            "run_id": run_id or "",
            "started_at": "",
            "generated_at": generated_at,
            "current_total": len(current_records),
            "current_success": _count(current_records, "success"),
            "current_blocked": _count(current_records, "blocked"),
            "current_fail": _count(current_records, "fail"),
            "current_unknown": _count(current_records, "unknown"),
            "current_legacy_unknown": _count(current_records, "legacy_unknown"),
            "current_industries": current_industries,
            "current_industry_count": len(current_industries),
            "current_records": current_records,
        }
    else:
        current_records = current_stats.get("current_records", [])
        generated_at = current_stats.get("generated_at") or generated_at
        run_id = current_stats.get("run_id") or run_id

    blocked_jobs = [j for j in failed if _status_of(j) == "blocked"]
    fail_jobs = [j for j in failed if _status_of(j) == "fail"]
    unknown_jobs = [j for j in failed if _status_of(j) == "unknown"]
    legacy_jobs = [j for j in failed if _status_of(j) == "legacy_unknown"]

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>投递汇报 - {generated_at} - { _esc(run_id or "-") }</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; background: #f5f5f5; color: #333; line-height: 1.6; }}
.container {{ max-width: 980px; margin: 0 auto; padding: 20px; }}
.header {{ background: linear-gradient(135deg, #00b38a, #009688); color: #fff; padding: 30px; border-radius: 12px; text-align: center; margin-bottom: 20px; }}
.header h1 {{ font-size: 28px; margin-bottom: 8px; }}
.header .subtitle {{ opacity: 0.9; font-size: 14px; }}
.stats {{ display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }}
.stat-card {{ flex: 1; min-width: 120px; background: #fff; padding: 16px; border-radius: 8px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.stat-card .num {{ font-size: 28px; font-weight: bold; color: #00b38a; }}
.stat-card .label {{ font-size: 13px; color: #888; margin-top: 4px; }}
.stat-card.fail .num {{ color: #e74c3c; }}
.stat-card.blocked .num {{ color: #e67e22; }}
.stat-card.unknown .num {{ color: #8e44ad; }}
.section {{ background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
.section h2 {{ font-size: 18px; margin-bottom: 16px; padding-bottom: 10px; border-bottom: 2px solid #f0f0f0; }}
table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
th {{ text-align: left; padding: 10px 8px; color: #888; font-weight: 500; border-bottom: 1px solid #eee; }}
td {{ padding: 10px 8px; border-bottom: 1px solid #f8f8f8; }}
tr:hover td {{ background: #fafafa; }}
.tag {{ display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; background: #e8f5e9; color: #2e7d32; }}
.tag.fail {{ background: #fbe9e7; color: #c62828; }}
.tag.blocked {{ background: #fff3e0; color: #e65100; }}
.tag.unknown {{ background: #f3e5f5; color: #6a1b9a; }}
.tip-section {{ background: #fff; border-radius: 8px; padding: 30px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }}
.tip-section h2 {{ font-size: 20px; margin-bottom: 12px; }}
.tip-section p {{ color: #888; margin-bottom: 20px; }}
.tip-codes {{ display: flex; justify-content: center; gap: 40px; flex-wrap: wrap; }}
.tip-code .placeholder {{ width: 180px; height: 180px; border: 2px dashed #ddd; border-radius: 8px; display: flex; align-items: center; justify-content: center; color: #aaa; font-size: 13px; }}
.tip-code .name {{ margin-top: 8px; font-size: 14px; color: #555; }}
.empty {{ text-align: center; padding: 40px; color: #aaa; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>投递汇报</h1>
    <div class="subtitle">生成时间: {generated_at}　run_id: {_esc(run_id or "-")}</div>
    <div class="subtitle">运行开始: {_esc(current_stats.get("started_at") or "-")}</div>
  </div>
  <div class="stats">
    <div class="stat-card"><div class="num">{stats["success_total"]}</div><div class="label">累计 success</div></div>
    <div class="stat-card blocked"><div class="num">{stats["blocked_total"]}</div><div class="label">累计 blocked</div></div>
    <div class="stat-card fail"><div class="num">{stats["fail_total"]}</div><div class="label">累计 fail</div></div>
    <div class="stat-card unknown"><div class="num">{stats["unknown_total"]}</div><div class="label">累计 unknown</div></div>
    <div class="stat-card unknown"><div class="num">{stats["legacy_unknown_total"]}</div><div class="label">累计 legacy_unknown</div></div>
  </div>
  <div class="stats">
    <div class="stat-card"><div class="num">{stats["unique_total"]}</div><div class="label">唯一岗位</div></div>
    <div class="stat-card"><div class="num">{stats["duplicate_removed"]}</div><div class="label">重复合并数</div></div>
    <div class="stat-card"><div class="num">{stats["industry_count"]}</div><div class="label">覆盖行业</div></div>
    <div class="stat-card"><div class="num">{stats["empty_industry_count"]}</div><div class="label">空行业成功数</div></div>
  </div>
  <div class="section">
    <h2>本次调用结果</h2>
    <div class="stats">
      <div class="stat-card"><div class="num">{current_stats["current_total"]}</div><div class="label">本次处理数</div></div>
      <div class="stat-card"><div class="num">{current_stats["current_success"]}</div><div class="label">本次 success</div></div>
      <div class="stat-card blocked"><div class="num">{current_stats["current_blocked"]}</div><div class="label">本次 blocked</div></div>
      <div class="stat-card fail"><div class="num">{current_stats["current_fail"]}</div><div class="label">本次 fail</div></div>
      <div class="stat-card unknown"><div class="num">{current_stats["current_unknown"]}</div><div class="label">本次 unknown</div></div>
    </div>
    <p>本次覆盖行业: {_esc("、".join(current_stats.get("current_industries") or []) or "无")}</p>
"""

    html += _table(
        [[_esc(j.get("title","")), _esc(j.get("company","")), _esc(_status_of(j)), _esc(j.get("industry","") or "空")] for j in current_records],
        ["#", "岗位名称", "公司", "状态", "行业"],
        "本次调用暂无新增结果",
    )
    html += "  </div>\n"

    html += '  <div class="section">\n    <h2>累计成功明细</h2>\n'
    html += _table(
        [[_esc(j.get("title","")), _esc(j.get("company","")), _esc(j.get("salary","")), _esc(j.get("industry","") or "空"), '<span class="tag">success</span>'] for j in delivered],
        ["#", "岗位名称", "公司", "薪资", "行业", "结果"],
        "暂无成功记录",
    )
    html += "  </div>\n"

    def grouped_section(title, jobs, css):
        block = f'  <div class="section">\n    <h2>{_esc(title)}</h2>\n'
        block += _table(
            [[_esc(j.get("title","")), _esc(j.get("company","")), f'<span class="tag {css}">{_esc(j.get("reason") or _status_of(j))}</span>'] for j in jobs],
            ["#", "岗位名称", "公司", "原因"],
            f"暂无{title}",
        )
        block += "  </div>\n"
        return block

    html += grouped_section("blocked 明细", blocked_jobs, "blocked")
    html += grouped_section("fail 明细", fail_jobs, "fail")
    html += grouped_section("unknown 明细", unknown_jobs, "unknown")
    html += grouped_section("legacy_unknown 明细", legacy_jobs, "unknown")

    wechat_qr = _load_qr_base64("wechat_qr.jpg")
    alipay_qr = _load_qr_base64("alipay_qr.jpg")
    html += """  <div class="tip-section">
    <h2>如果这个工具帮到了你</h2>
    <p>投递是个体力活，如果节省了你的时间，可以请作者喝杯咖啡</p>
    <div class="tip-codes">"""
    if wechat_qr:
        html += f'      <div class="tip-code"><img src="{wechat_qr}" width="180" height="180" style="border-radius:8px;object-fit:contain;" alt="微信赞赏码"><div class="name">微信赞赏</div></div>'
    if alipay_qr:
        html += f'      <div class="tip-code"><img src="{alipay_qr}" width="180" height="180" style="border-radius:8px;object-fit:contain;" alt="支付宝收款码"><div class="name">支付宝赞赏</div></div>'
    if not wechat_qr and not alipay_qr:
        html += '      <div class="tip-code"><div class="placeholder">二维码加载失败</div></div>'
    html += """    </div>
  </div>
</div>
</body>
</html>"""

    os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    if latest_copy and os.path.abspath(latest_copy) != os.path.abspath(output_path):
        shutil.copyfile(output_path, latest_copy)

    print(f"投递汇报已生成: {output_path}")
    print(f"  unique_total: {stats['unique_total']}")
    print(f"  success_total: {stats['success_total']}")
    print(f"  blocked_total: {stats['blocked_total']}")
    print(f"  fail_total: {stats['fail_total']}")
    print(f"  unknown_total: {stats['unknown_total']}")
    print(f"  legacy_unknown_total: {stats['legacy_unknown_total']}")
    print(f"  duplicate_removed: {stats['duplicate_removed']}")
    print(f"  industry_count: {stats['industry_count']}")
    print(f"  empty_industry_count: {stats['empty_industry_count']}")
    print(f"  current_total: {current_stats['current_total']}")
    print(f"  current_success: {current_stats['current_success']}")
    print(f"  current_blocked: {current_stats['current_blocked']}")
    print(f"  current_fail: {current_stats['current_fail']}")
    print(f"  current_unknown: {current_stats['current_unknown']}")
    print(f"  current_legacy_unknown: {current_stats['current_legacy_unknown']}")
    return output_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="投递汇报 HTML 生成")
    parser.add_argument("--progress", default="stream_progress.json", help="进度文件路径")
    parser.add_argument("--output", default="", help="输出 HTML 路径；缺省为时间戳文件")
    parser.add_argument("--run-id", default="", help="本次调用 run_id")
    args = parser.parse_args()
    output = args.output
    if not output:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output = f"投递汇总_{stamp}.html"
        seq = 1
        while os.path.exists(output):
            output = f"投递汇总_{stamp}_{seq:02d}.html"
            seq += 1
    result = build_report(args.progress, output, run_id=args.run_id or None, latest_copy="投递汇总.html")
    if not result:
        sys.exit(1)


if __name__ == "__main__":
    main()
