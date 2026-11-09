# 接线清单：碰总线的模块与不接的后果

判据：模块是否读写四条总线之一 —— **状态通道 / 提示词 / 存储 / 召回**。
静态粗扫得 83 个，按簇归并成十组。

| 簇 | 代表模块 | 碰的总线 | 不接的后果 |
| --- | --- | --- | --- |
| 主入口 | `biocore_runtime/pipeline.py` | 存储·召回·注入 | 捕获与注入全断。今晚 DSH 的现状：条目在写、向量与事件全空 |
| 记忆引擎 | `biocore_memory/engine.py` | 存储·召回 | 宿主没有可用 API，一切退回手写 JSON |
| 事件层 | `event/segment` `event/claims` `event/events` `event/compaction` | 召回·提示词 | 只有「点」没有「面」；断言不生成 → 待办、承诺、未答永远空 |
| 召回层 | `recall/activation` `recall/cover` `recall/segments` `recall/point_expand` | 召回 | 检索退化为向量直排；长尾事实取不到 |
| 存储层 | `store/sql_store` `store/near_dup` `store/versioning` | 存储 | 无结构化半区、无近似去重、无版本裁决；改写即覆盖 |
| 通道 | `runtime/dimensions` `runtime/field` `runtime/arbiter` | 状态通道 | 多模块写同一状态时互相覆盖，且无人仲裁 |
| 提示词块 | `model/blocks` `model/runtime` `model/render` | 提示词 | 状态算出来也无处呈现，模型看不到 |
| 主动 | `runtime/standby` `batch_d` `model/autonomy_tick` | 提示词·注入 | 不会主动开口；八点那条只剩硬编码的时钟 |
| 治理 | `runtime/governance` `runtime/lifecycle` `runtime/growth` | 存储 | 记忆只增不减，无衰减、无巩固、无整理 |
| 增强 | `retrieval_plus` `rerank` `space_learning` | 召回 | 召回质量停在基线；空间轴权重不更新 |

## 结论

- **十组里只有两组（主入口、引擎）在部署侧接上了**，其余八组要么没接、要么接了没有读取方
- 判断「该不该插」的标准只有一条：**是否读写总线**。纯计算（appraisal 打分、切分算法）不插，保持库
- 判断「接了没有」的标准也只有一条：**journal / traces 里有没有它的执行痕迹**。静态 import 不算数
