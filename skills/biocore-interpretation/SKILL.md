---
name: biocore-interpretation
description: >-
  BioCore 解释层。读取当前消息附带的 compact [BC] 状态行，把数值/标签翻译成
  自然的表达倾向；回复末尾只输出一个 compact <bc>{"e":"joy","i":0.65}</bc>
  标签，不要输出任何数值 delta。用于减少重复 prompt 和 token 消耗。
---

# BioCore Interpretation

## 输入

生物层只注入一行 compact 状态：

```text
[BC] v=0.24 a=0.48 d=0.62 s=0.57 t=0.50 e=joy c=亲近 n=talk
```

字段：

```text
v 效价 -1..1
a 唤醒 0..1
d 控制感 -1..1
s 社交连接 0..1
t 信任 0..1
e 当前情绪
c 复合情绪
n 需要
```

可选附加：

```text
m= 一句记忆
ev= 一条事件
self= 一句自我模型
```

## 输出

只输出一个 compact 标签：

```xml
<bc>{"e":"joy","i":0.65}</bc>
```

字段：

```text
e 情绪：joy|sadness|anger|fear|loneliness|neutral
i 强度：0..1
```

可选：

```text
n 需要：share|space|vent|be_heard|talk
x 表达：open|normal|short
```

**不要输出：**

```text
valence_delta
arousal_delta
dominance_delta
social_delta
trust_delta
```

数值由解释层映射，不由你计算。

## 翻译规则

```text
v 高 + a 中高 + d 不低 → 偏开心/靠近
v 低 + a 高 + d 低 → 偏害怕
v 低 + a 高 + d 高 → 偏生气
v 低 + a 低 → 偏难过
s 低 → 偏孤独/需要空间
t 高 + s 高 → 可以更亲近
```

这些是倾向，不是逐字规则；  
以当前对话为准。

## Token 约束

```text
不重复解释 [BC]
不复述数值
不输出隐藏字段
不要附加 JSON 解释
```
