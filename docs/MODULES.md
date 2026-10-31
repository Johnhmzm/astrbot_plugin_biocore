# 模块说明表（MODULES）

> 57 个模块，按层分组。行数不含测试。

## L0 生物层（mixin）（5 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `bio_state.py` | 231 | 状态：关系上下文、应对、事件记忆、评价意图、记忆痕迹、反刍、拒绝姿态、衰减 |
| `bio_goal.py` | 199 | 目标：签名、证据打分、冲突解决、优先级推进、未了结 |
| `bio_emotion.py` | 128 | 情绪叶子方法：复合情绪、恢复速度、情绪谱概率 |
| `bio_util.py` | 75 | 文本/向量工具：分词命中、余弦、相似度、强度、派生量 |
| `bio_const.py` | 49 | 生物层常量（情绪词典、情绪谱、敏感化参数） |

## L0 生物层（10 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `needs_esteem.py` | 119 | 四需求+自尊旧实现（已委托 needs_sleep） |
| `sleep_circadian.py` | 116 | 昼夜节律与睡眠窗口、睡眠质量→精力 |
| `attachment_regulation.py` | 76 | 依恋调节旧实现（已委托 mood/attachment_state） |
| `attribution.py` | 74 | 归因三轴（内部/外部·稳定·可控）→ 羞耻/愤怒/难过/内疚 |
| `needs_sleep.py` | 73 | 四需求（归属/自尊/控制/意义）+ 睡眠债 |
| `social_pain.py` | 70 | 社会疼痛（被无视/拒绝/排斥），与压力分离 |
| `self_esteem.py` | 51 | 状态自尊（Leary 社会计量器） |
| `bio_appraisal.py` | 50 | 评价与情绪分化（单一来源，供包装器复用） |
| `mood.py` | 49 | 心情慢变量（VALENCE/AROUSAL 基线，6-8 小时收敛） |
| `attachment_state.py` | 42 | 依恋激活与模式（过度激活/安抚/去激活） |

## L1 记忆层（2 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `memory_forgetting.py` | 127 | 遗忘幂律 + 再巩固 + 反刍内容 |
| `feedback_memory.py` | 96 | 反馈：事件再巩固与记忆衰减接线 |

## L2 解释层（3 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `render.py` | 911 | 解释层渲染：把生物状态写成结构化文本 |
| `proactive_context.py` | 152 | 主动消息上下文：状态块、关系、间隔、事件提示 |
| `autonomy_check.py` | 68 | 自主就绪度只读诊断 |

## L3 表达层（5 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `expr_state.py` | 205 | 表达层：状态 → 12 段中文块 |
| `expr_intent.py` | 78 | 表达层：这次想说什么（8 类候选加权选择） |
| `expr_template.py` | 67 | 表达层：主动/回复两套提示词拼装 |
| `expr_tone.py` | 41 | 表达层：行动倾向 → 语气与字数系数 |
| `expr_guard.py` | 25 | 表达层：禁止表达（编造/复述数值/内疚绑架） |

## L4 交互层（6 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `autonomy_model.py` | 648 | 自主核心：drive、闸门、DDM 累积、权重 |
| `autonomy_tick.py` | 134 | L4 编排：一次 tick 的完整流程（依赖注入） |
| `autonomy_loop.py` | 124 | 闭环：bid 结果、响应率、学习调权 |
| `autonomy_mode.py` | 115 | 自主设置校验与持久化 |
| `autonomy_reason.py` | 64 | 触发原因提取 + 提示词/回退文案 |
| `autonomy_affect.py` | 52 | 自主→生物层增量（防重复） |

## 反馈通道（3 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `feedback_guard.py` | 129 | 反馈唯一写入口：白名单/上限/clamp/幂等/审计 |
| `feedback_llm.py` | 88 | 反馈：LLM 输出 → 生物层 delta（带单步上限） |
| `feedback_user.py` | 85 | 反馈：用户行为 → 生物层 delta |

## 编排层（4 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `stages.py` | 458 | 11 个 stage 工厂（感知→呈现） |
| `runtime.py` | 283 | 组装默认流水线 + shadow/active 模式 + 入参上下文 |
| `pipeline.py` | 240 | 流水线执行器：可插拔/可关闭/可隔离/可观测 |
| `pipeline_api.py` | 201 | 流水线 API：状态/开关/试运行/模式持久化 |

## 工具/支撑（19 个）

| 模块 | 行数 | 职责 |
|---|---|---|
| `migrate_store.py` | 337 | 旧存储迁移工具（一次性） |
| `reply_split.py` | 203 | 回复分段策略 |
| `sanitize.py` | 202 | 回复最终清理（标签/协议回显） |
| `reply_limit.py` | 183 | 回复 max_tokens 读写与同步 |
| `core_bridge.py` | 172 | AstrBot→BioCore 桥（历史遗留） |
| `connection_bids.py` | 121 | 连接邀请（Gottman）+ 感知回应性 + 信任三层 |
| `core_client.py` | 121 | BioCore 客户端（默认关闭） |
| `core_commands.py` | 113 | 聊天内核心命令 |
| `social_repair.py` | 111 | 感激/边界/共情/对话修复/时间感知 |
| `frustration_curve.py` | 110 | 挫折倒U曲线 + 可变间隔强化 + 目标 + 自主/胜任 |
| `social_theory.py` | 109 | 自我生活事件/提问回抛/心智理论 |
| `ui_settings.py` | 109 | 面板设置权威存储（跨重启） |
| `core_mode.py` | 99 | 核心模式切换（off/shadow/primary）+ 回滚 |
| `relationship_stage.py` | 97 | 关系阶段（Hall 小时数）+ 联系频率 + 习惯化 |
| `prompt_rules.py` | 92 | 行为规则与长度规则的确定性生成 |
| `plugin_config.py` | 83 | 插件配置原子持久化 |
| `appraisal_action.py` | 79 | 评价→情绪→行动倾向→好奇心（包装器） |
| `services.py` | 79 | 外部服务网关 |
| `archive_queue.py` | 59 | 归档批处理队列（未接线） |

## 各层汇总

| 层 | 模块数 | 说明 |
|---|---|---|
| L0 生物层（mixin） | 5 | |
| L0 生物层 | 10 | |
| L1 记忆层 | 2 | |
| L2 解释层 | 3 | |
| L3 表达层 | 5 | |
| L4 交互层 | 6 | |
| 反馈通道 | 3 | |
| 编排层 | 4 | |
| 工具/支撑 | 19 | |
