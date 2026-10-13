# 规则引擎回测指标（v5.6.6 闭环反馈）

- 用途：每次批量运行后回测 screen() 表现，作为调 ROBOTICS_TOKENS / 排除词的信号。
- 关联模块：batch_deliver.py(I+) / webbridge_client.ProgressManager
- 维护状态：v5.6.6 新增

| 时间                  | 规则分布                                                           | 自动化覆盖率 / NEED_REVIEW负担 | 累计投递健康度                   |
| ------------------- | -------------------------------------------------------------- | ---------------------- | ------------------------- |
| 2026-10-12 19:51:35 | APPROVE 0 / REJECT 0 / NEED_REVIEW 0 / READ_FAILED 27 / SKIP 0 | 自动化 0.0% / 负担 0.0%     | 投递成功 23 / 失败 0 / 率 100.0% |
| 2026-10-12 20:23:07 | APPROVE 5 / REJECT 3 / NEED_REVIEW 0 / READ_FAILED 0 / SKIP 0  | 自动化 100.0% / 负担 0.0%   | 投递成功 28 / 失败 0 / 率 100.0% |
| 2026-10-12 20:39:53 | APPROVE 8 / REJECT 2 / NEED_REVIEW 4 / READ_FAILED 0 / SKIP 0  | 自动化 71.4% / 负担 28.6%   | 投递成功 36 / 失败 0 / 率 100.0% |

| 2026-10-12 20:46:43 | APPROVE 11 / REJECT 2 / NEED_REVIEW 0 / READ_FAILED 0 / SKIP 0 | 自动化 100.0% / 负担 0.0% | 投递成功 46 / 失败 1 / 率 97.9% |

| 2026-10-12 21:08:11 | APPROVE 4 / REJECT 1 / NEED_REVIEW 2 / READ_FAILED 0 / SKIP 0 | 自动化 71.4% / 负担 28.6% | 投递成功 50 / 失败 1 / 率 98.0% |
| 2026-10-12 21:18:10 | APPROVE 47 / REJECT 7 / NEED_REVIEW 4 / READ_FAILED 0 / SKIP 0 | 自动化 93.1% / 负担 6.9% | 投递成功 97 / 失败 1 / 率 99.0% |
| 2026-10-12 21:22:00 | APPROVE 12 / REJECT 0 / NEED_REVIEW 1 / READ_FAILED 0 / SKIP 0 | 自动化 92.3% / 负担 7.7% | 投递成功 109 / 失败 1 / 率 99.1% |
| 2026-10-12 21:33:50 | APPROVE 41 / REJECT 6 / NEED_REVIEW 7 / READ_FAILED 0 / SKIP 0 | 自动化 87.0% / 负担 13.0% | 投递成功 134 / 失败 17 / 率 88.7% |
