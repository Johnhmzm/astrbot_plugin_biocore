# 分层契约（LAYER-CONTRACT）

六层 + 一条横切反馈通道。每个模块文件首行必须写明 `层：Lx`。

```
L5 适配层  AstrBot 接入 / 面板 API / 命令
L4 交互层  何时发起、频率、闸门、记账
L3 表达层  状态 → 语言输入（说什么、怎么说）
L2 解释层  语料 ↔ 结构化（解析消息、渲染上下文）
L1 记忆层  存 / 取 / 衰减 / 再巩固
L0 生物层  状态内核（情绪/需求/关系/目标）
─────────────────────────────
反馈通道   行为结果 → 状态增量（横切 L1–L4）
```

## 契约表

| 层 | 读 | 写 | 禁止 |
|---|---|---|---|
| L0 生物层 | 无 | 情绪/需求/关系/目标 | 不读消息文本、不碰 prompt |
| L1 记忆层 | 事件、查询 | 记忆条目、强度 | 不改情绪 |
| L2 解释层 | 消息文本、LLM 输出 | 语义事件、结构化增量 | 不直接改状态 |
| L3 表达层 | 生物层快照 | **纯文本**（prompt 片段） | 不改状态、不编造事实 |
| L4 交互层 | 冲动、限额 | 是否发送、记账 | 不生成文案 |
| L5 适配层 | 平台事件 | 平台消息 | 不含心理逻辑 |
| 反馈通道 | 行为结果 | 状态增量（delta） | 不直接 set 字段 |

## 当前文件归属

```
L0  biolayer: main.py(BioCore 类) / homeostasis.py
L1  memory_meta.py / dsh-biocore-memory / 事件库
L2  interpretation.py / render.py / relationship_meta.py
L3  expr_state.py / expr_tone.py / expr_intent.py
    expr_template.py(待) / expr_guard.py(待)
L4  autonomy_model.py / autonomy_loop.py / autonomy_reason.py
    autonomy_check.py / autonomy_mode.py / autonomy_tick.py(待拆)
L5  main.py(plugin 层) / pages/ / scripts/
反馈 feedback_llm.py(待) / feedback_user.py(待)
     feedback_memory.py(待) / feedback_guard.py(待)
```

## 表达层（L3）完整清单

| 模块 | 职责 | 状态 |
|---|---|---|
| expr_state | 状态 → 12 段中文块 | ✅ |
| expr_tone | 情绪/调节 → 语气 + 字数系数 | ✅ |
| expr_intent | 决定这次说什么 | ✅ |
| expr_template | 主动/回复两套拼装 | 待 |
| expr_guard | 不许说什么（不编造/不复述数值/不内疚绑架） | 待 |

## 反馈通道清单

| 模块 | 职责 | 状态 |
|---|---|---|
| feedback_llm | LLM 输出 → 生物层增量 | 待 |
| feedback_user | 用户行为 → 生物层增量 | 待 |
| feedback_memory | 事件 → 记忆强度 | 待 |
| feedback_guard | 写回校验（clamp/单步上限/审计） | 待 |

## 检查规则

1. 新增模块必须声明层号；跨层调用要在注释写明。
2. 表达层不得出现 `core.x =` 赋值（只读）。
3. 交互层不得出现字符串模板（不生成文案）。
4. 反馈通道只返回 delta dict，由 L0 应用。
5. 收敛（task-103）按本表逐项核对归属。


## ARCH-1（task-103）

| 心理量 | 归属层 | 文件 | 说明 |
|---|---|---|---|
| appraisal/情绪分化 | L0 | `bio_appraisal.py` | 唯一数值源；`appraisal_action` 为包装器 |
| needs/sleep_debt | L0 | `needs_sleep.py` | `needs_esteem` 委托 |
| rumination | L1/L0 交界 | `memory_forgetting.py` | 单处，无 core 赋值 |
| circadian | L0 | `sleep_circadian.py` | 优先读 core.`circadian_alertness` |
| allostatic_load | L0 | homeostasis | 无自主层副本 |
| trust | L0 关系 | `connection_bids.py` | 新增派生 `trust_from_relationship`；旧 `trust_update` deprecated |
| mood/attachment | L0 | `mood.py`/`attachment_state.py` | `attachment_regulation` 仅包装 |


## MOD-2（task-106）

`autonomy_tick_engine`（legacy|module，默认 legacy）：module 模式由 main 组装真实 deps（ui_settings accumulator、`_autonomy_private_sessions`/`_latest_private_core`、core.snapshot、autonomy_model.step/send_gate、_AutonomySendTarget 发送、expr_template/模板文本、logger），异常自动回退 legacy；两条路径都输出 V/theta/decision/reason 日志。面板可切换并持久化（page/autonomy `tick_engine`）。
