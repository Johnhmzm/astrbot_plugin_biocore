# 参数出处表（PARAM-PROVENANCE）

规则：每个参数必须能归入下面四类之一。**不允许出现「论文没写但我当成论文」的情况**。

| 标签 | 含义 |
|---|---|
| `[原值]` | 论文/标准模型给出可直接用的数值 |
| `[方向]` | 论文给出方向/顺序，具体数值待校准 |
| `[校准]` | 由「目标行为」反推得到的数值，需参数恢复测试验证 |
| `[工程]` | 与拟人无关的工程约束（防刷屏、性能、存储） |

## 一、结构（有论文支撑）

| 机制 | 论文 | 代码位置 |
|---|---|---|
| 社交需求累积与饱和 | Matthews & Tye 2019 | social_gap / 回复后 V×0.3 |
| 分离三阶段 | Bowlby 1969/1973 | silence_phase |
| 依恋风格差异 | Bartholomew & Horowitz 1991；Mikulincer & Shaver 2007 | attachment_style 系数 |
| 社会计量器→自责 | Leary 1995 | self_blame |
| 自责两型 | Janoff-Bulman 1979 | 行为性自责权重 |
| 拒绝敏感性 | Downey & Feldman 1996 | rejection_sensitivity |
| 打扰的期望效用 | Horvitz 1999 | gate() |
| 证据累积+噪声越阈 | Ratcliff 1978（DDM） | step() |
| 挫折增强动机 | Amsel 1958；Brehm 1966 | frustration → frust_mult |
| 间歇强化 | Ferster & Skinner 1957 | 黏人模式 |
| 反刍 | Nolen-Hoeksema 1991 | echo / rumination |
| 事件到期与未了结 | Zeigarnik 1927 | open_loops / memory_due |
| 情绪→行动倾向强度不等 | Frijda 1986；Scherer 2005 | 权重相对大小 |

## 二、参数逐项标注

### 2.1 社交缺口

| 参数 | 当前值 | 标签 | 说明 |
|---|---|---|---|
| `tau_hours` | 18 | 校准 | 指数累积时间常数；论文只给「累积-饱和」形状，无小时数 |
| social_baseline 乘子 | 0.6+0.4×closeness | 方向 | 越亲近越在意联系（Canary & Stafford 1994） |

目标：`Tau=18h` 应使「一天没联系」的社交缺口落在 0.5 左右（可测）。

### 2.2 情绪权重

| 参数 | 当前值 | 标签 | 说明 |
|---|---|---|---|
| `w_social` | 0.25 | 校准 | 主导项，需与阈值匹配 |
| `w_lonely` | 0.12 | 校准 | |
| `w_anxiety` | 0.12 | 校准 | |
| `w_sadness` | 0.10 | 校准 | |
| `w_joy` | 0.08 | 校准 | |
| `w_anger` | 0.08 | 校准 | |
| `w_boredom` | 0.05 | 校准 | |
| `w_stress` | 0.10 | 校准 | |
| `w_drive` | 0.10 | 校准 | |

排序依据（可引）：恐惧/愤怒 > 悲伤 > 愉悦（Frijda 1986 行动倾向）；
具体数值无出处，全部为校准值。

### 2.3 DDM 累积

| 参数 | 当前值 | 标签 | 说明 |
|---|---|---|---|
| `leak` | 0.15 | 工程 | 每 tick 漏 15%，半衰期 4.3 tick |
| `theta` | 0.55 | 工程 | 阈值 |
| `sigma` | 0.06 | 校准 | 噪声幅度，决定「临界抖动」 |
| tick 间隔 | 300s | 工程 | 计算/打扰频率 |
| 冷却 | 30min | 工程 | 防刷屏 |

**已知问题（待校准）**：稳态度 V∞ = drift/leak ≈ 0.43 < theta 0.55，
导致触发依赖噪声越界而非稳定累积。校准目标见下。

### 2.4 沉默阶段边界

| 阶段 | 当前边界 | 标签 | 说明 |
|---|---|---|---|
| expect | 0–2h | 校准 | |
| protest | 2–6h | 校准 | |
| loss | 6–24h | 校准 | |
| withdraw | >24h | 校准 | |

论文只给出顺序（protest→despair→detachment），**小时数无出处**。
依恋系数：anxious 1.4/0.9、secure 1.0/0.35、avoidant 0.8/0.2 均为校准。

### 2.5 自责

| 参数 | 当前值 | 标签 | 说明 |
|---|---|---|---|
| 曲线 | (h/24)·RS·coef，封顶 0.7 | 校准 | 方向有据（Leary 1995），形状无据 |
| `rejection_sensitivity` | 0.4 | 校准 | 个体差异参数 |
| 衰减窗口 | 4h | 工程 | 用户回话后线性归零 |

### 2.6 挫败与频控

| 参数 | 当前值 | 标签 | 说明 |
|---|---|---|---|
| 每次被拦 +3% 冲动 | 0.03 | 校准 | 方向有据（Amsel 1958），幅度无据 |
| 封顶 +30% | 1.30 | 工程 | 防失控 |
| 每日上限 | 5 | 工程 | 体验约束 |
| 每小时 | ceil(daily/3) | 工程 | 防刷屏 |
| 静默时段 | 0–8 | 工程 | 常识 |

### 2.7 打断决策（gate）

| 参数 | 当前值 | 标签 | 说明 |
|---|---|---|---|
| `gate_c0` | 0.35 | 校准 | Horvitz 1999 只给 E[U]=P·B−C 形式，无具体成本 |
| 安静时段 +0.25 | 0.25 | 校准 | |
| 刚说话 −0.15 | 0.15 | 校准 | |
| 寂寞/焦虑折扣 −0.10/−0.08 | | 校准 | |
| 愤怒 +0.10 | | 校准 | |

## 三、校准目标（先定效果，再反推数值）

| 编号 | 目标现象 | 可测指标 | 当前是否满足 |
|---|---|---|---|
| T1 | 强烈焦虑（0.8）单独可在 30–60 分钟内触发 | 伪时间模拟：仅 anxiety=0.8，记录触发 tick 数 | ❌ 不可能（权重太小） |
| T2 | 6 小时沉默带来可见情绪变化 | core.v 变化 ≥ 0.10 | ❌ 当前 −0.015 |
| T3 | 被限流 5 次后明显「急」 | drift 提升 ≥ 20% | ⚠️ 系数够但基数小 |
| T4 | 稳态不落在阈值附近抖动 | V∞ ≤ 0.8×theta，且强信号可越过 | ❌ 0.43 vs 0.55（临界） |
| T5 | 一天没联系，社交缺口 ≈ 0.5 | social_gap(24h, Tau=18) | ✅ ≈0.51 |
| T6 | 自责在 24h 达到 RS×coef | self_blame(24h) | ✅ |
| T7 | 强烈自责（0.7）使表达明显犹豫 | confidence ≤ 0.7 | ✅ 0.65 |

## 四、校准方法（方法论文献）

- Wilson & Collins 2019, *Ten simple rules for the computational modeling of behavioral data*（eLife）：
  先定义目标现象 → 选可测指标 → 拟合参数 → 做参数恢复。
- Palestro et al. 2018：参数恢复（parameter recovery）——用模拟数据验证能否找回参数。
- 本项目的落地：`scripts/autonomy-calibrate.mjs`（待写）对 T1–T7 逐条跑伪时间模拟并输出是否达标。

## 五、执行顺序

1. 先按 T1–T4 重算权重/阈值/噪声（目标驱动，不拍脑袋）
2. 每个新值回填本表，标注 `[校准]` 与目标编号
3. 写校准脚本，作为发版前必跑项
4. 任何参数改动必须同时更新本表，否则视为未完成


## 五、校准结果（2026-10-31，scripts/autonomy-calibrate.py）

| 编号 | 结果 | 数值 |
|---|---|---|
| T1 焦虑单独触发 | PASS | anxiety=0.8 → drift=0.120，第 8 tick 触发（目标 6–12） |
| T2 6h 沉默情绪可见 | PASS | valence −0.120（目标 ≥0.10） |
| T3 限流 5 次更急 | PASS | drive_mult 1.20（+20%） |
| T4 稳态不临界 | PASS | baseline drift=0.050，V∞=0.333=0.61×theta（≤0.8） |
| T5 24h 社交缺口 | PASS | 默认 baseline 0.7/closeness 0.5 → 0.55 |
| T6 24h 自责 | PASS | 0.400 = RS×coef |
| T7 自责 0.7 犹豫 | PASS | confidence 0.650 |

**第二轮 [校准] 改动（非零保留）**：social 0.16 / lonely 0.08 / anxiety 0.13 / sadness 0.07 / joy 0.06 / anger 0.06 / boredom 0.03 / stress 0.07 / drive_dev 0.06 / open_loops 0.04 / nostalgia 0.02 / repair 0.02 / distress 0.04 / activity 0.03 / memory_due 0.10 / guilt 0.02 / gratitude 0.01 = 1.00（全部 >0）；T1=10 tick、T8=11 tick、T9 不触发。

**首轮 [校准] 改动**：w_anxiety 0.12→0.15、w_social 0.25→0.20、w_sadness 0.10→0.09、w_stress 0.10→0.09、w_drive 0.10→0.08、w_nostalgia 0.03→0.02、w_boredom 0.05→0.04（总和=1.0，distress/activity/memory_due/guilt/gratitude 权重归 0，仅保留 parts 观测）；silence valence 系数 0.06→0.60、lonely 0.08→0.50（/24h×weight）；frustration 0.03→0.04（封顶 1.30）；theta 保持 0.55。


## 六、关系阶段参数来源

| 参数 | 来源 | 值 |
|---|---|---|
| 阶段阈值 | Hall 2019（约 50h 熟人→朋友、90h→好友） | stranger <10h / acquaintance 10–50h / friend 50–90h / close >90h |
| Tau / daily | Dunbar & Saramäki 2012 频率分层 + Hall 2019 | stranger 8h/1、acquaintance 14h/3、friend 24h/5、close 36h/7 |
| 最小间隔 | Dunbar 2012 | 24h/(daily×0.6) |
| 习惯化 | Rankin 2009 | novelty=0.85^重复次数，<0.3 禁用 24h（7 天窗口） |
