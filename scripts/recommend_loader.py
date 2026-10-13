#!/usr/bin/env python3
"""
模块 C: 推荐页导航 + 分批懒加载

★ v4.4 核心改动 — 分批滚动+提取:
  不再一口气滚到底再提取，而是分批处理:
  1. 每批滚动加载约 BATCH_SIZE 条岗位（约2-3次滚动）
  2. 立刻增量提取本批新岗位 → append 到 surface_cache.json
  3. 输出本批岗位列表供 AI 筛选 + 串行投递
  4. 自动继续下一批滚动，直到穷尽或达到每日投递上限

  ★ 分批不等于批量投递 — 每批内的投递仍然严格串行（serial_loop.py 控制）

★ v4.4 状态持久化 — 写死连续滚动规则:
  serial_loop.py 每批以独立 CLI 进程调用本模块，模块级 _state 会重置。
  必须将分批进度持久化到 batch_state.json，否则第二批会从 page_order=0
  重新开始，等于"第一批结束后就忘了向下还能滚动"。
  → _load_state() 在每次操作前恢复进度
  → _save_state() 在每次修改后持久化

优势:
  - 快进快出: 第一批50条2分钟内即可进入筛选投递
  - 提前止损: 如果投到每日上限，直接停手不再滚动
  - 页面稳定: 每批卡片在视口内，不会因虚拟滚动消失
  - 数据量可控: AI每次只分析50-80条
  - ★ 跨进程记忆: batch_state.json 确保第二批从第一批结束处继续

★ v5.6.1 修复②/④（2026-10-12）:
  - 修复②：init 进入推荐页后若 URL 丢失 city 参数，改为带 city 重新 navigate，
    但不再二次点击频道（二次点击会再次丢城）。降级时仅告警，依赖 surface_cache
    的 city 字段做初筛剔除跨城岗位。
  - 修复④：_click_algorithm_channel() 消除 Python 转义序列 SyntaxWarning（v5.6.2 改为
    注入可配置 CHANNEL_TAB，仍保持零告警）。

★ v5.6.2 频道标签可配置化（2026-10-12）:
  - _click_algorithm_channel() 不再硬编码「算法工程师」，改为注入 profile_loader.CHANNEL_TAB；
    标签文本经 json.dumps 安全嵌入 JS，匹配前先归一化（全角括号（）→半角() + 去多余空白），
    再按「精确相等 或 前缀包含（indexOf===0）」判定，兼容用户写「算法工程师」「算法工程师（广州）」
    「算法工程师(广州)」等任意写法，命中 DOM 真实标签「算法工程师(广州)」。
  - CHANNEL_TAB 赋值优先级：环境变量 BOSS_CHANNEL_TAB（对话中由 Agent 直接指定）
    > 画像 JSON 的 channel_tab 字段（外部 JSON 文件）> 默认值 "算法工程师（广州）"。
    切换账号/方向只需改该变量值即可保持刷新界面目标岗位命中率。

★ v5.6.3 默认推荐模式（2026-10-12）:
  - 页面实测（截图）确认：打开 /web/geek/jobs 默认停在「推荐」标签（选中态），
    「推荐」不是可点击的频道标签而是默认态；可点击频道仅「算法工程师(广州)」「电气/自动化(广州)」。
  - 新增 DEFAULT_CHANNEL_SENTINELS 哨兵（推荐/默认/default/__default__）：channel_tab
    取哨兵值时 _is_default_channel() 命中，navigate_to_recommend 跳过频道点击，
    直接使用推荐页默认岗位流；不点频道则 URL 不丢 city 参数，城市过滤天然生效。
  - 用途：不指定方向时用默认推荐流（岗位面更广），指定方向时仍点频道聚焦。

★ v5.6.7 刷新补量 + 卡片选择器统一（2026-10-13）:
  - 【刷新补量 refresh_feed()】单频道信息流不是"滚完就没了"——BOSS 的推荐/频道流
    每次**重新进入**（reload 页面 / 重新点击频道标签）都会换一批岗位，这是"同一个
    算法工程师频道可以一直刷出新岗位"的供给来源（用户 2026-10-13 实测确认并明确指出）。
    旧版只有「滚动」一种补量手段，滚动到底就判"穷尽"，Agent 于是被迫去换频道/换城市/
    走搜索页，既越权又低效。v5.6.7 新增 `--step refresh`：重新进频道取新一批，
    与已见 jobId 去重后累计；连续 MAX_NO_NEW_ROUNDS 轮刷不出新岗位才判定【真穷尽】，
    此时停下来汇报，**不换频道、不换城市、不走搜索页**。
  - 【卡片选择器统一】旧版硬编码 `.job-card-wrap`，改版后的真实容器为
    `li.job-card-box`；两处（本模块 _count_cards / webbridge_client.extract_jobs）
    口径不一致会导致"数到 0 张卡 → 连续无新增 → 假穷尽"。现统一引用
    webbridge_client.CARD_SELECTORS，并在计数为 0 时用 a[href*=job_detail] 兜底。

★ v5.6.4 频道点击后不再被城市重导冲掉（2026-10-12）:
  - 用户实测暴露：v5.6.1 修复②在点击具体频道后仍检测 URL 丢 city 参数并带 city 重新导航，
    导航会整页重置回「推荐」默认态，把刚点击的「算法工程师(广州)」频道冲掉（用户看到
    页面停在「推荐」而非所选频道）。
  - 修复：navigate_to_recommend 先判定 _is_default_channel(CHANNEL_TAB)；仅【默认推荐模式】
    才执行修复②的城市回退导航（默认流无频道参数，城市过滤依赖 ?city=）。点击具体频道后
    【信任频道、不再城市重导】——频道标签中的（广州）等仅为标签文本，非城市约束。

独立可运行:
    python recommend_loader.py --city 101210100

也可被其他模块 import:
    from scripts.recommend_loader import navigate_to_recommend, scroll_next_batch, is_exhausted
    navigate_to_recommend("101210100")
    batch = scroll_next_batch()  # 返回本批新岗位列表
"""

import json
import time
import random
import sys
import os

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SKILL_DIR)

from scripts.profile_loader import WORK_DIR, CITY_CODE as _PROFILE_CITY, CHANNEL_TAB

from scripts.webbridge_client import (
    SESSION, navigate, evaluate, scroll_page,
    ensure_active_tab, health_check, extract_jobs, CARD_SELECTORS,
)
from scripts.surface_cache import KEEP_FIELDS, append_cache

# ═══════════════════════════════════════════════════════════
# 配置常量
# ═══════════════════════════════════════════════════════════

RECOMMEND_URL = "https://www.zhipin.com/web/geek/jobs"

# 分批参数
BATCH_SIZE = 50           # 每批目标岗位数（达到此数量即停止滚动，进入提取）
# ★ v5.6.7 修正（2026-10-13 用户指出）：BOSS 岗位列表是「无限滚动」，一路往下滚就会
#   持续出新的岗位（实测一次滚到 330 张卡），这是【主要供给方式】。原值 8 太小，
#   每批滚 8 次就停，容易被误读成"到底了"。改为 20，让单次 next-batch 滚得更透。
#   真正的终点由 MAX_TOTAL_SCROLLS(80) 与底部标记「没有更多了」收口；
#   --step refresh 只在滚动确实不再出货时才用（兜底，不是主力）。
MAX_SCROLLS_PER_BATCH = 20
RENDER_WAIT = 3           # 滚动后等待渲染秒数

# 穷尽检测
MAX_TOTAL_SCROLLS = 80    # 全局最大滚动次数（安全上限）
STABLE_THRESHOLD = 4      # 连续 N 次无新增 → 穷尽

# ★ v5.6.7 刷新补量参数
REFRESH_SCROLLS = 6       # 每次刷新后先滚动几次把首屏之外也加载出来
MAX_NO_NEW_ROUNDS = 3     # 连续 N 轮刷新刷不出新岗位 → 判定【真穷尽】，停止并汇报

# ★ v4.4 跨进程状态持久化文件
#   serial_loop.py 每次以独立 CLI 进程调用，模块级 _state 会重置。
#   必须将分批进度持久化到文件，否则第二批会从 page_order=0 重新开始。
BATCH_STATE_FILE = os.path.join(WORK_DIR, "batch_state.json")

# ═══════════════════════════════════════════════════════════
# 模块级状态 — 跟踪分批进度
# ═══════════════════════════════════════════════════════════

_state = {
    "total_cards": 0,       # 当前页面总卡片数
    "total_extracted": 0,   # 已提取的岗位数
    "total_scrolls": 0,     # 累计滚动次数
    "exhausted": False,     # 是否已穷尽（单轮滚动口径）
    "exhaust_reason": "",   # 穷尽原因
    "batch_num": 0,         # 当前批次号
    # ★ v5.6.7 刷新补量计数（跨 refresh 轮次保留，仅 full reset 清零）
    "refresh_round": 0,     # 已刷新轮数
    "no_new_rounds": 0,     # 连续刷不出新岗位的轮数
    "last_refresh_new": 0,  # 上一轮刷新带来的新岗位数
}


def _load_state():
    """★ v4.4 从文件加载分批状态（跨进程持久化）

    serial_loop.py 每批以独立进程调用本模块，模块级 _state 会重置为默认值。
    必须在每次操作前从 batch_state.json 恢复进度，否则:
      - 第二批会从 page_order=0 重新提取（重复）
      - exhausted 标志丢失（已穷尽的页面会再次尝试滚动）
      - total_scrolls 重置（全局上限保护失效）
    """
    global _state
    if os.path.exists(BATCH_STATE_FILE):
        try:
            with open(BATCH_STATE_FILE, 'r', encoding='utf-8') as f:
                saved = json.load(f)
                _state.update(saved)
        except (json.JSONDecodeError, IOError) as e:
            print(f"[状态] 加载 batch_state.json 失败: {e}，使用默认状态")
    return _state


def _save_state():
    """★ v4.4 保存分批状态到文件（跨进程持久化）

    每次修改 _state 后必须调用，确保下一批进程能恢复进度。
    """
    try:
        with open(BATCH_STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(_state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"[状态] 保存 batch_state.json 失败: {e}")


# ═══════════════════════════════════════════════════════════
# 「默认推荐」哨兵值（★ v5.6.3）
#   BOSS 打开 /web/geek/jobs 时默认就停在「推荐」标签上（页面实测截图确认：
#   顶栏为 推荐（选中态）｜算法工程师(广州)｜电气/自动化(广州)｜+），
#   「推荐」不是可点击的频道标签，而是默认态。因此 channel_tab 取下列
#   哨兵值时跳过频道点击，直接使用推荐页默认岗位流。
# ═══════════════════════════════════════════════════════════

DEFAULT_CHANNEL_SENTINELS = {"推荐", "默认", "default", "__default__"}


def _is_default_channel(tab):
    """判断 channel_tab 是否为「默认推荐」哨兵值（跳过频道点击）。"""
    return (tab or "").strip() in DEFAULT_CHANNEL_SENTINELS


def _click_algorithm_channel():
    """点击配置的频道标签（CHANNEL_TAB，外部可配置），返回点击到的文本或 not_found。

    标签文本来自 profile_loader.CHANNEL_TAB，支持环境变量 BOSS_CHANNEL_TAB 覆盖与
    画像 JSON channel_tab 字段赋值；默认 "算法工程师（广州）"。匹配规则：先把标签与
    CHANNEL_TAB 同时归一化（全角括号（）→半角()、压缩空白），再按「精确相等 或 前缀
    包含（indexOf===0）」判定，兼容「算法工程师」「算法工程师（广州）」「算法工程师(广州)」
    等任意写法，稳定命中 DOM 真实标签「算法工程师(广州)」。
    """
    needle = json.dumps(CHANNEL_TAB)  # 安全的 JS 字符串字面量（含中文/引号转义）
    js = (
        "(function(){"
        "  var CHANNEL_TAB = " + needle + ";"
        # ★ v5.6.2 修正：DOM 标签文本用半角括号 ( )，而用户常写全角 （ ），
        #   归一化（全角→半角 + 去多余空白）后再比较，兼容两种写法；
        #   匹配语义保留原前缀匹配（indexOf===0），即 needle 为 "算法工程师"
        #   也能命中 "算法工程师(广州)"，同时 needle 带城市后缀时要求精确/前缀一致。
        "  function norm(s){"
        "    s = (s||'').replace(/\\s+/g,' ').trim();"
        "    var out='';"
        "    for(var i=0;i<s.length;i++){"
        "      var c=s.charCodeAt(i);"
        "      if(c===0xFF08) out+='(';"       # 全角左括号 → 半角
        "      else if(c===0xFF09) out+=')';"   # 全角右括号 → 半角
        "      else out+=s[i];"
        "    }"
        "    return out;"
        "  }"
        "  var want = norm(CHANNEL_TAB);"
        "  var nodes = Array.from(document.querySelectorAll('.expect-item, .expect-item .text-content'));"
        "  var el = nodes.find(function(n){"
        "    var t = norm(n.textContent || n.innerText || '');"
        "    return t === want || t.indexOf(want) === 0;"
        "  });"
        "  if (!el) return 'not_found';"
        "  (el.closest('.expect-item') || el).click();"
        "  return 'clicked:' + (el.textContent || el.innerText || '').trim();"
        "})()"
    )
    return evaluate(js) or ""


def navigate_to_recommend(city_code=_PROFILE_CITY):
    """导航到 BOSS直聘 推荐页

    参数:
        city_code: 城市编码 (如 101210100 = 杭州)

    返回:
        bool: 导航是否成功
    """
    url = f"{RECOMMEND_URL}?city={city_code}" if city_code else RECOMMEND_URL
    print(f"[导航] {url}")
    navigate(url, wait_range=(8, 10))

    current_url = evaluate("window.location.href") or ""
    if "jobs" not in current_url and "ka=header-jobs" not in current_url:
        print(f"[警告] 当前URL可能不在推荐页: {current_url}")
        return False

    time.sleep(2)

    # ★ v5.6.3 默认推荐模式 / v5.6.4 频道点击不二次重导：
    #   - 默认推荐模式（推荐/默认/default 哨兵）：跳过频道点击，直接用推荐页默认岗位流；
    #     此时 URL 不带频道，城市过滤依赖 ?city=，故保留 fix② 城市回退导航。
    #   - 点击具体频道（如 算法工程师（广州））：频道本身已对「方向+城市」聚焦，标签里的
    #     （广州）等只是标签文本、不是城市约束；若此时再带 city 重新导航会跳回「推荐」
    #     默认流、把刚点的频道冲掉（用户实测即看到页面停在「推荐」）。故【点具体频道后
    #     不再做 fix② 城市回退导航】，直接信任频道。
    use_default = _is_default_channel(CHANNEL_TAB)
    if use_default:
        print(f"[导航] channel_tab={CHANNEL_TAB!r} → 默认推荐模式，跳过频道点击，使用推荐页默认岗位流")
    else:
        switched = _click_algorithm_channel()
        print(f"[??] algorithm channel action: {switched}")
        if not switched.startswith('clicked:'):
            print("[ERROR] algorithm channel not found; stop before collecting recommendation jobs")
            return False
        time.sleep(4)

    # ★ 修复②（仅默认推荐模式生效）：默认流下 URL 不带频道，城市过滤靠 ?city=；若参数丢失
    #   则带 city 重新导航（不再二次点击频道）。【点击具体频道时此分支不执行】，避免把频道冲回「推荐」。
    if use_default:
        current_url = evaluate("window.location.href") or ""
        if ("city=" + str(city_code)) not in current_url:
            print(f"[导航] 检测到城市参数丢失，重新以 city={city_code} 导航（保留城市过滤，不再二次点击频道以免再次丢参）")
            navigate(f"{RECOMMEND_URL}?city={city_code}", wait_range=(6, 8))
            time.sleep(2)
            current_url = evaluate("window.location.href") or ""
            if ("city=" + str(city_code)) not in current_url:
                print(f"[警告] 城市参数仍未生效 ({current_url})；将依赖 surface_cache 的城市字段在初筛时过滤")

    card_count = _count_cards()
    if card_count == 0:
        print("[警告] 推荐页无岗位卡片，可能页面未渲染完成")
        time.sleep(3)
        card_count = _count_cards()

    print(f"[导航] 推荐页已加载，初始卡片数: {card_count}")
    _state["total_cards"] = card_count
    _save_state()  # ★ 持久化
    return card_count > 0


def _count_cards():
    """统计当前页面岗位卡片数量

    ★ v5.6.7：选择器统一引用 webbridge_client.CARD_SELECTORS（同时兼容
      li.job-card-box 与旧 .job-card-wrap）；若两个 class 都数不到（BOSS 再次改版），
      退化用 a[href*="job_detail"] 的数量兜底，避免"数到 0 → 假穷尽"。
    """
    # ★ 按【唯一 jobId】计数，而不是按元素个数：
    #   li.job-card-box 内部还套着 div.job-card-wrap，按元素数会双倍计数
    #   （实测 45 个岗位被数成 90），虚高的"新增"会掩盖真正的穷尽。
    #   唯一 jobId 才是与 extract_jobs 一致的口径。
    result = evaluate(
        "(function(){"
        "  var s = {}, links = document.querySelectorAll('a[href*=\"job_detail\"]');"
        "  for (var i = 0; i < links.length; i++) {"
        "    var m = (links[i].getAttribute('href')||'').match(/job_detail\\/([^.?#]+)/);"
        "    if (m) s[m[1]] = 1;"
        "  }"
        "  var n = Object.keys(s).length;"
        "  if (n === 0) {"
        "    n = document.querySelectorAll("
        + json.dumps(CARD_SELECTORS) + ").length;"
        "  }"
        "  return n.toString();"
        "})()"
    ) or "0"
    try:
        return int(result)
    except (ValueError, TypeError):
        return 0


def _check_end_marker():
    """检测页面底部的"没有更多了"等文案"""
    result = evaluate("""
    (function(){
        var bodyText = document.body.innerText || '';
        var markers = [
            '没有更多了', '已经到底', '没有更多', '到底了',
            '已加载全部', '暂无更多', 'No more'
        ];
        for (var i = 0; i < markers.length; i++) {
            if (bodyText.indexOf(markers[i]) >= 0) return 'true';
        }
        return 'false';
    })()
    """) or "false"
    return result == "true"


def _extract_new_jobs(from_index):
    """增量提取新岗位（从 from_index 开始的岗位）

    参数:
        from_index: 之前已提取的数量，新岗位从此索引开始

    返回:
        list[dict]: 新岗位列表（精简字段 + page_order）
    """
    jobs = extract_jobs()

    # 去重
    seen = set()
    unique_jobs = []
    for job in jobs:
        jid = job.get('jobId', '')
        if jid and jid not in seen:
            seen.add(jid)
            unique_jobs.append(job)

    # 计算薪资上限
    for job in unique_jobs:
        salary_str = job.get('salary', '')
        job['salary_max_k'] = __import__('scripts.webbridge_client', fromlist=['parse_salary_max']).parse_salary_max(salary_str)

    _state["total_cards"] = len(unique_jobs)

    # 只取 from_index 之后的新岗位
    if len(unique_jobs) <= from_index:
        return []

    new_jobs = unique_jobs[from_index:]
    for i, job in enumerate(new_jobs):
        job['page_order'] = from_index + i

    # 精简字段
    slim_jobs = []
    for job in new_jobs:
        slim = {k: job.get(k, '') for k in KEEP_FIELDS}
        slim_jobs.append(slim)

    return slim_jobs


def scroll_next_batch(cache_file="surface_cache.json"):
    """滚动加载下一批岗位并增量提取

    ★ 分批核心函数:
      1. 滚动直到新增岗位数 >= BATCH_SIZE 或达到穷尽/上限
      2. 增量提取新岗位
      3. append 到缓存文件
      4. 返回本批岗位列表

    ★ v4.4 跨进程安全:
      进入函数时先 _load_state() 恢复上一批的进度，
      确保第二批从第一批结束的 page_order 继续向下滚动。

    参数:
        cache_file: 缓存文件路径（增量追加）

    返回:
        dict: {
            "batch_num": int,        # 批次号
            "new_jobs": list[dict],  # 本批新岗位
            "new_count": int,        # 本批新岗位数
            "total_extracted": int,  # 累计提取数
            "total_cards": int,      # 页面总卡片数
            "exhausted": bool,       # 是否已穷尽
            "exhaust_reason": str,   # 穷尽原因
        }
    """
    # ★ v4.4 跨进程恢复 — 从文件加载上一批的进度
    _load_state()

    if _state["exhausted"]:
        print(f"[分批] 已穷尽({_state['exhaust_reason']})，不再滚动")
        print(f"[分批] 累计提取 {_state['total_extracted']} 条，总滚动 {_state['total_scrolls']} 次")
        return {
            "batch_num": _state["batch_num"],
            "new_jobs": [],
            "new_count": 0,
            "total_extracted": _state["total_extracted"],
            "total_cards": _state["total_cards"],
            "exhausted": True,
            "exhaust_reason": _state["exhaust_reason"],
        }

    _state["batch_num"] += 1
    batch_num = _state["batch_num"]
    from_index = _state["total_extracted"]

    print(f"\n[分批] === 第{batch_num}批 === 从 page_order={from_index} 开始")
    print(f"[分批] 目标: 新增 {BATCH_SIZE} 条 (最多滚动 {MAX_SCROLLS_PER_BATCH} 次)")
    print(f"[分批] 累计进度: 已提取{_state['total_extracted']}条, 已滚动{_state['total_scrolls']}次")

    stable_count = 0
    batch_scrolls = 0

    while batch_scrolls < MAX_SCROLLS_PER_BATCH:
        # 检查全局上限
        if _state["total_scrolls"] >= MAX_TOTAL_SCROLLS:
            _state["exhausted"] = True
            _state["exhaust_reason"] = f"达到全局滚动上限{MAX_TOTAL_SCROLLS}次"
            print(f"[分批] {_state['exhaust_reason']}")
            _save_state()  # ★ 持久化
            break

        # 检查底部标记
        if _check_end_marker():
            _state["exhausted"] = True
            _state["exhaust_reason"] = "检测到底部标记"
            print(f"[分批] {_state['exhaust_reason']}")
            _save_state()  # ★ 持久化
            break

        # 滚动一次
        scroll_page()
        _state["total_scrolls"] += 1
        batch_scrolls += 1
        time.sleep(random.uniform(0.8, 1.5))

        # 等待渲染后计数
        if batch_scrolls % 2 == 0:  # 每滚2次检查一次
            time.sleep(RENDER_WAIT)
            current_cards = _count_cards()
            new_since_scroll = current_cards - _state["total_cards"]

            if new_since_scroll > 0:
                print(f"[分批] 滚动{_state['total_scrolls']}: 卡片{current_cards} (本批新增{new_since_scroll})")
                _state["total_cards"] = current_cards
                stable_count = 0
            else:
                stable_count += 1
                print(f"[分批] 滚动{_state['total_scrolls']}: 卡片{current_cards} (无新增, 稳定{stable_count}/{STABLE_THRESHOLD})")

            # 连续无新增 → 穷尽
            if stable_count >= STABLE_THRESHOLD:
                _state["exhausted"] = True
                _state["exhaust_reason"] = f"连续{STABLE_THRESHOLD}次无新增"
                print(f"[分批] {_state['exhaust_reason']}")
                _save_state()  # ★ 持久化
                break

            # 本批新增达到目标 → 停止滚动
            new_total = current_cards - from_index
            if new_total >= BATCH_SIZE:
                print(f"[分批] 本批已新增{new_total}条，达到目标{BATCH_SIZE}，停止滚动")
                break

    # 增量提取新岗位
    new_jobs = _extract_new_jobs(from_index)

    if new_jobs:
        # 追加到缓存文件
        append_cache(new_jobs, cache_file)
        _state["total_extracted"] += len(new_jobs)
        print(f"[分批] 第{batch_num}批提取 {len(new_jobs)} 条，累计 {_state['total_extracted']} 条")

        # 打印前5条预览
        for i, j in enumerate(new_jobs[:5]):
            print(f"  [{j.get('page_order','?')}] {j.get('title','')[:25]} | {j.get('salary','')} | {j.get('company','')[:15]}")
        if len(new_jobs) > 5:
            print(f"  ... 共{len(new_jobs)}条")
    else:
        print(f"[分批] 第{batch_num}批无新岗位")
        if not _state["exhausted"]:
            _state["exhausted"] = True
            _state["exhaust_reason"] = "本批无新岗位"

    # ★ v4.4 持久化 — 保存本批进度供下一批进程恢复
    _save_state()

    # ★ 提示连续滚动 — 写死规则，不让学生忘了还有下一批
    if not _state["exhausted"]:
        print(f"\n[分批] ★ 本批处理完后，必须继续运行 --step next-batch 加载第{batch_num + 1}批")
        print(f"[分批] ★ 当前页面还有更多岗位可向下滚动，不要停在第一批！")
    else:
        print(f"\n[分批] ★ 已穷尽: {_state['exhaust_reason']}")
        print(f"[分批] ★ 总计 {_state['total_extracted']} 条岗位，{_state['total_scrolls']} 次滚动")

    return {
        "batch_num": batch_num,
        "new_jobs": new_jobs,
        "new_count": len(new_jobs),
        "total_extracted": _state["total_extracted"],
        "total_cards": _state["total_cards"],
        "exhausted": _state["exhausted"],
        "exhaust_reason": _state["exhaust_reason"],
    }


def is_exhausted():
    """是否已穷尽（所有岗位都加载完了）"""
    _load_state()  # ★ v4.4 跨进程恢复
    return _state["exhausted"]


def get_state():
    """获取当前分批状态"""
    _load_state()  # ★ v4.4 跨进程恢复
    return dict(_state)


def reset_state(full=False):
    """重置分批状态（新一轮开始时调用）

    ★ v5.6.7：
      full=True  —— 连刷新轮次计数一起清零（--step init 开新一轮时用）
      full=False —— 保留 refresh_round / no_new_rounds（--step refresh 用它重置
                    滚动与提取进度，但保留"刷了几轮、连续几轮没新货"的判断依据）
    """
    _state.update({
        "total_cards": 0,
        "total_extracted": 0,
        "total_scrolls": 0,
        "exhausted": False,
        "exhaust_reason": "",
        "batch_num": 0,
    })
    if full:
        _state["refresh_round"] = 0
        _state["no_new_rounds"] = 0
        _state["last_refresh_new"] = 0
    _save_state()  # ★ v4.4 持久化重置后的状态
    tail = "（含刷新轮次计数）" if full else "（保留刷新轮次计数）"
    print(f"[状态] 已重置分批进度 (batch_state.json 已清零){tail}")


# ═══════════════════════════════════════════════════════════
# ★ v5.6.7 刷新补量（refresh_feed）
# ═══════════════════════════════════════════════════════════

_DOM_JOB_IDS_JS = r"""
(function(){
    var links = document.querySelectorAll('a[href*="job_detail"]');
    var seen = {}, out = [];
    for (var i = 0; i < links.length; i++) {
        var m = (links[i].getAttribute('href') || '').match(/job_detail\/([^.?#]+)/);
        if (!m) continue;
        if (seen[m[1]]) continue;
        seen[m[1]] = 1;
        out.push(m[1]);
    }
    return JSON.stringify(out);
})()
"""


def _current_job_ids():
    """取当前页面所有岗位 jobId（DOM 抓取，与 Vue 通道互为兜底）。

    只要任一通道拿到 id 集合就返回；两者都空才返回 []。
    """
    ids = set()
    try:
        for j in extract_jobs():
            jid = (j or {}).get("jobId")
            if jid:
                ids.add(jid)
    except Exception:
        pass
    try:
        raw = evaluate(_DOM_JOB_IDS_JS) or "[]"
        for jid in json.loads(raw):
            ids.add(jid)
    except (json.JSONDecodeError, TypeError):
        pass
    return list(ids)


def _load_seen_job_ids():
    """汇总"已经见过"的 jobId：历史缓存 + 当前候选池 + 已投递/已失败记录。

    刷新补量的去重基准——避免把同一岗位反复算成"新货"导致误判供给充足。
    """
    seen = set()

    def _collect(path, is_progress=False):
        if not os.path.exists(path):
            return
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            return
        if is_progress:
            for key in ("delivered", "failed"):
                for rec in (data.get(key) or []):
                    if isinstance(rec, dict) and rec.get("jobId"):
                        seen.add(rec["jobId"])
            return
        if isinstance(data, list):
            for rec in data:
                if isinstance(rec, dict) and rec.get("jobId"):
                    seen.add(rec["jobId"])

    _collect(os.path.join(WORK_DIR, "surface_cache.json"))
    _collect(os.path.join(WORK_DIR, "jd_to_read.json"))
    _collect(os.path.join(WORK_DIR, "stream_progress.json"), is_progress=True)
    return seen


def refresh_feed(city_code=_PROFILE_CITY):
    """★ v5.6.7 刷新补量：重新进入频道，取 BOSS 换上来的新一批岗位

    原理（用户 2026-10-13 实测确认）：BOSS 的推荐/频道信息流每次**重新进入**
    （reload 页面或重新点击频道标签）都会换一批岗位。同一个「算法工程师(广州)」
    频道可以一直刷出新岗位，根本不需要换频道/换城市/走搜索页。

    流程：
      1. 重新导航到推荐页 → 重新点击 CHANNEL_TAB 频道（默认推荐模式则跳过点击）
      2. 滚动 REFRESH_SCROLLS 次把首屏之外的卡片也加载出来
      3. 取当前页 jobId，与"已见过"集合去重 → 得到本轮真正的新货
      4. 重置分批进度（保留刷新轮次计数），让后续 --step next-batch 能从顶部重新提取
      5. 连续 MAX_NO_NEW_ROUNDS 轮刷不出新货 → truly_exhausted=True，停止并汇报

    返回:
        dict: {
            "ok": bool, "refresh_round": int, "current_ids": int,
            "new_ids": list, "new_count": int,
            "no_new_rounds": int, "truly_exhausted": bool, "reason": str,
        }
    """
    _load_state()
    seen = _load_seen_job_ids()
    before = len(seen)

    _state["refresh_round"] = _state.get("refresh_round", 0) + 1
    rnd = _state["refresh_round"]
    print(f"\n[刷新] ═══ 第 {rnd} 轮刷新补量 ═══")
    print(f"[刷新] 频道: {CHANNEL_TAB} | 城市码: {city_code} | 已见岗位: {before} 条")

    url = f"{RECOMMEND_URL}?city={city_code}" if city_code else RECOMMEND_URL
    navigate(url, wait_range=(6, 8))
    time.sleep(2)

    use_default = _is_default_channel(CHANNEL_TAB)
    if use_default:
        print("[刷新] 默认推荐模式，跳过频道点击")
    else:
        switched = _click_algorithm_channel()
        print(f"[刷新] 频道点击: {switched}")
        if not switched.startswith("clicked:"):
            _state["no_new_rounds"] = _state.get("no_new_rounds", 0) + 1
            _save_state()
            return {
                "ok": False, "refresh_round": rnd, "current_ids": 0, "new_ids": [],
                "new_count": 0, "no_new_rounds": _state["no_new_rounds"],
                "truly_exhausted": _state["no_new_rounds"] >= MAX_NO_NEW_ROUNDS,
                "reason": f"频道标签未命中({switched})",
            }
        time.sleep(4)

    # 滚动把首屏之外的卡片加载出来
    for i in range(REFRESH_SCROLLS):
        scroll_page()
        time.sleep(random.uniform(0.8, 1.4))
    time.sleep(RENDER_WAIT)

    current = _current_job_ids()
    new_ids = [j for j in current if j not in seen]
    cards = _count_cards()

    if new_ids:
        _state["no_new_rounds"] = 0
    else:
        _state["no_new_rounds"] = _state.get("no_new_rounds", 0) + 1
    _state["last_refresh_new"] = len(new_ids)

    truly = _state["no_new_rounds"] >= MAX_NO_NEW_ROUNDS

    # 重置滚动/提取进度（保留刷新轮次），让 next-batch 从顶部重新提取本轮新货
    _state.update({
        "total_cards": cards,
        "total_extracted": 0,
        "total_scrolls": 0,
        "exhausted": False,
        "exhaust_reason": "",
        "batch_num": 0,
    })
    _save_state()

    print(f"[刷新] 本页岗位 {len(current)} 条（卡片计数 {cards}）")
    print(f"[刷新] ★ 本轮新货 {len(new_ids)} 条（去重基准 {before} 条）")
    print(f"[刷新] 连续无新货轮数: {_state['no_new_rounds']}/{MAX_NO_NEW_ROUNDS}")

    if truly:
        print(f"[刷新] ★★★ 连续 {MAX_NO_NEW_ROUNDS} 轮刷新无新岗位 → 判定【真穷尽】★★★")
        print(f"[刷新] ★ 请停止补量并向用户汇报；不要换频道、不要换城市、不要走搜索页")

    return {
        "ok": True,
        "refresh_round": rnd,
        "current_ids": len(current),
        "new_ids": new_ids,
        "new_count": len(new_ids),
        "no_new_rounds": _state["no_new_rounds"],
        "truly_exhausted": truly,
        "reason": "ok" if new_ids else "本轮无新岗位",
    }


# ═══════════════════════════════════════════════════════════
# 兼容旧API — exhaust_lazy_load 保留但标记为废弃
# ═══════════════════════════════════════════════════════════

def exhaust_lazy_load(max_scrolls=MAX_TOTAL_SCROLLS, stable_threshold=STABLE_THRESHOLD,
                      progress_callback=None):
    """[已废弃] 一口气下拉到底 — v4.4 改为分批模式，请用 scroll_next_batch()

    保留仅为向后兼容，内部循环调用 scroll_next_batch。
    """
    print("[穷尽] exhaust_lazy_load 已废弃，建议使用 scroll_next_batch() 分批模式")
    print("-" * 50)

    while not _state["exhausted"] and _state["total_scrolls"] < max_scrolls:
        result = scroll_next_batch()
        if progress_callback:
            progress_callback(_state["total_scrolls"], result["total_cards"], result["new_count"])

    return {
        "total_cards": _state["total_cards"],
        "total_scrolls": _state["total_scrolls"],
        "exhausted": _state["exhausted"],
        "reason": _state["exhaust_reason"],
    }


def main():
    """CLI 入口: 导航到推荐页 + 分批加载

    CLI模式会一次性跑完所有批次（仅用于测试）。
    正式投递时应该由上层编排逐批调用 scroll_next_batch()。
    """
    global BATCH_SIZE
    import argparse
    parser = argparse.ArgumentParser(description="推荐页导航 + 分批懒加载")
    parser.add_argument("--city", default=_PROFILE_CITY, help="城市编码 (从user_profile读取)")
    parser.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="每批目标岗位数")
    parser.add_argument("--reset", action="store_true", help="重置分批状态（新一轮开始时用）")
    args = parser.parse_args()

    BATCH_SIZE = args.batch_size

    if args.reset:
        reset_state()
        print("[CLI] 已重置状态，准备从头开始")

    if not health_check():
        print("WebBridge 不可达，请先运行 env_check.py")
        sys.exit(1)

    if not ensure_active_tab():
        print("无法建立标签页")
        sys.exit(1)

    # 1. 导航到推荐页
    if not navigate_to_recommend(args.city):
        print("导航到推荐页失败")
        sys.exit(1)

    # 2. 分批加载（CLI测试模式：一次性跑完）
    print(f"\n[CLI测试] 开始分批加载 (每批 {BATCH_SIZE} 条)")
    print("=" * 60)

    while not is_exhausted():
        result = scroll_next_batch()
        print(f"\n[批次{result['batch_num']}] 新增{result['new_count']}条, 累计{result['total_extracted']}条, 穷尽={result['exhausted']}")

    # 3. 汇总
    print("\n" + "=" * 60)
    print(f"分批加载完成:")
    print(f"  总批次: {_state['batch_num']}")
    print(f"  总卡片数: {_state['total_cards']}")
    print(f"  总提取数: {_state['total_extracted']}")
    print(f"  总滚动次数: {_state['total_scrolls']}")
    print(f"  是否穷尽: {_state['exhausted']}")
    print(f"  穷尽原因: {_state['exhaust_reason']}")
    print("=" * 60)


if __name__ == "__main__":
    main()
