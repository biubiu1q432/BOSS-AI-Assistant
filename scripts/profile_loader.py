#!/usr/bin/env python3
"""
中央配置加载器 — 所有用户信息从此模块获取，禁止在各脚本中硬编码。

★ 设计原则:
  1. 唯一数据源: user_profile.json
  2. 所有脚本通过 from scripts.profile_loader import XXX 获取用户信息
  3. 本模块不依赖任何其他技能模块（无循环导入风险）
  4. WORK_DIR 通过环境变量 BOSS_WORK_DIR 或当前目录自动解析（不新增 BOSS_DIR）。
     报告写入 WORK_DIR/投递汇总_YYYYMMDD_HHMMSS.html，可用投递汇总.html 作为最新副本。

用法:
    from scripts.profile_loader import (
        USER_NAME, CITY_CODE, TARGET_CITY, MIN_SALARY_K,
        DAILY_TARGET, SESSION_NAME, WORK_DIR, SKILL_DIR,
        SEARCH_KEYWORDS, CHANNEL_TAB, USER_PROFILE, get_llm_prompt,
    )
"""

import os
import json

# ═══════════════════════════════════════════════════════════
# 路径解析
# ═══════════════════════════════════════════════════════════

# 技能目录（自适应定位：脚本所在目录的父目录）
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 用户画像文件：默认保持原入口；可通过 BOSS_PROFILE 切换到 profiles/<name>.json
PROFILE_NAME = os.environ.get("BOSS_PROFILE", "").strip().lower()
PROFILE_ALIASES = {
    "integration": "integration",
    "system": "integration",
    "robot-integration": "integration",
    "algorithm": "algorithm",
    "algo": "algorithm",
    "hybrid": "hybrid",
    "mixed": "hybrid",
}
_PROFILE_KEY = PROFILE_ALIASES.get(PROFILE_NAME, PROFILE_NAME)
if _PROFILE_KEY:
    USER_PROFILE_FILE = os.path.join(SKILL_DIR, "profiles", f"{_PROFILE_KEY}.json")
else:
    USER_PROFILE_FILE = os.path.join(SKILL_DIR, "user_profile.json")

# 工作目录: 优先环境变量，否则使用当前目录
#   SKILL.md 指导用户 cd $workdir 后运行脚本，os.getcwd() 即为工作目录
#   多用户/多环境时可通过 BOSS_WORK_DIR 环境变量覆盖
WORK_DIR = os.environ.get("BOSS_WORK_DIR", os.getcwd())

# ═══════════════════════════════════════════════════════════
# 加载用户画像
# ═══════════════════════════════════════════════════════════


def _load_profile():
    """加载用户画像 JSON，返回 dict"""
    if not os.path.exists(USER_PROFILE_FILE):
        if PROFILE_NAME:
            raise FileNotFoundError(
                f"用户画像不存在: {PROFILE_NAME}（支持 integration / algorithm / hybrid）\n"
                f"期望文件: {USER_PROFILE_FILE}"
            )
        raise FileNotFoundError(
            f"用户画像文件不存在: {USER_PROFILE_FILE}\n"
            f"请参考 SKILL.md 创建 user_profile.json"
        )
    with open(USER_PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# 模块级加载 — import 时即读取
USER_PROFILE = _load_profile()

# ═══════════════════════════════════════════════════════════
# 从用户画像提取的配置变量
# ═══════════════════════════════════════════════════════════

# --- 用户身份 ---
USER_NAME = USER_PROFILE.get("user_name", "")
ROLE_SUMMARY = USER_PROFILE.get("role_summary", "")
EXPERIENCE = USER_PROFILE.get("experience", "")
DOMAIN_DESCRIPTION = USER_PROFILE.get("domain_description", "")

# --- 求职目标 ---
TARGET_CITY = USER_PROFILE.get("target_city", "")
TARGET_CITIES = USER_PROFILE.get("target_cities", [TARGET_CITY] if TARGET_CITY else [])
PROFILE_CITY_CODE = USER_PROFILE.get("city_code", "")
CITY_CODES = USER_PROFILE.get("city_codes", [PROFILE_CITY_CODE] if PROFILE_CITY_CODE else [])
# BOSS 页面一次只接受一个城市编码；运行时可用 BOSS_CITY_CODE 切换当前城市。
# ★ v5.6.7 护栏：见下方 _OVERRIDE_GUARD 说明，未经 BOSS_ALLOW_OVERRIDE=1 的
#   环境变量覆盖会被拒绝并回落到画像值。
_CITY_CODE_ENV = (os.environ.get("BOSS_CITY_CODE") or "").strip()
CITY_CODE = _CITY_CODE_ENV or PROFILE_CITY_CODE
MIN_SALARY_K = USER_PROFILE.get("min_salary_k", 0)

# --- 投递参数 ---
DAILY_TARGET = USER_PROFILE.get("daily_target", 50)
SESSION_NAME = USER_PROFILE.get("session_name", "boss-main")
INTERNSHIP_ONLY = USER_PROFILE.get("internship_only", False)

# --- 偏好 ---
PREFER = USER_PROFILE.get("prefer", [])
AVOID = USER_PROFILE.get("avoid", [])
PREFER_NO_BIG_COMPANY = USER_PROFILE.get("prefer_no_big_company", False)
PREFER_NO_HEADHUNTER = USER_PROFILE.get("prefer_no_headhunter", False)

# --- 搜索关键词（纯关键词，不含城市后缀）---
SEARCH_KEYWORDS = USER_PROFILE.get("search_keywords", [])

# --- 频道切换标签（可配置外部变量）---
# 刷新岗位界面时切换到的目标频道标签文本（如 "算法工程师（广州）"）。
# 赋值优先级（从高到低）：
#   1) 环境变量 BOSS_CHANNEL_TAB —— 对话中由 Agent 直接指定（无需改文件）
#   2) 画像 JSON 的 channel_tab 字段 —— 外部 JSON 文件赋值
#   3) 默认值 "算法工程师（广州）" —— 保持原有行为
# ★ v5.6.3 默认推荐模式：取哨兵值「推荐 / 默认 / default / __default__」时，
#   recommend_loader 跳过频道点击，直接使用推荐页默认岗位流（打开 URL 即在
#   「推荐」标签上）；不带城市后缀的核心词（如 "算法工程师"）由前缀匹配命中。
# ★ v5.6.7 护栏：环境变量覆盖需同时设 BOSS_ALLOW_OVERRIDE=1，否则拒绝并回落画像值
#   （详见下方 _OVERRIDE_GUARD 段）。
_CHANNEL_TAB_ENV = (os.environ.get("BOSS_CHANNEL_TAB") or "").strip()
CHANNEL_TAB = _CHANNEL_TAB_ENV or USER_PROFILE.get("channel_tab") or "算法工程师（广州）"

# ═══════════════════════════════════════════════════════════
# ★ v5.6.7 配置护栏（2026-10-13 事故防线）
# ═══════════════════════════════════════════════════════════
# 事故回顾：Agent 在「算法工程师(广州)」频道信息流滚完后，为了凑投递量，自行在命令里
# 加了 BOSS_CHANNEL_TAB=电气/自动化(广州)、BOSS_CITY_CODE 深→广→沪，把页面带到了
# 用户从未指定的频道与城市。用户明确要求：频道与城市以画像为准，要改必须先问。
#
# 制度性防线：环境变量覆盖 CHANNEL_TAB / CITY_CODE 必须同时显式声明
#   BOSS_ALLOW_OVERRIDE=1
# 否则一律拒绝覆盖、回落到画像值，并在终端打印醒目告警（留审计痕迹）。
# 这不是"禁止切换"，而是"让越权切换无法在无意中发生"。
ALLOW_OVERRIDE = os.environ.get("BOSS_ALLOW_OVERRIDE", "0") == "1"


def _guard(name, env_value, profile_value, fallback):
    """护栏核心：未授权的环境变量覆盖 → 拒绝并回落画像值。"""
    if env_value and not ALLOW_OVERRIDE:
        print("=" * 68)
        print(f"[护栏] ⛔ 拒绝未授权的配置覆盖: {name}={env_value!r}")
        print(f"[护栏]    画像约定值: {profile_value or fallback!r}")
        print(f"[护栏]    画像写的频道/城市就是约定；要改必须先取得用户明确指示，")
        print(f"[护栏]    并同时设置 BOSS_ALLOW_OVERRIDE=1 才能生效。")
        print("=" * 68)
        return profile_value or fallback
    return env_value or profile_value or fallback


CHANNEL_TAB = _guard("BOSS_CHANNEL_TAB", _CHANNEL_TAB_ENV,
                     USER_PROFILE.get("channel_tab"), "算法工程师（广州）")
CITY_CODE = _guard("BOSS_CITY_CODE", _CITY_CODE_ENV, PROFILE_CITY_CODE, PROFILE_CITY_CODE)

# --- 可选自定义排除列表 ---
C_EXCLUDE = USER_PROFILE.get("c_exclude", None)       # None = 使用 config_v3 内置默认值
T_EXCLUDE = USER_PROFILE.get("t_exclude", None)       # None = 使用 config_v3 内置默认值


# ═══════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════


def get_profile():
    """获取完整用户画像（副本）"""
    return USER_PROFILE.copy()


def get_work_dir():
    """获取工作目录（运行时重新解析，支持环境变量动态切换）"""
    return os.environ.get("BOSS_WORK_DIR", os.getcwd())


def get_llm_prompt():
    """生成 LLM 审核提示词（基于用户画像，不硬编码任何用户信息）

    提示词中的「目标岗位范围」来自 user_profile.json 的 domain_description 字段；
    若未填写该字段则自动由 prefer/avoid 拼接。

    返回:
        str: 完整的 LLM 审核提示词
    """
    prefer_str = ", ".join(PREFER[:8]) if PREFER else "无"
    avoid_str = ", ".join(AVOID[:10]) if AVOID else "无"
    big_company_note = "不要大厂/上市公司（已上市、2000人以上）" if PREFER_NO_BIG_COMPANY else "无限制"
    headhunter_note = "不要猎头岗位" if PREFER_NO_HEADHUNTER else "无限制"

    # ★ 领域描述：优先使用 domain_description，否则由 prefer/avoid 自动拼接
    if DOMAIN_DESCRIPTION:
        domain_section = DOMAIN_DESCRIPTION
    else:
        prefer_lines = "目标领域（偏好岗位）：" + (", ".join(PREFER) if PREFER else "不限")
        avoid_lines = "排除领域：" + (", ".join(AVOID) if AVOID else "无特定排除")
        domain_section = prefer_lines + "\n" + avoid_lines

    return f"""你是一位严格的岗位匹配审核专家。请根据候选人画像和岗位信息，判断该岗位是否适合投递。

【候选人画像】
- 姓名：{USER_NAME}
- 经验：{EXPERIENCE}
- 目标城市：{TARGET_CITY}
- 目标城市范围：{", ".join(TARGET_CITIES) if TARGET_CITIES else TARGET_CITY}
- 最低薪资：{MIN_SALARY_K}K
- 仅限实习：{"是" if INTERNSHIP_ONLY else "否"}
- 大厂偏好：{big_company_note}
- 猎头偏好：{headhunter_note}
- 偏重方向：{prefer_str}
- 排除方向：{avoid_str}

【目标岗位范围】
{domain_section}

【输入】
{{job_info}}

【输出格式】
必须严格按以下JSON格式输出，不要任何解释：
{{
  "decision": "APPROVE" | "REJECT" | "NEED_JD",
  "reason": "简短理由",
  "confidence": "high" | "medium" | "low"
}}

规则：
- APPROVE：岗位明显匹配目标领域，可直接投递
- REJECT：岗位明显不匹配或属于绝对不适合类别
- NEED_JD：从标题/行业无法明确判断，需要看JD详情再决定
- 如果仅限实习，正式全职、社招或长期全职岗位必须 REJECT；只有实习生、实习、校招实习或明确短期实习岗位才可继续判断
- 如果不确定，宁可REJECT也不要勉强APPROVE
"""


# ═══════════════════════════════════════════════════════════
# 版本信息
# ═══════════════════════════════════════════════════════════

__version__ = "1.0.0"
__updated__ = "2026-08-04"
