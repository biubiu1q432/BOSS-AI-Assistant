# 文件元信息
- 用途：BOSS 自动化投递「两轮复盘 + 效率提升方案」，对比 v5.6.4 手写多轮与 v5.6.5 加速器尝试的耗时差异，定位投递速度慢的根本原因，形成结构化总结与可落地方案，并定义持续升级闭环。
- 职责范围：项目级复盘与策略文档；不涉及具体投递代码逻辑，仅给出优化方向与已落地动作索引。
- 关联模块：`serial_loop.py`(I) / `batch_deliver.py`(I+) / `webbridge_client.py` / `build_jd.py`(I+辅助) / `ensure_webbridge.py`(0)
- 维护状态：v5.6.6 新增（2026-10-12）

---

# BOSS 自动化投递 · 两轮复盘与效率提升方案

> 数据来源：本会话两轮运行的真实日志与时间戳（第一轮 2026-10-12 16:50–17:16；第二轮 2026-10-12 19:28–19:42）。部分耗时为按日志还原的近似值，标注"约"。

## 一、两轮过程还原（时间线）

### 第一轮 · v5.6.4 正式投递（16:50 – 17:16，约 26 分钟）
| 阶段 | 动作 | 产物 |
|------|------|------|
| 16:50 | `init`：验证 v5.6.4 频道修复，点击「算法工程师(广州)」 | 频道稳定停留，75 条岗位载入缓存 |
| 16:5x | `next-batch` + Agent 逐条 `read`→写 `decision.json`→`decide` | 27 条语义筛选 |
| 17:0x–17:16 | 23 条 APPROVE 真实投递 / 4 条 REJECT | 23 success / 4 拒绝 |
| 17:16 | `finish` | 报告 `投递汇总_20261012_171610.html` |
- **有效产出：23 投递成功**
- **单位耗时：≈ 26 min ÷ 23 ≈ 1.13 份/分；单条有效投递 ≈ 65 秒（不含模型/多轮往返的隐性开销）**

### 第二轮 · v5.6.5 加速器尝试（19:28 – 19:42，约 14 分钟，**0 投递**）
| 阶段 | 耗时(约) | 动作 |
|------|----------|------|
| 19:28–19:32 | 4 min | 定位守护进程二进制（`~/.kimi-webbridge/bin/` 此前未被检索命中）→ 首次 `start`（后台化）→ 探测在线，但命令结束后进程被工具清理 |
| 19:32–19:35 | 3 min | 发现 `health_check` 对当前 daemon 版本误报「不可达」（GET / 返回 502，而 `/command` 正常）→ 修复 `health_check` |
| 19:35–19:39 | 4 min | `start` 因残留 `daemon.pid`（进程 179820 被标记存活但端口拒绝）失败 → 杀进程 + 清 pid → `start --foreground` 经 `run_in_background` 托管重启成功 |
| 19:39–19:42 | 3 min | `init` 通过、`next-batch` 加载 15 条、构建 `jd_to_read` 因 jid 含 `.html` 后缀与 `surface_cache` 失配 → 全量跳过（写出 0 条）、DOM 调试 |
- **有效产出：0 投递**
- **14 分钟 100% 消耗在「环境恢复 + 流程 bug 修复」，投递执行被完全阻塞**

## 二、耗时差异对比
| 维度 | 第一轮 | 第二轮 |
|------|--------|--------|
| 墙钟耗时 | 26 min | 14 min |
| 有效投递 | 23 | 0 |
| 有效吞吐 | 0.88 份/分 | 0 |
| 主要耗时去向 | 投递执行本身（逐条多轮） | 环境恢复 + bug 修复（无产出） |
| 主导瓶颈 | **流程环节**（逐条 Agent 往返） | **资源/环境**（守护进程脆弱 + health_check 不兼容） |

**核心结论**：第一轮瓶颈在"投递执行"；v5.6.5 加速器本应消除该瓶颈，但第二轮暴露出**新的、更致命的瓶颈——基础设施脆弱性**。若不先解决环境稳定性，任何执行层提速都无从落地。

## 三、根本原因定位（按四类）

### 1. 流程环节（process）
- 第一轮：每条岗位 `read → 写 decision.json → decide` 跨多轮 Agent 往返；单条 APPROVE 至少 3–4 次工具调用 + 模型推理。（**v5.6.5 加速器已消除此环节**：一次进程调用完成整批读JD+决策+投递。）
- 第二轮：环境恢复无标准化流程，靠临时排查，耗时不可控。

### 2. 等待节点（waiting）
- `step_read`：`scrollIntoView` 1.5s + 点击等待 2s + `verify_panel` 轮询 ≤5s ≈ **8–9s/条**（纯浏览器等待）。
- `deliver_engine._wait_delivery_outcome`：轮询聊天跳转/弹窗，数秒/条。
- **Agent 多轮往返的模型思考 + 工具往返隐性延迟**：随 27 条 × 多轮累积显著（第一轮最大的隐藏成本）。

### 3. 资源瓶颈（resource）
- 单浏览器标签、单线程自动化 → **本质串行，无法并行**（这是物理下限，只能靠减少条数/等待来逼近）。
- **守护进程生命周期未被托管**：跨工具调用被清理、残留 `daemon.pid` 阻塞重启（第二轮 14 min 归零的根因）。
- `health_check` 与当前 daemon 版本不兼容（GET / 返回 502）→ 误报"不可达"，阻断启动。

### 4. 执行顺序（ordering）
- 第一轮：逐条 `read` 后才 `decide`，`decision.json` 每次被清空需重写，摩擦大。
- 构建 `jd_to_read` 依赖**实时 DOM 抓城市**，脆弱：第二轮 jid 含 `.html` 后缀导致与 `surface_cache` 失配 → 全量跨城跳过（0 条写出）。
- 候选筛选与投递串行内联，无批量决策。

## 四、关键问题结构化总结
| 编号 | 问题 | 类别 | 影响 |
|------|------|------|------|
| **K1** | 逐条多轮 Agent 往返 | 流程 | 第一轮主瓶颈，≈65s/条 |
| **K2** | 守护进程无托管、易死、残留 pid 阻塞 | 资源/环境 | 第二轮 14 min 归零产出 |
| **K3** | `health_check` 与 daemon 版本不兼容 | 资源 | 误报不可达，阻断启动 |
| **K4** | 单条读 JD 浏览器等待 8–9s | 等待 | 累积显著 |
| **K5** | `jd_to_read` 依赖实时 DOM 抓城市，易失配 | 执行顺序 | 第二轮构建 0 条 |
| **K6** | 单频道 feed 候选量有限 | 资源 | 难达 150 目标 |

## 五、可落地的效率提升方案
| 方案 | 对应问题 | 状态 | 说明 |
|------|----------|------|------|
| **P1** 批量投递加速器 `batch_deliver.py` | K1 | ✅ 已落地（v5.6.5），**待真实一轮实测校准提速比** | 一次调用完成整批读JD+决策+投递；保守规则引擎自动判定；仅 NEED_REVIEW 转人工 |
| **P2** 守护进程生命周期托管 `ensure_webbridge.py` + run_in_background 起守护进程 | K2/K3 | ✅ 已落地（v5.6.6） | `health_check` 已改探 `/command`；`ensure_webbridge.py` 探活→清残留 pid→提示 run_in_background 托管 `start --foreground` 保活；消除 14 min 归零 |
| **P3** 削减单条浏览器等待 | K4 | ✅ 已落地（v5.6.6），**待真实一轮校准** | `jd_reader` 滚动 1.5→1.0s、点击后 2→1.0s、verify 5→2.5s；`deliver_engine` 点卡 verify 5→2.5s、弹窗后 2→1.0s、sent 1.5→1.0s、留此页 2→1.2s；仅缩短等待、不删校验 |
| **P4** 离线优先构建 `build_jd.py` | K5 | ✅ 已落地（v5.6.6） | 实时 DOM 取 jid（去 .html）→ 关联 `surface_cache` 取城市 → 仅留目标四城；跨城不占浏览器读 |
| **P5** 扩大候选量 | K6 | ✅ 已落地（v5.6.6，`build_jd --append`） | 多次 `next-batch` + 每次 `build_jd --append` 累积候选池，单批喂满加速器；150 目标拆多批 |
| **P6** 人审闭环 + 规则自迭代 | K1/K3 收尾 | ✅ 已落地（v5.6.6，`batch_deliver --report`） | 每批 NEED_REVIEW 小批秒确认；`--report` 回测 verdict 分布/自动化覆盖率/投递成功率，写入 rule_metrics.md，调 token |

## 六、持续升级闭环（落地机制）
1. **标准一轮**：`ensure_webbridge` → `init` → `next-batch` → `build_jd` → `batch_deliver --dry-run` → 人工确认 NEED_REVIEW → `--apply` → `finish`。
2. **度量**：投递吞吐（份/分）、APPROVE 精度（人审 vs 自动）、NEED_REVIEW 率。
3. **回测**：用 `stream_progress` 成功/拒绝样本调 `ROBOTICS_TOKENS` 与排除词，提升自动判定召回/精度。
4. **自愈**：`ensure_webbridge` 探活失败自动清 pid 并重拉；`health_check` 已修（探 /command）。
5. **本轮已落地动作（v5.6.6 已全部代码交付）**：`health_check` 改探 `/command`（修 K3）；`ensure_webbridge.py` 探活/清 pid/提示 run_in_background 托管（修 K2/K3）；`build_jd.py` 修正 jid 匹配 + `--append` 扩量（修 K5/P5）；`jd_reader`/`deliver_engine` 节流（修 K4/P3）；`batch_deliver --report` 闭环回测（P6）。**下一步**：守护进程恢复后跑通标准一轮（ensure_webbridge → init → 多次 next-batch + build_jd --append → batch_deliver --dry-run → 人工确认 NEED_REVIEW → --apply → finish → --report），用实际吞吐校准 P1 真实提速比、用 --report 回测规则精度。
