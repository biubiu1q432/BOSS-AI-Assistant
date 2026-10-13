# 版本迭代日志 — BOSS直聘自动化投递技能

> **维护约定（2026-10-12 起生效）**
> 每次版本迭代完成后，从「产品迭代视角」系统补充本日志：记录本次变更的要点、功能改动、影响范围、目的与价值，并覆盖**全部代码文件、skill 文档与 `references/` 资料**，以保障项目可维护性与可追溯性。
> **版本号口径**：本日志采用技能内部发布号（`v5.x`）。技能根目录 `_meta.json` 中的 `"version": "26.8.5"` 为**应用市场发布号**，与内部迭代号相互独立，不在此日志追踪范围内。

## 如何阅读

- 第一章「项目资产清单」是全部资产的职责与状态基线；每次迭代只更新发生变更的条目，未变更条目保留角色说明以维持可追溯。
- 第二章「迭代记录」倒序排列；每条含：迭代目的与价值 / 功能改动（按**代码文件、skill 文档、references** 三类）/ 影响范围 / 验收与验证。
- 历史大版本（v5.6 及以前）的详细维护说明仍以 `SKILL.md` 为准，本日志只保留目的与影响索引。

---

## 一、项目资产清单（职责与状态基线）

### 1.1 Skill 文档与配置

| 资产 | 职责 | 最近变更 |
|------|------|----------|
| `SKILL.md` | 技能主文档：架构总览、三层循环执行流程、画像切换、约束、版本历史与维护说明 | v5.6.5（新增批量投递加速器 batch_deliver.py + 抬头/版本历史/维护说明同步） |
| `_meta.json` | 应用市场元数据（ownerId / slug / 市场版本号 26.8.5），与内部迭代号独立 | 市场发布，非迭代追踪对象 |
| `user_profile.json` | 默认用户画像（唯一数据源之一）；v5.6.1 将 `prefer_no_big_company` 置 false（实习不排大厂） | v5.6.1 |
| `profiles/algorithm.json` `hybrid.json` `integration.json` | 三套预设实习画像（机器人算法 / 系统集成 / 综合），同将 `prefer_no_big_company` 置 false | v5.6.1 |
| `boss_applied.json` | 已投递岗位计数/记录（当前为空数组 `[]`），由投递流程维护 | 基线 |

### 1.2 代码文件（`scripts/`）

分类：**A** = 活跃三层循环架构（当前主流程调用）；**B** = 遗留五阶段 pipeline（独立/旧流程，未被当前三层循环调用）；**C** = 包基础设施。

| 文件 | 模块 / 职责 | 分类 | 最近变更版本 |
|------|------------|------|--------------|
| `profile_loader.py` | 中央配置加载器：读取 `user_profile.json` / 预设画像（`BOSS_PROFILE` 切换），导出 `WORK_DIR`、`DAILY_TARGET`、`CITY_CODE`、`CHANNEL_TAB`、`USER_PROFILE` 等全局常量 | A | **v5.6.7（新增配置护栏：环境变量覆盖 `BOSS_CHANNEL_TAB`/`BOSS_CITY_CODE` 必须同时设 `BOSS_ALLOW_OVERRIDE=1`，否则拒绝并回落画像值 + 打印审计告警）** |
| `env_check.py` | 环境自检 + 自动修复：校验 WebBridge、账户匹配（用户名/城市 vs 登录账户） | A | v5.6 架构 |
| `webbridge_client.py` | 共享 HTTP 客户端（端口 10086）：`api()` 重试、`extract_jobs()`、`decrypt_salary()`、`ProgressManager` 去重；投递证据与统计核心 | A | **v5.6.7（① 统一卡片选择器 `CARD_SELECTORS` 兼容 `li.job-card-box` + DOM 兜底，修"半盲"计数；② 新增 `is_verification_page()` 风控拦截检测）** |
| `recommend_loader.py` | 模块 C：推荐页导航 + 分批懒加载（★ v4.4 分批滚动 + 持久化 `batch_state`）；含频道点击（v5.6.2 起标签可配置 + 括号归一化匹配；v5.6.3 起默认推荐模式跳过点击；v5.6.4 起点击具体频道后不再被修复②城市重导冲掉） | A | **v5.6.7（① 新增 `refresh_feed()` 刷新补量——重新进频道取新一批并与已见 jobId 去重，连续 `MAX_NO_NEW_ROUNDS` 轮无新货才判真穷尽；② `_count_cards()` 改为按唯一 jobId 计数，消除 li/内层 div 双倍计数；③ `reset_state(full=)` 区分"开新一轮"与"刷新保留轮次计数"）** |
| `surface_cache.py` | 模块 D：批量读取左侧表面信息 → 缓存；`KEEP_FIELDS` 精简字段 | A | v5.6.1（修复③：city 重新纳入，7→8 字段） |
| `jd_reader.py` | 页面内原地点卡读 JD，写入 `current_jd.json` | A | v5.6.6（等待调优：scroll 1.5→1.0s、点击后 2→1.0s、verify max_wait 5→2.5s，修 K4 节流） |
| `deliver_engine.py` | 模块 F：页面内投递执行引擎（`deliver_inplace` / `check_delivery_target`），投递证据与状态判定 | A | v5.6.1（修复①④，核心）；v5.6.6（等待调优：点卡 verify 5→2.5s、弹窗后 2→1.0s、sent 1.5→1.0s、留此页 2→1.2s，修 K4 节流） |
| `report_builder.py` | 模块 G：生成时间戳 HTML 汇报（`投递汇总_*.html`），统一统计口径 | A | v5.6.1（仅模块抬头对齐） |
| `keyword_evolver.py` | 模块 H：AI 关键词进化 + 搜索导航（v5.0 NEW），驱动外层循环换词 | A | v5.0（v5.6.1 未变） |
| `serial_loop.py` | 模块 I：三层循环主控制器（CLI `--step init/next-batch/**refresh**/read/decide/evolve/status/finish`），信号文件与 `run_id` 边界 | A | **v5.6.7（① 新增 `--step refresh` 刷新补量步骤；② 滚动穷尽不再直接推 `evolve` 搜索路线，改为引导 `refresh`；③ `step_read` 前置风控拦截检测；④ `init` 用 `reset_state(full=True)` 清刷新计数）** |
| `batch_deliver.py` | 模块 I+：批量投递加速器（v5.6.5 新增）；复用 serial_loop 的读卡+读JD+决策+投递全链路，内置保守规则引擎 `screen()`（拒绝信号命中即 REJECT、不确定转 NEED_REVIEW、绝不盲目投），含同公司重复拦截与已投递记录跳过（`stream_progress.json`）防二次投递；`--apply` 真实批量投递、`--dry-run` 仅预览；v5.6.6 新增 `--report` 规则回测（闭环反馈 P6） | A | **v5.6.7（① 每条前置风控拦截检测，命中安全验证页立即停批；② 连续 3 条 READ_FAILED 时自动区分"风控拦截"与"虚拟滚动窗口已过"并给出对应处置）** |
| `build_jd.py` | 模块 I+ 辅助（v5.6.6 新增）：离线优先构建 `jd_to_read.json`——从当前页面卡片取 jobId（去 `.html` 后缀）→ 关联 `surface_cache` 取城市/公司 → 仅留目标四城；修正 v5.6.5 实测 jid 含 `.html` 失配导致全量跨城跳过（K5）；新增 `--append` 多轮 `next-batch` 累积扩量（P5） | A | **v5.6.7（① 城市/公司/薪资支持实时 DOM 兜底，`surface_cache` 无记录不再全量误判跨城；② `surface_cache.json` 缺失时降级为空而非崩溃；③ 字段取值优先级改为 Vue 解密值优先，修 DOM 薪资字体反爬乱码）** |
| `ensure_webbridge.py` | 模块 0（v5.6.6 新增）：WebBridge 守护进程健康检查与自愈辅助——探测 `/command` 在线、离线清理残留 `daemon.pid` 并提示用 `run_in_background` 托管起守护进程；消除「误报不可达 / 残留 pid 阻塞 / 跨调用被清理」三类环境故障（K2/K3） | A | v5.6.6（新增） |
| `phase1_collect.py` | Phase 1 统一采集（遗留五阶段）：WebBridge 搜索 + Vue 提取 + 薪资解密 | B | 基线（v1 采集） |
| `phase2_screen.py` | Phase 2 统一机械筛选（遗留）：薪资 / 城市 / 猎头 / 标题硬条件 | B | 基线 |
| `phase5_deliver.py` | Phase 5 统一投递执行 v2（遗留）：页面反馈监测、每日上限检测 | B | v2（基线） |
| `config_v3.py` | 统一配置 v5（遗留五阶段共用）：从 `profile_loader` 读全部画像，机械预筛硬条件，`C_EXCLUDE`/`T_EXCLUDE` 可定制 | B | v5（基线） |
| `cleanup.py` | BOSS 自动缓存清理 v1：保留最近 N 个 pipeline_state / phase 中间文件 / apply 报告，删 3 天前 archive；不动 `boss_applied.json` | B | v1（基线） |
| `__init__.py` | `scripts` 包标记 | C | 基线 |

### 1.3 参考资料（`references/`）

| 文档 | 职责 | 最近变更 | 状态 |
|------|------|----------|------|
| `operations.md` | 当前操作手册 v5.6：14 步操作契约 + 正例 + 验收；指向 `archive/operations-pre-v5.6.md` | v5.6（2026-10-12） | 有效，v5.6.3 同步默认推荐模式（step 2） |
| `pitfalls.md` | v5.6 投递与维护反例表（14 类坑 + 正确处理）；指向 `archive` 旧版 | v5.6（2026-10-12） | 有效，v5.6.1 未改 |
| `filtering.md` | 当前实习画像筛选规则：实习限定、薪资单位、排除词分层、候选仅限本轮当前页 | v5.6（当前版） | 有效，v5.6.1 未改 |
| `dom_structure.md` | BOSS DOM 实测结构（2026-06-13）：易错选择器对照表、提取 JS、投递按钮定位、snapshot vs evaluate | 2026-06-13 基线 | 有效，v5.6.1 未改 |
| `salary_decrypt.md` | 薪资字体加密（`@font-face` woff2）与解密公式（2026-06-15 修正 off-by-one） | 2026-06-15 基线 | 有效，v5.6.1 未改 |
| `delivery_retro.md` | 两轮投递复盘与效率提升方案（v5.6.6 新增）：还原时间线、耗时对比、根因定位（流程/等待/资源/执行顺序）、K1–K6 问题表、P1–P6 方案表、持续升级闭环 | v5.6.6（2026-10-12） | 有效，新增 |
| `rule_metrics.md` | 规则引擎回测指标（v5.6.6 新增）：每次批量运行后记录 verdict 分布与投递健康度，作为调 `ROBOTICS_TOKENS` / 排除词的闭环信号 | v5.6.6（2026-10-12） | 有效，新增（由 `batch_deliver.py --report` 追加） |
| `diagnosis_playbook.md` | 自动化诊断作战手册（2026-10-12 深夜新增）：出问题时定位根因的经验单——死会话假象 / 每日沟通上限模态 / 模型不能看截图 / 推荐页面板间歇性卡 loading / 首联与续联点击差异，含快速诊断 SOP；6 张经验单均经 `evaluate` DOM 文本证据验证，非截图推断 | 2026-10-12 深夜 | 有效，新增（文档补强，无代码改动） |
| `error_rules.md` | **真实事故规则归档（2026-10-13 新增）**：按错误类型分节（A 供给与滚动 / B 配置与越权 / C 执行编排 / D 风控与账号安全 / E 候选池与数据 / F 判定与证据 / G 运行时与进程），每条「错误做法 → 后果 → 正确做法 → 验证」四行，只收今日真实发生并已验证的事故；节内按出错频率降序。追加规则：新事故加对应节末尾、不改已有编号、无证据不入库 | 2026-10-13 | 有效，新增（由 `SKILL.md` 高频红线引用） |

---

## 二、迭代记录（倒序）

### 规则沉淀（2026-10-13 21:1x）— 事故规则归档（无代码改动）

**目的与价值**：把当日真实犯过的错误从"口头教训"变成"执行前可对照的清单"，并让 `SKILL.md` 瘦身——主文档只留触发条件、核心流程与高频红线，完整案例下沉到 `references/`。

**改动 — references**

- 新增 `references/error_rules.md`：按错误类型分节归档（A 供给与滚动 / B 配置与越权 / C 执行编排 / D 风控与账号安全 / E 候选池与数据 / F 判定与证据 / G 运行时与进程），共 13 条；每条「错误做法 → 后果 → 正确做法 → 验证」四行，祈使句，附可核验证据（330 张卡、护栏 ⛔、`已处理 0/34`、wave2 的 20 条 READ_FAILED 等）。节内按出错频率降序，A 类（供给误判）置顶——它直接诱发了 B、C 两类错误。
- 文件头写明维护约定：新事故加对应节末尾、不改已有编号与结论、无证据不入库。

**改动 — skill 文档**

- `SKILL.md` 新增「高频红线（必须做 / 禁止做）」章节：8 条必须做 + 7 条禁止做，全部祈使句、可核验，并在开头指向 `references/error_rules.md`。既有章节（画像切换、核心原则、架构总览、三层循环、版本历史、各版维护说明）**全部保留，未删改**。
- `SKILL.md` 参考资料索引行补入 `error_rules.md`。

**影响范围**：纯文档，不影响任何代码路径与 CLI 行为。

### v5.6.7（2026-10-13）— 刷新补量 + 配置护栏 + 风控拦截检测

**迭代目的与价值**

用户当日两次指出严重问题并要求整改：① 页面被带到「电气/自动化(广州)」频道，而画像明确配置「算法工程师（广州）」——Agent 越权覆盖了 `BOSS_CHANNEL_TAB` / `BOSS_CITY_CODE`；② 用户指出「昨天我在算法工程师频道下不断刷新就有新岗位，今天你为什么没刷新？明显是没刷新导致岗位耗尽」——**技能缺少"刷新补量"能力**，滚动到底即判"穷尽"，逼得 Agent 去换频道/换城市/走搜索页。

本迭代把这两类问题从"靠人记住"变成"代码级不可绕过"：补上刷新补量通路、给配置加护栏、给风控加检测。价值是**让自动化在供给耗尽时自己有合法出路，从而不再需要越权**。

**根因定位（2026-10-13 实测证据链）**

| # | 根因 | 实测证据 |
|---|------|----------|
| R1 | **无刷新补量通路**：`scripts/` 内零 refresh/reload 实现（grep 仅命中注释）。BOSS 频道流每次**重新进入**都会换一批岗位（用户实测），但旧版只有"滚动"一种补量手段，滚到底就 `exhausted=True` | `batch_state.json`：`total_cards=15, total_scrolls=8, exhausted=true, reason='连续4次无新增'` |
| R2 | **穷尽后引导错误**：`next-batch`/`decide` 穷尽时统一推 `--step evolve`（搜索页路线）。而搜索页点卡片会**跳转** job_detail，`step_read` 依赖"原地加载右侧面板"，实测 ~100% READ_FAILED——把 Agent 推向死路 | 2026-10-13 实测：搜索页每 15 条仅成功 1 条 |
| R3 | **卡片选择器"半盲"**：`extract_jobs`/`_count_cards` 硬编码 `.job-card-wrap`，改版后真实容器还包含 `li.job-card-box`。旧口径只看到 15 张卡，统一后同页面看到 30 张 | init 输出：修复前 15 → 修复后 30 |
| R4 | **卡片计数双倍虚高**：`li.job-card-box` 内还套 `div.job-card-wrap`，按元素数计数把 45 个岗位数成 90，虚高的"新增"会**掩盖真穷尽** | refresh 输出：`本页岗位 45 条（卡片计数 90）`→ 修正后 45=45 |
| R5 | **越权改配置无防线**：`BOSS_CHANNEL_TAB` / `BOSS_CITY_CODE` 可无条件覆盖画像值 | 日志 `clicked:电气/自动化(广州)` |
| R6 | **风控拦截被误判成"卡片不在 DOM"**：高频读 JD 会触发 BOSS 安全验证页 `passport/zp/verify.html`，此时 DOM 零卡片，全部 `no_link_match`；旧代码只会继续重试、硬撞风控 | 实测 `URL=.../web/passport/zp/verify.html`，`TITLE=安全验证 - BOSS直聘` |

**功能改动 — 代码文件（`scripts/`）**

| 文件 | 改动 |
|------|------|
| `recommend_loader.py` | ① 新增 `refresh_feed()`：重新导航 + 重点频道 → 滚动 `REFRESH_SCROLLS` 次 → 取当前页 jobId 与"已见集合"（`surface_cache` + `jd_to_read` + `stream_progress`）去重 → 输出本轮新货；连续 `MAX_NO_NEW_ROUNDS=3` 轮无新货判**真穷尽**并提示"停止汇报、严禁换频道/城市/搜索页"。② 新增 `_current_job_ids()`（Vue + DOM 双通道取 id）、`_load_seen_job_ids()`（三源去重基准）。③ `_count_cards()` 改为按**唯一 jobId** 计数（修 R4），并对齐统一选择器（修 R3）。④ `reset_state(full=)`：`init` 用 `full=True` 清刷新计数，`refresh` 用默认保留。⑤ `_state` 新增 `refresh_round` / `no_new_rounds` / `last_refresh_new` |
| `serial_loop.py` | ① 新增 `--step refresh` + `step_refresh()`，输出新货数与下一步指引。② `next-batch` / `decide` 穷尽引导由 `evolve` 改为 `refresh`，并显式注明"滚动穷尽只是这一屏滚完了，不是频道没岗位"（修 R2）。③ `step_read` 前置 `is_verification_page()` 检测。④ `step_init` 改调 `reset_state(full=True)` |
| `webbridge_client.py` | ① 新增常量 `CARD_SELECTORS = ".job-card-box, .job-card-wrap"`；`extract_jobs` 改为 Vue 优先 + **DOM 兜底**（无 `__vue__` 时按 `a[href*=job_detail]` 解析 title/city/company/salary），并打印 `mode=vue/dom` 便于观测。② 新增 `is_verification_page()` + `VERIFY_URL_MARKERS` / `VERIFY_TITLE_MARKERS`（修 R6） |
| `profile_loader.py` | 新增配置护栏 `ALLOW_OVERRIDE` / `_guard()`：未设 `BOSS_ALLOW_OVERRIDE=1` 时的 `BOSS_CHANNEL_TAB` / `BOSS_CITY_CODE` 覆盖一律**拒绝并回落画像值**，同时打印醒目审计告警（修 R5） |
| `batch_deliver.py` | ① 每条前置风控检测，命中即停批并提示人工验证。② 连续 3 条 READ_FAILED 时自动判定是"风控拦截"还是"虚拟滚动窗口已过"，分别给出处置建议 |
| `build_jd.py` | ① DOM 兜底城市/公司/薪资，`surface_cache` 无记录不再全量误判跨城（刷新新货此前会被整批跳过）。② `surface_cache.json` 缺失降级为空而非崩溃。③ 字段优先级改为 **Vue 解密值优先**，修 DOM 薪资字体反爬乱码（实测 `300-500元/天` 变乱码字形） |

**功能改动 — skill 文档**

- `SKILL.md`：版本号 5.6.6 → **5.6.7**（frontmatter `version` / 描述 / H1 / 版本历史表）；新增 `--step refresh` 到三层循环命令体系；新增「v5.6.7 维护说明」章节（背景、根因 R1–R6、改动、验收、强制纪律）。

**功能改动 — references**

- `diagnosis_playbook.md`：新增经验单「安全验证页 = 零卡片，勿误判为虚拟滚动」与「刷新补量是合法出路，不是换频道」。

**影响范围与兼容性**

- 全部为**增量改动**，未删除任何既有 CLI 步骤；`evolve` / `navigate-search` 仍保留（仅不再被穷尽分支自动推荐）。
- `BOSS_CHANNEL_TAB` / `BOSS_CITY_CODE` 的行为**发生变化**：未带 `BOSS_ALLOW_OVERRIDE=1` 时不再生效（这是有意的护栏）。既有 v5.6.3「默认推荐模式」用法需改为 `BOSS_ALLOW_OVERRIDE=1 BOSS_CHANNEL_TAB=推荐`。

**验收与验证（真实浏览器，2026-10-13 19:35–19:50，账号已登录）**

| 项 | 结果 |
|----|------|
| 编译 | 6 个改动脚本 `py_compile -W error::SyntaxWarning` 全通过 |
| 护栏 | 未授权 `BOSS_CHANNEL_TAB=电气/自动化(广州)` → ⛔ 拒绝，回落 `算法工程师（广州）`；带 `BOSS_ALLOW_OVERRIDE=1` → 正常生效 |
| init | `clicked:算法工程师(广州)`，初始卡片 **30**（修复前 15，验证 R3） |
| next-batch | 提取 60 条，含城市/行业字段，mode=vue |
| **refresh（新能力）** | 第 1 轮：本页 45 条，**新货 19 条**；第 2 轮：本页 45 条，**新货 25 条**；计数口径修正后 45=45 |
| build_jd | 34 候选（四城）/ 跨城跳过 26；薪资解密正常（`8-12K`、`180-200元/天`） |
| batch_deliver dry-run | APPROVE=11 REJECT=2 NEED_REVIEW=9 READ_FAILED=12 |
| **风控检测** | 运行中触发 BOSS 安全验证页 → 脚本立即输出 ⛔ 并停批（`已处理 0/34`），未硬撞验证 |

**v5.6.7 修订（2026-10-13 20:5x，用户指正）— 更正"刷新"的定位**

用户指出：「你要的是刷新岗位的话，一直滚列表就会出新的了，跟刷抖音一样，不明白你在说什么」。**用户是对的**，本条更正前文的定位偏差：

- **滚动才是主要供给方式**。BOSS 岗位列表是无限滚动，一路往下滚持续出新岗位，实测一次滚到 **330 张卡**。
- **此前"滚不出来"的真因不是缺刷新功能，而是两处代码缺陷**：① `_count_cards()` 选择器半盲（实际 30 张只数到 15，滚动后数字恒定 → 连续 4 次"无新增" → 假穷尽）；② `MAX_SCROLLS_PER_BATCH=8` 太小，每批只滚 8 次就停。两者叠加才诱发"频道耗尽"的误判与后续越权换频道。
- **修正**：`MAX_SCROLLS_PER_BATCH` 8 → **20**；`serial_loop.next-batch` 穷尽输出改为**先区分原因**（滚动配额用尽 vs 真的不再出货），只有后者才建议 `--step refresh`；SKILL.md 步骤 2b 与 `diagnosis_playbook` 经验单 8 改写为「滚动主力 / refresh 兜底」，并写明教训「报穷尽时先怀疑计数与滚动配额，不要先怀疑供给」。
- 编译校验通过；参数改动待下一轮真实浏览器校准实际吞吐。

**遗留与下一步**

- 本次 dry-run 的 12 条 READ_FAILED 已于事后定位为**风控拦截**（R6）而非虚拟滚动，风控解除后重跑即可收敛。
- 本迭代**未产生新的真实投递**（闭环测试只跑到 dry-run 即被风控拦停）；用户完成人工验证后按 `init → next-batch → refresh → build_jd --append → batch_deliver --apply` 推进日目标 150。
- NEED_REVIEW 负担 9/22 ≈ 41% 偏高，下一轮应回测 `screen()` 的 `ROBOTICS_TOKENS` 与排除词（`batch_deliver.py --report`）。

---

### 文档补强（2026-10-12 深夜）— 诊断作战手册（无代码改动）

#### 目的与价值
2026-10-12 深夜排查"16 条 failed 待恢复"时，因 WebBridge 会话 `tabs:[]`（死会话）导致一系列"面板卡 loading / 按钮失效"的假象诊断，又因模型不能直接看截图，误将"BOSS 每日沟通上限 150/天"弹窗当成"UI 变更破坏自动化"，浪费多轮诊断。为避免后续 agent 重蹈，把本次踩坑提炼为 `references/diagnosis_playbook.md` 结构化经验单（含快速诊断 SOP），全部条目经 `evaluate` DOM 文本证据验证。

#### 功能改动（按文档 / references 一类）
- **`references/diagnosis_playbook.md`（新增）**：6 张经验单（死会话假象 / 直连只读探测金标准 / 每日沟通上限模态 / 模型不能看截图 / 面板间歇性卡 loading / 首联续联点击差异）+ 快速诊断 SOP。
- **`SKILL.md`**：正文索引新增 `diagnosis_playbook.md` 链接（与 `operations.md` / `pitfalls.md` 并列）。
- **`CHANGELOG.md`**：资产清单 1.3 参考资料表新增 `diagnosis_playbook.md` 行；本段为唯一迭代记录。

#### 影响范围
仅文档层；不影响任何代码路径、投递逻辑与统计口径。建议后续给 `deliver_engine.py` 增加 `daily_limit` 检测分支（点击后立即延时扫 `body.innerText` 命中"沟通上限"即记 `blocked`/上限并停止当天空转），此为可选增强，不在本次文档改动内。

#### 验收与验证
新文档经人工审阅，条目与本会话 DOM 文本证据一致（如上限模态文案「您已达到沟通上限 您今天已与150位BOSS沟通，休息一下，明天再来吧～」由 MutationObserver + body.innerText 实锤）。

### v5.6.6（2026-10-12）— 两轮复盘后的效率加固（闭环迭代）

#### 迭代目的与价值
用户要求「全面复盘最近两轮投递 → 定位慢根因 → 形成可落地效率方案 → 继续迭代形成持续升级闭环」。v5.6.5 加速器本应消除第一轮瓶颈（逐条多轮 Agent 往返），但第二轮实测暴露**更致命的基础设施脆弱性**（守护进程易死 / health_check 与新 daemon 不兼容 / jid 失配导致构建 0 条），14 分钟 100% 消耗在环境恢复与 bug 修复，0 产出。本迭代据此把复盘 K/P 项落地为代码与流程：
- **P3 节流**：削减单条浏览器等待（jd_reader / deliver_engine），把单条读JD+投递的纯等待预算从约 14s 压到约 7s，逼近 DOM 稳定下限、不删校验步骤。
- **P4 稳构建**：`build_jd.py` 修正 jid 含 `.html` 失配（修 K5），离线优先取城市，跨城不占浏览器读。
- **P5 扩候选**：`build_jd.py` 新增 `--append`，支持多次 `next-batch` 累积候选池，逼近日目标 150。
- **P2/K2/K3 环境加固**：`ensure_webbridge.py` 探活 + 清残留 pid + 提示 `run_in_background` 托管；`health_check` 改探 `/command`（已修，兼容新 daemon）。
- **P6 闭环反馈**：`batch_deliver.py` 新增 `--report` 回测规则分布与投递健康度，写入 `references/rule_metrics.md`，作为调 token 的信号。

#### 功能改动
**A. 代码文件**
- `jd_reader.py`（节流）：`click_card_inplace` 滚动等待 1.5→1.0s、点击后等待 2→1.0s；`_verify_panel` 默认 `max_wait` 5→2.5s（轮询步长 1s 不变）。
- `deliver_engine.py`（节流）：`deliver_inplace` 点卡 `verify max_wait` 5→2.5s、首段等待 1→0.6s、弹窗后等待 2→1.0s、`sent_greeting` 1.5→1.0s、「留在此页」后等待 2→1.2s。
- `build_jd.py`（新增，P4/P5）：实时 DOM 取 jid（去 `.html`）→ 关联 `surface_cache` 取城市 → 仅留目标四城；新增 `--append` 与现有 `jd_to_read.json` 按 jobId 合并重排 `page_order`，支持多轮扩量。
- `ensure_webbridge.py`（新增，P2/K2/K3）：`health()` 探 `/command`；`--fix` 清理残留 `daemon.pid` 并提示用 `run_in_background` 托管 `start --foreground` 跨调用保活。
- `webbridge_client.py`：`health_check` 改探 `/command`（原 GET / 仅认 200/404，当前 daemon 对 / 返回 502 而 /command 正常，导致误报不可达）。
- `batch_deliver.py`：新增 `--report` 模式（P6），读 `stream_progress.json` + `batch_deliver_log.json` 计算 verdict 分布、自动化覆盖率、NEED_REVIEW 负担、投递成功率，追加至 `references/rule_metrics.md`。

**B. skill 文档**
- `SKILL.md`：frontmatter / 描述行 / H1 同步 v5.6.6；版本历史表新增 v5.6.6 行；新增「v5.6.6 维护说明」章节；架构总览新增 `build_jd.py` / `ensure_webbridge.py` 两个辅助模块。

**C. references**
- `delivery_retro.md`（新增）：两轮复盘与效率提升方案全文档（K1–K6 / P1–P6 / 闭环）。
- `rule_metrics.md`（新增，由 `--report` 追加）：规则回测指标表。

#### 影响范围
- 行为影响：节流仅缩短等待、不改变判定/校验逻辑（保守）；`build_jd --append` 为增量能力、默认覆盖行为不变；`--report` 只读不写投递数据；`ensure_webbridge` 仅探测/清理/提示，不起进程。
- 数据影响：新增 `references/rule_metrics.md`（追加式）；`jd_to_read.json` 在 `--append` 下结构不变（仅扩量 + 重排 `page_order`）。
- 兼容影响：与 v5.6.5 完全向后兼容；v5.6.4 实测链路（23 成功）不受影响。

#### 验收与验证（2026-10-12）
- 编译：5 个改动脚本 `py_compile -W error::SyntaxWarning` 全部通过。
- `--report` 离线验证：读取 `stream_progress.json`（成功 23 / 失败 0 / 成功率 100%）与历史 `batch_deliver_log.json`，正确输出 verdict 分布并追加 `rule_metrics.md` 一行。
- 节流幅度（理论）：单条读JD等待 ≈ 1.0(scroll)+1.0(click)+≤2.5(verify) ≈ 4.5s（原 8–9s）；单条投递等待 ≈ 0.6+1.0+1.0+1.2 ≈ 3.8s（原 ≈ 5.5s）。**待守护进程恢复后真实一轮校准实际提速比与校验通过率。**

#### 待验收 / 后续（闭环下一步）
- 守护进程恢复后跑通标准一轮：`ensure_webbridge` → `init` → 多次 `next-batch`+`build_jd --append` → `batch_deliver --dry-run` → 人工确认 NEED_REVIEW → `--apply` → `finish` → `--report`，用实际吞吐与 `--report` 指标校准 P1 真实提速比并回测规则精度。
- 若 `--report` 显示 NEED_REVIEW 负担过高（如 >40%），收紧 `ROBOTICS_TOKENS` / 排除词；若 APPROVE 过多且投递失败率上升，放宽验证或回退部分等待削减。

### v5.6.5（2026-10-12）— 批量投递加速器（速度提升，新增可选快速通道）

#### 迭代目的与价值
首次正式投递实测暴露「逐条 read → 写 decision.json → decide」的多轮 Agent 往返是**速度瓶颈**：27 条候选、23 条真实投递耗时约 25 分钟（单条 APPROVE 需多轮工具调用 + 人工/模型决策）；且每次 decide 后 `decision.json` 被清空需重写、同公司重复需人工识别。本迭代新增批量投递加速器 `batch_deliver.py`，把整批「读 JD + 决策 + 投递」压缩为**一次进程调用**；内置保守规则引擎 `screen()` 自动判定，仅 `NEED_REVIEW` 转人工复核，Agent 只在人工环节介入，从根本上提速，同时不降低质量（拒绝信号命中即 REJECT、不确定绝不盲目投）。

#### 功能改动
**A. 代码文件**
- `batch_deliver.py`（新增）：复用 `scripts.serial_loop` 的 `step_read`/`step_decide`/`step_finish` 与全局常量，保证进度/报告与三层循环一致；`screen(job, jd_text)` 规则引擎分级判定（跨城→REJECT；学历门槛/雇佣类型/排斥方向→REJECT；自动驾驶域无核心研发→NEED_REVIEW；无实习信号→NEED_REVIEW；无机器人域→NEED_REVIEW；其余 APPROVE）；含两道安全闸——① 同公司重复拦截（`approved_companies` 集合，本轮已投公司不再投，防骚扰）；② 已投递记录跳过（载入 `stream_progress.json` 的 `delivered`/`failed` jobId，重跑 `jd_to_read` 时 `SKIP` 防二次真实投递）。CLI `--apply` 真实批量投递、`--dry-run`（默认）仅预览判定。

**B. skill 文档**
- `SKILL.md`：frontmatter `version: "5.6.5"`；描述行与 H1 同步为 v5.6.5；版本历史表新增 v5.6.5 行；新增「v5.6.5 维护说明」章节（加速器用法 + 安全闸 + 速度收益）。

**C. references**
- 无（`operations.md` / `pitfalls.md` 步骤不变；加速器为可选快速通道，不改变既有三层循环契约与验收要求）。

#### 影响范围
- 行为影响：新增**可选**加速器，默认不启用（需显式 `--apply`）；不改变 `serial_loop` 既有任何行为；`--dry-run` 完全不投递、仅输出判定预览。
- 数据影响：无新增字段/文件（沿用 `jd_to_read.json` / `current_jd.json` / `decision.json` / `stream_progress.json`）；仅新增 `batch_deliver_log.json` 决策日志。
- 兼容影响：与 v5.6.4 完全向后兼容；首次正式投递的 23 条 success 记录被加速器识别为已投递并在重跑时跳过。

#### 验收与验证（2026-10-12）
- 编译：`batch_deliver.py` `py_compile -W error::SyntaxWarning` 通过。
- 规则引擎离线逻辑校验 8 例（覆盖否定实习边界「无实习」、域匹配、跨城、学历门槛、排斥方向、自动驾驶域、弱域转人工）→ **7/8 通过**；唯一不符为测试用例期望偏差（「视觉」属 `ROBOTICS_TOKENS`，对该「算法工程师+视觉+本科在读」判 APPROVE 为合理，非规则缺陷）。
- 防重复验证：载入 `stream_progress.json` 已投 23 条 → 重跑 `jd_to_read.json` 时全部 `SKIP`，不触发二次投递。

### v5.6.4（2026-10-12）— 修复频道点击被城市重导冲掉（缺陷修复）

#### 迭代目的与价值
用户以 `BOSS_PROFILE=integration` + `BOSS_CHANNEL_TAB=算法工程师（广州）` 发起正式投递，init 输出 `clicked:算法工程师(广州)` 后紧接「检测到城市参数丢失，重新以 city= 导航」「推荐页已加载」，页面实际停在「推荐」——v5.6.1 修复②在点击具体频道后仍无条件执行，URL 丢 `?city=` 即带 city 重新导航，整页重置回「推荐」默认态，把刚点的频道冲掉，频道聚焦功能在真实投递中失效。本迭代修复该冲突：修复②仅默认推荐模式生效，点击具体频道后信任频道、不再城市重导，使「点频道聚焦」在正式投递中真正落地。

用户语义澄清（本迭代前提）：频道标签「算法工程师(广州)」中的「广州」仅是标签文本、**非城市约束**；点击频道即完成「方向+城市」聚焦；城市无所谓（四个目标城市均可），无需为保城市参数牺牲频道。

#### 功能改动
**A. 代码文件**
- `recommend_loader.py`：`navigate_to_recommend` 先计算 `use_default = _is_default_channel(CHANNEL_TAB)`；修复②城市回退导航块包裹于 `if use_default:` —— 仅默认推荐模式（未点频道、城市过滤依赖 `?city=`）执行；点击具体频道后不再城市重导。模块文档补 v5.6.4 说明。

**B. skill 文档**
- `SKILL.md`：frontmatter `version: "5.6.4"`；描述行与 H1 同步；版本历史表新增 v5.6.4 行；新增「v5.6.4 维护说明」章节（含语义澄清与验收记录）。

**C. references**
- 无（operations.md 步骤 2 的频道/默认模式描述不受影响；城市重导行为为内部实现细节）。

#### 影响范围
- 行为影响：仅「点击具体频道」路径——不再触发城市回退导航，页面停留在所选频道；「默认推荐模式」路径行为不变（仍保留城市回退导航以保城市过滤）。
- 数据影响：无新增文件/字段；画像 JSON 不变。
- 兼容影响：默认值「算法工程师（广州）」路径即为本次修复的主受益路径；无破坏性变更。

#### 验收与验证（真实投递实测 · 2026-10-12 16:50–17:16）
- 实测：`BOSS_PROFILE=integration BOSS_WORK_DIR=Desktop/Internalship BOSS_CHANNEL_TAB=算法工程师（广州）` 运行 `--step init` → 输出 `clicked:算法工程师(广州)`，**无**「城市参数丢失重新导航」日志；截图确认顶栏「算法工程师(广州)」为选中态、岗位列表为机器人/算法岗。
- `--step next-batch` 在 `algorithm_channel` 页型下加载 75 条（含 city 字段）。
- 内层循环 27 条语义筛选（城市∈深广沪杭 + 仅实习 + 域匹配）：23 条 APPROVE 全部 `success - 已进入沟通界面`、4 条 REJECT（自动驾驶域×1、硕博门槛×1、智驾测试支持岗×1、同司重复岗×1）；`--step finish` 统计：累计唯一 23 / success 23 / fail 0，覆盖 8 行业，报告 `投递汇总_20261012_171610.html`。

### v5.6.3（2026-10-12）— 默认推荐模式（功能增强，v5.6.2 同迭代补充）

#### 迭代目的与价值
v5.6.2 实现频道标签可配置后，实测截图确认：打开 `/web/geek/jobs` 页面顶栏为「推荐（选中态）｜算法工程师(广州)｜电气/自动化(广州)｜+」，其中「推荐」是默认态、**非可点击频道**；可点击频道仅后两者。原版本 `navigate_to_recommend` 无条件点击频道，点击失败即 ERROR 中断，「不使用频道、直接用默认推荐流」这一常见场景无法支持。本迭代新增「默认推荐模式」：channel_tab 取哨兵值时跳过频道点击，直接使用推荐页默认岗位流，使「不指定方向用默认推荐 / 指定方向点频道聚焦」二者均由同一可配置变量控制，无需改代码。

#### 功能改动
**A. 代码文件**
- `recommend_loader.py`：新增 `DEFAULT_CHANNEL_SENTINELS = {"推荐","默认","default","__default__"}` 与 `_is_default_channel(tab)`；`navigate_to_recommend` 在频道点击前判定，命中哨兵则打印「默认推荐模式，跳过频道点击」并继续（不调用 `_click_algorithm_channel`、不触发 v5.6.1 修复②的城市回退导航——未点频道则 URL 不丢 `?city=`，城市过滤天然生效）。模块文档补 v5.6.3 说明。
- `profile_loader.py`：`CHANNEL_TAB` 注释补充默认推荐哨兵说明；默认值仍为「算法工程师（广州）」以保留既有行为（仅当画像/环境变量显式设哨兵值时进入默认推荐模式）。

**B. skill 文档**
- `SKILL.md`：frontmatter `version: "5.6.3"`；描述与版本历史表新增 v5.6.3；配置表 `channel_tab` 行补充哨兵值说明；约束 1「频道入口」改为「推荐为默认态、哨兵值跳过点击」；新增「v5.6.3 维护说明」章节。

**C. references**
- `operations.md`：步骤 2 同步「channel_tab 为「推荐」时跳过点击、使用默认推荐流」。

#### 影响范围
- 行为影响：init 频道处理逻辑分叉——哨兵值→跳过点击用默认推荐流；具体频道词→点击聚焦；默认值「算法工程师（广州）」保持原聚焦行为。
- 数据影响：无新增文件/字段；4 个画像 JSON 的 `channel_tab` 仍为「算法工程师（广州）」，不影响既有调用。
- 兼容影响：既有行为（未设哨兵值）完全不变；新增能力对历史流程零副作用。

#### 验收与验证（实测 · 2026-10-12 16:1x）
- 编译：`recommend_loader.py` / `profile_loader.py` `py_compile -W error::SyntaxWarning` 通过。
- 单元：`_is_default_channel` 对「推荐/默认/default/__default__」→ True，对空串与「算法工程师」→ False。
- 实测（Kimi WebBridge 真实浏览器，BOSS 已登录）：`BOSS_CHANNEL_TAB=推荐 BOSS_CITY_CODE=101280100 BOSS_PROFILE=algorithm` 运行 `--step init` → 输出「channel_tab='推荐' → 默认推荐模式，跳过频道点击，使用推荐页默认岗位流」，并成功加载 15 张卡片，**未触发**「城市参数丢失重新导航」（因未点频道），城市过滤天然生效。

#### 待验收 / 后续
- 若用户希望「未设置任何 channel_tab（连 JSON 字段都缺省）」也默认走推荐流，可将 `profile_loader.CHANNEL_TAB` 的最终兜底值由「算法工程师（广州）」改为哨兵值「推荐」；当前为保守保留既有聚焦默认，用户按需在画像/环境变量显式设哨兵值即可。

### v5.6.2（2026-10-12）— 频道切换标签可配置化（功能增强）

#### 迭代目的与价值
原 `recommend_loader._click_algorithm_channel()` 硬编码「算法工程师」前缀匹配，标签值写死在代码里；切换账号/方向时需改代码才能保持刷新界面目标岗位命中率。本迭代将其改造为可配置外部变量 `CHANNEL_TAB`，支持两种赋值方式（外部 JSON 文件 / 对话直接指定），提升可维护性与多账号适配能力。

#### 功能改动
**A. 代码文件**
- `profile_loader.py`：新增 `CHANNEL_TAB`，赋值优先级 环境变量 `BOSS_CHANNEL_TAB` > 画像 JSON `channel_tab` 字段 > 默认 `"算法工程师（广州）"`。
- `recommend_loader.py`：`_click_algorithm_channel()` 注入 `CHANNEL_TAB`（经 `json.dumps` 安全嵌入 JS），匹配前先归一化（DOM 标签与 `CHANNEL_TAB` 的全角括号 `（）`→半角 `()`、压缩多余空白），再按「精确相等 或 前缀包含（indexOf===0）」判定，稳定命中 DOM 真实标签「算法工程师(广州)」并兼容用户写「算法工程师」「算法工程师（广州）」「算法工程师(广州)」等任意写法；模块文档补 v5.6.2 说明。

**B. skill 文档**
- `SKILL.md`：frontmatter `version: "5.6.2"`；描述与版本历史表新增 v5.6.2；配置表新增 `channel_tab` 字段与 `BOSS_CHANNEL_TAB` 环境变量说明；「频道入口/核验/步骤 1」改为引用可配置 channel_tab；新增「v5.6.2 维护说明」章节。

**C. references**
- `operations.md` / `pitfalls.md`：同步「点击配置的频道标签（channel_tab）」，不再写死「算法工程师频道」。

#### 影响范围
- 行为影响：init 频道点击的标签文本由写死改为读取 `CHANNEL_TAB`；匹配经括号归一化 + 精确/前缀判定，兼容性优于原「前缀匹配」且不再因括号全/半角差异漏配。
- 数据影响：4 个画像 JSON 新增 `channel_tab` 字段（默认 `"算法工程师（广州）"`），不影响既有投递记录。
- 兼容影响：默认值与旧行为一致，未设置变量的既有调用完全向后兼容。

#### 验收与验证（实测 · 2026-10-12 15:4x）
- 编译：`profile_loader.py` / `recommend_loader.py` `py_compile -W error::SyntaxWarning` 通过（v5.6.2 修正后复测）。
- JSON：4 份画像解析通过；`CHANNEL_TAB` 默认解析为 `"算法工程师（广州）"`。
- **实测（Kimi WebBridge 真实浏览器，BOSS 已登录）**：
  1. 首轮 `init` 暴露缺陷：`algorithm channel action: not_found` —— DOM 真实标签为「算法工程师(广州)」（**半角括号**），而 `channel_tab` 配置为「算法工程师（广州）」（**全角括号**），v5.6.2 初版「精确/包含」匹配因括号类型不一致漏配。已修复（全角→半角归一化），复测 `init` 输出 `algorithm channel action: clicked:算法工程师(广州)`，频道切换成功。
  2. `next-batch` 在 `algorithm_channel` 页型下加载 47 条广州岗位；`read`→`decide(REJECT)` 内层循环通路正常（本轮回避真实投递）。
  3. 结论：**可配置频道标签功能符合预期**（环境变量 / JSON 两种赋值均生效，点击命中配置标签），但本账号该频道实时 feed 多为「数据挖掘 / 资深算法（全职）/ 销售 / 行政」等，**未出现匹配 `algorithm.json` 严格域（机器人算法 / 具身智能 / 实习限定）的岗位**，印证了用户原始诉求「刷新结果常不匹配」。故本轮未做真实 APPROVE 投递（避免向不匹配岗位发招呼），报告因无投递记录未生成（预期行为）。

#### 待验收 / 后续
- **账号画像一致性**：`profiles/algorithm.json` 当前 `city_code=101280600`（深圳），但 `channel_tab=算法工程师（广州）` 且账号真实频道标签均为「(广州)」，二者城市不一致。实测以 `BOSS_CITY_CODE=101280100`（广州）覆盖后频道点击与城市过滤才自洽；建议将 `algorithm.json.city_code` 改为 `101280100` 与频道对齐（或在对话中由 Agent 用 `BOSS_CITY_CODE` 指定）。
- 若 BOSS 实际频道标签文本与配置不一致（如括号差异），匹配规则（归一化 + 精确/前缀）可兼容；极端情况下由 Agent 用 `BOSS_CHANNEL_TAB` 实时纠正。
- 频道命中后仍无匹配实习岗时，按设计走 `evolve` → `navigate-search`（搜索关键词进化）以检索真实机器人/具身智能实习岗，提升命中率。

### v5.6.1（2026-10-12）— 快速实测暴露缺陷修复（维护补丁，不引入新流程）

#### 迭代目的与价值
在 v5.6 落地后的首次真实单岗位投递实测中，暴露出若干会导致「投递成功却被误判 unknown」与「混入跨城岗位」的缺陷，直接影响统计可信度与投递精准度。本迭代以「快速测试暴露的问题」为输入，定位根因并修复，价值在于：① 恢复投递成功判定的准确性（不再把已发送的招呼误判为 unknown）；② 保证城市过滤在频道切换后不丢失；③ 消除运行时 `SyntaxWarning` 噪音；④ 保持代码与文档版本号一致，提升可维护性。

#### 功能改动

**A. 代码文件**
- `deliver_engine.py`（核心，①④）：
  - **① 状态判定失效（最高优先级）**：根因是点击「留在此页」弹窗后按钮消失，`_chat_evidence` 读不到 `stay_btn` → `classify_delivery` 误判 `unknown`。修复：把过程标志 `stayed_on_page` 并入证据 `stay_btn`；新增 `_wait_delivery_outcome()` 轮询等待聊天页跳转（SPA 路径A）或原地「留在此页」确认（路径B），并实时检测每日上限；`_chat_evidence` 新增会话列表核验 `chat_list_match`（目标公司 + 送达/您好）作为权威成功信号；路径A 成功后自动返回岗位列表。
  - **④** 内联 JS 正则 `/\s+/` 所在 Python 普通字符串改为 raw string，消除 `SyntaxWarning: invalid escape sequence '\s'`。
- `recommend_loader.py`（②④）：
  - **② init 频道点击丢失城市参数**：`navigate_to_recommend` 频道点击后校验 URL 是否含 `city=`，缺失则带 city 重新 navigate 但**不二次点击频道**（二次点击会再次丢参）；仍失败仅告警，依赖 `surface_cache` 的 city 字段由 Agent 初筛剔除。
  - **④** `_click_algorithm_channel()` 选择器模板改 raw string 消转义告警。
- `surface_cache.py`（③）：`KEEP_FIELDS` 由 7 字段增至 8 字段，重新纳入 `city`（`extract_jobs` 已提供），使 `recommend_loader` 与 `surface_cache` 提取的岗位均带城市，支持初筛剔城。
- `serial_loop.py` / `report_builder.py` / `webbridge_client.py`：仅将模块文档抬头 `Skill v5.6` 对齐为 `Skill v5.6.1`（发布版本号一致），功能逻辑未变，内部 `v5.6 改进` 历史说明保留。
- 其余 12 个代码文件（含 `profile_loader.py` 被新增 import `CITY_CODE`、`env_check.py`、`jd_reader.py`、`keyword_evolver.py`、`phase1/2/5_*.py`、`config_v3.py`、`cleanup.py`、`__init__.py`）及 `user_profile.json` / `profiles/*` 本次**未变更**（角色见资产清单 1.2 / 1.1）。

**B. skill 文档**
- `SKILL.md`：frontmatter `version: "5.6.1"` 与描述首行更新；版本历史表新增 v5.6.1 行；新增「v5.6.1 维护说明」章节（①②③④ 修复细节 + ⑤⑥⑦ 非缺陷确认 + 实测验收）；更正架构总览中 `surface_cache` 字段数 7→8；H1 标题同步为 v5.6.1。

**C. references/**
- 初版 v5.6.1 代码迭代未改 references；**后续同版本文档协同补强（2026-10-12 15:1x）**对全部 8 个 reference 文件做了系统化梳理：① 为每份文件补「文件元信息」抬头（用途 / 职责范围 / 关联模块 / 维护状态）；② 修正 `salary_decrypt.md` 对不存在的 `phase1_extract.py` / `phase3_jd.py` 的引用，改为 `webbridge_client.decrypt_salary()` + `surface_cache` / `jd_reader`；③ `dom_structure.md` 的「Phase 1/5 使用」标注改为当前模块 `extract_jobs()` / `deliver_engine.deliver_inplace()`；④ `operations.md` / `pitfalls.md` 同步 v5.6.1 的 `stay_btn` / `chat_list_match` 权威成功证据（修正原「留在此页不参与判定」的反例）；⑤ `filtering.md` 补充 v5.6.1 大厂不排（`prefer_no_big_company=false`）与 `city` 字段跨城剔除说明；⑥ 3 个 `archive/` 文件加「冻结·禁止执行」抬头。详见下文本次梳理总结。

#### 影响范围
- **行为影响**：投递成功判定逻辑（`deliver_engine`）重写步骤 5–7；init 城市导航（`recommend_loader`）；缓存字段（`surface_cache`）增加 `city`。
- **数据影响**：`surface_cache.json` 既有记录新增 `city` 字段（向后兼容，旧记录无 city 不影响读取）；`stream_progress.json` 证据新增 `stay_btn` / `chat_list_match` 来源。
- **兼容影响**：仅抬头 / 文档版本号变更的文件对外行为零变化；遗留五阶段 pipeline（`phase*` / `config_v3` / `cleanup`）完全未触碰，互不影响。
- **用户画像影响**：`user_profile.json` 与三套预设画像的 `prefer_no_big_company` 在 v5.6.1 同期置 false（实习不排大厂），属配置调整而非代码改动。

#### 验收与验证（已实测通过）
- **①** 广州「SLAM 定位算法工程师」经 `--step decide` 后 `result=success`，证据 `stayed_on_page=true` / `stay_btn=true`（路径B 命中），对比修复前同路径误判 `unknown`。
- **②** init 后缓存 15 条岗位城市均为「广州」，城市过滤生效。
- **③** 缓存含 `city` 字段。
- **④** 全量 16 个脚本 `py_compile -W error::SyntaxWarning` 通过，无转义告警。
- 历史报告（修复前 `D:\boss-zhipin-run\投递汇总.html` 的「卧安机器人」unknown）按新规则迁移为 success 并重新生成，验证判定一致性。

#### 非缺陷确认（⑤⑥⑦）
- **⑤** 每次 decide 自动出报告：为升级功能，保留。
- **⑥** Edge 扩展 v2.0.15 落后 skill 市场版 2.0.23：仅信息提示，无代码改动。
- **⑦** 其他 agent 的记录：与本次技能无关，忽略。

---

### 历史版本索引（详细维护说明见 `SKILL.md` 版本历史）

- **v5.6（2026-10-12）**：修复维护文档编码；明确投递证据、去重统计、串行保护与验收契约。**目的**＝让维护文档与行为契约一致；**影响**＝确立当前三层循环的操作 / 反例 / 筛选基线（`operations` / `pitfalls` / `filtering` 三份 references 同步到 v5.6）。
- **v5.5（2026-08-05）**：`decision.json` 写入改为 `shell_executor` + Python 一行覆写，消除 `delete`+`write_file` 触发的循环确认弹窗。
- **v5.4（2026-08-04）**：100% 收尾保证——`target_met` / `fatal_limit` 自动 `finish` + `atexit` 兜底钩子，确保任意退出路径均生成投递汇总。
- **v5.3（2026-08-04）**：面向 GitHub 通用发布——去除硬编码用户画像，`user_profile.json` 为唯一数据源，LLM prompt 由 `domain_description` 驱动，排除列表可自定义，修复 `keyword_evolver` 城市名硬编码。
- **v5.2（2026-08-04）**：Marvis 适配版。
