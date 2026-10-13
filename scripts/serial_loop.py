#!/usr/bin/env python3
"""
模块 I：三层循环主控制器（Skill v5.6.1，2026-10-12）

流程：页面初始化 → 分批提取 → 逐条 read → Agent 决策 → decide → 汇报。
命令：--step init / next-batch / read / decide / evolve / status / finish。
信号文件：jd_to_read.json、current_jd.json、decision.json、serial_progress.json。
累计投递记录：stream_progress.json；历史表面缓存：surface_cache.json。

v5.6 改进：--step init 创建 run_id 作为本次调用边界；每次 finish 生成
时间戳报告 投递汇总_YYYYMMDD_HHMMSS.html，不覆盖历史文件；status/finish/自动收尾
共用同一统计函数，终端与 HTML 字段一致。
"""

import json
import os
import sys
import time
import argparse
import atexit
import uuid
from datetime import datetime

# Windows 控制台统一使用 UTF-8，避免中文/符号输出触发 GBK 崩溃
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import WORK_DIR, CITY_CODE as _PROFILE_CITY, USER_PROFILE_FILE
try:
    from scripts.profile_loader import PROFILE_NAME
except ImportError:
    PROFILE_NAME = ""

# 信号文件路径
JD_TO_READ = os.path.join(WORK_DIR, "jd_to_read.json")
CURRENT_JD = os.path.join(WORK_DIR, "current_jd.json")
DECISION_FILE = os.path.join(WORK_DIR, "decision.json")
SERIAL_PROGRESS = os.path.join(WORK_DIR, "serial_progress.json")
SURFACE_CACHE = os.path.join(WORK_DIR, "surface_cache.json")
PROGRESS_FILE = os.path.join(WORK_DIR, "stream_progress.json")

from scripts.webbridge_client import (
    SESSION, evaluate, health_check, ensure_active_tab,
    ProgressManager, is_verification_page,
)
from scripts.jd_reader import read_jd_for_job
from scripts.deliver_engine import deliver_inplace, check_delivery_target, DAILY_TARGET
from scripts.recommend_loader import (
    navigate_to_recommend, scroll_next_batch, is_exhausted, get_state, reset_state,
    refresh_feed,
)
from scripts.keyword_evolver import (
    evaluate_page_results, get_next_keyword, add_evolved_keyword,
    mark_keyword_tried, navigate_to_search, start_new_page,
    load_page_state, save_page_state, reset_page_state,
)
from scripts.report_builder import build_report


# ═══════════════════════════════════════════════════════════
# 串行进度管理
# ═══════════════════════════════════════════════════════════

def _empty_serial_progress():
    return {
        "current_index": 0,
        "total": 0,
        "processed": [],
        "results": [],
        "batch_num": 0,
        "fatal_stop": False,
        "fatal_reason": "",
        "target_met": False,
        "run_id": "",
        "started_at": "",
        "profile_file": "",
        "channel": "algorithm_channel",
        "finished_at": "",
        "last_report": "",
    }


def _safe_clear(path):
    """安全重置信号文件：写入 null JSON 替代 os.remove（避免安全拦截）"""
    with open(path, 'w', encoding='utf-8') as f:
        f.write('null')


def load_serial_progress():
    """加载串行进度"""
    if os.path.exists(SERIAL_PROGRESS):
        with open(SERIAL_PROGRESS, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if data is None:
                return {
                    "current_index": 0,
                    "total": 0,
                    "processed": [],
                    "results": [],
                    "batch_num": 0,
                    "fatal_stop": False,
                    "fatal_reason": "",
                    "target_met": False,
                }
            return data
    return {
        "current_index": 0,
        "total": 0,
        "processed": [],
        "results": [],
        "batch_num": 0,
        "fatal_stop": False,
        "fatal_reason": "",
        "target_met": False,
    }


def save_serial_progress(progress):
    """保存串行进度"""
    with open(SERIAL_PROGRESS, 'w', encoding='utf-8') as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)



def _now_text():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_run_state(progress=None, force_new=False):
    """保证 serial_progress.json 带有本次调用 run_id。"""
    progress = progress or load_serial_progress()
    if force_new or not progress.get("run_id"):
        progress["run_id"] = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        progress["started_at"] = _now_text()
        progress["profile_file"] = USER_PROFILE_FILE
        progress["channel"] = "algorithm_channel"
        progress["results"] = []
        progress["processed"] = []
        progress["current_index"] = 0
        progress["fatal_stop"] = False
        progress["fatal_reason"] = ""
        progress["target_met"] = False
        save_serial_progress(progress)
    return progress


def unique_timestamp_report_path(work_dir=None):
    """生成本地时间戳报告路径，同秒冲突自动追加序号。"""
    work_dir = work_dir or WORK_DIR
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(work_dir, f"投递汇总_{stamp}.html")
    seq = 1
    while os.path.exists(path):
        path = os.path.join(work_dir, f"投递汇总_{stamp}_{seq:02d}.html")
        seq += 1
    return path


def collect_unified_stats(run_id=None):
    """status / finish / 自动收尾共用的统计口径。"""
    pm = ProgressManager(PROGRESS_FILE)
    pm.load()
    cumulative = pm.stats()
    serial = load_serial_progress()
    run_id = run_id or serial.get("run_id") or ""
    records = list(pm.data.get("delivered", [])) + list(pm.data.get("failed", []))
    current = [r for r in records if run_id and r.get("run_id") == run_id]
    def count_status(items, status):
        return sum(1 for item in items if pm.classify_status(item) == status)
    current_industries = sorted({j.get("industry") for j in current if j.get("result") == "success" and j.get("industry")})
    current_stats = {
        "run_id": run_id,
        "started_at": serial.get("started_at", ""),
        "generated_at": _now_text(),
        "profile_file": serial.get("profile_file", USER_PROFILE_FILE),
        "channel": serial.get("channel", "algorithm_channel"),
        "current_total": len(current),
        "current_success": count_status(current, "success"),
        "current_blocked": count_status(current, "blocked"),
        "current_fail": count_status(current, "fail"),
        "current_unknown": count_status(current, "unknown"),
        "current_legacy_unknown": count_status(current, "legacy_unknown"),
        "current_industries": current_industries,
        "current_industry_count": len(current_industries),
        "current_records": current,
    }
    return pm, cumulative, current_stats, serial


def print_unified_stats(cumulative, current_stats, title="统计"):
    print(f"{title}")
    print(f"run_id: {current_stats.get('run_id') or '-'}")
    print(f"运行开始: {current_stats.get('started_at') or '-'}")
    print(f"报告生成: {current_stats.get('generated_at')}")
    print(f"累计唯一岗位: {cumulative['unique_total']}")
    print(f"累计 success: {cumulative['success_total']}")
    print(f"累计 blocked: {cumulative['blocked_total']}")
    print(f"累计 fail: {cumulative['fail_total']}")
    print(f"累计 unknown: {cumulative['unknown_total']}")
    print(f"累计 legacy_unknown: {cumulative['legacy_unknown_total']}")
    print(f"重复合并数: {cumulative['duplicate_removed']}")
    print(f"覆盖行业: {cumulative['industry_count']}")
    print(f"空行业成功数: {cumulative['empty_industry_count']}")
    print(f"本次调用处理数: {current_stats['current_total']}")
    print(f"本次 success: {current_stats['current_success']}")
    print(f"本次 blocked: {current_stats['current_blocked']}")
    print(f"本次 fail: {current_stats['current_fail']}")
    print(f"本次 unknown: {current_stats['current_unknown']}")
    print(f"本次 legacy_unknown: {current_stats['current_legacy_unknown']}")
    print(f"本次覆盖行业: {current_stats['current_industry_count']}")


def load_jobs():
    """加载 jd_to_read.json"""
    if not os.path.exists(JD_TO_READ):
        return []
    with open(JD_TO_READ, 'r', encoding='utf-8') as f:
        jobs = json.load(f)
    # 顺序守卫: 按 page_order 排序
    if jobs and 'page_order' in jobs[0]:
        jobs.sort(key=lambda x: x.get('page_order', 0))
    return jobs


# ═══════════════════════════════════════════════════════════
# ★ 外层循环: 页面级
# ═══════════════════════════════════════════════════════════

def step_init(city_code=_PROFILE_CITY):
    """★ 流程图: 开始 → 检查环境 → 定位到职位推荐页

    1. 检查 WebBridge 环境
    2. 重置所有状态（分批状态 + 页面状态）
    3. 导航到推荐页
    4. 提示下一步: --step next-batch
    """
    print("[初始化] ═══ v5.0 三层循环投递系统启动 ═══")

    # 1. 环境检查
    if not health_check():
        print("[初始化] ERROR: WebBridge 不可达")
        print("[初始化] 请先运行: python env_check.py")
        return False

    if not ensure_active_tab():
        print("[初始化] ERROR: 无法建立标签页")
        return False

    print("[初始化] WebBridge 环境正常")

    # 2. 重置状态（★ v5.6.7：init 开新一轮，刷新轮次计数一并清零）
    reset_state(full=True)   # 重置分批状态 (batch_state.json)
    reset_page_state()       # 重置页面状态 (page_state.json)

    # 清理旧的串行进度
    _safe_clear(SERIAL_PROGRESS)
    _safe_clear(JD_TO_READ)

    # 创建本次调用边界，不清理累计 stream_progress.json
    run_state = ensure_run_state(force_new=True)
    print(f"[初始化] run_id={run_state['run_id']}")
    print(f"[初始化] started_at={run_state['started_at']}")
    print(f"[初始化] profile_file={run_state['profile_file']}")

    # 3. 导航到推荐页
    print("[初始化] 导航到推荐页...")
    page_state = load_page_state()
    page_state['page_type'] = 'algorithm_channel'
    page_state['current_keyword'] = ''
    page_state['pages_processed'] = 1

    # 记录本页面开始时的投递数
    pm = ProgressManager(PROGRESS_FILE)
    pm.load()
    page_state['page_start_delivered'] = len(getattr(pm, 'delivered', []))
    save_page_state(page_state)

    if not navigate_to_recommend(city_code):
        print("[初始化] ERROR: 导航到推荐页失败")
        return False

    # 4. 提示下一步
    print(f"\n[初始化] ★ 推荐页已就绪")
    print(f"[初始化] ★ 投递目标: {DAILY_TARGET} 份")
    print(f"[初始化] ★ 下一步: python serial_loop.py --step next-batch")
    print(f"[初始化] ★ 然后AI对本批岗位做语义初筛，逐条 --step read/decide")

    return True


def step_evolve(city_code=_PROFILE_CITY):
    """★ 外层循环: 页面穷尽后 → AI评估 → 新关键词 → 搜索页

    流程图: AI评估当前页面投递结果 → 找出新的关键词 → 以新关键词搜索 → 定位到搜索结果页

    1. 评估当前页面的投递结果
    2. 获取下一个未尝试的搜索关键词
    3. 如果有可用关键词 → 导航到搜索页 → 提示 --step next-batch
    4. 如果无可用关键词 → 提示AI生成新关键词 (--step add-keyword)
    5. 如果投递目标已达标 → 提示 --step finish
    """
    print("[进化] ═══ 外层循环: 页面穷尽，开始关键词进化 ═══")

    # 0. 先检查投递目标是否已达标
    target_check = check_delivery_target(PROGRESS_FILE)
    if target_check["target_met"]:
        print(f"[进化] ★ 投递目标 {DAILY_TARGET} 份已达标！无需继续搜索")
        # ★ 自动触发 finish，确保 100% 生成投递汇总页面
        print(f"[进化] ★ 自动生成投递汇总...")
        step_finish()
        return True

    # 1. 评估当前页面投递结果
    print(f"\n[进化] 步骤1: 评估当前页面投递结果")
    eval_result = evaluate_page_results()

    print(f"\n[进化] 评估结果:")
    print(f"  本页面投递: {eval_result['page_delivered']} 份")
    print(f"  累计投递: {eval_result['total_delivered']} 份")
    print(f"  目标: {DAILY_TARGET} 份 (还差 {target_check['remaining']})")
    print(f"  行业分布: {eval_result['industry_distribution']}")
    print(f"  高频标题词: {eval_result['title_keywords']}")

    # 2. 获取下一个关键词
    print(f"\n[进化] 步骤2: 获取下一个搜索关键词")
    next_kw = get_next_keyword()

    if next_kw:
        print(f"[进化] 找到可用关键词: {next_kw}")
        print(f"\n[进化] ★ AI请确认是否使用此关键词，或用 --step add-keyword 添加自定义关键词")
        print(f"[进化] ★ 确认后运行:")
        print(f"  python serial_loop.py --step navigate-search --keyword \"{next_kw}\"")
        return True
    else:
        print(f"[进化] ⚠ 预定义关键词已全部用完！")
        print(f"[进化] ★ AI需要基于投递结果生成新的搜索关键词")
        print(f"[进化] ★ 参考信息:")
        print(f"  - 成功投递的行业分布: {eval_result['industry_distribution']}")
        print(f"  - 高频标题关键词: {eval_result['title_keywords']}")
        print(f"  - 用户画像偏好: 见 user_profile.json")
        print(f"\n[进化] ★ AI生成新关键词后运行:")
        print(f"  python serial_loop.py --step add-keyword --keyword \"新关键词\"")
        print(f"  python serial_loop.py --step navigate-search --keyword \"新关键词\"")
        return False


def step_navigate_search(keyword, city_code=_PROFILE_CITY):
    """导航到搜索结果页（外层循环的页面切换）

    流程图: 以新关键词搜索岗位 → 定位到搜索结果页 → 回到"当前页面处理开始"
    """
    print(f"[搜索] ═══ 导航到搜索结果页: {keyword} ═══")

    if not health_check():
        print("[搜索] ERROR: WebBridge 不可达")
        return False

    # 导航到搜索页
    ok, clean_kw = navigate_to_search(keyword, city_code)
    if not ok:
        print(f"[搜索] ERROR: 导航到搜索页失败 (关键词: {keyword})")
        print(f"[搜索] 该关键词可能无搜索结果，请尝试其他关键词")
        return False

    # 标记关键词为已尝试（使用清洗后的关键词）
    mark_keyword_tried(clean_kw)

    # 更新页面状态
    page_state = load_page_state()
    page_state['page_type'] = 'search'
    page_state['current_keyword'] = keyword
    page_state['pages_processed'] = page_state.get('pages_processed', 0) + 1

    # 记录本页面开始时的投递数
    pm = ProgressManager(PROGRESS_FILE)
    pm.load()
    page_state['page_start_delivered'] = len(getattr(pm, 'delivered', []))
    save_page_state(page_state)

    # 重置分批状态（新页面从0开始）
    reset_state()

    print(f"\n[搜索] ★ 搜索结果页已就绪")
    print(f"[搜索] ★ 页面类型: 搜索页")
    print(f"[搜索] ★ 关键词: {keyword}")
    print(f"[搜索] ★ 已处理页面数: {page_state['pages_processed']}")
    print(f"[搜索] ★ 下一步: python serial_loop.py --step next-batch")

    return True


def step_add_keyword(keyword):
    """添加AI进化生成的新关键词"""
    add_evolved_keyword(keyword)
    print(f"[进化] 已添加新关键词: {keyword}")
    print(f"[进化] 下一步: python serial_loop.py --step navigate-search --keyword \"{keyword}\"")


# ═══════════════════════════════════════════════════════════
# ★ 中层循环: 分批级
# ═══════════════════════════════════════════════════════════

def step_next_batch():
    """★ 中层循环: 滚动加载下一批50条

    流程图: 当前页面是否还有更多岗位？→ 是 → 下拉加载一批 → 提取 → AI初筛

    1. 检查页面是否已穷尽
    2. 如果穷尽 → 提示 --step evolve (进入外层循环)
    3. 如果未穷尽 → 滚动加载下一批 → 增量提取 → append缓存
    4. 输出本批岗位列表供AI初筛
    """
    if not health_check():
        print("ERROR: WebBridge 不可达")
        return False

    # 检查是否已穷尽
    if is_exhausted():
        state = get_state()
        reason = state.get('exhaust_reason', '?')
        print(f"[分批] ★ 当前页面已穷尽: {reason}")
        print(f"[分批] 累计提取 {state.get('total_extracted', 0)} 条 / 已滚动 {state.get('total_scrolls', 0)} 次")

        # ★ v5.6.7 修正：滚动是主要供给方式（一路往下滚会持续出新岗位，实测可到 330 张）。
        #   因此"穷尽"要先分清是【全局滚动上限用尽】还是【真的滚到底/不再出货】：
        #     - 滚动次数已达 MAX_TOTAL_SCROLLS → 只是本轮配额用尽，再开一轮即可
        #     - 命中底部标记「没有更多了」/连续无新增 → 才考虑 --step refresh 兜底
        scrolls = state.get('total_scrolls', 0) or 0
        if scrolls >= 80:
            print(f"[分批] ★ 原因: 已达单轮滚动上限({scrolls} 次)，不是没岗位")
            print(f"[分批] ★ 下一步: --step next-batch 会继续（或重跑 --step init 开新一轮再滚）")
        else:
            print(f"[分批] ★ 注意: 滚动确实不再出货（{reason}），才轮到刷新兜底")
            print(f"[分批] ★ 下一步(兜底): python serial_loop.py --step refresh")
            print(f"[分批] ★ 连续多轮 refresh 无新货才算真穷尽 → --step finish 汇报")
        return False

    # 滚动加载下一批
    result = scroll_next_batch(cache_file=SURFACE_CACHE)

    if result["new_count"] > 0:
        print(f"\n[分批] ═══ 第{result['batch_num']}批加载完成 ═══")
        print(f"[分批] 新增: {result['new_count']} 条")
        print(f"[分批] 累计提取: {result['total_extracted']} 条")
        print(f"[分批] 页面总卡片: {result['total_cards']} 条")
        print(f"[分批] 穷尽状态: {result['exhausted']}")

        # 输出本批岗位列表
        page_state = load_page_state()
        page_type = page_state.get('page_type', 'recommend')
        current_kw = page_state.get('current_keyword', '')

        print(f"\n{'='*60}")
        print(f"本批岗位列表 (供AI语义初筛)")
        print(f"页面类型: {page_type}" + (f" | 关键词: {current_kw}" if current_kw else ""))
        print(f"{'='*60}")
        for j in result["new_jobs"]:
            po = j.get('page_order', '?')
            title = j.get('title', '')[:25]
            salary = j.get('salary', '')[:12]
            company = j.get('company', '')[:15]
            industry = j.get('industry', '')[:12]
            print(f"  [{po:>3}] {title:<25} {salary:<12} {company:<15} {industry}")

        print(f"\n[分批] ★ AI请对本批{result['new_count']}条做语义初筛")
        print(f"[分批] ★ 筛选结果追加到 jd_to_read.json (保持page_order顺序)")
        print(f"[分批] ★ 然后逐条:")
        print(f"  python serial_loop.py --step read --index N")
        print(f"  python serial_loop.py --step decide --index N")

        # 更新进度
        progress = load_serial_progress()
        progress["batch_num"] = result["batch_num"]
        progress["total"] = result["total_extracted"]
        save_serial_progress(progress)
    else:
        print(f"[分批] 本批无新岗位")
        if result["exhausted"]:
            print(f"[分批] ★ 本屏已滚完 → 补量: python serial_loop.py --step refresh")
            print(f"[分批] ★ （不要用 evolve 走搜索页：搜索页点卡片会跳转 job_detail，step_read 读不到 JD）")

    return result["new_count"] > 0


def step_refresh(city_code=_PROFILE_CITY):
    """★ v5.6.7 中层循环补量: 刷新频道信息流，取 BOSS 换上来的新一批岗位

    背景（2026-10-13 用户实测指出）：同一个频道（如「算法工程师(广州)」）每次重新
    进入都会换一批岗位，供给是可持续的。旧版只有"滚动"一种补量手段，滚到底就判
    "穷尽"，导致 Agent 误以为没有岗位，进而越权换频道/换城市/走搜索页。

    规则：
      - 只在【当前频道】刷新，绝不动 CHANNEL_TAB / CITY_CODE
      - 连续 MAX_NO_NEW_ROUNDS 轮无新货 → 真穷尽 → 停止并向用户汇报
    """
    if not health_check():
        print("ERROR: WebBridge 不可达")
        return False

    if not ensure_active_tab():
        print("ERROR: 无法建立标签页")
        return False

    result = refresh_feed(city_code)

    if not result.get("ok"):
        print(f"[刷新] 失败: {result.get('reason')}")
        print(f"[刷新] ★ 可能是页面未渲染完成，可重跑 --step refresh；连续失败请勿换频道，先向用户汇报")
        return False

    print(f"\n[刷新] ═══ 第{result['refresh_round']}轮结果 ═══")
    print(f"[刷新] 本页岗位: {result['current_ids']} 条")
    print(f"[刷新] 去重后新货: {result['new_count']} 条")

    if result["truly_exhausted"]:
        print(f"\n[刷新] ★★★ 真穷尽：连续 {result['no_new_rounds']} 轮刷新无新岗位 ★★★")
        print(f"[刷新] ★ 请停止补量，运行 --step finish 生成汇报并向用户汇报")
        print(f"[刷新] ★ 严禁自行换频道 / 换城市 / 走搜索页（需用户明确指示）")
        return False

    if result["new_count"] == 0:
        print(f"[刷新] 本轮无新货（连续 {result['no_new_rounds']} 轮）")
        print(f"[刷新] ★ 下一步: python serial_loop.py --step refresh  （再刷一轮）")
    else:
        print(f"[刷新] ★ 下一步: python serial_loop.py --step next-batch  （提取本轮新货）")
        print(f"[刷新] ★ 然后: python scripts/build_jd.py --append → batch_deliver.py --apply")

    return result["new_count"] > 0


# ═══════════════════════════════════════════════════════════
# ★ 内层循环: 岗位级
# ═══════════════════════════════════════════════════════════

def step_read(index):
    """★ 内层循环 步骤A: 读取第 index 条JD

    流程图: 取序号最靠前的待处理岗位 → 点击标签卡读取右侧JD
    """
    jobs = load_jobs()
    if not jobs:
        print("ERROR: jd_to_read.json 为空或不存在")
        print("★ 请先运行 --step next-batch 加载岗位，然后AI初筛生成 jd_to_read.json")
        return False

    if index < 1 or index > len(jobs):
        print(f"ERROR: 索引超出范围 1~{len(jobs)}")
        return False

    job = jobs[index - 1]
    jid = job.get('jobId', '')
    title = job.get('title', '')
    company = job.get('company', '')
    salary = job.get('salary', '')
    page_order = job.get('page_order', '?')

    print(f"[串行] ═══ 内层循环 [{index}/{len(jobs)}] ═══")
    print(f"[串行] page_order={page_order}")
    print(f"[串行] 读取JD: {title} | {salary} | {company}")

    if not health_check():
        print("ERROR: WebBridge 不可达")
        return False

    # ★ v5.6.7 风控拦截检测：安全验证页上一张卡都没有，读 JD 必然 no_link_match。
    #   先判定再动手，命中立即停止并交回用户人工验证，绝不重试硬撞。
    blocked, b_url, b_title = is_verification_page()
    if blocked:
        print("=" * 66)
        print("[串行] ⛔ 命中 BOSS 安全验证/风控拦截页，停止读 JD")
        print(f"[串行]    URL  : {b_url}")
        print(f"[串行]    标题 : {b_title}")
        print("[串行] ★ 请人工完成验证后重新 --step init；脚本不得绕过验证")
        print("=" * 66)
        return False

    result = read_jd_for_job(jid)

    if not result.get('ok'):
        print(f"[串行] JD读取失败: {result.get('detail', '')}")
        with open(CURRENT_JD, 'w', encoding='utf-8') as f:
            json.dump({
                'index': index,
                'total': len(jobs),
                'jobId': jid,
                'title': title,
                'company': company,
                'salary': salary,
                'page_order': page_order,
                'jd_text': '',
                'status': 'READ_FAILED',
                'error': result.get('detail', ''),
                'surface_info': job,
            }, f, ensure_ascii=False, indent=2)
        return False

    jd_data = result.get('jd', {})
    jd_text = jd_data.get('jd_text', '')

    with open(CURRENT_JD, 'w', encoding='utf-8') as f:
        json.dump({
            'index': index,
            'total': len(jobs),
            'jobId': jid,
            'title': title,
            'company': company,
            'salary': salary,
            'page_order': page_order,
            'jd_text': jd_text,
            'jd_full': jd_data,
            'surface_info': job,
        }, f, ensure_ascii=False, indent=2)

    print(f"[串行] JD已写入 current_jd.json (共{len(jd_text)}字)")
    print(f"[串行] ★ 等待AI阅读 current_jd.json 并写入 decision.json")
    print(f"[串行] ★ decision.json 格式: {{\"decision\": \"APPROVE\"/\"REJECT\", \"reason\": \"...\"}}")

    # 更新进度
    progress = load_serial_progress()
    progress['current_index'] = index
    progress['total'] = len(jobs)
    save_serial_progress(progress)

    return True


def step_decide(index):
    """★ 内层循环 步骤B+C: 执行AI决策 + 检查投递目标

    流程图: 是否投递？ → 是 → 点击"立即沟通" → 总投递数量是否满足要求？
                        → 否 → 将该岗位标记为已处理
    """
    if not os.path.exists(DECISION_FILE):
        print(f"ERROR: {DECISION_FILE} 不存在，AI尚未做决策")
        print(f"★ AI请先阅读 current_jd.json，然后写入 decision.json")
        return False

    with open(DECISION_FILE, 'r', encoding='utf-8-sig') as f:
        decision_data = json.load(f)

    decision = decision_data.get('decision', '').upper()
    reason = decision_data.get('reason', '')

    jobs = load_jobs()
    if index < 1 or index > len(jobs):
        print(f"ERROR: 索引超出范围 1~{len(jobs)}")
        return False

    job = jobs[index - 1]
    jid = job.get('jobId', '')
    title = job.get('title', '')
    if not os.path.exists(CURRENT_JD):
        print('[ERROR] 缺少 current_jd.json，请先读取目标岗位 JD')
        return False
    with open(CURRENT_JD, 'r', encoding='utf-8') as f:
        current = json.load(f)
    if current.get('jobId') != jid or not current.get('jd_text'):
        print('[ERROR] JD 为空或 jobId 不一致，停止投递')
        return False
    if current.get('status') == 'READ_FAILED':
        print('[ERROR] current_jd.json status=READ_FAILED，不允许继续投递')
        return False

    print(f"[串行] [{index}/{len(jobs)}] AI决策: {decision}")
    print(f"[串行] 理由: {reason}")

    progress = load_serial_progress()
    result_entry = {
        'index': index,
        'jobId': jid,
        'title': title,
        'decision': decision,
        'reason': reason,
        'page_order': job.get('page_order', '?'),
    }

    if decision == 'APPROVE':
        # 流程图: 点击"立即沟通" → 弹窗中点击"留在此页" → 投递成功
        print(f"[串行] 执行投递: {title} ({jid[:16]}...)")

        if not health_check():
            print("ERROR: WebBridge 不可达")
            return False

        status, detail, evidence = deliver_inplace(jid, job_info=job)
        result_entry['deliver_status'] = status
        result_entry['deliver_detail'] = detail
        result_entry['evidence'] = evidence
        result_entry['run_id'] = progress.get('run_id', '')
        result_entry['updated_at'] = _now_text()

        print(f"[串行] 投递结果: {status} - {detail}")

        # 记录到 ProgressManager
        pm = ProgressManager(PROGRESS_FILE)
        pm.load()
        if status == 'success':
            pm.add_delivered(jid, job, run_id=progress.get('run_id'), evidence=evidence)
        else:
            mapped = status if status not in ('fatal_limit', 'login_expired', 'skip') else 'fail'
            pm.add_failed(jid, job, f"{status}: {detail}", run_id=progress.get('run_id'), evidence=evidence, status=mapped)
        pm.save()

        # ★ 流程图: 总投递数量是否满足要求？
        target_check = check_delivery_target(PROGRESS_FILE)

        # 致命错误检测
        if status == 'fatal_limit':
            print(f"[串行] ★★★ 致命错误: 每日上限！停止所有投递 ★★★")
            progress['fatal_stop'] = True
            progress['fatal_reason'] = detail
            progress['target_met'] = target_check['target_met']
            save_serial_progress(progress)
            # ★ 自动触发 finish，确保 100% 生成投递汇总页面
            print(f"[串行] ★ 自动生成投递汇总...")
            step_finish()
            return True

        if target_check["target_met"]:
            print(f"\n[串行] ★★★ 投递目标 {DAILY_TARGET} 份已达成！★★★")
            progress['target_met'] = True
            save_serial_progress(progress)
            # 仍然标记本条为已处理
            if index not in progress.get('processed', []):
                progress.setdefault('processed', []).append(index)
            progress.setdefault('results', []).append(result_entry)
            save_serial_progress(progress)
            if os.path.exists(DECISION_FILE):
                _safe_clear(DECISION_FILE)
            # ★ 自动触发 finish，确保 100% 生成投递汇总页面
            print(f"[串行] ★ 自动生成投递汇总...")
            step_finish()
            return True

    elif decision == 'REJECT':
        # 流程图: 将该岗位标记为已处理
        print(f"[串行] 跳过: {title}")
        result_entry['deliver_status'] = 'skipped'
    else:
        print(f"ERROR: 无效决策 '{decision}'，必须是 APPROVE 或 REJECT")
        return False

    # 标记为已处理
    if index not in progress.get('processed', []):
        progress.setdefault('processed', []).append(index)
    progress.setdefault('results', []).append(result_entry)
    save_serial_progress(progress)

    # 清理 decision.json
    if os.path.exists(DECISION_FILE):
        _safe_clear(DECISION_FILE)

    print(f"[串行] ✓ 第{index}条处理完成")

    # ★ 提示下一步 — 根据流程图判断走向
    if progress.get('target_met'):
        print(f"[串行] ★ 投递目标已达成")
        print(f"[串行] ★ 下一步: python serial_loop.py --step finish")
    elif index < len(jobs):
        # 本批还有待处理岗位 → 继续内层循环
        print(f"[串行] 下一条: python serial_loop.py --step read --index {index+1}")
    else:
        # 本批处理完 → 检查页面是否还有更多岗位（中层循环）
        print(f"[串行] ★ 本批{len(jobs)}条已全部处理完毕！")
        if is_exhausted():
            # 页面穷尽 → 先刷新补量（★ v5.6.7：不直接跳外层搜索循环）
            print(f"[串行] ★ 当前屏已滚完")
            print(f"[串行] ★ 下一步: python serial_loop.py --step refresh  （刷新频道取新一批）")
        else:
            # 页面还有更多岗位 → 中层循环
            print(f"[串行] ★ 当前页面还有更多岗位可加载")
            print(f"[串行] ★ 下一步: python serial_loop.py --step next-batch")

    return True


# ═══════════════════════════════════════════════════════════
# ★ 终止: 生成汇报
# ═══════════════════════════════════════════════════════════

def step_finish():
    """生成带时间戳的投递汇报，同时展示累计快照和本次调用结果。"""
    print("[完成] ═══ 生成投递汇报 ═══")
    serial = ensure_run_state()
    output_path = unique_timestamp_report_path()
    latest_copy = os.path.join(WORK_DIR, "投递汇总.html")
    _, cumulative, current_stats, serial = collect_unified_stats(serial.get("run_id"))
    result = build_report(
        progress_file=PROGRESS_FILE,
        output_path=output_path,
        run_id=serial.get("run_id"),
        latest_copy=latest_copy,
        current_stats=current_stats,
    )
    if result:
        print(f"\n[完成] ★ 投递汇报已生成: {result}")
        print(f"[完成] ★ 最新副本: {latest_copy}")
        print()
        print("=" * 60)
        print_unified_stats(cumulative, current_stats, title="最终统计")
        serial["finished_at"] = current_stats["generated_at"]
        serial["last_report"] = result
        save_serial_progress(serial)
        if serial.get("fatal_stop"):
            print("停止原因: 致命错误 - " + str(serial.get("fatal_reason", "")))
        elif serial.get("target_met"):
            print(f"停止原因: 投递目标达成")
        else:
            print(f"停止原因: 页面穷尽/主动结束")
        print("=" * 60)
    else:
        print("[完成] ERROR: 汇报生成失败")
    return result is not None


def step_status():
    """查看三层循环完整进度；投递统计与 HTML 使用同一口径。"""
    progress = load_serial_progress()
    jobs = load_jobs()
    batch_state = get_state()
    page_state = load_page_state()
    _, cumulative, current_stats, _ = collect_unified_stats(progress.get("run_id"))
    target_check = check_delivery_target(PROGRESS_FILE)

    total = len(jobs)
    current = progress.get("current_index", 0)
    processed = progress.get("processed", [])
    results = progress.get("results", [])
    approved = [r for r in results if r.get("decision") == "APPROVE"]
    rejected = [r for r in results if r.get("decision") == "REJECT"]

    print("=" * 60)
    print("v5.6 三层循环进度")
    print("=" * 60)
    print("run_id: " + (progress.get("run_id") or "-"))
    print("profile_file: " + (progress.get("profile_file") or USER_PROFILE_FILE))
    print("channel: " + (progress.get("channel") or "algorithm_channel"))
    print()
    print("┌─ 外层循环 (页面级) ──────────────────────")
    print("│ 页面类型: " + str(page_state.get("page_type", "?")))
    print("│ 当前关键词: " + str(page_state.get("current_keyword", "(推荐页)")))
    print("│ 已处理页面: " + str(page_state.get("pages_processed", 0)))
    print()
    print("├─ 中层循环 (分批级) ──────────────────────")
    print("│ 当前批次: 第" + str(batch_state.get("batch_num", 0)) + "批")
    print("│ 累计提取: " + str(batch_state.get("total_extracted", 0)))
    print("│ 穷尽: " + str(batch_state.get("exhausted", False)))
    print()
    print("├─ 内层循环 (岗位级) ──────────────────────")
    print(f"│ jd_to_read.json: {total}条待处理")
    print(f"│ 当前处理: 第{current}条")
    print(f"│ 已处理: {len(processed)}")
    print(f"│   APPROVE: {len(approved)}")
    print(f"│   REJECT: {len(rejected)}")
    print(f"│ 剩余: {total - len(processed)}")
    print()
    print("├─ 投递目标 ──────────────────────────────")
    print("│ 目标: " + str(target_check["target"]) + " 份")
    print("│ 已投递: " + str(target_check["delivered_count"]) + " 份")
    print("│ 达标: " + ("是" if target_check["target_met"] else "否"))
    print()
    print("├─ 统一统计 ──────────────────────────────")
    print_unified_stats(cumulative, current_stats, title="│")
    if progress.get("fatal_stop"):
        print("致命停止: " + str(progress.get("fatal_reason", "")))
    print("=" * 60)
    return True


def _ensure_finish_on_exit():
    """atexit 钩子：仅在 decide/finish 后且尚未生成本次报告时兜底。"""
    try:
        if os.environ.get("BOSS_SKIP_ATEXIT_FINISH") == "1":
            return
        step = getattr(_ensure_finish_on_exit, "step", "")
        if step not in ("decide", "finish"):
            return
        if not os.path.exists(PROGRESS_FILE):
            return
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not (data.get("delivered") or data.get("failed")):
            return
        serial = load_serial_progress()
        last_report = serial.get("last_report")
        if last_report and os.path.exists(last_report):
            return
        print("[收尾] ═══ 自动生成投递汇总（atexit 兜底） ═══")
        step_finish()
    except Exception:
        pass


def main():
    atexit.register(_ensure_finish_on_exit)
    parser = argparse.ArgumentParser(
        description="★v5.0 三层嵌套循环主控制器",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
三层循环命令体系:
  外层 (页面级):
    --step init                    检查环境+导航推荐页 (开始)
    --step evolve                  页面穷尽→AI评估→新关键词
    --step navigate-search --kw X  导航到搜索结果页
    --step add-keyword --kw X      添加AI生成的新关键词

  中层 (分批级):
    --step next-batch              滚动加载下一批50条
    --step refresh                 ★v5.6.7 刷新频道信息流取新一批（滚动穷尽后首选）

  内层 (岗位级):
    --step read --index N          读第N条JD
    --step decide --index N        执行AI决策+检查目标

  终止:
    --step finish                  生成HTML汇报+打赏页面
    --step status                  查看三层完整进度
        """)
    parser.add_argument("--step", required=True,
                        choices=['init', 'next-batch', 'refresh', 'read', 'decide',
                                 'evolve', 'navigate-search', 'add-keyword',
                                 'finish', 'status'],
                        help="执行步骤")
    parser.add_argument("--index", type=int, default=0,
                        help="处理第几条 (read/decide时需要)")
    parser.add_argument("--keyword", default="",
                        help="搜索关键词 (navigate-search/add-keyword时需要)")
    parser.add_argument("--city", default=_PROFILE_CITY,
                        help="城市编码 (默认从 user_profile.json 读取)")
    args = parser.parse_args()
    _ensure_finish_on_exit.step = args.step

    if args.step == 'init':
        step_init(args.city)

    elif args.step == 'next-batch':
        step_next_batch()

    elif args.step == 'refresh':
        step_refresh(args.city)

    elif args.step == 'read':
        if args.index < 1:
            print("ERROR: --index 必须 >= 1")
            sys.exit(1)
        step_read(args.index)

    elif args.step == 'decide':
        if args.index < 1:
            print("ERROR: --index 必须 >= 1")
            sys.exit(1)
        step_decide(args.index)

    elif args.step == 'evolve':
        step_evolve(args.city)

    elif args.step == 'navigate-search':
        if not args.keyword:
            print("ERROR: 需要 --keyword 参数")
            sys.exit(1)
        step_navigate_search(args.keyword, args.city)

    elif args.step == 'add-keyword':
        if not args.keyword:
            print("ERROR: 需要 --keyword 参数")
            sys.exit(1)
        step_add_keyword(args.keyword)

    elif args.step == 'finish':
        step_finish()

    elif args.step == 'status':
        step_status()


if __name__ == "__main__":
    main()
