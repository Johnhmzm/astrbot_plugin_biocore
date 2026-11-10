# 插件实现说明（内部）

> 内部文档，不随 npm 包发布。


面向改这个仓库的人。用户文档在 [README](../README.md)，发版流程在 [CONTRIBUTING](../CONTRIBUTING.md)。

## 一、组成

```
lib/modules/        宿主侧：payload 构造、注入接线、面板、开关
python/biocore_runtime/   核心：状态、记忆、注入、学习
python/mindbase/          生物底座：联想学习、噪声、生存筛选
python/biocore_model/     评价与表达：appraisal、expr_state
python/dsh_adapter/       会话适配：一次 turn 的状态推进
ui/                 面板
```

## 二、一轮怎么走

```
用户消息
  → lib/modules/core-turn.js      构造 turn_start payload（含 body_state）
  → lib/py-bridge.js              JSON 动作 → 常驻 worker
  → service.py dispatch
  → pipeline.turn_start
       advance    先让身体走过这段时间（无人时也在走）
       body_turn  用这一轮的评价值推状态（推，不是覆盖）
       state      写进 session_state，供渲染
       prompt_block  「此刻：效价… 读法…」+ 约束块
  → 模型生成回复
  → pipeline.turn_end
       judge_exchange  模型给这一来一回打分
       q_reward_last   策略表记账（含「没人理」的负分）
       teach           蘑菇体按预测误差写权重
       micro_evolve    噪声幅度随适应度微调
```

## 三、状态

| 变量 | 范围 | 谁写 |
| --- | --- | --- |
| 效价 valence | -1…1 | 身体（模型评价只推动，不覆盖） |
| 唤醒 arousal | 0…1 | 同上 |
| 支配 dominance | -1…1 | 同上 |
| 紧张 stress | 0…1 | 同上，并受噪声影响 |
| 社交 social | 0…1 | 驱力层 |
| 锚点 anchor | 慢变量 | 每轮以 25% 学习率被经验挪动 |
| 承诺 commit | 计数 | 评维度返回 made/kept |

状态落盘在 `<store>/sessions/<sid>/`：

```
mindbase_body.json   当前状态 + 锚点 + 承诺
mindbase_clock.json  上次推进时间
mindbase_needs.json  适应度、噪声幅度、L3–L5
mindbase_mb.json     蘑菇体权重
mindbase_mirror.json 从主记忆镜像过来的句子
policy_q.json        策略表
recall_digest.txt    上一轮回想起的句子
```

## 四、身体

`mindbase_bridge.DialogueBody` 是唯一入口：

```
feed(text, dims)   推一次状态；tick 在前、push 在后
idle(n)            只走时间，不受消息影响
state()            输出当前数值
```

三个必须知道的机制：

1. **affect 不是积分器**：每 tick 从目标值重算，直接写 affect 会被抹掉——所以噪声走驱力，push 放在 tick 之后。
2. **噪声驱动驱力**：`EndogenousNoise` 的 `last_noise` 按 0.30 幅度加到驱力上，12 个种子静置 200 步会分化出「说/不说」。
3. **锚点是慢变量**：经历以 25% 学率挪它，每步以 4% 把它拉回当前值——这让「被骂过」在 12 小时后仍留痕。

## 五、学习

```
策略层   policy_learning（Q 表）：情境 = 停顿时相|依恋|时段；动作 = approach/share/…
         回合内读：主动决策时若学出 withdraw/rest 就不发
         回合末写：模型判分；半小时无人回应记负分
关联层   蘑菇体 KC→MBON：DAN 按 (reward - 预测) 写入，正负通道分开
身体层   micro_evolve：每轮爬山，只调噪声幅度一个旋钮，步长 3%
```

## 六、记忆与注入

```
排序      平铺句池按分数排序（曾经只在命中概念时才排，普通查询拿到时间序）
预算      inject_chars 生效；inject_block 默认值不再覆盖配置
精排      对余弦前 60 名做 rerank，键名 base_url/model/api_key → rerank_*
情绪一致性  条目 affect 与当前效价接近的加权；无标签时该权重为 0
镜像      召回过的句子写入 mindbase_mirror.json，重启时回放进身体记忆
```

## 七、配置位置

```
<data>/core_config.json     唯一配置源（summarizer / embedding / rerank / recall / switches）
<data>/memory/              记忆存储
```

核心会从 `<data>/memory` 向上找一层配置——宿主把记忆放 memory、配置放 data，只读本层会报「no summarizer block」。

## 八、测试

```
pytest tests              核心全量（701 项）
node test/hook-wiring.mjs 宿主接线
npm run selftest          package 自检
```

## 九、已知限制

```
旧条目的 affect 未回填，情绪一致性只对新记忆生效
身体能否决主动消息，还不能自己发起
长程漂移（连续数天）未观测
```
