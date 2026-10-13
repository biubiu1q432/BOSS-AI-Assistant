> **文件元信息**
> - **用途**：定义当前实习画像的岗位筛选规则（实习限定、薪资单位、排除词分层、候选来源），指导 Agent 初筛与决策。
> - **职责范围**：覆盖筛选语义与规则；不含投递执行或报告生成。
> - **关联模块**：依赖 `profile_loader.py`（模块：中央配置加载器，提供 `USER_PROFILE` / `CITY_CODE` / `prefer_no_big_company` 等）；跨城剔除使用 `surface_cache.py` 的 `city` 字段（v5.6.1 新增）；候选来自 `recommend_loader.py` / `surface_cache.py` 本轮页面。
> - **维护状态**：有效（v5.6.1，大厂不排已置 false）；迭代明细见 `CHANGELOG.md`。

# 当前岗位筛选规则

筛选依据是 `profile_loader.USER_PROFILE_FILE` 对应的实际画像和本轮实际读取的 JD。默认文件与预设画像不能混用。输出配置路径，按 prefer、avoid、domain_description、城市和公司限制判断；最终决定由 Agent 作出。

- integration、algorithm、hybrid 仅限实习。标题含“实习/实习生”是候选依据，仍须阅读 JD 判断技术方向；正式全职、社招、长期全职岗位拒绝。
- 日薪、时薪不能作为通用排除条件；保留原始单位，不能将日薪数字直接与月薪 K 阈值比较。配置要求最低薪资而单位无法比较时，记录疑问并澄清。
- 排除词按标题、公司、正文区分；正文中的“五险一金”等福利不应触发行业排除。
- 猎头、大厂等限制按实际画像生效，不使用旧用户的行业、公司或薪资规则。
- 候选只来自本轮当前页面。读取 JD 后核对 jobId；READ_FAILED 或目标不一致时阻断投递。页面切换后重新抓取并读取，历史缓存仅供参考。

> **v5.6.1 配置与跨城说明**：四份画像（默认 + 三套预设）的 `prefer_no_big_company` 已置 `false`，大厂实习岗位**不**应被排除，筛选时不得仅因"大厂"标签拒绝实习岗；猎头排除仍按 `prefer_no_headhunter` 生效。跨城剔除使用 `surface_cache.py` 的 `city` 字段（v5.6.1 新增），初筛据此过滤非目标城市岗位。

旧酒店/文旅画像的五阶段流程与筛选示例已移入 [历史档案](archive/filtering-pre-v5.6.md)，不得用于当前实习画像。
