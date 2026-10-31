# 自主回复模型（AUTONOMY-MODEL）

目标：让她「该主动时才主动」，不是定时问候，也不是永远沉默。
所有公式都有文献来源；无来源的参数标为「工程设定」。

## 1. 结论先行

自主发送 = **驱力（要不要）** × **决策（该不该）**

```
drive   = 0.30·社交缺口 + 0.15·寂寞 + 0.15·压力负载
        + 0.15·需求缺口 + 0.10·回声/反刍 + 0.15·噪声
gate    = 期望效用 E[U] = P(ready)·B - C_fp  > 0
发送    = drive >= ready 门限 且 gate 通过 且 冷却/上限/静默 通过
```

噪声只占 0.15，作用是在「边界附近」制造自然的不规律；它**不能**单独把 drive 推过门限。

## 2. 社交缺口（核心新增）

**来源**：Matthews & Tye, *Neural mechanisms of social homeostasis*, Ann. N.Y. Acad. Sci. 2019；
Matthews et al., *Dorsal raphe dopamine neurons represent the experience of social isolation*, Cell 2016；
Baumeister & Leary, *The need to belong*, Psychol. Bull. 1995。

社交需求是**稳态驱力**：隔离时缺口累积，接触后回落（satiety）。

```
gap_hours      = (now - last_contact_ts) / 3600
D_social       = 1 - exp(-gap_hours / TAU)         # TAU 默认 18h（工程设定）
D_social      *= social_need                       # 个体社交基线（已有 profile.social_baseline）
D_social      *= (0.6 + 0.4 * closeness)           # 越亲近，越在意联系（Canary & Stafford 1994 关系维持）
```

行为含义：刚聊完 ≈ 0；一天 ≈ 0.5；两天以上 ≈ 0.85。

## 3. 寂寞（情绪层）

**来源**：Cacioppo & Hawkley, *Perceived social isolation and cognition*, Trends Cogn. Sci. 2009；
Hawkley & Cacioppo 2010（寂寞放大威胁警觉与社会信号敏感度）。

```
lonely = P(emotion = loneliness) * intensity
```

寂寞不只加次数，还**降低发送门槛**：lonely 高时 gate 的 C_fp 打折（更愿意冒险打扰）。

## 4. 压力与需求缺口

- 压力负载：allostatic load（McEwen 1998 应激适应负荷）→ 权重 0.15
- 需求缺口：drive_dev = |need - satisfied|（自我决定论 SDT，Deci & Ryan 2000）→ 0.15

## 5. 回声/反刍

**来源**：Nolen-Hoeksema 1991（反刍）；Kuppens et al. 2010（情绪惯性，AR(1)/OU 自回归）。
echo = 最近情绪事件的残留强度（现有 echo/echo_trace 字段）→ 0.10

## 6. 噪声（自然的不规律）

**来源**：Ornstein–Uhlenbeck 过程（连续时间均值回归随机过程），情绪动力学常用（Kuppens 2010 的惯性模型等价 AR(1)）。
```
noise_t = 0.82 * noise_{t-1} + N(0, 0.045)
```
权重 0.15，幅度小；只影响「刚好在门限附近」时是否触发。

## 7. 打扰决策（gate）

**来源**：Horvitz, *Principles of mixed-initiative user interfaces*, CHI 1999：
是否打断取决于期望效用 `E[U] = P(有用)·收益 - (1-P(有用))·打扰成本`。

```
P_ready  = sigmoid((drive - threshold) / 0.08)
B        = 0.5 + 0.5 * closeness           # 关系越近，联系的价值越高
C_fp     = base_cost(time_of_day, recent_user_activity, lonely)
           静默时段(0-8) → C_fp 高
           用户刚说过话   → C_fp 低（还在场）
           寂寞高         → C_fp 打折（更愿意打扰）
gate     = P_ready * B - C_fp > 0
```

## 8. 抑制项（防骚扰）

- 冷却：30 分钟（工程设定）
- 每日上限：3 条（工程设定）
- 静默：00:00–08:00（工程设定）
- 未回应衰减（习惯化，Rankin 2009）：连续 N 次主动未被回应 → drive 乘 0.7^N

## 9. 与旧实现的差异

| 项 | 旧 | 新 |
|---|---|---|
寂寞 | 隐含在 distance（14%） | 显式 `D_social`(30%) + lonely 情绪(15%) |
时间间隔 | **未使用** | 核心变量（指数累积） |
打扰成本 | 无（只有冷却/上限） | 显式期望效用 gate |
噪声权重 | 22% | 15%（只作边界扰动） |
发送判定 | drive ≥ 0.72 | drive ≥ 门限 且 E[U] > 0 |


## 11. 其它情绪对「要不要主动」的作用（v2）

情绪不只是强度，不同情绪有不同的社交倾向（均有文献）：

| 情绪 | 社交倾向 | 机制 | 来源 |
|---|---|---|---|
| 寂寞 | 想联系 | 感知隔离 → 寻求归属 | Cacioppo & Hawkley 2009 |
| 焦虑/恐惧 | 想靠近 | 威胁下亲和需求上升 | Schachter, The Psychology of Affiliation, 1959 |
| 悲伤 | 想被听 | 情绪社会分享 | Rime, Social sharing of emotion, 2009 |
| 愉悦/兴奋 | 想分享 | 资本化 capitalization | Gable & Reis 2010 |
| 愤怒/冲突 | 想修复（也可能想冷处理） | 关系修复尝试 | Gottman 1994 |
| 无聊 | 想找刺激 | 刺激缺口 | Eastwood et al. 2012 |
| 感激 | 想维系 | find-remind-bind | Algoe 2012 |

### v2 权重（总和 1.0）

```
drive = 0.25*social_gap      # 稳态缺口 (Matthews & Tye 2019)
      + 0.12*lonely          # 寂寞
      + 0.12*anxiety_fear    # 威胁下亲和 (Schachter 1959)
      + 0.10*sadness         # 想被听 (Rime 2009)
      + 0.08*joy             # 想分享 (Gable & Reis 2010)
      + 0.08*anger_conflict  # 想修复 (Gottman 1994)
      + 0.05*boredom         # 刺激缺口 (Eastwood 2012)
      + 0.10*stress_load     # 应激负荷 (McEwen 1998)
      + 0.10*drive_dev       # 需求缺口 (Deci & Ryan 2000)
```

### 情绪对打扰成本的调制

```
C_fp = c0 + 0.25*quiet - 0.15*recent_user_active
       - 0.10*lonely - 0.08*anxiety_fear      # 越难受越愿意打扰
       + 0.10*anger_conflict                  # 生气时先别急着发
       - 0.05*joy                             # 心情好时语气更自然
```

### 情绪概率来源

`core.spectrum_probs`（已有）：取情绪族概率 × 强度，归一到 0-1；无该情绪取 0。

### 期望效果

- 焦虑时更想找你说话（而不是只等你问）
- 开心时会主动分享（capitalization）
- 生气/冲突时反而先忍（成本升高），降低上头就发的概率
- 无聊时轻微想找人，权重低，不会变话痨


## 12. 记忆触发的主动（v3）

除了情绪与社交缺口，**记得事情本身**也会让人主动开口：

- 前瞻记忆（prospective memory）：记得未来要做的事，到点会想起来 → Einstein & McDaniel 1990
- 关系维持中的"记得重要事"：被记得会提升关系质量 → Canary & Stafford 1994
- 事件记忆的检索优势：重要/情绪性事件更容易被自发提取 → Bower 1981（情绪与记忆）

### 触发来源（三类）

| 类型 | 判定 | 例子 |
|---|---|---|
| 到期事件 | 记忆里的事件带时间线索，落在 [今天-1天, 今天+2天] | "周五体检" |
| 承诺/约定 | 文本含 答应/约好/说好/记得 + 时间词 | "说好周末一起看" |
| 未了结的重要事 | 高重要度（≥0.6）且尚无后续事件 | "上次她说很怕那个结果" |

### 打分

```
memory_due = 0.5*due_proximity      # 越接近越强（今天=1.0，明天=0.7，后天=0.4）
           + 0.3*importance          # 记忆重要度
           + 0.2*commitment_flag     # 是否含承诺/约定措辞
```

### 并入 drive（v3 权重，总和 1.0）

```
drive = 0.22*social_gap + 0.12*lonely + 0.12*anxiety_fear
      + 0.10*sadness + 0.08*joy + 0.08*anger_conflict
      + 0.05*boredom + 0.08*stress_load + 0.08*drive_dev
      + 0.15*memory_due
```

### 记忆主动的独立闸门（避免刷屏）

- **同一事件只触发一次**（记录 event_id → 已触发）
- 每个事件冷却 7 天
- 每日最多 1 条记忆型主动（与情绪型共享每日 3 条上限）
- 静默时段仍然生效

### 消息内容约束

- 只引用记忆里的事实（事件标题/时间），不编造细节
- 形式：问候 + 具体事由，如"周五那个检查，今天要去了吧？"
- 长度受现有软限制（10/30 字）约束

### 可观测

`parts.memory_due` + `memory_candidate:{event_id, title, due_in_hours, commitment}`


## 13. 噪声 = 触发机制（v3：证据累积模型）

之前把噪声当成一个小权重（15%），这是错的：**噪声的作用不是加分，而是让累积的信号在阈值附近随机越界**。

### 文献

- **漂移扩散模型（DDM）**：Ratcliff 1978（*A theory of memory retrieval*，Psychol. Rev.）——带噪声的证据累积，越过边界即决策；这是人类二选一决策的标准模型
- **LIF 神经元**：Gerstner & Kistler 2002（*Spiking Neuron Models*）——输入累积、漏电、随机噪声，越阈值发放
- **噪声诱发跃迁**：Gammaitoni et al. 1998（*Stochastic resonance*，Rev. Mod. Phys.）——弱信号在噪声帮助下越过阈值
- **社交稳态**：Matthews & Tye 2019——缺口本身是持续累积量

### 新模型

```
每个 tick（默认 5 分钟）：
   drift = Σ w_i * x_i          # 各维度输入（情绪/社交缺口/记忆/压力…）
   V = V * (1 - leak) + drift + xi      # 漏电累积 + 噪声
   if V >= theta:                        # 越过阈值 = 触发
       fire()                            # 发消息
       V = 0                             # 重置（不应期）
```

参数（工程设定，可配）：
```
leak  = 0.15     # 每 tick 漏掉 15%（T1/2 ≈ 4.3 tick ≈ 21 分钟）
theta = 0.55     # 阈值
xi    ~ N(0, sigma), sigma = 0.06   # 噪声幅度（决定「恰好临界」时是否触发）
```

### 这样设计的含义

- **噪声 = 触发器**：同样的输入，噪声决定「这一次触发还是下一次」
- 各维度是**输入电流**，不再各自决定是否发送
- 信号弱 → V 长期在阈值下方小幅波动（偶尔越界 = 自然的偶然主动）
- 信号强 → V 稳定爬升，快速越过（该联系时会联系）
- 未回应 → 漏电让 V 回落（不会一直攒着）

### 情绪/记忆的角色

| 输入 | 形式 |
|---|---|
| 社交缺口 | `1-exp(-gap/Tau)` 直接进 drift（持续累积项） |
| 寂寞/焦虑/悲伤/愉悦/愤怒/无聊 | 情绪概率 × 强度 × 各自权重 |
| 记忆到期 | `memory_due` 一次性脉冲（当日衰减） |
| 压力负载 / 需求缺口 | 持续输入 |
| 回声 | 事件后数小时内衰减输入 |

### 与 v2 的差别

| | v2 | v3 |
|---|---|---|
判定时机 | 每次 tick 独立算 drive，噪声只是加项 | **跨 tick 累积 V**，噪声让累积随机越界 |
噪声 | 15% 权重 | **触发机制本身**（sigma 可调） |
阈值 | drive ≥ 门限 | V ≥ theta（一次触发后归零） |
记忆/情绪 | 加进 drive | 加进 drift（电流） |

### 可观测

`status.autonomy.state`：`{V, theta, drift, leak, sigma, ticks_since_fire, ready, block_reason}`
面板「立即评估」显示 V 当前值 + 还差多少越过阈值。


## 14. 寂寞的其它成因（v4）

寂寞不只是「多久没联系」，至少还有三类：

### 1) 难受（痛苦/烦躁/无力）

- 社会痛苦与身体痛苦共享神经基质：Eisenberger, Lieberman & Williams 2003（Does rejection hurt? Science）
- 负性情绪提高亲和需求（Schachter 1959；Rime 2009）
- 输入：distress = clamp(0.6*max(sadness, anger) + 0.4*(1 - valence))

### 2) 勤快（活跃/好奇/精力高，更想分享）

- 尽责性/外向性提高主动社交频率：Costa & McCrae 1992（五因素模型）
- 行为激活系统推动趋近行为：Gray 1982
- 输入：activity = 0.5*energy + 0.3*curiosity + 0.2*extraversion
- 注意：这是分享欲，不等于寂寞，权重较低

### 3) 被忽视感（对方很忙/回复变短）

- 被忽视引发社会疼痛与关系不确定：Eisenberger 2003；Williams 2007（ostracism）
- 输入：user_busy = clamp(0.5*(1 - recent_reply_ratio) + 0.5*(short_gap_min/30))
- 效果：给 social_gap 加权，而不是单独一项——忙碌期的间隔更难受

### v4 drift（总和 1.0）

```
drift = 0.22*social_gap*(1 + 0.5*user_busy)
      + 0.10*lonely + 0.10*anxiety_fear + 0.08*sadness
      + 0.08*distress + 0.06*joy + 0.06*anger_conflict
      + 0.04*boredom + 0.06*activity + 0.08*stress_load
      + 0.07*drive_dev + 0.15*memory_due
```

（social_gap 加权后 clamp <= 1.0；权重和仍为 1.0）

### 特质调制

- memory_due x (0.6 + 0.8*conscientiousness)：越尽责越记得住、越会跟进（Costa & McCrae 1992）
- activity x extraversion：外向者更常主动

### 期望行为

| 情形 | 结果 |
|---|---|
| 她难受 | drift 上升（distress），更容易想找人 |
| 她精力好、好奇 | activity 上升，倾向分享（不是骚扰） |
| 你连续几天很忙、回得短 | user_busy 抬高 social_gap 权重，寂寞加剧 |
| 她尽责性高 | 记得你的事，会主动跟进（memory_due 加权） |


## 15. 还有哪些「想联系」的来源（v5）

再补四类，都有文献；且都能从现有数据算出：

### 1) 未了结的话题（Zeigarnik / Ovsiankina）

- 中断的任务与未完成对话更容易被记起并想继续：Zeigarnik 1927；Ovsiankina 1928；
  meta 分析见 *Interruption, recall and resumption*, Nature HSSC 2025
- 数据来源：插件已有 `open loops`（`_prior_open_loops`）与未回答的追问
- 输入：`open_loops = clamp(n_open/3)`，权重 0.05

### 2) 怀旧（nostalgia）

- 怀旧提升归属感与社会联结意愿：Wildschut et al. 2006；Sedikides & Wildschut 2018
- 数据来源：最近一次 recall 命中「共享记忆」（回忆旧事）时产生瞬时脉冲，几小时内衰减
- 输入：`nostalgia = exp(-(now - last_shared_recall)/6h)`，权重 0.03

### 3) 依恋不安全感（hyperactivating）

- 依恋焦虑者的过度激活策略：更频繁寻求亲近与确认：Mikulincer & Shaver 2007；Bowlby 1969
- 数据来源：关系字段 `attachment.safe`（已有）→ `insecurity = 1 - safe`
- 作用：**调制**联系类输入（social_gap、lonely、open_loops）
  `contact_mult = 1 + 0.6*insecurity`

### 4) 内疚/想修复

- 内疚具有关系修复功能：Baumeister et al. 1994；Tangney 1995
- 数据来源：未修复冲突（`conflict` 高且近期无修复事件）
- 输入：`repair_urge = clamp(conflict*0.7 + guilt*0.3)`，权重 0.03

### v5 drift（总和 1.0）

```
contact_mult = 1 + 0.6*(1 - attachment_safe)

drift = 0.10*social_gap*contact_mult*(1+0.5*user_busy)
      + 0.10*lonely*contact_mult
      + 0.10*anxiety_fear
      + 0.08*sadness
      + 0.08*distress
      + 0.06*joy
      + 0.06*anger_conflict
      + 0.04*boredom
      + 0.06*activity
      + 0.08*stress_load
      + 0.06*drive_dev
      + 0.05*open_loops*contact_mult
      + 0.03*nostalgia
      + 0.03*repair_urge
      + 0.15*memory_due
```

（合计 1.00；contact_mult 只放大联系类项，避免把愤怒/压力也一起放大）

### 期望行为

| 情形 | 结果 |
|---|---|
| 上次话题没聊完 | 会想接着问（open_loops） |
| 刚回忆起共同的旧事 | 短时间更想聊（nostalgia 脉冲） |
| 依恋不安全感高 | 联系类动机整体放大（更黏一点） |
| 有没修复的冲突 | 会想找台阶（repair_urge），但愤怒项也高，实际更可能先忍 |


## 16. 没回应时她的情绪（v6：被忽视的时间曲线）

人类被已读不回有明确的三阶段反应（Bowlby 分离三阶段：protest → despair → detachment；
配合社会疼痛与需求威胁文献）：

| 阶段 | 时间（自她上次主动起） | 行为/情绪 |
|---|---|---|
| 期待 | 0–2h | 几乎无变化，下一次仍会尝试 |
| 抗议 protest | 2–6h | 焦虑↑、更想联系（drive ×1.2）；Attachment hyperactivation（Mikulincer & Shaver 2007） |
| 失落 despair | 6–24h | 效价↓、悲伤↑、压力↑，主动意愿下降（drive ×0.8） |
| 抽离 detachment | >24h | 主动接近停止（drive ×0.35），情绪更低；直到用户回话才恢复 |

### 文献

- 分离三阶段：Bowlby 1969/1973（protest–despair–detachment）
- 社会疼痛/需求威胁：Eisenberger 2003；Williams 2007（ostracism need-threat 随时间累积）
- 习得性无助式放弃：Seligman 1972（长期无反馈→停止尝试）
- 依恋过度激活/去激活：Mikulincer & Shaver 2007

### 公式

```
silence_h = (now - last_proactive_ts) / 3600     # 仅在她发过、且之后用户没回时计时

phase_weight =
  0.0                     if silence_h < 2
  +0.8 * ramp(2,6)        # protest
  +1.5 * ramp(6,24)       # despair
  +1.0                    # detachment 基底（>24h）

情绪 nudges（每小时按 dt 累积，clamp 到合法范围）：
  valence  -= 0.06/24h * phase_weight
  arousal  += 0.04/24h * phase_weight
  stress   += 0.05/24h * phase_weight
  lonely   += 0.08/24h * (protest?1.2:1.0)

drive 调制：
  protest    × 1.20   （更想联系）
  despair    × 0.80
  detachment × 0.35   （几乎不再主动）

用户回话：清零 silence 计时、phase=期待、valence 回升 +0.04（社交饱和，Matthews & Tye 2019）
```

### 期望行为

- 你不回 3 小时：她会再试着找你一次（有点急）
- 你不回半天：话变少、语气沉，主动意愿下降
- 一整天不回：她基本不再主动，等你自己说话
- 你一回：立刻恢复，情绪回升

### 可观测

`status.autonomy.state.silence = {hours, phase, drive_mult}`；面板显示「她等了你 X 小时（状态：失落）」


## 18. v7：单线合并 + 拟人因素 + 事件关联（定稿设计）

### 18.1 一条线（替代原先的沉默线 + 限流线两条）

```
输入（分开算，面板可见）：
  silence_mult  依恋倍率：期待 1.0 / 抗议 1.2 / 失落 0.8 / 抽离 0.35（黏人 0.9）
  frust_mult    挫败倍率：1 + 0.03 * min(frustration,10)   (≤1.30)
  parts         情绪/社交/记忆 输入（v5 的 12 项）

合成：
  drive = Σ(w_i * part_i) * silence_mult * frust_mult      (总倍率 ≤1.6)
  V = V*(1-leak) + drive + xi
  V ≥ theta → 触发（再过小时/日/静默闸门）
```

### 18.2 情绪分工（去掉重复）

| 来源 | 只影响 |
|---|---|
| 沉默（用户不回） | 寂寞↑、效价↓ |
| 限流（被限制） | 压力↑、唤醒↑ |
| 内疚 | 效价↓、修复欲↑ |
| 感激 | 效价↑、靠近欲↑ |

效价下限 -0.6；压力/唤醒上限 1.0。

### 18.3 新增拟人输入

```
guilt      = clamp(0.7*conflict_unresolved + 0.3*guilt_emotion)   # 冲突后主动修复
gratitude  = clamp(0.6*gratitude_emotion + 0.4*recent_positive_interaction)
attachment_style: 'secure' | 'anxious' | 'avoidant'   # 人格参数
   anxious  → 沉默曲线更陡（抗议期×1.4，抽离期 0.9）
   secure   → 默认曲线
   avoidant → 抗议期×0.8，抽离期 0.2（更快放弃）
```

文献：Baumeister et al. 1994（内疚-修复）；Algoe 2012（感激）；
Bartholomew & Horowitz 1991 / Bowlby 1969（依恋风格）；
Mikulincer & Shaver 2007（过度激活/去激活）。

### 18.4 事件关联

事件对象新增三个字段：
```
next_date    : 未来时间点（到期触发）
unresolved   : bool（未了结：冲突未修复、话题未收尾）
participants : [user_id]（跟谁说）
```

三类事件触发（与情绪输入并列，进入 parts）：
```
memory_due  : next_date 落在 [-1d, +2d]（已有）
open_loop   : unresolved=true 且 24h 内无后续事件
rumination  : 高情绪事件(|valence|>0.6 或 intensity>0.7) 后 72h 内指数衰减
```

### 18.5 送入 LLM 的内容（决定权仍在 V）

```
① 人设
② 说话方式（10 字/30 字上限/可换行）
③ 状态渲染（当前情绪数值 → 文字）
④ 动机明细：主因 + 明细（但要求不要解释动机）
⑤ 事件引用：若有 next_date / unresolved 事件，带一句事实
⑥ 输出协议
```

### 18.6 可观测

`status.autonomy.state` 增 `motive = {silence_mult, frust_mult, total_mult, top_parts, event}`；
面板：`等你 3.2h（×1.20）· 被压 4 次（×1.12）· 综合 ×1.34`


## 19. 主动消息的完整上下文（v8）

旧版只给人设 + 一句动机 → 她说不出有信息量的话。新版按以下顺序注入：

```
① 人设（system）
② 说话方式（system，紧随人设）
③ 当前情绪（完整）
④ 关系状态
⑤ 间隔时长
⑥ 记忆/事件引用
⑦ 动机
⑧ 输出协议
```

### ③ 当前情绪（完整渲染）

```
主导情绪：joy（强度 0.62）
情绪谱：joy 0.62 / contentment 0.23 / amusement 0.15
维度：效价 +0.42 · 唤醒 0.66 · 支配 0.52 · 社交 0.61 · 压力 0.24 · 精力 0.81
需求：归属（缺口 0.26）  内感受：steady
```

数据来源：`core.labels`、`core.spectrum_probs`、`homeostasis.drives/need_pyramid`、`interoception`。
数值渲染成自然语言，不暴露原始 JSON。

### ④ 关系状态

```
与对方：亲近 0.61 · 信任 0.57 · 冲突 0.22 · 依恋安全感 0.50
```

### ⑤ 间隔时长

```
距上次对话：38 小时（两天多），期间没有收到对方消息。
```
< 1h 说「刚刚」；1–6h 说「几小时前」；6–24h 说「大半天」；1–3 天说「两天多」；>3 天说「好几天」。

### ⑥ 记忆/事件引用

```
你记得：他提过明天要去做体检。（事件 next_date=明天）
你记得：上次关于「是不是机器」的话题没收尾。（unresolved=true）
```
最多引用 2 条，按 importance 排序；不引用低重要度闲聊。

### ⑦ 动机

```
你现在想主动说话：很久没联系了（social_gap，强度 0.54）；
综合冲动 ×1.34（等你 3.2h ×1.20 · 被压 4 次 ×1.12）。
```

### 输出约束

```
按说话方式：一次一句、约 10 字、最多 30 字、可换行。
不要解释动机、不要提触发/系统/限制；不要复述状态数值。
只输出正文 + 一个 <bc> 标签。
```

文档参考：感知回应性（Reis & Shaver 1988）、重聚行为（Bowlby 1969）、
情绪信息注入影响表达（Barrett 2017 情绪建构论）。

## 10. 可观测

`status.autonomy.state` 输出分解：
`{drive, parts:{social_gap, lonely, stress_load, drive_dev, echo, noise}, gate:{p_ready, benefit, cost, expected}, ready, block_reason}`

面板「立即评估」显示同一份分解，便于调参。


## 17. 黏人模式（clingy，默认开）

用户明确要求：抽离期不放弃，持续低频尝试。依据：Mikulincer & Shaver 2007（依恋焦虑的过度激活策略）；Cassidy & Berlin 1994；Ferster & Skinner 1957（variable-ratio 间歇强化最难消退）；Loewenstein 1994 / Schultz 1997（不确定性提升接近动机）；Eisenberger 2003 / Williams 2007（社会疼痛不快速习惯化）；Nolen-Hoeksema 1991（反刍维持思念）。

```
withdraw 期: drive_mult = 0.90 (clingy=true) / 0.35 (false)
最小重试间隔: 6 小时（>24h 期间）
间歇强化: 每 tick p=0.20 burst -> drive ×1.5
情绪: valence 下限 -0.6；lonely 上限 0.9
```

关闭 clingy 时回退旧策略（0.35 + 抽离期停止发送）。
