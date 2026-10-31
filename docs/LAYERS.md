# 分层功能清单（LAYERS）

四层职责一句话：**生物层决定「她是什么状态」；模型层决定「她怎么做事」；记忆层决定「她记得什么」；解释层决定「怎么说出来 / 怎么读回来」。**

## 一、生物层（Biological）

文件：`main.py`（BioCore 类，273 个方法）、`homeostasis.py`（362 行）

### 1.1 情绪内核
```
v/a/d/social/stress/energy/trust        七维主状态
labels / spectrum_probs / compound     情绪标签与复合情绪
infer_labels / _spectrum / _calibrate_spectrum_prototypes
emotion_decay_factors / valence/arousal/social_decay_minutes  衰减
apply_affect / feedback / _decay_to_now  事件→情绪增量
regulation / regulation_stats / _choose_regulation  调节策略
```
### 1.2 评价与归因
```
appraisal{novelty, goal_relevance, coping, agency, norm_compatibility}
meta_emotion / goal_conflict / _update_meta_emotion
attribution（新，Weiner 三轴）
```
### 1.3 生理与稳态
```
homeostasis.step / drives / need_pyramid / interoception
circadian_alertness / _apply_circadian_effects
allostatic_load / _update_allostatic_load
energy / social / stress
```
### 1.4 关系
```
relationship_dynamics / relationship_context / trust
conflict_ema / update_conflict_ema
gottman 命中 / repair_step（relationship_meta 内的生物侧算法）
```
### 1.5 目标与自我
```
goals / goal_focus / goal_scores / _advance_goals / _resolve_goal_conflict
open_loops / update_open_loops / open_loops_due
narrative_self / core_self / autobiography / self_timeline
```
### 1.6 记忆痕迹与反刍
```
echo / echo_trace / apply_memory_trace
rumination_ema / update_rumination_ema / rumination_suppress
reconsolidation_seconds / retention_model
```
### 1.7 自主循环（生物侧旧实现）
```
autonomy_loop_tick / _autonomy_loop_candidates / _autonomy_loop_param
（与模型层 autonomy_model 并存，属于历史遗留，待收敛）
```

## 二、模型层（Model / 行为与设定）

文件：`biocore_model/`（36 个模块）

| 组 | 模块 | 作用 |
|---|---|---|
| 自主 | autonomy_model / autonomy_loop / autonomy_reason / autonomy_check / autonomy_affect | 累积、阈值、原因、诊断、反作用 |
| 设定 | autonomy_mode / plugin_config / ui_settings | 面板设置与持久化 |
| 关系 | relationship_stage / connection_bids | 关系阶段、bid、信任 |
| 情绪外壳 | self_esteem / social_pain / mood / attachment_state / attribution | 生物层新字段的纯函数 |
| 行为学 | frustration_curve / memory_forgetting / social_repair / social_theory / sleep_circadian / needs_esteem | 论文机制实现 |
| 回复规则 | reply_limit / reply_split / prompt_rules | 长度、分段、行为规则 |
| 核心切换 | core_mode / core_commands / core_client / core_bridge | 核心迁移与兼容 |
| 工具 | migrate_store / services / archive_queue | 迁移、服务、归档 |

## 三、记忆层（Memory）

### 3.1 插件内记忆元数据（`memory_meta.py`，2335 行 / 92 函数）
```
来源与置信：source_for_input / initial_confidence / update_confidence / merge_sources
层级：memory_tier / retrieval_weight / is_self_defining
冲突：detect_conflict / merge_version / rollback_entry
检索：select_top / summarize_recall / retrieval_inhibition
作答约束：should_abstain / abstention_gate / answer_gate / answer_confidence
写操作：classify_write_op / build_destination / schema_congruence
```
### 3.2 DSH 记忆引擎（`dsh-biocore-memory/`，独立进程）
```
契约 v1.20 / 56 方法；store / recall / forget / checkup
BM25 + 向量 + 衰减 + MMR 排序
```
### 3.3 事件库
```
remember_event / event archive / event_anchors / daily_digests
```

## 四、解释层（Interpretation）

### 4.1 输出（状态→LLM 输入）
```
plan / self_block / user_block / memory_block / event_block / image_block
render_compact / render_semantic / semantic_brief
compose_bc_block（预算 + 去重 + 排序）
prompt_rules.render_rules / render_length_rule / render_speak_style
proactive_context.build_proactive_prompt
```
### 4.2 输入（LLM 输出→状态增量）
```
parse_response / _payload_to_update / _repair_json_payload
strip_protocol_echo / leak_guard_snapshot / note_prompt_rule_echo
```
### 4.3 呈现与安全
```
sanitize.py（最终文本清理）
reply_split / reply_limit
```
### 4.4 关系解释
```
relationship_meta.py（843 行 / 30 函数）：absence_state / attachment_profile /
closeness_step / gottman_hits / repair_step / apply_tom_update
```

## 五、孤儿模块审查结果

| 模块 | 结论 |
|---|---|
| `archive_queue.py` | 仅测试引用，主流程未调用 → 归档批处理未启用 |
| `core_bridge.py` | 6 处引用在自身与测试，main 只有 core_mode 相关引用 → 桥接层可能已废弃 |
| `core_client.py` | 默认关闭的客户端，保留 |
| `migrate_store.py` | 一次性迁移工具，保留但不再调用 |

## 六、汇总

```
生物层：273 方法 + 362 行稳态模块         （最厚）
记忆层：2335 行元数据 + 独立引擎 56 方法
解释层：2052 行 + 关系 843 行             （第二厚）
模型层：36 个模块                          （最新，多为行为学实现）
```

结论：**四层都已有实装，缺的是「表达」和「反馈」的收口**，不是缺功能。
