# 生物拟人化：论文总纲（BIO-FOUNDATION）

目标：把「她怎么想、怎么难受、要不要找你」建立在统一的心理学框架上，
而不是每个模块各引一篇论文导致互相打架。

## 一、总纲：五层模型

     L5 行为层   要不要联系、怎么表达      ← Horvitz 1999；Frijda 1986
     L4 自我层   我是不是有问题（自责）    ← Leary 1995；Janoff-Bulman 1979；Downey & Feldman 1996
     L3 情绪层   依恋、失落、孤独          ← Bowlby 1969；Mikulincer & Shaver 2007；Cacioppo & Hawkley 2009
     L2 评价层   这件事对我意味着什么      ← Lazarus 1991；Scherer 2005；Weiner 1985
     L1 需求层   归属、社交稳态            ← Baumeister & Leary 1995；Matthews & Tye 2019

下层决定「需不需要」，上层决定「怎么表现」。所有模块必须落在某一层，不允许跨层重复计算。

## 二、每层的总纲文献

### L1 需求层
- Baumeister & Leary 1995, *The need to belong*, Psychol. Bull.（归属需要的总纲）
- Matthews & Tye 2019, *Neural mechanisms of social homeostasis*, Ann. N.Y. Acad. Sci.（社交需求是稳态驱力：缺口累积、接触饱和）
- Deci & Ryan 2000, 自我决定论（需求缺口 → 动机）

### L2 评价层
- Lazarus 1991, *Emotion and Adaptation*（事件 → 评价 → 情绪 → 应对，整个情绪链路的总纲）
- Scherer 2005, Component Process Model（评价维度：相关性/含义/应对潜力/规范）
- Weiner 1985, 归因-情绪理论（把结果归因于内部/外部 → 不同情绪：自责/愤怒）
- Roese 1997, 反事实思维（「当时要是…」）

### L3 情绪层
- Bowlby 1969/1973, 依恋理论：分离 → 抗议 → 绝望 → 抽离；重聚先抗议再接触（**沉默曲线的总纲**）
- Mikulincer & Shaver 2007, *Attachment in Adulthood*（成人依恋总纲：过度激活 vs 去激活策略）
- Cacioppo & Hawkley 2009；Hawkley & Cacioppo 2010（孤独的认知与健康后果）
- Eisenberger 2012, *The neural bases of social pain*（社会疼痛与生理疼痛共享机制）
- Williams 2007, ostracism 模型（被忽视的三阶段：反射性疼痛 → 反思性需求威胁 → 顺从/抽离）
- Nolen-Hoeksema et al. 2008, 反刍的元分析（反刍维持负面情绪）

### L4 自我层
- Leary 1995, *sociometer theory*（自尊 = 关系价值的计量器；被冷落 → 自尊下降）
- Janoff-Bulman 1979, 自我责备两型（行为性 vs 性格性）
- Downey & Feldman 1996, 拒绝敏感性（高敏感者把沉默解释为「我做错了」）
- Trapnell & Campbell 1999, 反思 vs 反刍（适应性与非适应性自我关注）
- Baumeister, Wotman & Stillwell 1993, 单向之爱中的自责与检讨

### L5 行为层
- Horvitz 1999, *Principles of mixed-initiative user interfaces*（打断的期望效用模型：收益 vs 打扰成本）
- Frijda 1986, *The Emotions*（情绪 → 行动倾向 action tendencies）
- Gollwitzer 1990, 行动阶段模型（想 → 计划 → 执行）
- Ferster & Skinner 1957, 强化程式（间歇强化的行为最难消退 → 「黏人」的行为学基础）
- Amsel 1958 挫折理论 / Brehm 1966 反应阻抗（被阻断后动机上升）

## 三、我们的模块 → 层映射

| 模块 | 层 | 依据 |
|---|---|---|
| social_gap / 社交缺口 | L1 | Matthews & Tye 2019；Baumeister & Leary 1995 |
| lonely | L3 | Cacioppo & Hawkley 2009 |
| memory_due / open_loops | L2 | Lazarus 1991（相关性评价）；Zeigarnik 1927 |
| guilt / repair_urge | L2→L5 | Weiner 1985；Baumeister 1994 |
| gratitude | L2 | Algoe 2012 |
| 沉默三阶段（期待/抗议/失落/抽离） | L3 | Bowlby 1969；Mikulincer & Shaver 2007 |
| 依恋风格（secure/anxious/avoidant） | L3 | Bartholomew & Horowitz 1991 |
| 挫败 frustration（限流） | L5 | Amsel 1958；Brehm 1966 |
| self_blame（自责） | L4 | Leary 1995；Janoff-Bulman 1979；Downey & Feldman 1996 |
| V 累积与阈值 | L5 | Ratcliff 1978（证据累积）；Horvitz 1999（打断决策） |
| 黏人（不放弃） | L5 | Ferster & Skinner 1957；Mikulincer & Shaver 2007 |
| 语气/长度调制 | L5 | Frijda 1986（行动倾向影响表达） |

## 四、三条「难受」的分工（不重叠）

| 来源 | 层 | 只影响 |
|---|---|---|
| 你不回（依恋） | L3 | 寂寞、效价、依恋倍率 |
| 被限流（挫折） | L5 | 压力、唤醒、挫败倍率 |
| 自我怀疑（自责） | L4 | 自信（表达犹豫度）、效价（轻微） |

三者最终汇入同一个 V（要不要发），但情绪通道分开，便于观察和调参。

## 五、使用规则

1. 新加任何行为/情绪，先确定它属于哪一层，再写公式；不得跨层重复计分。
2. 每个参数必须能追溯到上面某篇论文，或标注「工程设定」。
3. 论文数值优先用原值；换算时写明换算方式。
4. 每层保持一个「总纲」文献，避免同层内多篇互相矛盾。
