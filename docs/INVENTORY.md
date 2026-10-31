# 现状清单（INVENTORY）

> 目的：先搞清楚「我们到底有什么」，再决定加什么。
> 更新方式：每次任务完成后同步此表。

## 一、生物层（BioCore 核心状态，唯一真相源）

### 1.1 快照字段（snapshot() 输出）

```
情绪：v, a, d(支配), social, stress, energy, trust
疼痛/自我：self_esteem, social_pain
心情/依恋：mood{valence,arousal}, attachment{style,activation,mode}
评价：appraisal{novelty,goal_relevance,coping,agency,norm_compatibility,...}
归因：attribution{locus,stability,controllability,emotion_hint}
生理：circadian_alertness, allostatic_load, homeostasis, energy
记忆/反刍：echo, echo_trace, rumination_ema, reconsolidation
关系：relationship_dynamics, interpersonal, conflict_ema
目标：goals, goal_focus, goal_scores, open_loops, open_loops_due
自我叙事：autobiography, self_timeline, narrative_self, core_self
其它：noise, ripple, spiking, momentum, attention, boredom, info_gap,
      boundary_pressure, refusal_readiness, regulation_stats, meta_emotion
```

### 1.2 生物层内部子系统（BioCore 类属性，共 120+ 项）

- 情绪动力学：emotion_decay_factors, valence/arousal/social_decay_minutes
- 调节：regulation, regulation_stats, soft_bound_*, emotion_gating_enabled
- 关系：relationship_dynamics, gottman_enabled, learning_relationship_enabled
- 学习：learning_state, bio_learning, learning_bandit_enabled
- 记忆：retention_model, reconsolidation_seconds, temporal_validity_enabled
- 目标：goals, goal_conflict, goal_focus, open_loops
- 自我：narrative_self, core_self, autobiography, self_timeline
- 社交：interpersonal, boundary_pressure, refusal_readiness, conflict_ema
- 生理：circadian_alertness, allostatic_load, homeostasis

## 二、自主层（只做「要不要发」与记账）

| 模块 | 作用 | 状态 |
|---|---|---|
| autonomy_model.py | drive/gate/step/apply_fire/权重 | 在用 |
| autonomy_loop.py | bid 结果、回应率、学习 | 在用 |
| autonomy_reason.py | 触发原因提取 + prompt | 在用 |
| autonomy_check.py | 只读诊断 | 在用 |
| autonomy_mode.py | 面板设置校验 | 在用 |
| autonomy_affect.py | 自主→生物层的增量 | 在用 |
| autonomy_tick（在 main.py 内） | 每 5 分钟 tick | **待拆（task-104）** |

## 三、重复实现（待收敛，task-103）

| 能力 | 生物层 | 自主层重复 | 处理 |
|---|---|---|---|
评价 | core.appraisal | appraisal_action.py | 删自主层，读生物层 |
需求 | homeostasis.need_pyramid | needs_esteem.py | 改为委托 |
心情 | core.mood（已迁） | attachment_regulation.py 包装 | 已兼容 |
依恋 | core.attachment（已迁） | 同上 | 已兼容 |
反刍 | rumination_ema | memory_forgetting 反刍对象 | 合并 |
昼夜 | circadian_alertness | sleep_circadian 节律 | 合并 |
负载 | allostatic_load | task-90（暂停） | 取消 |
信任 | relationship.trust | connection_bids 三层 | 合并 |

## 四、未接线模块（ORPHAN）

```
archive_queue.py   归档批处理（未见调用）
core_bridge.py     AstrBot→BioCore 桥（可能已废弃）
core_client.py     客户端（默认关闭）
migrate_store.py   迁移工具（一次性，保留）
```

## 五、面板可见项（自主行为页）

```
开关：启用 / 允许发送 / 黏人模式
参数：依恋风格 / 拒绝敏感性 / 每日上限 / 阈值 / 最大字数
状态：V进度 / 动机分解 / 等待时长 / 自责与自信 / 本小时额度 /
      闭环统计 / 上次主动 / 需求 / 自尊 / 社会疼痛 / 归因 /
      心情 / 依恋 / 调节 / 挫折 / 间隔 / 关系阶段 / 感激 / 共情 /
      连接邀请 / 信任 / 睡眠 / 模板 / 她今天 / 她猜你
```

## 六、任务完成状态

```
✅ task-80 睡眠节律      ✅ task-81 遗忘反刍     ✅ task-82 四需求（待收敛）
✅ task-83 bid/信任      ✅ task-84 自我生活     ✅ task-85 关系阶段
✅ task-86 依恋调节      ✅ task-87 评价行动     ✅ task-88 挫折强化
✅ task-89 感激修复      ⏸ task-90 危机（暂停） ✅ task-91 自尊
✅ task-92 社会疼痛      ✅ task-93 归因         ✅ task-94 心情依恋迁入
☐ task-95 需求/睡眠债迁入  ☐ task-96~99 表达层   ☐ task-100~102 反馈层
☐ task-103 架构收敛      ☐ task-104 拆分 tick
```

## 七、结论

1. **生物层已经很完整**（120+ 属性、40+ 快照字段），大多数心理量不需要新建。
2. 真正缺的是：**表达层**（把状态写成话）和 **反馈层**（LLM/用户行为写回）。
3. 目前重复 8 处，需在表达层开工前收敛（task-103 提前）。
4. 有 4 个孤儿模块，需确认是否废弃。


- `biocore_model/needs_sleep.py`：生物层四需求（含 control/meaningful_existence）与睡眠债，纯函数；`needs_esteem.py` 委托。


## ARCH-1 收敛结果（task-103）

| # | 重复项 | 改前 | 改后 | 状态 |
|---|---|---|---|---|
| 1 评价 | appraisal_action 五维 | 自主层自算 | 委托 L0 `bio_appraisal` | ✅ |
| 2 需求 | needs_esteem 四需求 | 自主层自算 | 委托 `needs_sleep`（task-95） | ✅ |
| 3 反刍 | memory_forgetting | 单处 | 保持单处，无 core 赋值 | ✅ |
| 4 昼夜 | sleep_circadian | 自算节律 | 新增 `circadian_from_snapshot` 优先读 core | ✅ |
| 5 负载 | allostatic_load | 仅生物层 | 无自主层副本（grep 确认） | ✅ |
| 6 信任 | connection_bids.trust_update | 自主层并行存储 | 新增 `trust_from_relationship` 派生，旧函数 deprecated | ✅ |
| 7 心情/依恋 | attachment_regulation | 自主层自算 | 委托 mood/attachment_state（task-94） | ✅ |
| 8 评价→情绪 | appraisal_action 映射 | 两处 | 统一在 L0 `bio_appraisal` | ✅ |
