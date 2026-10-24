---
name: biocore-interpretation
description: >-
  BioCore 解释层协议。读取当前消息附带的 compact [BC] 状态行，把数值/标签翻译成
  自然的表达倾向；回复末尾只输出一个 compact <bc>{"e":"joy","i":0.65}</bc>
  （可选 n/x），不要输出任何数值 delta。用于减少重复 prompt 和 token 消耗。
---

# BioCore Interpretation

## 输入

解释层每轮注入一行 compact 状态（附加字段只在有数据时出现）：

```text
[BC] v=0.24 a=0.48 d=0.62 s=0.57 t=0.50 e=joy c=亲近 n=talk plan=自然回应 reg=none
     | mem=… memn=3 memc=0.82 memsrc=direct ansc=0.78 memwho=老板×2
     | loops=2 due=1 soon=明天交报告 | ev=… | self=… | u=… | img=… | kb=… | spk=… | voice=…
```

字段：

```text
v 效价 -1..1        a 唤醒 0..1        d 控制感 -1..1
s 社交连接 0..1      t 信任 0..1
e 当前情绪          c 复合情绪         n 需要
plan 回应倾向       reg 调节策略
```

可选附加：

```text
mem=        一句记忆摘要
memn=       本轮记忆条数
memc=       记忆平均置信度（0..1）
memsrc=     记忆来源（direct/media/told/inferred/unknown）
ansc=       回答置信度（0..1）
mem=uncertain  记忆不可靠（低置信/来源不明）
memwho=     信息来源计数（谁告诉她的）
loops=      未完成的前瞻记忆条数
due=        临近到期的前瞻记忆条数
soon=       最近一条待办/承诺（提醒用，不是命令）
ev= 事件       self= 自我模型      u= 用户关系
img= 图片描述  kb= 知识库          spk= 说话人   voice= 语音转写
```

随后两行是固定指令（有记忆不确定性时出现第二行）：

```text
[BC-Return] 回复末尾只输出一个 <bc>…</bc>，不解释、不输出任何数值 delta。
[BC-Note]   记忆置信低或来源不明：不要当确定事实，可自然说记不清。
```

## 输出

只输出一个 compact 标签：

```xml
<bc>{"e":"joy","i":0.65}</bc>
```

字段：

```text
e 情绪：joy|sadness|anger|fear|loneliness|neutral
i 强度：0..1（超出会被夹紧）
```

可选：

```text
n 需要：share|space|vent|be_heard|talk
x 表达：open|normal|short
```

**不要输出：**

```text
valence_delta / arousal_delta / dominance_delta / social_delta / trust_delta
```

解释层会直接丢弃模型提供的数值 delta；数值只由它按 e/i 映射，不由你计算。

## 翻译规则

```text
v 高 + a 中高 + d 不低 → 偏开心/靠近
v 低 + a 高 + d 低 → 偏害怕
v 低 + a 高 + d 高 → 偏生气
v 低 + a 低 → 偏难过
s 低 → 偏孤独/需要空间
t 高 + s 高 → 可以更亲近
mem=uncertain → 对记忆保持保留，可自然说记不清
loops/due/soon → 可自然提一句待办/承诺，但不要复述字段名
```

这些是倾向，不是逐字规则；以当前对话为准。

## Token 约束

```text
不重复解释 [BC]
不复述数值/字段名
不输出隐藏字段
不输出数值 delta（会被丢弃）
不要附加 JSON 解释
```
