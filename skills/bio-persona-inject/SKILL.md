---
name: bio-persona-inject
description: >-
  Use when a persona prompt must be compiled once by the LLM into numeric
  tendencies and injected into the biological emotion core (traits, affect
  baselines, drives, autonomy, learning rate). Not for per-turn prompt parsing.
---

# Bio Persona Inject

## 原则

Persona text = semantic layer, stays as prompt.
Persona numbers = tendencies, compiled once.
Never parse persona with LLM every turn.
Never write persona numbers into memory/facts/safety.

## 流程

1. 保存当前 bio_profile 到 backups/
2. 输入 persona 文本：
   python apps/dsh_persona_compile.py --text "..."
   或 --file persona.txt
3. LLM 输出 persona.json（一次调用）
4. Companion 启动时读取 persona.json
5. 若 bio.persona_version 不一致，按顺序注入：
   traits -> affect baseline -> drives -> autonomy/learning
6. 写入 bio_profile，记录 persona_version

## 注入白名单

O C E A N
baseline_v baseline_a
stress_reactivity recovery_rate
social/energy/curiosity/safety baseline
da/oa/ht baseline
autonomy_gain
learning_rate

## 禁止

memory contents
user facts
goals
identity claims
safety policy
fixed catchphrases

## 文件

- apps/dsh_persona_compile.py
- mindbase/persona_bridge.py
- mindbase/data/chat_app/persona.json

## 验证

590 tests
第一次编译稳定
同一 persona 得到同一 profile
profile 变化可回滚
## 数值字典（唯一真源）

- 字段名/范围/含义/基线：`docs/NUMERIC-SCHEMA.md`，由 `biocore_model/schema.py` 的 `GROUPS` 生成；改字段先改 schema.py 再重新生成文档。
- 运行时图例 `schema.numeric_legend(snapshot)` 只列 |x-baseline| > 0.15 的 3–5 项，总长 ≤400 字，注入 system（人设之后、输出格式之前）。
- `biocore_model/autonomy_params.py` 的 theta/tau/cooldown 均已由人设推导；不要再把 0.55/1800s 等硬编码当默认。