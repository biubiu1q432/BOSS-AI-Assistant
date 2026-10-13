# BOSS-AI-Assistant

BOSS直聘自动化投递技能。依赖 Kimi WebBridge 控制**已登录的 Chrome**，在指定频道内滚动取岗位、读取 JD、按画像规则判定后投递，并生成投递汇总报告。

当前版本：**v5.6.7**

## 它能做什么

- 锁定指定频道（如「算法工程师(广州)」）与城市，全程不换频道
- 无限滚动持续取岗位（实测单次可滚到 330 张卡），滚动停摆时 `--step refresh` 兜底换一批
- 批量加速器 `batch_deliver.py`：一次调用完成整批「读 JD → 规则判定 → 投递」
- 规则保守：命中拒绝信号即 REJECT，拿不准转 NEED_REVIEW 交人工，绝不盲目投
- 两道安全闸：同公司重复拦截、已投递记录跳过
- 生成带时间戳的 HTML 投递汇总报告

## 依赖

- Python 3.11+（仅用标准库）
- Kimi WebBridge，守护进程监听 `127.0.0.1:10086`
- Chrome 已登录 BOSS直聘

## 快速开始

```powershell
$env:BOSS_PROFILE = "integration"        # 可选：integration / algorithm / hybrid
$env:BOSS_WORK_DIR = "C:\path\to\run"    # 可选：运行目录，默认当前目录

python scripts/serial_loop.py --step init          # 锁定频道
python scripts/serial_loop.py --step next-batch    # 滚动取岗位，可反复执行
python scripts/build_jd.py                         # 从当前 DOM 构建候选池
python scripts/batch_deliver.py --dry-run          # 预演规则判定
python scripts/batch_deliver.py --apply            # 真实投递
python scripts/serial_loop.py --step finish        # 生成汇总报告
python scripts/batch_deliver.py --report           # 回测规则指标
```

供给不足时：继续跑 `--step next-batch`；滚动确实不再出货才用 `--step refresh`。

## 目录结构

```
SKILL.md                 主文档：触发条件、核心流程、高频红线
CHANGELOG.md             版本迭代日志（资产清单 + 逐版记录）
user_profile.json         默认画像（不含任何个人信息，需自行填写）
profiles/                三套预设画像：integration / algorithm / hybrid
scripts/                 19 个模块，分 A(活跃三层循环) / B(遗留五阶段) / C(包基建)
references/              参考文档
  ├── error_rules.md       真实事故规则归档（三段式，按频率排序）
  ├── diagnosis_playbook.md 浏览器诊断作战手册
  ├── operations.md        操作手册
  ├── pitfalls.md          反例表
  └── ...
```

## 高频红线

**必须做**：锁定画像频道与城市；用滚动取岗位；报穷尽前先核对唯一 jobId 计数与滚动次数；每波用 `build_jd.py`（不带 `--append`）全新构建候选池；投递只走 `batch_deliver.py`；读 JD 前先判安全验证页；候选超 30 条用后台进程；收尾 `--step finish`。

**禁止做**：改 `BOSS_CHANNEL_TAB` / `BOSS_CITY_CODE`（需 `BOSS_ALLOW_OVERRIDE=1` 且用户明确指示）；把"滚动无新增"当成没岗位并据此换频道/城市/走搜索页；为取候选或编排另写脚本；在安全验证页继续点击；跨波用 `--append` 累积候选；用按钮文案判定投递成败（金标准＝聊天列表出现 `[送达]`）；自动放行 `NEED_REVIEW`。

完整案例与成因见 [references/error_rules.md](references/error_rules.md)。

## 配置

| 环境变量 | 作用 |
|---|---|
| `BOSS_PROFILE` | 切换预设画像 |
| `BOSS_WORK_DIR` | 运行目录（信号文件、缓存、报告） |
| `BOSS_CHANNEL_TAB` | 覆盖频道（**需同时设 `BOSS_ALLOW_OVERRIDE=1`**） |
| `BOSS_CITY_CODE` | 覆盖城市（**需同时设 `BOSS_ALLOW_OVERRIDE=1`**） |

## 说明

- 代码不含任何特定用户信息，`user_profile.json` 是唯一数据源，使用前请填写自己的求职画像。
- 自动化投递受平台每日上限与风控约束；命中安全验证页时脚本会立即停手并交回人工处理。
- 本项目仅用于个人求职效率工具，请遵守平台规则。
