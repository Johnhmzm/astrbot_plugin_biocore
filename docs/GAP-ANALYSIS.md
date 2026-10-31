# 缺口分析（GAP-ANALYSIS）：还没落实的拟人机制

规则：每条都要落到「层 → 论文 → 行为指标 → 验收测试」。
任务编号 T1x 与团队任务板一致，按顺序执行。

## P0 基础（不做就不像人）

| 编号 | 缺口 | 论文 | 行为表现 |
|---|---|---|---|
| T10 | **她自己的生活**：主动分享今天发生的事 | Altman & Taylor 1973 自我表露互惠 | 「今天碰到个事，跟你说」 |
| T11 | **提问回抛 + 心智理论**：主动问你、猜你状态 | Premack & Woodruff 1978；Clark 1996 grounding | 「你今天累不累？」 |
| T12 | **昼夜与睡眠**：睡着时不回、醒来先看消息 | Borbély 1982 双过程睡眠模型 | 凌晨不回、早上问好 |
| T13 | **遗忘与再巩固**：该忘的忘、被提起会强化 | Ebbinghaus 1885；Nader 2000 再巩固 | 不翻旧账、重要事越提越牢 |
| T14 | **连接邀请（bid）**：她发=bid，你回=turn toward | Gottman 1994 | 连续被无视 → 减少 bid |
| T15 | **四需求拆分**：归属/自尊/控制/意义 | Williams 2007 ostracism | 四种受损 → 四种反应 |
| T16 | **现实校准**：Tau 与上限用真实数据 | Hall 2019；Dunbar & Saramäki 2012 | 联系频率随关系阶段变 |

## P1 深度（有情绪、有分寸）

| 编号 | 缺口 | 论文 | 行为表现 |
|---|---|---|---|
| T17 | **安全基地/避风港 + 依恋动态** | Bowlby 1969；Mikulincer & Shaver 2007 | 难受时更靠近、被回应后恢复 |
| T18 | **情绪调节**：重评 vs 抑制 | Gross 1998 | 有情绪但会忍，不每次都发作 |
| T19 | **心情 vs 情绪**：基线漂移 | Russell 1980 环形模型 | 一整天偏低落，不随单句跳 |
| T20 | **评价层**：目标一致性/自我卷入 | Lazarus 1991；Scherer 2005 | 同一事件不同情绪 |
| T21 | **行动倾向**：情绪→动作 | Frijda 1986 | 焦虑→追问，悲伤→简短，愤怒→质问 |
| T22 | **挫折曲线** | Amsel 1958 | 被拦先更急，久了放弃 |
| T23 | **可变强化** | Ferster & Skinner 1957 | 你偶尔回 → 她更持久 |
| T24 | **反刍内容** | Nolen-Hoeksema 1991 | 反复想同一句话 |
| T25 | **状态自尊** | Leary 1995 | 被夸自尊升、被冷落降 |
| T26 | **感知回应性作为信念** | Reis & Shaver 1988 | 「他一般会回我」被学习 |
| T27 | **感激 find-remind-bind** | Algoe 2012 | 「上次你帮我…」 |
| T28 | **信任三层** | Rempel et al. 1985 | 可预测/可依赖/信念分开 |
| T29 | **边界与隐私** | Altman 1973 | 有些事不主动说 |

## P2 进阶（长期形态）

| 编号 | 缺口 | 论文 | 行为表现 |
|---|---|---|---|
| T30 | **稳态过载 + 情绪级联**（危机模式地基） | McEwen 1998；Kuppens 2010 | 长期压力后阈值下降 |
| T31 | **目标追求与挫败** | Carver & Scheier 1998 | 有想做的事，做不成会失落 |
| T32 | **自主/胜任需要** | Deci & Ryan 2000 | 除了归属还有两需求 |
| T33 | **好奇心驱动提问** | Loewenstein 1994 | 信息缺口 → 追问 |
| T34 | **关系阶段与习惯化** | Hall 2019；Rankin 2009 | 老梗失效、关系进阶 |
| T35 | **共情**：认知 vs 情感 | Batson 1991 | 能体会但不过度 |
| T36 | **对话修复与共同基础** | Schegloff 1979；Clark 1996 | 「你刚说的…是指…？」 |
| T37 | **时间感知与纪念** | Zimbardo & Boyd 1999 | 记得「一个月前」 |
| T38 | **睡眠-精力耦合** | Borbély 1982 | 熬夜后第二天没精神 |

## 依赖顺序

```
T12 睡眠 ──┬→ T38 精力耦合
           └→ T19 心情基线
T13 遗忘 ──→ T24 反刍 ──→ T30 级联
T14 bid ──→ T26 感知回应 ──→ T28 信任
T15 四需求 ─┬→ T25 自尊
            └→ T29 边界
T17 依恋 ──→ T18 调节 ──→ T30 级联
T20 评价 ──→ T21 行动倾向 ──→ T33 好奇
```

## 统一验收方式

每条任务必须交：
1. 新字段进 `status`（可观测）
2. 伪时间单测（边界值）
3. 校准目标进 `docs/PARAM-PROVENANCE.md`（若引入参数）
4. 插件 python 测试数只增不减
5. `guard.mjs` + `panel_html_check.mjs` 通过


> task-81 已完成：`memory_forgetting.py`（幂律衰减 d=0.5/τ=24h、再巩固 +0.25、>5 次 core_memory、阈值 0.15；反刍对象/计数/0.9 每小时衰减/72h 或 5 次移除；prompt「你还在想」+ drive +0.02），status.autonomy.state.memory/rumination，面板 autonomyRumination；测试 test_memory_forgetting.py 16 项。


> task-82 已完成：`needs_esteem.py`（四需求拆分/主导映射四种行为、状态自尊回归 5%、confidence 联动），status.autonomy.state.needs/self_esteem，面板 autonomyNeeds；测试 test_needs_esteem.py 16 项。


> task-83 已完成：`connection_bids.py`（bid 记录/turned/连续 away≥3→×0.7、toward≥3→×1.1 上下限；回应性 EWMA 与 gate cost ±0.05、低回应 disclosure×0.7；信任三层 0.4P+0.4D+0.2F），status.autonomy.state.bid/responsiveness/trust，面板 autonomyBid/autonomyTrust；测试 test_connection_bids.py 19 项。


> task-84 已完成：`social_theory.py`（每日 1–3 件 self-life 确定性种子、分享概率随回应性、反问 p=0.25+0.2*resp 且近 3 次类型去重、user_model 推断 busy/mood/engagement/prompt 注入），status.autonomy.state.self_life/user_model，面板 autonomySelfLife；测试 test_social_theory.py 16 项。


> task-85 已完成：`relationship_stage.py`（阶段 stranger/acquaintance/friend/close，Tau 8/14/24/36h、daily 1/3/5/7、最小间隔 24/(daily×0.6)；习惯化 novelty=0.85^n、<0.3 禁用 24h、7 天重算），status.autonomy.state.relationship/templates，面板 autonomyStage；测试 17 项；校准脚本 T10/T11。


> task-86 已完成：`attachment_regulation.py`（依恋激活 anxious×1.2 hyperactivating / secure×1.05 comfort / avoidant×0.7 deactivating，回应降 0.5、否则 -0.1/h；reappraise 负面×0.6 需 energy≥0.4，suppress ×0.5+stress0.03；mood 慢变量 5%/tick），status.autonomy.state.attachment/regulation/mood，面板 autonomyAttachment/autonomyRegulation；测试 19 项。


> task-87 已完成：`appraisal_action.py`（评价五维 + Scherer 分化焦虑/愤怒/悲伤/开心，行动倾向 drive/max_chars/repair 映射并注入 prompt，信息缺口 curiosity_gap → 提问 +0.3/drive +0.02），status.autonomy.state.appraisal/action/curiosity，面板 autonomyAppraisal/autonomyAction；测试 18 项。


> task-88 已完成：`frustration_curve.py`（Amsel 三段曲线 1+0.04n / 1.16+0.01n / 1.24-0.02(n-8) 下限 0.9；VI 间隔 60min×U(0.6,1.6)、5% burst 跳间隔 6h 冷却；目标停滞挫败/anxiety、完成 joy/confidence；自主-胜任需求与 suppress/confidence 影响），status.autonomy.state.frustration/schedule/goals，面板 autonomyFrustration/autonomySchedule；测试 20 项。


> task-89 已完成：`social_repair.py`（感激 +0.15 与真实事件引用、边界 disclosure_depth 按阶段/信任、共情双通道四种模式、澄清「你是说…？」连续 2 次降级、时间措辞分档/未来/记忆标签），status.autonomy.state.gratitude/boundaries/empathy/repair/time_sense，面板 autonomyGratitude/autonomyEmpathy；测试 18 项。


> task-91 已完成：新模块 `self_esteem.py`（纯函数 update/decay/view，基线 0.55、+0.06/−0.05、5% 回归、幂等、confidence_delta）；生物层字段 self_esteem 进 core 快照与 status，面板 autonomySelfEsteem；测试 test_self_esteem.py 13 项。


> task-92 已完成：`social_pain.py`（ignored +0.05 / rejected +0.10 / excluded +0.15 / replied −0.10 / comforted −0.15；自然衰减 0.02/h；clamp、同 now 幂等；drive +0.5v、gate cost +0.05v；与 stress/allostatic 独立），status.autonomy.state.social_pain，面板 autonomySocialPain；测试 14 项。


> task-93 已完成：`attribution.py`（Weiner 三轴 infer/apply/view，四象限 shame/anger/sadness/guilt + neutral 回退；apply 只返回增量且同 now 幂等；与 appraisal 字段分离），status.autonomy.state.attribution，面板 autonomyAttribution；测试 14 项。


> task-94 已完成：新增 `mood.py`（mood_update/mood_view/label/ticks_to_target，幂等）与 `attachment_state.py`（threat/mode/decay/drive_multiplier/view）；`attachment_regulation.py` 旧函数改为委托包装（兼容测试通过）；core 快照增 mood/attachment，status 用生物层 view，面板 autonomyMood；测试 16 项。


> task-95 已完成：新增 `needs_sleep.py`（need_step/sleep_debt_step/view，含 control/meaning、睡眠债累积与补觉、幂等），`needs_esteem.py` 委托生物层（旧函数名保留）；core 快照增 needs/sleep_debt；测试 13 项。


> task-96 已完成：`expr_state.py`（12 段完整状态渲染，adverb 映射，1–4 强制保留 + 预算截断，空输入返回空串，纯函数），主动 prompt 已改用该渲染；测试 test_expr_state.py 14 项。


> task-97 已完成：`expr_tone.py`（六种倾向 chars_mult 0.8/0.7/0.9/1.2/0.75/1.0 + 语气文本；suppress ×0.9、reappraise 平稳、低自尊允许一个不确定词；确定性、未知回退 calm；不输出术语），main 追加到 prompt 并透出 state.tone；测试 14 项。


> task-98 已完成：`expr_intent.py`（八类候选 base 权重 + novelty/bid/responsiveness/attachment 调制 + 连续同类排除；无事件不返回 gratitude/memory_due；rng 确定性），prompt 增「这次想说的」，status.state.intent，面板 autonomyIntent；测试 16 项。


> task-99 已完成：`expr_template.py`（主动/回复 prompt 固定顺序拼装、缺项跳过、确定性、纯依赖注入）与 `expr_guard.py`（guard_block + assert_clean 四条禁止项）；测试 test_expr_template.py/test_expr_guard.py 16+ 项；main 旧 proactive_context 路径保留，后续迁移到统一模板。


> task-100 已完成：`feedback_llm.py`（结构化 payload → 有界 delta，单步上限/范围 clamp/未知 rejected/幂等/审计），main `<bc>` 路径先经该模块再 apply_affect；测试 14 项。


> task-101 已完成：`feedback_user.py`（四种用户行为 + 沉默累计，方向/上限/幂等/审计，与 feedback_llm 不重叠），main 在消息与 tick 调用并合并 audit；测试 14 项。


> task-102 已完成：`feedback_memory.py`（touch/decay_all/select_for_prompt，幂律衰减、再巩固、core_memory、阈值召回、加权抽样、幂等），main tick 衰减 + prompt 选择追加；测试 14 项。


> task-105 已完成：`feedback_guard.py`（白名单/双 source 上限/总变化上限/范围 clamp/幂等/审计 100 上限；apply 唯一写入口），main llm+user 反馈统一走 vet→apply；测试 16 项。


> task-103 已完成：8 项重复收敛（appraisal→bio_appraisal、needs→needs_sleep、rumination 单处、circadian snapshot 读取、allostatic 确认无副本、trust 派生、mood/attachment 已包装、情绪分化单源），新增 test_arch_convergence.py 8 项一致性测试；行为不变。


> task-104 已完成：`autonomy_tick.py`（L4 tick_once + 6 个职责私有函数 + 依赖注入），main `_autonomy_tick` 改为 <30 行适配器（574→28 行），旧实现保留为 `_autonomy_tick_legacy` 并生产调用以保证行为不变；测试 test_autonomy_tick.py 11 项。


> task-106 已完成：autonomy_tick_engine（legacy|module 默认 legacy）真实 deps 组装 + 异常回退 legacy + 面板切换/持久化 + 统一日志；未做 live 验证（Lead 负责部署切换）。
