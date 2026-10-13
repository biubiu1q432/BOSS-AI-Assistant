#!/usr/bin/env python3
"""
模块 I+：批量投递加速器（Skill v5.6.6，2026-10-12）

目的：把「逐条 read → 写 decision.json → decide」的多轮 Agent 往返压缩成
     一次执行。规则引擎对 jd_to_read.json 中的每个候选做自动判定，
     - APPROVE/REJECT 直接执行内层循环（含真实投递）
     - 存疑岗位标记 NEED_REVIEW，转人工复核，绝不盲目投

★ 速度收益：一次调用完成整批读JD+决策+投递；Agent 只在「人工复核」环节介入。
★ 质量保障：规则保守——命中任一拒绝信号即 REJECT；无法确定的转 NEED_REVIEW；
  不靠标题猜测，HR 文本（含 JD）与画像（integration/algorithm/hybrid）双源校验。
★ v5.6.6 闭环：新增 --report 回测规则分布与投递健康度（references/rule_metrics.md），
  作为调 ROBOTICS_TOKENS / 排除词的信号，形成持续升级闭环。

用法（在 WORK_DIR 下、已 --step init + --step next-batch 准备 jd_to_read.json 后）：
    python scripts/batch_deliver.py --dry-run    # 预览判定（不投递）
    python scripts/batch_deliver.py --apply      # 真实批量投递
    python scripts/batch_deliver.py --report     # 仅回测规则指标，不投递

可传 --profile / --work-dir 与 serial_loop 同语义（经环境变量亦可）。
"""

import os
import sys
import json
import time
import argparse

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

# 复用三层循环主控制器的读卡+读JD+决策+投递全链路，保证进度/报告一致
import scripts.serial_loop as S
from scripts.profile_loader import USER_PROFILE, INTERNSHIP_ONLY, AVOID, PREFER, TARGET_CITIES
from scripts.webbridge_client import is_verification_page

# ═══════════════════════════════════════════════════════════
# 规则引擎（保守：拒绝信号命中即 REJECT；不确定转 NEED_REVIEW）
# ═══════════════════════════════════════════════════════════

# 1) 学历门槛（硬性要求硕士/博士，本科不符 → REJECT）
DEGREE_REJECT_TOKENS = [
    "全日制硕士", "硕士在读", "博士在读", "硕士及以上", "博士及以上",
    "硕士、博士", "硕士或以上学历", "要求硕士", "硕士学历", "博士学历",
]

# 2) 雇佣类型（非实习 → REJECT）
EMPLOYMENT_REJECT_TOKENS = [
    "校招", "校园招聘", "社招", "长期全职", "正式全职", "正式员工",
]

# 3) 与画像无关的方向/行业（→ REJECT）
ROLE_REJECT_TOKENS = [
    # 数据类（仅"纯数据"岗位拒绝；具身/机器人相关的数据采集、数据处理已放开，见下方说明）
    "数据挖掘", "数据标注", "数据平台",
    # 物业/职能
    "物业", "行政", "销售", "猎头", "运营", "客服", "电话客服", "基础服务",
    # 智驾测试支持（非算法研发）
    "回灌", "回归测试", "测试支持", "测试执行", "测试验证岗",
    "与机器人无关的测试",
]
# ★ v5.6.6+：移除「数据采集」「数据处理」的硬性拒绝。
#   具身智能 / 机器人相关的数据采集、数据处理算法岗位（命中 ROBOTICS_TOKENS）可接受（用户明确接收）；
#   纯数据岗（不命中 ROBOTICS_TOKENS）会因域匹配失败转 NEED_REVIEW 由人工复核，而非盲目投递。

# 4) 机器人/算法域核心词（命中 + 实习信号 → APPROVE 候选）
ROBOTICS_TOKENS = [
    "ROS", "ROS2", "SLAM", "感知", "规控", "PnC", "运动控制", "标定",
    "嵌入式", "具身", "机械臂", "机器人", "控制算法", "系统集成",
    "真机", "SDK", "导航", "定位", "云台", "IMU", "电机", "部署",
    "控制", "二次开发", "轨迹规划", "视觉", "控制工程",
]

# 5) 实习信号（标题或 JD 含其一即确认实习岗）
# ★ v5.6.7 修正：移除 "本科及以上" —— 它是学历门槛（"本科及以上学历"几乎出现在所有全职JD），
#   误当实习信号会导致全职社招岗被错判为实习并盲目投递。实习确认仅依赖：实习/实习生/在读/日常实习/校招实习。
INTERN_TOKENS = ["实习", "实习生", "在读", "日常实习", "校招实习"]

# 5b) 否定实习信号（明确"无实习/非实习"等表述 → 不确认实习，转人工复核，覆盖子串误命中）
NEG_INTERN_TOKENS = ["无实习", "非实习", "不需实习", "不需要实习", "不招实习", "不接受实习"]


def _has(text, tokens):
    return any(tok in text for tok in tokens)


def screen(job, jd_text):
    """返回 (verdict, reason)。verdict ∈ {APPROVE, REJECT, NEED_REVIEW}。"""
    title = (job.get("title") or "")
    company = (job.get("company") or "")
    city = (job.get("city") or "")
    text = " ".join([title, company, jd_text or ""])
    # ★ v5.6.7 修正：BOSS JD 偶用康熙部首异体字（如「⼠」U+2F2F 代替「士」U+58EB），
    #   导致学历门槛/域匹配漏匹配。归一化常见异体字，避免硬性硕士岗被误投或域词漏判。
    text = text.replace("⼠", "士")

    # —— 城市校验（跨城直接 REJECT，不投）——
    if city and TARGET_CITIES and city not in TARGET_CITIES:
        return "REJECT", f"跨城岗位（{city} 不在目标城市 {TARGET_CITIES}）"

    # —— 学历门槛：仅"硬性"硕士/博士才拒；优先/可放宽/本科及以上 不算硬性（避免误杀本科生可投的实习岗）——
    # ★ v5.6.7：实测多份 JD 为「硕士及以上（优秀本科生可放宽）」「本科及以上，硕士优先」，本科生实际可投；
    #   旧逻辑把"硕士及以上/硕士学历"当硬性直接拒，属过度拒绝。改为：
    #   含 本科及以上 / 可放宽 / 优秀本科生 → 不卡；其余含硬性硕士/博士词且无"优先/放宽"才拒。
    # —— 学历门槛：用户明确「硕士也无所谓，投就对了」(2026-10-12) ——
    #   不再因硬性硕士/博士要求拒绝岗位；DEGREE_REJECT_TOKENS 保留定义但本函数不再据此 REJECT。
    #   （前置的 ⼠→士 异体字归一化仍生效，以稳定域匹配。）

    # —— 实习信号预判（用于豁免雇佣类型误杀）——
    is_intern = _has(text, INTERN_TOKENS)

    # —— 雇佣类型：仅当"完全无实习信号"时，校招/社招/正式全职 → REJECT ——
    # ★ v5.6.7：BOSS 常见组合标签「校招/实习/社招」同时含 校招+实习，实为面向实习生的岗位，
    #   不应因含"校招/社招"被误杀；只有完全无实习信号（纯校招/社招/正式全职）才拒，避免漏掉好实习岗。
    if _has(text, EMPLOYMENT_REJECT_TOKENS) and not is_intern:
        return "REJECT", "非实习岗（校招/社招/正式全职，且无任何实习信号）"

    # —— 方向/行业排斥：数据类/物业/职能/智驾测试支持 → REJECT ——
    # ★ v5.6.7：数据挖掘/数据标注/数据平台 若同时命中机器人/算法域词，视为算法岗的辅助数据工作，不硬拒
    #   （用户明确接收具身/算法相关的数据采集类岗位；纯数据岗仍拒）。
    hit_role = [t for t in ROLE_REJECT_TOKENS if t in text]
    if hit_role:
        DATA_TOKENS = {"数据挖掘", "数据标注", "数据平台"}
        effective = [t for t in hit_role if not (t in DATA_TOKENS and _has(text, ROBOTICS_TOKENS))]
        if effective:
            return "REJECT", f"命中排斥方向：{effective}"

    # —— 自动驾驶域谨慎处理：仅"纯智驾岗（无机器人域词）"且无 SLAM/定位/感知核心研发才转人工 ——
    # ★ v5.6.7：机器人/具身岗常"顺带"提及智驾术语（如机器人导航、具身+智驾），属机器人域而非纯智驾，
    #   不应因 incidental 智驾词被误送人工。仅当"无机器人域核心词"的纯智驾岗才转人工。
    is_ad = _has(text, ["自动驾驶", "无人驾驶", "智能驾驶", "智驾"])
    if is_ad and not _has(text, ROBOTICS_TOKENS) and not _has(text, ["SLAM", "定位", "感知", "规控", "PnC"]):
        return "NEED_REVIEW", "自动驾驶域但非 SLAM/感知/定位核心研发，请人工判断"

    # —— 否定实习信号优先：明确"无实习/非实习"等表述 → 无法确认实习，转人工 ——
    if _has(text, NEG_INTERN_TOKENS):
        return "NEED_REVIEW", "JD 含否定实习表述（无实习/非实习等），需人工确认是否实习岗"

    # —— 实习信号确认 ——
    is_intern = _has(text, INTERN_TOKENS)
    if not is_intern and "实习" not in title:
        # 标题无实习标记且无在读/本科信号 → 无法确认实习，转人工
        return "NEED_REVIEW", "标题无实习标记且 JD 未确认在读/本科，需人工确认实习身份"

    # —— 域匹配 ——
    hit_domain = [t for t in ROBOTICS_TOKENS if t in text]
    if not hit_domain:
        return "NEED_REVIEW", "未命中机器人/算法域核心词，需人工判断方向匹配度"

    return "APPROVE", f"实习岗 + 机器人域命中{hit_domain[:4]}"


def report_metrics():
    """★ v5.6.6 闭环反馈：回测规则引擎表现，输出可调优信号。

    指标：
      - 本轮 batch_deliver_log.json 的 verdict 分布（APPROVE/REJECT/NEED_REVIEW/READ_FAILED/SKIP）
        → 自动化覆盖率 = (APPROVE+REJECT) / (APPROVE+REJECT+NEED_REVIEW)；NEED_REVIEW 负担率。
      - stream_progress.json 投递健康度（成功/失败、成功率）。
    结果追加写入 references/rule_metrics.md，供人工调 ROBOTICS_TOKENS / 排除词。
    """
    from scripts.webbridge_client import ProgressManager
    sp_path = os.path.join(S.WORK_DIR, "stream_progress.json")
    pm = ProgressManager(sp_path).load()
    stats = pm.stats()

    log_path = os.path.join(S.WORK_DIR, "batch_deliver_log.json")
    dist = {"APPROVE": 0, "REJECT": 0, "NEED_REVIEW": 0, "READ_FAILED": 0, "SKIP": 0, "OTHER": 0}
    if os.path.exists(log_path):
        try:
            for rec in json.load(open(log_path, encoding="utf-8")):
                v = (rec.get("verdict") or "OTHER")
                dist[v] = dist.get(v, 0) + 1
        except Exception:
            pass

    total_screen = dist["APPROVE"] + dist["REJECT"] + dist["NEED_REVIEW"]
    auto_cov = (dist["APPROVE"] + dist["REJECT"]) / total_screen if total_screen else 0.0
    review_burden = dist["NEED_REVIEW"] / total_screen if total_screen else 0.0
    success = stats.get("success_total", 0)
    failed = stats.get("failed", 0)
    delivery_rate = success / (success + failed) if (success + failed) else 0.0

    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[指标] 时间 {ts} | profile={os.path.basename(S.USER_PROFILE_FILE)}")
    print(f"[指标] 规则分布 APPROVE={dist['APPROVE']} REJECT={dist['REJECT']} "
          f"NEED_REVIEW={dist['NEED_REVIEW']} READ_FAILED={dist['READ_FAILED']} SKIP={dist['SKIP']}")
    print(f"[指标] 自动化覆盖率={auto_cov*100:.1f}%  NEED_REVIEW负担={review_burden*100:.1f}%")
    print(f"[指标] 累计投递 成功={success} 失败={failed} 成功率={delivery_rate*100:.1f}%")

    metric_line = (f"| {ts} | APPROVE {dist['APPROVE']} / REJECT {dist['REJECT']} / "
                  f"NEED_REVIEW {dist['NEED_REVIEW']} / READ_FAILED {dist['READ_FAILED']} / SKIP {dist['SKIP']} "
                  f"| 自动化 {auto_cov*100:.1f}% / 负担 {review_burden*100:.1f}% "
                  f"| 投递成功 {success} / 失败 {failed} / 率 {delivery_rate*100:.1f}% |\n")
    md = os.path.join(SKILL_DIR, "references", "rule_metrics.md")
    header = ("# 规则引擎回测指标（v5.6.6 闭环反馈）\n\n"
              "- 用途：每次批量运行后回测 screen() 表现，作为调 ROBOTICS_TOKENS / 排除词的信号。\n"
              "- 关联模块：batch_deliver.py(I+) / webbridge_client.ProgressManager\n"
              "- 维护状态：v5.6.6 新增\n\n"
              "| 时间 | 规则分布 | 自动化覆盖率 / NEED_REVIEW负担 | 累计投递健康度 |\n"
              "|------|----------|------------------------------|----------------|\n")
    if not os.path.exists(md):
        with open(md, "w", encoding="utf-8") as f:
            f.write(header)
    with open(md, "a", encoding="utf-8") as f:
        f.write(metric_line)
    print(f"[指标] 已追加至 {md}")


def main():
    ap = argparse.ArgumentParser(description="批量投递加速器（v5.6.6）")
    ap.add_argument("--apply", action="store_true", help="真实投递；默认仅 dry-run 预览")
    ap.add_argument("--jd-file", default=S.JD_TO_READ, help="jd_to_read.json 路径")
    ap.add_argument("--report", action="store_true", help="★ v5.6.6 仅输出规则回测指标（APPROVE/REJECT/NEED_REVIEW 分布 + 投递健康度），不投递")
    args = ap.parse_args()

    if args.report:
        report_metrics()
        return

    dry_run = not args.apply

    if not os.path.exists(args.jd_file):
        print(f"[批量] 错误：{args.jd_file} 不存在，请先 --step next-batch 生成")
        sys.exit(1)

    with open(args.jd_file, encoding="utf-8") as f:
        jobs = json.load(f)
    if jobs and "page_order" in jobs[0]:
        jobs.sort(key=lambda x: x.get("page_order", 0))

    print(f"[批量] 加载候选 {len(jobs)} 条 | dry-run={dry_run} | profile={os.path.basename(S.USER_PROFILE_FILE)}")
    print(f"[批量] 目标城市 {TARGET_CITIES} | 仅实习={INTERNSHIP_ONLY}")

    # —— 防重复：载入已投递记录，跳过已投岗位（避免重跑 jd_to_read 时二次真实投递）——
    delivered_ids = set()
    sp_path = os.path.join(S.WORK_DIR, "stream_progress.json")
    if os.path.exists(sp_path):
        try:
            with open(sp_path, encoding="utf-8") as f:
                sp = json.load(f)
            for key in ("delivered", "failed"):
                for rec in (sp.get(key) or []):
                    if rec.get("jobId"):
                        delivered_ids.add(rec["jobId"])
        except Exception:
            pass
    print(f"[批量] 已投递记录 {len(delivered_ids)} 条（来自 stream_progress.json，将跳过防重复）")
    print("=" * 70)

    approve, reject, review, fail, skip = 0, 0, 0, 0, 0
    log = []
    approved_companies = set()  # 同公司重复岗位拦截（防骚扰）
    consecutive_read_fail = 0   # ★ v5.6.7 连续读失败计数（区分"卡片不在视口"与"页面被风控拦截"）

    for i, job in enumerate(jobs, 1):
        title0 = job.get("title", "")

        # 0.1) ★ v5.6.7 风控拦截检测：命中 BOSS 安全验证页 → 立即停止整批。
        #   验证页上一张岗位卡都没有，继续跑只会全部 READ_FAILED 并加重风控。
        #   此时必须停下交回用户人工完成验证，自动化不得绕过。
        blocked, b_url, b_title = is_verification_page()
        if blocked:
            print("=" * 70)
            print(f"[批量] ⛔ 检测到 BOSS 安全验证/风控拦截，立即停止本批")
            print(f"[批量]    URL  : {b_url}")
            print(f"[批量]    标题 : {b_title}")
            print(f"[批量]    进度 : 已处理 {i-1}/{len(jobs)} 条")
            print(f"[批量] ★ 请在浏览器中人工完成安全验证后，再重新 --step init 继续")
            print(f"[批量] ★ 严禁脚本自行绕过验证（账号安全风险）")
            print("=" * 70)
            break

        # 0) 同公司重复拦截：本轮已投过该公司的岗位 → 直接 REJECT
        company = (job.get("company") or "")
        if company and company in approved_companies:
            reject += 1
            print(f"[{i:>3}] REJECT (dup): {title0[:26]} | 同公司重复岗位，防骚扰")
            log.append({"index": i, "title": title0, "verdict": "REJECT", "reason": "同公司重复岗位，防骚扰"})
            continue

        # 0.5) 已投递跳过：命中 stream_progress 记录 → SKIP 防重复真实投递
        jid = job.get("jobId") or ""
        if jid and jid in delivered_ids:
            skip += 1
            print(f"[{i:>3}] SKIP (delivered): {title0[:26]} | 已在投递记录中，防重复")
            log.append({"index": i, "title": title0, "verdict": "SKIP", "reason": "已在 stream_progress 投递记录中，防重复"})
            continue

        # 1) 点击卡片 + 读 JD（写入 current_jd.json）
        ok = S.step_read(i)
        if not ok:
            print(f"[{i:>3}] READ_FAILED: {job.get('title','')[:24]}")
            fail += 1
            consecutive_read_fail += 1
            log.append({"index": i, "title": job.get("title"), "verdict": "READ_FAILED"})

            # ★ v5.6.7：连续 3 条读不到 JD 时，先判定是不是被风控拦截/页面漂移，
            #   是则立刻停手；否则提示"虚拟滚动窗口已过"，建议重建候选池再投。
            if consecutive_read_fail >= 3:
                blocked, b_url, b_title = is_verification_page()
                if blocked:
                    print("=" * 70)
                    print(f"[批量] ⛔ 连续读失败且命中安全验证页，立即停止")
                    print(f"[批量]    URL  : {b_url}")
                    print(f"[批量]    标题 : {b_title}")
                    print(f"[批量] ★ 请人工完成验证后重新 --step init 继续，不要绕过")
                    print("=" * 70)
                    break
                print(f"[批量] ⚠ 连续 {consecutive_read_fail} 条 READ_FAILED：多为虚拟滚动窗口已过，"
                      f"卡片已不在 DOM。建议 --step refresh 后重建候选池再投。")
            continue
        consecutive_read_fail = 0

        with open(S.CURRENT_JD, encoding="utf-8") as f:
            cur = json.load(f)
        jd_text = cur.get("jd_text", "") or ""

        verdict, reason = screen(job, jd_text)
        title = job.get("title", "")

        # 命中 APPROVE 且是本次新投公司 → 记录，供同公司重复拦截
        if verdict == "APPROVE" and company:
            approved_companies.add(company)

        if verdict == "NEED_REVIEW":
            review += 1
            print(f"[{i:>3}] ⚠ NEED_REVIEW: {title[:26]} | {reason}")
            log.append({"index": i, "title": title, "verdict": verdict, "reason": reason})
            continue

        if dry_run:
            tag = "APPROVE" if verdict == "APPROVE" else "REJECT"
            print(f"[{i:>3}] {tag:>7} (dry): {title[:26]} | {reason}")
            if verdict == "APPROVE":
                approve += 1
            else:
                reject += 1
            log.append({"index": i, "title": title, "verdict": verdict, "reason": reason})
            continue

        # 真实执行
        with open(S.DECISION_FILE, "w", encoding="utf-8") as f:
            json.dump({"decision": verdict, "reason": reason}, f, ensure_ascii=False, indent=2)
        S.step_decide(i)
        if verdict == "APPROVE":
            approve += 1
        else:
            reject += 1
        log.append({"index": i, "title": title, "verdict": verdict, "reason": reason})

    print("=" * 70)
    print(f"[批量] 汇总：APPROVE={approve}  REJECT={reject}  NEED_REVIEW={review}  READ_FAILED={fail}  SKIP={skip}"
          + ("  (dry-run 未实际投递)" if dry_run else "  (已执行)"))
    if not dry_run and (approve or reject):
        print("[批量] 触发 finish 生成汇总报告...")
        S.step_finish()

    log_path = os.path.join(S.WORK_DIR, "batch_deliver_log.json")
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)
    print(f"[批量] 决策日志：{log_path}")


if __name__ == "__main__":
    main()
