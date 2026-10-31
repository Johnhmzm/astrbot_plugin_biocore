# 层边界（LAYER-BOUNDARY）

架构原则：**生物层是唯一中枢**，解释层只读取/渲染，main.py 只做调用、写回、日志。

| 字段/机制 | 归属 | 模块 | 说明 |
|---|---|---|---|
| self_esteem（状态自尊） | 生物层 | `biocore_model/self_esteem.py` | 纯函数 update/decay/view；main 只调用后写回 core，不写公式 |
| social_pain（关系性疼痛） | 生物层 | `biocore_model/social_pain.py` | 只由关系事件驱动；与 stress（任务性）/allostatic_load（长期负荷）**三字段独立，禁止互相赋值** |
| autonomy（驱动/累积） | 生物层 | `autonomy_model.py` | 同上 |
| affect / silence / blame | 生物层 | `autonomy_affect.py` 等 | 增量施加，解释层不计算 |
| needs / sleep_debt | 生物层 | `biocore_model/needs_sleep.py` | Williams 四需求扩展 control/meaning + Borbély 睡眠债；needs_esteem 旧函数改为委托 |
| mood（心情慢变量） | 生物层 | `biocore_model/mood.py` | 自主层 attachment_regulation.mood_update 仅 re-export；`mood.label` 供表达层定基调 |
| attachment（依恋激活） | 生物层 | `biocore_model/attachment_state.py` | threat/mode/decay；自主层旧函数改为包装器（兼容），不保留第二套公式 |
| attribution（归因） | 生物层 | `biocore_model/attribution.py` | Weiner 三轴；与 appraisal 分工：「意味着什么」vs「为什么」，字段分开互不影响 |
| expr_intent（意图选择） | 表达层 | `biocore_model/expr_intent.py` | 八类候选加权选择；只读、无真实事件不返回 gratitude/memory_due、同 kind 连续两次排除 |
| expr_tone（语气指令） | 表达层 | `biocore_model/expr_tone.py` | 行动倾向→语气指令+字数系数；不覆盖 prompt_rules 长度规则，不输出心理学术语 |
| expr_state（完整状态渲染） | 表达层 | `biocore_model/expr_state.py` | 只读生物层快照+关系，纯函数；不写状态、不读文件；人类语言不暴露字段名 |
| prompt 文案 / 渲染 | 解释层 | `interpretation.py` / `prompt_rules.py` | 只读数值，不改心理公式 |

约束：新增心理变量必须先建纯函数模块（无 IO/全局状态），再在 main 接线；禁止在 main.py 内写心理公式。
