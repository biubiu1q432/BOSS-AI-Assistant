> **文件元信息**
> - **用途**：定义当前三层循环投递的操作契约与验收标准（init→next-batch→read→decide→evolve→finish），是 Agent 执行投递的动作依据。
> - **职责范围**：覆盖操作步骤、成功/失败证据判定、报告与统计口径；不含底层选择器或筛选规则（见 `dom_structure.md` / `filtering.md`）。
> - **关联模块**：由 `serial_loop.py`（模块I）驱动各 `--step`；投递证据由 `deliver_engine.py`（模块F）采集；岗位缓存由 `surface_cache.py`（模块D）/ `recommend_loader.py`（模块C）；汇总由 `report_builder.py`（模块G）。
> - **维护状态**：有效（v5.6.3，含成功证据细化与默认推荐模式）；迭代明细见 `CHANGELOG.md`。
>
# BOSS 直聘操作手册（当前有效版本 v5.6.3）

Historical examples: [archive](archive/operations-pre-v5.6.md). Do not execute historical instructions.

## 操作流程与验收（v5.6.3；v5.6 于 2026-10-12 建立，v5.6.1 细化成功证据，v5.6.2/5.6.3 频道可配置与默认推荐模式）

本节是当前操作契约；归档中的旧入口、固定等待和岗位数量示例不能替代实时页面核验。

1. 加载 `BOSS_PROFILE` 指定的画像（默认 `user_profile.json`），输出实际配置路径。通过 Kimi WebBridge 操作同一标签页。
2. 打开 `/web/geek/jobs`（默认停在「推荐」标签，非可点击频道）。若 channel_tab 取哨兵值「推荐」（或 默认/default），则**跳过点击、直接使用推荐页默认岗位流**；否则点击配置频道标签（channel_tab，默认「算法工程师（广州）」，支持不带城市后缀的核心词）。URL 可能相同，必须检查选中标签与岗位 DOM。
3. 记录当前 URL、频道、城市、本轮批次数量与历史缓存数量。候选岗位必须来自本轮当前页面，不能直接从历史 `surface_cache.json` 生成投递列表。
4. 执行 read，实际阅读 JD 并核对 jobId。失败写入 `READ_FAILED`；禁止继续 APPROVE 或投递。页面变化后重新读取。
5. 按真实 JD 和配置生成决策。JSON 使用 UTF-8，读取端兼容 UTF-8 BOM，避免 PowerShell 管道丢失中文。
6. 投递前核对目标卡片仍在当前 DOM。先读取登录、上限和关闭提示，再处理弹窗，避免关闭弹窗后丢失错误证据。
7. 点击立即沟通后检查目标聊天对象、自动招呼、聊天关系、首条消息或送达状态。保存前后证据；不要重复点击来猜测结果。
8. 自动招呼发送且目标聊天关系和消息证据齐全才为 success。**v5.6.1 起，以下两类被采纳为权威成功信号**：① `stay_btn`（路径B：捕获到"留在此页"确认，证明招呼已发送）；② `chat_list_match`（会话列表核验：目标公司 + 送达/您好）。明确关闭为 blocked；明确错误为 fail；其余为 unknown，并记录缺失证据。孤立的 `popup=sent` 或"留在此页"弹窗**不能单独**替代最终证据（须落入上述两类信号之一）。
9. 按 jobId 保存最终状态并生成去重报告，分别列出成功、blocked、fail、unknown、重复合并数、成功岗位非空行业及空行业数。

维护验收：编译只验证语法。必须另测去重、历史 unknown 分类、失败转成功、JD 失败阻断、目标聊天身份匹配，以及终端与 HTML 数字一致性。真实单岗位测试应保留过程日志，不能仅根据 unknown 推断自动打招呼关闭。

### 正例：证据闭环与无重复计数

示例输入：本轮读取目标岗位 A，JD 与 jobId 一致，筛选通过；操作后在对应招聘者的会话中看到新自动招呼和送达标识。预期结果：记录一条 success；再次统计不重复增加；A 原有失败记录移出最终失败集合。此例是验收用例，不是已完成真实测试的声明。

示例输入：仅弹出"留在此页"但未被捕获为 `stay_btn` 证据，也无目标会话消息与设置关闭提示。预期结果：unknown，保存缺失字段，不推断 blocked，不重发消息。若 `stay_btn=true`（留在此页已确认），则判 success（路径B）。


10. 工作目录只认 BOSS_WORK_DIR，否则使用当前目录；不新增 BOSS_DIR。
11. --step init 创建本次 run_id，累计进度仍写入 stream_progress.json。
12. --step finish 每次生成新文件 投递汇总_YYYYMMDD_HHMMSS.html，同秒冲突追加序号，不覆盖历史报告；可同步最新副本 投递汇总.html。
13. 报告与终端使用同一统计口径：累计唯一岗位、success/blocked/fail/unknown/legacy_unknown、重复合并数、覆盖行业、空行业成功数；同时列出本次调用处理数、各状态数量、覆盖行业、运行开始时间和报告生成时间。
14. 历史无自动打招呼证据的 unknown 标记为 legacy_unknown。新投递不得写入 legacy_unknown。
