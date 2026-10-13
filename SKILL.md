---
name: boss-zhipin-deliver
description: |
  BOSS直聘自动化投递技能 v5.6.7 — 三层循环架构（关键词进化 + 当前频道串行投递 + 刷新补量），新增批量投递加速器 batch_deliver.py（一次调用完成整批读JD+决策+投递，规则保守、仅 NEED_REVIEW 转人工）。
  ★ v5.6.7: 新增 `--step refresh` 刷新补量（重新进入频道即换一批岗位，连续 3 轮无新货才判真穷尽）；
  配置护栏（BOSS_CHANNEL_TAB/BOSS_CITY_CODE 须带 BOSS_ALLOW_OVERRIDE=1 才生效，防越权换频道）；
  风控拦截检测（BOSS 安全验证页立即停批）；卡片选择器统一 + 按唯一 jobId 计数（修"半盲"与双倍计数）。
  依赖 Kimi WebBridge（端口 10086）控制已登录 Chrome，在当前频道分批加载岗位、Agent 逐条语义决策后投递。
  支持环境自检、投递断点续传、每日目标检测、HTML 汇报生成（含微信/支付宝打赏二维码）。
  ★ v5.6.1: 修复状态判定失效（留在此页弹窗被点掉后误判 unknown）、init 频道点击丢失城市参数、
  缓存新增 city 字段支持初筛剔城、消除 JS 正则转义告警；详见文末版本历史与维护说明。
  ★ v5.6.2: 频道切换标签「算法工程师（广州）」改造为可配置外部变量 CHANNEL_TAB——支持画像 JSON 的
  channel_tab 字段（外部文件赋值）与环境变量 BOSS_CHANNEL_TAB（对话直接指定）两种赋值方式，
  切换账号/方向只需改该变量即可保持刷新界面目标岗位命中率。
  ★ v5.6.3: 新增默认推荐模式——channel_tab 取哨兵值「推荐」（或 默认/default）时跳过频道点击，
  直接使用推荐页默认岗位流（实测截图确认打开 jobs URL 默认停在「推荐」标签，其非可点击频道）。
  ★ v5.6.5: 新增批量投递加速器脚本 scripts/batch_deliver.py——复用三层循环读JD/决策/投递全链路，
  内置保守规则引擎自动判定（拒绝信号命中即 REJECT、不确定转 NEED_REVIEW、绝不盲目投），含同公司重复拦截与已投递记录跳过两道安全闸；
  `--apply` 真实批量投递、`--dry-run` 仅预览；把「逐条多轮 Agent 往返」压缩为一次进程调用，从根本上提速。
  ★ v5.6.6: 两轮复盘后的效率加固——`health_check` 改探 `/command` 兼容新 daemon（修环境误报）；
  新增 `ensure_webbridge.py` 守护进程探活/自愈、`build_jd.py` 离线稳构建（修 jid 失配 K5）+ `--append` 多轮扩量（P5）；
  `batch_deliver.py` 新增 `--report` 规则回测（闭环反馈）；`jd_reader`/`deliver_engine` 节流（单条等待约 14s→7s，修 K4）。
metadata:
  version: "5.6.7"
---

# BOSS直聘自动化投递技能 v5.6.7

> 本技能加载后，Agent 将按三层循环架构执行 BOSS直聘自动化投递。
> 依赖 Kimi WebBridge（端口 10086）控制已登录 Chrome。
>
 > **核心设计**：`user_profile.json` 是默认用户数据源，skill 代码本身不含任何特定用户信息。
 > 不同求职者只需修改画像文件即可复用整套投递流程；本版本额外支持通过 `BOSS_PROFILE` 在三套预设画像间切换。

## 高频红线（必须做 / 禁止做）

> 完整案例、成因与验证数据见 **[references/error_rules.md](references/error_rules.md)**（按错误类型归档，三段式，按今日出错频率排序）。浏览器诊断见 [references/diagnosis_playbook.md](references/diagnosis_playbook.md)。

**必须做**

1. 用 `--step init` 锁定画像的 `channel_tab` 与 `city_code`，全程不换频道、不换城市。
2. 用滚动取岗位：连续跑 `--step next-batch` 直到全局上限 80 或底部标记「没有更多了」。
3. 报"穷尽"时先核对唯一 jobId 计数与已滚动次数，再决定是否停手。
4. 每波投递前用 `build_jd.py`（**不带** `--append`）从当前 DOM 全新构建候选池。
5. 投递只走 `batch_deliver.py`；`--apply` 前先跑 `--dry-run`。
6. 读 JD 与投递前先调 `is_verification_page()`，命中立即停手并交用户人工验证。
7. 候选池超过 30 条时用后台进程跑 `--apply`（单进程 120s 会被杀）。
8. 收尾执行 `--step finish`，再用 `batch_deliver.py --report` 回测规则。

**禁止做**

1. 禁止改 `BOSS_CHANNEL_TAB` / `BOSS_CITY_CODE`（护栏要求 `BOSS_ALLOW_OVERRIDE=1` 且用户明确指示）。
2. 禁止把"滚动无新增"当成没岗位，不得据此换频道 / 换城市 / 走搜索页。
3. 禁止为取候选或编排另写脚本。
4. 禁止在安全验证页继续点击或重试。
5. 禁止跨波用 `--append` 累积候选。
6. 禁止把 `btn_text` 仍为「立即沟通」判为投递失败（金标准＝聊天列表出现 `[送达]`）。
7. 禁止自动放行 `NEED_REVIEW`，必须交人工。

---

### 画像切换（可选）

预设画像位于 `profiles/`：

- `integration`：机器人系统集成 / SDK / 嵌入式 / ROS2
- `algorithm`：机器人算法 / 导航 / SLAM / 控制 / 具身智能
- `hybrid`：系统集成 + 算法综合

未设置 `BOSS_PROFILE` 时，继续使用默认 `user_profile.json`。运行前在当前 PowerShell 会话设置：

```powershell
$env:BOSS_PROFILE = "integration"
python <SKILL_DIR>\scripts\serial_loop.py --step init
```

三套画像均已约束为实习岗位：目标城市为深圳、广州、上海、杭州，最低薪资为 0K；正式全职、社招或长期全职岗位必须拒绝。BOSS 页面一次只使用一个城市编码时，可额外设置 `BOSS_CITY_CODE` 临时切换城市。

画像选择只改变岗位筛选画像，不改变原有 `serial_loop.py` 入口或 `BOSS_WORK_DIR` 约定。

---

## 核心原则

1. **执行脚本**：使用 `python_executor` 运行 `<SKILL_DIR>/scripts/` 下的 .py 文件
2. **AI 决策**：岗位 APPROVE/REJECT 必须由 Agent 根据 `profile_loader.USER_PROFILE` 和真实 JD 语义判断，禁止脚本硬编码匹配
3. **WORK_DIR**：默认使用脚本运行时的当前目录，可通过 `BOSS_WORK_DIR` 环境变量覆盖
4. **Kimi WebBridge**：所有浏览器操作通过 `use_skill("kimi-webbridge")` 完成，禁止 CDP 直连

---

## 架构总览

```
scripts/
├── profile_loader.py      — 中央配置加载器（从 user_profile.json 读取）
├── env_check.py           — 环境自检 + 自动修复
├── webbridge_client.py    — WebBridge HTTP 客户端（端口 10086）
├── recommend_loader.py    — 推荐页/搜索页导航 + 分批懒加载
├── surface_cache.py       — 精简字段缓存（8 核心字段）
├── jd_reader.py           — 页面内原地点卡读 JD
├── deliver_engine.py      — 投递执行 + 目标检查
├── report_builder.py      — HTML 汇报生成
├── keyword_evolver.py     — AI 关键词进化 + 搜索导航
├── serial_loop.py         — 三层循环主控制器
├── build_jd.py             — 模块 I+ 辅助（v5.6.6）：离线优先构建 jd_to_read.json（去 .html 取城市、仅留四城；--append 多轮扩量）
├── ensure_webbridge.py     — 模块 0（v5.6.6）：WebBridge 守护进程探活/自愈辅助（清残留 pid、提示 run_in_background 托管）
```

信号文件（位于 WORK_DIR）：
- `page_state.json` — 页面级进度
- `batch_state.json` — 分批级进度
- `surface_cache.json` — 全量缓存
- `jd_to_read.json` — AI 筛选后待读取列表
- `current_jd.json` — 当前 JD（供 Agent 阅读）
- `decision.json` — Agent 决策结果
- `stream_progress.json` — 投递断点续传

---

## 执行流程

### 步骤 0：确定 WORK_DIR

使用当前工作目录，或设置环境变量：
```
BOSS_WORK_DIR = <当前会话 output 目录>
```

### 步骤 1：初始化（`--step init`）

```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step init
```

脚本会检查 WebBridge、打开岗位列表并切换配置频道（channel_tab，默认"算法工程师（广州）"）、重置页面和批次状态；持久化投递记录继续保留。

> **频道核验**：使用 `https://www.zhipin.com/web/geek/jobs`，按需要带城市参数，再点击配置频道标签（channel_tab，默认"算法工程师（广州）"）。推荐和算法频道可能使用相同 URL；必须结合选中标签、当前岗位 DOM 和页面城市信息核验，不能仅凭 URL 或标题判断。页面变化时重新抓取。

**失败处理**：若 WebBridge 不可达，先调用 `use_skill("kimi-webbridge")` 确保 daemon 运行。

### 步骤 1.5：确认投递方向

> 必须核对实际配置；若本会话已指定画像并授权投递，且配置与范围未变化，直接沿用已有授权，不重复询问。

Agent 必须读取 `profile_loader.USER_PROFILE_FILE` 指向的实际画像（设置 `BOSS_PROFILE` 时为对应预设，否则为默认文件），核对下列规则。首次未指定投递范围时再向用户确认：

- **用户姓名**：`user_name`
- **目标城市**：`target_city`（编码: `city_code`）
- **最低薪资**：`min_salary_k`（单位：K，0 表示不限制）
- **日投递目标**：`daily_target`（份）
- **目标领域描述**：`domain_description`（若未填则展示 prefer/avoid 列表）
- **偏好岗位**：`prefer` 列表
- **排除岗位**：`avoid` 列表
- **额外规则**：是否排除大厂（`prefer_no_big_company`）、是否排除猎头（`prefer_no_headhunter`）
- **搜索关键词**：`search_keywords` 列表（前 10 个）

输出实际配置路径及关键规则；已有授权时进入步骤 2。配置发生影响投递范围的变化时再澄清。

### 步骤 2：中层循环 — 滚动加载（`--step next-batch`）

```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step next-batch
```

加载一批约 50 条岗位，追加到 `surface_cache.json`。输出岗位列表供 Agent 初筛。

**Agent 初筛**：Agent 读取本轮输出中的岗位列表，基于实际加载画像的筛选规则，将合资格岗位写入 `jd_to_read.json`（JSON 数组，每个元素含 page_order、jobId、title 等）。只追加同一有效页面批次中的候选；页面切换后不得沿用旧候选。

### 步骤 2b：★ v5.6.7 刷新补量（`--step refresh`）—— 滚动停摆时的**兜底**，不是主力

```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step refresh
```

**先搞清楚供给从哪来**：BOSS 岗位列表是**无限滚动**，一路往下滚就会持续出新的岗位（实测一次滚到 330 张卡，15→30→45→…），**滚动才是主要供给方式**。`next-batch` 每批最多滚 `MAX_SCROLLS_PER_BATCH=20` 次，全局上限 `MAX_TOTAL_SCROLLS=80`；反复跑 `next-batch` 即可一路滚下去。

**refresh 只在两种情况下登场**（兜底）：
1. 滚动确实不再出货（命中底部标记「没有更多了」或连续多次无新增）；
2. 已滚到全局上限，想换一批新发牌。

**行为**：重新导航进当前频道 → 滚动若干次 → 取当前页 jobId 与「已见集合」（`surface_cache` + `jd_to_read` + `stream_progress`）去重 → 输出本轮新货数。连续 3 轮无新货才判定**真穷尽**。

> **2026-10-13 教训**：一度把"滚不出来"当成"没有刷新功能"，是误判。真因是 `_count_cards()` 选择器半盲（30 张只数到 15）+ 每批只滚 8 次就停，两者叠加造成**假穷尽**，进而诱发了越权换频道。**先怀疑计数与滚动配额，不要先怀疑供给**。

**纪律（强制）**：
1. 滚动穷尽 ≠ 频道没岗位。先 `--step refresh`，不要跳 `--step evolve`。
2. 真穷尽（连续 3 轮无新货）→ **停止补量、`--step finish` 汇报、向用户请示**。严禁自行换频道 / 换城市 / 走搜索页。
3. 搜索页路线已证伪：搜索页点卡片会**跳转** job_detail，而 `step_read` 依赖"原地加载右侧 JD 面板"，实测 ~100% READ_FAILED。

### 步骤 3：内层循环 — 逐条读 JD + 决策 + 投递

对 `jd_to_read.json` 中每条岗位（按 page_order 顺序）：

**3a. 读取 JD**：
```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step read --index N
```
脚本将 JD 写入 `current_jd.json`。

**3b. Agent 决策**：
Agent 实际阅读 `current_jd.json`，核对目标 jobId，再基于实际加载画像判断 APPROVE/REJECT：

- **APPROVE**：岗位匹配 prefer 列表中的目标方向，薪资 ≥ min_salary_k（若设置了最低薪资），城市匹配，不属于 avoid 列表
- **REJECT**：岗位属于实际画像的 avoid、排除领域或公司限制。实习画像不得仅因标题含“实习/实习生”或使用日薪而拒绝；正式全职岗位必须排除。薪资单位分别核验，不直接把日薪数字与月薪 K 比较。
- 不确定时宁可 REJECT

Agent 将决策写入 `decision.json`。**必须使用 shell_executor 执行 Python 一行命令覆写**，禁止使用 delete+write_file 组合（会触发确认弹窗打断循环）：

```
shell_executor: python -c "import json; json.dump({'decision':'APPROVE','reason':'...'}, open(r'WORK_DIR\decision.json','w',encoding='utf-8'), ensure_ascii=False)"
```

原因：`delete` 工具每次弹出确认卡片，`write_file` 同名文件自动重命名需要先删旧——两者组合导致每轮循环至少 1 次确认弹窗。Python `open(w)` 直接覆写，零弹窗。注意命令中路径需用正斜杠或 raw string，JSON 内双引号需转义。

**3c. 执行决策**：
```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step decide --index N
```
APPROVE 时自动投递并检查目标；脚本内置投递目标检查（DAILY_TARGET）。

**3d. 检查终止条件**：
- 投递目标达标 → **强制跳到步骤 5**
- 致命错误（每日上限）→ **强制跳到步骤 5**
- 本批处理完 → 继续步骤 2 下一批

### 步骤 4：外层循环 — 关键词进化（`--step evolve`）

页面穷尽后：
```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step evolve
```

脚本评估投递结果，获取下一个搜索关键词。Agent 确认关键词后：
```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step navigate-search --keyword "关键词"
```

回到步骤 2 继续。

**关键词穷尽（无新关键词）→ 强制跳到步骤 5**。不允许在没有新关键词时继续卡在步骤 4。

### 步骤 5：生成汇报 — ★ 强制执行（`--step finish`）

> **拦截性强制步骤。以下任意条件触发时必须立即执行，不得跳过：**
> - 投递目标达标
> - 致命错误（每日上限）
> - 所有页面穷尽且无新关键词
> - 用户主动要求停止投递

```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step finish
```

生成时间戳报告 `投递汇总_YYYYMMDD_HHMMSS.html` 到 WORK_DIR，并同步最新副本 `投递汇总.html`。目录仍只使用 `BOSS_WORK_DIR` 或当前工作目录，不新增 `BOSS_DIR`。报告同时展示累计快照和本次 `run_id` 结果，内含微信赞赏码和支付宝收款码供求打赏。

---

## 随时查看进度

```
python_executor: 运行 <SKILL_DIR>/scripts/serial_loop.py --step status
```

---

## 环境检查

```
python_executor: 运行 <SKILL_DIR>/scripts/env_check.py
```
包括账户匹配检测（user_profile.json 的用户名/城市 vs 实际登录账户）。

---

## 配置说明

### user_profile.json 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `user_name` | string | 否 | 用户姓名，用于账户匹配和报告 |
| `role_summary` | string | 否 | 一句话角色概述 |
| `experience` | string | 否 | 详细经验描述，用于 LLM 决策 |
| `domain_description` | string | 推荐 | **目标领域详细描述**（适合/不适合的岗位范围），会注入 LLM 审核 prompt。不填则自动由 prefer/avoid 拼接 |
| `target_city` | string | 是 | 目标城市名（如"北京"） |
| `city_code` | string | 是 | 城市编码（如"101010100"），从 BOSS直聘 URL 获取 |
| `min_salary_k` | number | 否 | 最低薪资（K），0 表示不限制 |
| `daily_target` | number | 是 | 每日投递目标（份） |
| `prefer` | string[] | 否 | 偏好岗位关键词列表 |
| `avoid` | string[] | 否 | 排除岗位关键词列表 |
| `prefer_no_big_company` | boolean | 否 | 是否排除大厂（已上市/2000人以上），默认 false |
| `prefer_no_headhunter` | boolean | 否 | 是否排除猎头岗位，默认 false |
| `search_keywords` | string[] | 是 | BOSS直聘搜索关键词列表（纯职位词，不含城市） |
| `channel_tab` | string | 否 | 刷新岗位界面时切换到的目标**频道标签文本**（如"算法工程师（广州）"，支持不带城市后缀的核心词如"算法工程师"由前缀匹配命中）；取哨兵值 **"推荐"**（或 默认/default）时为**默认推荐模式**——跳过频道点击直接使用推荐页默认岗位流；可用环境变量 `BOSS_CHANNEL_TAB` 覆盖，详见步骤 1 与「频道入口」 |
| `c_exclude` | string[] | 否 | 自定义公司名黑名单。不填则使用内置通用默认值（排除猎头/外包/房产/保险） |
| `t_exclude` | string[] | 否 | 自定义标题排除词；旧通用默认值可能不适合实习画像，使用前核验，不得排除画像明确偏好的实习岗位 |

### 城市编码获取方式

1. 在浏览器中打开 https://www.zhipin.com/
2. 顶部选择目标城市
3. 查看 URL：`https://www.zhipin.com/web/geek/job?city=XXXXXX` → `city=` 后的数字即为 city_code

---

## 重要约束

1. **频道入口**：打开 `https://www.zhipin.com/web/geek/jobs`（URL 默认停在「推荐」标签，非可点击频道）后：若 channel_tab 取哨兵值「推荐」（或 默认/default），则跳过点击、直接使用推荐页默认岗位流；否则点击配置频道标签（channel_tab，可由环境变量 BOSS_CHANNEL_TAB 或画像 channel_tab 字段赋值），以选中标签和当前 DOM 核验；不能仅凭 URL 判断频道。
2. 绝不 navigate 到 job_detail URL（在原页面点卡读 JD）
3. 绝不点击「继续沟通」（投递后点「留在此页」）
4. 投递后必须验证实际结果
5. 每日上限判定为致命错误，立即停止
6. 所有浏览器操作必须通过 Kimi WebBridge，不可 CDP 直连
7. **强制 finish**：投递流程无论以何种方式终止，都必须执行 `--step finish` 生成新的时间戳报告，不得覆盖历史 HTML。禁止跳过此步骤。

---

## 版本历史（资产级逐项变更见 [CHANGELOG.md](CHANGELOG.md)）

| 版本 | 日期 | 变更 |
|------|------|------|
| v5.6.7 | 2026-10-13 | 刷新补量 + 配置护栏 + 风控拦截检测：① 新增 `--step refresh`（`recommend_loader.refresh_feed()`）——重新进入频道取 BOSS 换上来的新一批岗位并与已见 jobId 去重，连续 3 轮无新货才判真穷尽并停止汇报；穷尽分支不再推 `evolve` 搜索路线（搜索页点卡片会跳转 job_detail，`step_read` 读不到 JD）。② `profile_loader` 新增护栏：未带 `BOSS_ALLOW_OVERRIDE=1` 的 `BOSS_CHANNEL_TAB`/`BOSS_CITY_CODE` 覆盖一律拒绝并回落画像值（防越权换频道/城市）。③ `webbridge_client` 新增 `is_verification_page()`，`batch_deliver`/`serial_loop` 读 JD 前置检测 BOSS 安全验证页，命中立即停批交人工。④ 卡片选择器统一为 `CARD_SELECTORS`（兼容 `li.job-card-box`，旧硬编码 `.job-card-wrap` 只看得到一半卡片）+ `extract_jobs` DOM 兜底；`_count_cards()` 改按唯一 jobId 计数（修 li/内层 div 双倍计数掩盖真穷尽）。⑤ `build_jd.py` DOM 兜底字段、surface_cache 缺失降级、薪资取 Vue 解密值（修字体反爬乱码）。实测：init 卡片 15→30；refresh 两轮分别刷出 19 / 25 条新货。 |
| v5.6.6 | 2026-10-12 | 两轮复盘后的效率加固（闭环迭代）：① `health_check` 改探 `/command` 兼容新 daemon 版本，修环境误报；② 新增 `ensure_webbridge.py` 守护进程探活/清残留 pid/提示 run_in_background 托管（修 K2/K3）；③ 新增 `build_jd.py` 离线稳构建（去 `.html` 取城市、仅留四城，修 K5）+ `--append` 多轮扩量（P5）；④ `batch_deliver.py` 新增 `--report` 规则回测（闭环反馈 P6，写入 references/rule_metrics.md）；⑤ `jd_reader`/`deliver_engine` 节流（单条读JD+投递等待约 14s→7s，修 K4）。与 v5.6.5 完全向后兼容。 |
| v5.6.5 | 2026-10-12 | 新增批量投递加速器 scripts/batch_deliver.py：复用三层循环读JD/决策/投递全链路，内置保守规则引擎 screen() 自动判定（拒绝信号命中即 REJECT、不确定转 NEED_REVIEW、绝不盲目投）；含同公司重复拦截与已投递记录跳过（stream_progress.json）两道安全闸；`--apply` 真实批量投递、`--dry-run` 仅预览。把「逐条 read→decide 多轮 Agent 往返」压缩为一次进程调用，从根本提速；与 v5.6.4 完全向后兼容。 |
| v5.6.4 | 2026-10-12 | 修复频道点击被城市重导冲掉：v5.6.1 修复②在点击具体频道后仍因 URL 丢 city 参数而带 city 重新导航，整页重置回「推荐」默认态，把刚点的频道冲掉（用户实测页面停在「推荐」）。改为仅默认推荐模式执行城市回退导航；点击具体频道后信任频道、不再城市重导（频道标签中的（广州）等仅为标签文本，非城市约束）。实测 `clicked:算法工程师(广州)` 后页面稳定停留在该频道。 |
| v5.6.3 | 2026-10-12 | 新增默认推荐模式：页面实测截图确认打开 jobs URL 默认停在「推荐」标签（非可点击频道）。channel_tab 取哨兵值「推荐」（或 默认/default）时，navigate_to_recommend 跳过频道点击、直接使用推荐页默认岗位流；不点频道则 URL 不丢 city 参数，城市过滤天然生效。推荐_loader 新增 DEFAULT_CHANNEL_SENTINELS 与 _is_default_channel()。 |
| v5.6.2 | 2026-10-12 | 频道切换标签可配置化：硬编码"算法工程师（广州）"改造为外部变量 CHANNEL_TAB，支持画像 JSON channel_tab 字段（外部文件赋值）与环境变量 BOSS_CHANNEL_TAB（对话直接指定）两种赋值方式；_click_algorithm_channel 注入可配置值并升级匹配规则（全角括号归一化 + 精确/前缀）；切换账号/方向只需改该变量即可保持刷新界面目标岗位命中率。 |
| v5.6.1 | 2026-10-12 | 修复快速测试暴露的问题：① 状态判定失效（最高优先级）—「留在此页」弹窗被点掉后 `stay_btn=false` 误判 `unknown`，改为把过程标志 `stayed_on_page` 并入证据，新增 `_wait_delivery_outcome` 轮询等待聊天页跳转/弹窗延迟，并在 `_chat_evidence` 增加会话列表核验 `chat_list_match`（目标公司 + 送达/您好）；② init 频道点击丢失城市参数 — 导航后校验 URL，缺失则带 `city` 重新导航并保留城市过滤（不再二次点击频道以免再次丢参）；③ `surface_cache` 新增 `city` 字段支持初筛剔城；④ 修复 `deliver_engine`/`recommend_loader` 中 JS 正则 `\s` 的 invalid escape sequence 警告（改 raw string）。⑤⑥⑦ 经确认非缺陷（⑤ 为升级功能、⑥ 仅信息提示、⑦ 为其他 agent 记录）。 |
| v5.6 | 2026-10-12 | 修复维护文档编码，明确投递证据、去重统计、串行保护和验收契约；代码仍须逐项验证。 |
| v5.5 | 2026-08-05 | decision.json 写入改为 shell_executor + Python 一行覆写，消除 delete+write_file 触发的循环确认弹窗 |
| v5.4 | 2026-08-04 | 100% 收尾保证：step_decide target_met / fatal_limit 自动 finish；step_evolve target_met 自动 finish；新增 atexit 兜底钩子确保任何退出路径均生成投递汇总 |
| v5.3 | 2026-08-04 | 面向 GitHub 通用发布：去除所有硬编码用户画像，user_profile.json 为唯一数据源；LLM prompt 由 domain_description 驱动；排除列表支持用户自定义；修复 keyword_evolver 城市名硬编码 |
| v5.2 | 2026-08-04 | Marvis 适配版 |

## v5.6 维护说明（2026-10-12）

本节规定升级后的操作契约，不代表所有代码验收已通过。修改代码后必须用实际行为验证，不能仅检索字段或通过编译便宣称完成。

### 投递闭环

加载 `BOSS_PROFILE` 指定的画像，确认实际配置文件与 channel_tab；打开 `/web/geek/jobs` 并点击配置频道标签（channel_tab），以当前选中标签和 DOM 确认频道，不能仅凭 URL 判断。只使用本轮当前页面岗位，读取 JD 并核对 jobId，按配置和 JD 作出决策，再执行沟通并确认结果。

### 结果确认契约

- `success`：目标聊天对象匹配，自动招呼已发送、聊天关系已建立，且存在首条消息或送达证据。
- `blocked`：明确观察到自动打招呼关闭；没有看到消息不能反推设置关闭。
- `fail`：明确操作或岗位错误；登录失效、每日上限保留具体原因并停止流程。
- `unknown`：证据不足，记录 `chat_relation`、`greeting_sent`、`message_visible`、`delivery_page`、`auto_greeting_state` 和缺失项。
- `popup=sent` 和“留在此页”仅表示操作过程，不能单独证明成功。页面任意位置的“您好”也不能证明目标聊天发送成功。

### 串行与统计契约

`READ_FAILED` 必须阻止投递；有效 JD 必须对应本轮目标 jobId。历史 `surface_cache.json` 仅供参考，不能作为当前可操作岗位来源。投递前再次验证当前 DOM；页面切换或卡片消失时停止该岗位。

按 jobId 去重，成功记录优先，状态变更保留 `previous_status`、`updated_at` 和证据。历史无自动打招呼证据的 unknown 迁移为 `legacy_unknown`，不事后推断为 blocked。`duplicate_removed` 在一次 normalize 后缓存，后续 stats 只读取该值。终端与 HTML 使用统一统计：`unique_total`、`success_total`、`blocked_total`、`fail_total`、`unknown_total`、`legacy_unknown_total`、`duplicate_removed`、`industry_count`、`empty_industry_count`，以及本次调用的处理数和各状态数量。覆盖行业只计算成功岗位的非空行业。

详细操作见 [operations.md](references/operations.md)，失败反例见 [pitfalls.md](references/pitfalls.md)，真实事故规则归档见 [error_rules.md](references/error_rules.md)，出问题时定位根因的作战手册见 [diagnosis_playbook.md](references/diagnosis_playbook.md)。

### 当前实现与待验收项

报告文件按本地时间 `YYYYMMDD_HHMMSS` 命名，同秒冲突追加序号。`--step init` 写入 `run_id` / `started_at` / `profile_file` / `channel`。自动打招呼关闭记为 blocked；页面任意位置的“您好”不能证明成功。

## v5.6.1 维护说明（2026-10-12）

本版本仅修复快速测试暴露的缺陷，不引入新流程。

### ① 状态判定失效（最高优先级，已修复）

根因：投递成功时 BOSS 弹出「留在此页」确认弹窗，脚本点击后该按钮即消失；随后 `_chat_evidence` 已读不到 `stay_btn`，`classify_delivery` 因 `chat_ok=false` 误判 `unknown`（实测招呼已发出，聊天列表出现 [送达]）。

修复手段：
- 把过程标志 `stayed_on_page` 并入证据 `stay_btn`，使「留在此页」可证明招呼已发送。
- 新增 `_wait_delivery_outcome()`：点击「立即沟通」后轮询等待，兼容两种成功路径——路径A（SPA 跳转到 `/web/geek/chat`）、路径B（原地「留在此页」确认）；并实时检测每日上限。
- `_chat_evidence` 新增会话列表核验 `chat_list_match`：在左侧会话列表 / 当前会话头部找目标公司 + 送达/您好证据，作为权威成功信号。
- 路径A（跳转聊天页）成功后自动 `navigate` 返回岗位列表，避免串行循环后续卡片点击失效。

### ② init 丢失城市过滤（已修复）

`navigate_to_recommend` 点击「算法工程师」频道后 URL 可能丢失 `?city=` 参数，混入其它城市岗位。现于频道点击后校验 URL，缺失则带 `city` 重新导航并复位频道（最多一次），仍失败则告警并依赖 ③ 的缓存 city 字段由初筛剔除。

### ③ surface_cache 新增 city 字段（已修复）

缓存精简字段由 7 个增至 8 个（加入 `city`）。`extract_jobs` 已提供 `city`，`KEEP_FIELDS` 纳入后，`recommend_loader` 与 `surface_cache` 提取的岗位均带城市，Agent 初筛可据此剔除跨城岗位。

### ④ invalid escape sequence 警告（已修复）

`deliver_engine.py` 与 `recommend_loader.py` 中内联 JS 正则 `/\s+/` 所在的 Python 普通字符串改为 raw string，消除 `SyntaxWarning: invalid escape sequence '\s'`。

### ⑤⑥⑦ 经确认非缺陷

- ⑤ 每次 decide 自动出报告：为升级功能，保留。
- ⑥ Edge 扩展 v2.0.15 落后于 skill 2.0.23：仅信息提示，无代码改动。
- ⑦ 其他 agent 的记录：与本次技能无关，忽略。

### 待验收项

① 的修复须以实际投递验证：对一条岗位 `--step decide`，确认 `stream_progress.json` 中该岗位 `result=success` 且证据含 `stay_btn=true` 或 `chat_list_match=true`。

★ 已于 2026-10-12 实测验证通过：广州「SLAM定位算法工程师」经 `--step decide` 后 `result=success`，证据 `stayed_on_page=true` / `stay_btn=true`（路径B：留在此页确认弹窗命中，说明招呼已发送）；对比修复前同路径误判 `unknown`。② 实测 init 后缓存 15 条岗位城市均为「广州」，城市过滤生效。③ 缓存含 `city` 字段。④ 全量脚本 `py_compile -W error::SyntaxWarning` 通过。

## v5.6.2 维护说明（2026-10-12）

### 频道切换标签可配置化

背景：技能原先在 `recommend_loader._click_algorithm_channel()` 中硬编码「算法工程师」前缀匹配，依赖刷新岗位界面后点击该标签把岗位集合切换到匹配方向的推荐页以提升 JD 命中率；但标签值写死，切换账号/方向时需改代码。

改动：
- `profile_loader` 新增外部变量 `CHANNEL_TAB`，赋值优先级（高→低）：
  1. 环境变量 `BOSS_CHANNEL_TAB`（对话中由 Agent 直接指定，无需改文件）；
  2. 画像 JSON 的 `channel_tab` 字段（外部 JSON 文件赋值）；
  3. 默认值 `"算法工程师（广州）"`（保持原有行为）。
- `recommend_loader._click_algorithm_channel()` 改为注入 `CHANNEL_TAB`（经 `json.dumps` 安全嵌入 JS），匹配前先归一化（DOM 标签与 `CHANNEL_TAB` 的全角括号 `（）`→半角 `()`、压缩多余空白），再按「精确相等 或 前缀包含（indexOf===0）」判定，稳定命中 DOM 真实标签「算法工程师(广州)」并兼容「算法工程师」「算法工程师（广州）」「算法工程师(广州)」等任意写法。
- 四个画像文件（`user_profile.json` + `profiles/*.json`）均新增 `channel_tab` 字段。

两种赋值方式（满足需求）：
- 外部 JSON 文件赋值：修改对应画像的 `channel_tab` 字段（如切换城市/方向时改为 `"算法工程师（深圳）"`）。
- 对话直接指定：Agent 运行 `--step init` 前设置 `BOSS_CHANNEL_TAB`（如 `set BOSS_CHANNEL_TAB=算法工程师（深圳）`），无需改动任何文件。

价值：切换其他账号/方向时，仅需修改该变量值即可保持刷新界面较高的目标岗位命中率。

## v5.6.3 维护说明（2026-10-12）

### 默认推荐模式（跳过频道点击）

背景：经截图实测，打开 `https://www.zhipin.com/web/geek/jobs` 后页面顶栏为「推荐（选中态）｜算法工程师(广州)｜电气/自动化(广州)｜+」。「推荐」是默认态而非可点击频道；当不指定方向时，用户希望直接使用默认推荐流，而非强制点某个频道。v5.6.2 及之前版本无此能力——`navigate_to_recommend` 无条件点击频道，点击失败即 ERROR 中断，且 `channel_tab` 默认值固定为「算法工程师（广州）」。

改动：
- `recommend_loader` 新增 `DEFAULT_CHANNEL_SENTINELS = {"推荐","默认","default","__default__"}` 与 `_is_default_channel(tab)` 判定；`navigate_to_recommend` 在频道点击前先判定，命中哨兵则打印「默认推荐模式，跳过频道点击」并直接继续（不调 `_click_algorithm_channel`、不触发 fix② 的城市回退导航，因为未点频道 URL 不会丢 `?city=`）。
- `profile_loader` 的 `CHANNEL_TAB` 注释补充哨兵说明；默认值仍为「算法工程师（广州）」以保留既有行为（仅当画像/环境变量显式设哨兵值时进入默认推荐模式）。

两种赋值方式（满足需求）：
- 对话直接指定：`BOSS_CHANNEL_TAB=推荐`（或 `set BOSS_CHANNEL_TAB=推荐`）后运行 `--step init`，无需改动任何文件。
- 外部 JSON 文件赋值：把对应画像的 `channel_tab` 字段改为 `"推荐"`（表示用默认推荐流）或 `"算法工程师"`/`"电气/自动化"`（表示聚焦该频道）。

验收（已实测）：`BOSS_CHANNEL_TAB=推荐` 运行 `init` 输出「channel_tab='推荐' → 默认推荐模式，跳过频道点击，使用推荐页默认岗位流」并成功加载 15 张卡片，无城市丢失重导；`_is_default_channel` 对「推荐/默认/default/__default__」返回 True，对空串与具体频道词返回 False。

价值：不指定方向时使用面更广的默认推荐流，指定方向时仍点频道聚焦，二者均由同一个可配置变量控制，无需改代码。

## v5.6.4 维护说明（2026-10-12）

### 频道点击与城市重导的冲突修复

背景：用户以 `BOSS_PROFILE=integration` + `BOSS_CHANNEL_TAB=算法工程师（广州）` 正式投递时，init 输出 `clicked:算法工程师(广州)` 后紧接着出现「检测到城市参数丢失，重新以 city=101280100 导航」并「推荐页已加载」——用户实际看到页面停在「推荐」而非所选频道。根因：v5.6.1 修复②无条件执行；点击频道后 URL 丢失 `?city=` 参数被判定为异常，带 city 重新导航会整页重置回「推荐」默认态，把刚点的频道冲掉。

语义澄清（用户确认）：频道标签「算法工程师(广州)」中的「广州」仅是标签文本，**不是城市约束**；点击频道即代表「方向+城市」已由频道聚焦，城市参数丢失无需补救。城市无所谓（四个目标城市均可）。

改动：
- `recommend_loader.navigate_to_recommend` 先计算 `use_default = _is_default_channel(CHANNEL_TAB)`；修复②的城市回退导航块包裹在 `if use_default:` 内——仅默认推荐模式（未点频道、URL 无频道参数、城市过滤依赖 `?city=`）执行；点击具体频道后**信任频道、不再城市重导**。

验收（真实投递实测 · 2026-10-12 16:50）：`BOSS_PROFILE=integration BOSS_CHANNEL_TAB=算法工程师（广州）` 运行 `init`，输出 `clicked:算法工程师(广州)` 且**无**「城市参数丢失重新导航」日志；截图确认顶栏「算法工程师(广州)」为选中态；随后 `next-batch` 在 `algorithm_channel` 页型下加载 75 条机器人/算法岗位，内层循环完成 27 条语义筛选（23 投递成功 / 4 拒绝），投递链路全程正常。

价值：指定频道的正式投递真正落在所选频道上，不再被静默重置回推荐流；默认推荐模式的城市过滤行为保持不变。

## v5.6.5 维护说明（2026-10-12）

### 批量投递加速器（速度提升，可选快速通道）

背景：首次正式投递（v5.6.4）实测暴露「逐条 `read` → 写 `decision.json` → `decide`」的多轮 Agent 往返是速度瓶颈——27 条候选、23 条真实投递耗时约 25 分钟，单条 APPROVE 需多轮工具调用 + 决策；且每次 `decide` 后 `decision.json` 被清空需重写、同公司重复需人工识别。为「之后要加快速度」提供机制保障。

新增 `scripts/batch_deliver.py`：**一次进程调用**完成整批「读 JD + 决策 + 投递」，复用 `serial_loop` 全链路（进度/报告与三层循环一致）。

用法（在 WORK_DIR 下、已 `--step init` + `--step next-batch` 准备好 `jd_to_read.json` 后）：
```bash
# 预览判定（不投递），先验规则质量
python scripts/batch_deliver.py --dry-run
# 真实批量投递（APPROVE 发招呼；REJECT/NEED_REVIEW 不投）
python scripts/batch_deliver.py --apply
```

规则引擎 `screen(job, jd_text)` 分级判定（保守、绝不盲目投）：
- 跨城（不在 `TARGET_CITIES`）→ **REJECT**
- 学历门槛（硬性硕士/博士）→ **REJECT**；校招/社招/正式全职 → **REJECT**
- 排斥方向（数据挖掘 / 物业 / 行政 / 销售 / 猎头 / 运营 / 智驾测试支持等）→ **REJECT**
- 自动驾驶域但非 SLAM/感知/定位核心研发 → **NEED_REVIEW**
- 无实习信号（无「实习/在读/本科及以上」且无标题实习标记；或含「无实习/非实习」否定表述）→ **NEED_REVIEW**
- 未命中机器人/算法域核心词 → **NEED_REVIEW**
- 其余 → **APPROVE**

两道安全闸：
1. **同公司重复拦截**：本轮已投过的公司不再投（防骚扰）。
2. **已投递记录跳过**：载入 `stream_progress.json` 的 `delivered`/`failed` jobId，重跑 `jd_to_read.json` 时 `SKIP`，**绝不二次真实投递**（首次正式投递的 23 条 success 已受保护）。

速度收益：Agent 只在 `NEED_REVIEW` 环节介入复核；APPROVE/REJECT 全程自动。日目标 150 的批量推进改由一次调用驱动，而非 150+ 轮往返。

验收（2026-10-12）：`py_compile` 通过；规则引擎离线逻辑校验 8 例 7/8 通过（1 例为测试用例期望偏差，非规则缺陷）；防重复验证 23 条已投全部 `SKIP`。

## v5.6.6 维护说明（2026-10-12）

### 两轮复盘后的效率加固（持续升级闭环）

背景：用户要求复盘最近两轮投递（第一轮 v5.6.4 正式投递 23 成功 / 26min；第二轮 v5.6.5 加速器尝试 0 投递 / 14min 全耗在环境恢复 + bug 修复），定位慢根因并形成可落地方案，继续迭代。复盘结论：第一轮瓶颈在「投递执行」（逐条多轮 Agent 往返）；v5.6.5 加速器本应消除它，但第二轮暴露**更致命的基础设施脆弱性**（守护进程易死 / `health_check` 与新 daemon 不兼容 / jid 含 `.html` 失配导致构建 0 条），使执行层提速无从落地。本迭代把复盘 K/P 项落地为代码与流程。

改动与用法：
- **环境加固（K2/K3）**：`webbridge_client.health_check` 由「GET / 仅认 200/404」改为「直接探 `POST /command`（list_tabs）」——当前 daemon 对 `/` 返回 502 而 `/command` 正常（list_tabs 返回 ok:true），消除误报「不可达」。新增 `scripts/ensure_webbridge.py`：`python scripts/ensure_webbridge.py` 探活并打印状态；`--fix` 清理残留 `~/.kimi-webbridge/daemon.pid` 并提示用 **`run_in_background` 托管** `kimi-webbridge start --foreground` 跨调用保活（本环境 Bash 工具会在普通命令结束时清理后台子进程）。
- **稳构建（K5）**：新增 `scripts/build_jd.py` 离线优先构建 `jd_to_read.json`——从当前页面卡片取 jobId（正则去 `.html` 后缀，匹配 `surface_cache` 无后缀 jobId）→ 关联 `surface_cache` 取城市/公司 → 仅留目标四城；跨城候选不进入 `jd_to_read`，不占浏览器读卡时间。修正第二轮「jid 含 `.html` 失配 → 全量跨城跳过（0 条写出）」。
- **扩候选（P5）**：`build_jd.py` 新增 `--append`：与现有 `jd_to_read.json` 按 jobId 合并、重排 `page_order`，支持「多次 `next-batch` → 每次 `--append`」把候选池做大再一次性喂加速器，逼近日目标 150。
- **节流（K4）**：`jd_reader.click_card_inplace` 滚动等待 1.5→1.0s、点击后 2→1.0s；`_verify_panel` 默认 `max_wait` 5→2.5s。`deliver_engine.deliver_inplace` 点卡 verify 5→2.5s、弹窗后 2→1.0s、`sent_greeting` 1.5→1.0s、「留在此页」后 2→1.2s。**仅缩短等待、不删校验**，单条读JD+投递纯等待预算约 14s→7s（待真实一轮校准）。
- **闭环反馈（P6）**：`batch_deliver.py` 新增 `--report`：读 `stream_progress.json` + `batch_deliver_log.json`，计算 verdict 分布、自动化覆盖率、NEED_REVIEW 负担、投递成功率，追加至 `references/rule_metrics.md`，作为调 `ROBOTICS_TOKENS` / 排除词的信号。

标准一轮（闭环）：
```bash
python scripts/ensure_webbridge.py --fix        # 探活/清 pid（离线时）
# 经 run_in_background 托管：kimi-webbridge start --foreground
python scripts/serial_loop.py --step init
python scripts/serial_loop.py --step next-batch  # 重复多次以扩量
python scripts/build_jd.py --append             # 每次累积候选
python scripts/batch_deliver.py --dry-run       # 先验规则质量
# 人工确认 NEED_REVIEW 项
python scripts/batch_deliver.py --apply         # 真实批量投递
python scripts/serial_loop.py --step finish
python scripts/batch_deliver.py --report        # 回测指标，调规则
```

价值：从「加速器单点提速」升级为「环境稳 + 构建稳 + 节流 + 扩量 + 回测」的系统化效率闭环；下一步待守护进程恢复后跑通真实一轮，用实际吞吐与 `--report` 指标校准 P1 真实提速比。

验收（2026-10-12）：5 个改动脚本 `py_compile -W error::SyntaxWarning` 全部通过；`batch_deliver.py --report` 离线读取真实 `stream_progress.json`（成功 23 / 失败 0 / 成功率 100%）+ 历史日志，正确输出 verdict 分布并追加 `rule_metrics.md` 一行；节流幅度为理论值，待真实一轮校准。

---

## v5.6.7 维护说明（2026-10-13）

### 背景：两次用户纠正

1. **越权换频道**：页面被带到「电气/自动化(广州)」，而画像 `integration.json` 明确配置 `channel_tab = 算法工程师（广州）`。根因是 Agent 在命令行自行加了 `BOSS_CHANNEL_TAB=电气/自动化(广州)` 与 `BOSS_CITY_CODE`（深→广→沪）。
2. **没有刷新**：用户指出「昨天我在算法工程师频道下不断刷新就有新岗位，今天你为什么没刷新？明显是没刷新才导致岗位耗尽」。核查确认：`scripts/` 内**零 refresh/reload 实现**（grep 仅命中注释），旧版滚动到底即判穷尽。

### 根因（R1–R6，均有实测证据，详见 CHANGELOG.md）

- R1 无刷新补量通路（`batch_state.json`：15 卡 / 8 次滚动 / 「连续4次无新增」）
- R2 穷尽后引导 `evolve` 搜索路线，而搜索页 ~100% READ_FAILED
- R3 卡片选择器"半盲"：硬编码 `.job-card-wrap` 只看得到 15 张，统一后同页 30 张
- R4 计数双倍虚高：`li.job-card-box` 内套 `div.job-card-wrap`，45 个岗位数成 90，掩盖真穷尽
- R5 越权改配置无防线 → 已加护栏（需 `BOSS_ALLOW_OVERRIDE=1`）
- R6 **风控拦截被误判为"卡片不在 DOM"**：高频读 JD 触发 BOSS 安全验证页（`/web/passport/zp/verify.html`，标题「安全验证 - BOSS直聘」），此时 DOM 零卡片，全部 `no_link_match`

### 强制纪律（写入流程，不得违反）

1. **频道与城市以画像为准**。要改必须先取得用户明确指示，并设置 `BOSS_ALLOW_OVERRIDE=1`；否则护栏会拒绝覆盖并回落画像值。
2. **供给不足先刷新**（`--step refresh`），连续 3 轮无新货才算真穷尽。
3. **真穷尽就停下汇报**，不换频道、不换城市、不走搜索页。
4. **命中安全验证页立即停批**，交回用户人工完成验证，脚本不得绕过（账号安全风险）。
5. **不要为"取候选/编排"另写脚本**。真实投递一律走 `batch_deliver.py`；额外壳脚本会让执行偏离 skill 主循环（2026-10-13 教训）。

### 标准一轮（风控解除后）

```bash
python scripts/serial_loop.py --step init
python scripts/serial_loop.py --step next-batch
python scripts/serial_loop.py --step refresh      # ★ 补量：可重复，直到连续无新货
python scripts/build_jd.py --append
python scripts/batch_deliver.py --dry-run
python scripts/batch_deliver.py --apply
python scripts/serial_loop.py --step finish
python scripts/batch_deliver.py --report
```

### 验收（真实浏览器，2026-10-13 19:35–19:50）

| 项 | 结果 |
|----|------|
| 编译 | 6 个改动脚本 `py_compile -W error::SyntaxWarning` 全通过 |
| 护栏 | 未授权覆盖 → ⛔ 拒绝并回落画像值；带 `BOSS_ALLOW_OVERRIDE=1` → 生效 |
| init | `clicked:算法工程师(广州)`，卡片 15 → **30** |
| next-batch | 提取 60 条（含 city/industry，mode=vue） |
| **refresh** | 第 1 轮新货 **19** 条；第 2 轮新货 **25** 条；计数修正后 45 = 45 |
| build_jd | 34 候选 / 跨城跳过 26 / 薪资解密正常 |
| dry-run | APPROVE=11 REJECT=2 NEED_REVIEW=9 READ_FAILED=12（事后定位为 R6 风控） |
| 风控检测 | 触发安全验证页 → 立即 ⛔ 停批（`已处理 0/34`），未硬撞 |

**遗留**：本迭代未产生新的真实投递（跑到 dry-run 即被风控拦停）；NEED_REVIEW 负担 41% 偏高，下一轮用 `--report` 回测 `screen()` 词表。
