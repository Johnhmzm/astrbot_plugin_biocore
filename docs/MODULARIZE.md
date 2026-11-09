# 把 DSH 侧的改动做成模块，再接回原记忆层

原则：**不拷补丁，抽模块。** 每块都要能被注册表装配、被单独关掉、被单独验证。

## 一、DSH 侧这次改了什么 → 拆成哪些模块

| DSH 里的实现 | 抽成模块 | 契约（requires → provides） | 钩子 |
| --- | --- | --- | --- |
| 句子级填充 `_sentence_recall_block` | `recall/sentence_fill` | entries + vectors + budget → 块正文 | `recall.after` |
| 交付方式与预算 `delivery / inject_chars` | `recall/policy` | 配置 → 预算、交付模式 | `recall.before` |
| 事件构建修正（无上限、预算透传） | `event/build` | entries → events | `capture.after` |
| 向量写入修复（`with_vectors`、缺失归零） | `store/vector_io` | entries ↔ vector 列 | `store.read/write` |
| 断言状态行 `_claims_state_lines` | `event/claims_render` | claims → 【状态】行 | `inject.before` |
| 配置未知键保留（不让插件冲掉） | 宿主侧，不进记忆层 | — | — |
| 面板、版本号、UI 卡片 | 宿主侧，不进记忆层 | — | — |

**进记忆层的只有五块**，其余两块是宿主责任——这一点必须分清楚，否则又会把插件逻辑塞回核心。

## 二、契约格式（每个模块必须声明）

```
name      recall/sentence_fill
hook      recall.after
requires  entries(vector), budget
provides  block.sentences
on_error  raise（禁止静默降级）
order     50
```

四条硬约束，和总线判据配套：

1. 只碰声明过的通道，越界即报错
2. 抛错必须向上报，不许 catch 后返回空
3. 同一事件重复进入不得重复处理（幂等）
4. 每次执行写 trace：耗时、命中、输入规模

## 三、接回原记忆层的顺序

```
第一步  store/vector_io      —— 最底层，先保证向量真的读得出来、写得进去
第二步  event/build          —— 事件能落库；验收：events 行数 > 0
第三步  event/claims_render  —— 断言能渲染；验收：注入块顶部出现【状态】
第四步  recall/policy        —— 预算与交付模式可配；验收：块长随配置变化
第五步  recall/sentence_fill —— 逐句填充；验收：原句在场且带日期
```

每一步都单独开关、单独验收；**任何一步失败，退回上一步，不带着问题往下走。**

## 四、验收模板（每步都跑）

```
输入   同一段真实会话（只读副本）
检查   journal / traces 里有没有该模块的执行痕迹
       预期行数：events > 0、claims > 0、块含 【状态】、原句含日期
失败   抛错且日志可见；静默降级视为未通过
```

## 五、为什么必须先 store/vector_io

今晚 DSH 的实测：506 条 entries，**向量 0 条**。向量为空时，召回退化成按顺序取，后面所有模块都在空转——**上层改得再多也看不出来。** 所以底层不先修，模块化只是把空转做得更整齐。
