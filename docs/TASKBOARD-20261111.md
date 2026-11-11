# 任务清单（2026-11-11）

## 一、记忆七步：现状与判定

| 步骤 | 状态 | 证据 | 结论 |
| --- | --- | --- | --- |
| 记 | 部分接上 | importance 原为常数 5；今晚补 affect/self_relevance/公式 | 门槛不能用于「存不存」：丢 10% 条目召回 85.2%→74.2% |
| 取 | 只有语义一路 | 线索通道对中文命中 0/562（正则只认拉丁实体）；时间通道 normalize_time 返回空 | **用错了层**：实体该来自模型 claims 主体，不该来自正则 |
| 忘 | 未接 | eviction_order/score 只在 engine 内，pipeline 调用 0 次 | 待接（不删数据，只改顺序） |
| 改 | 部分 | tombstone/versions 在 engine；我们的删除是直删 | 待接墓碑；传播不可逆需先说清 |
| 沉 | 未接 | identity.api.write 只在 engine.remember | 待接：需要 event→identity 的证据链 |
| 长 | 未接 | identity.ledger/history 同理 | 依赖「沉」 |
| 续 | 未接 | relay/thread/slots 全在 engine | 待定 |

**根因**：`capture` 走 `load_memory → append → save_memory`，绕开了 `MemoryEngine`；七步设计都在 engine 里。

## 二、本轮已做（今晚提交）

```
停用即硬关闭 / 副作用回执 / 注入边界 / 请求级作用域 / 渲染 fail-closed
写集版本戳 / 变更日志+撤销 / 写后回读 / 原子门禁 / 配置白名单
keynorm 键归一 / chains 改口链 / 逻辑身份 semantic_id / 模型侧时间口径
条目轮次 turn / 事件 ID 稳定化 / link_repair 老数据修复
写入补 affect、self_relevance、importance、valid_from、时间桶
```

## 三、待办（按优先级）

```
P0  发版 0.5.20：全量测试 → 3081 冒烟 → 发布 → 安装 → 复验
P0  「取」修层：写入继承 claims 主体为实体；召回加实体加成（实测 57.3% 锚点吃这个加成）
P1  「忘」接进召回：eviction_order 只影响顺序，不删数据
P1  「沉」接身份写回：需要里程碑证据 → identity.write
P2  「改」接墓碑 / 「长」接版本链 / 「续」待定
P2  文档：CHANGELOG 补 40+ 提交；MEMORY.md 只覆盖引擎 1/5；19 条移植结论待合成
P3  em / rerank 用法与原理文章（材料查了一半）
```

## 四、用错地方/层的清单

```
线索通道   实体来源用正则（只认拉丁）→ 应改为模型 claims 主体
时间通道   查询侧不解析日期 → 只能靠调用方给，或干脆不用
价值门槛   用于「存不存」→ 应为「展开顺序」
步骤顺序   合并在翻译之前（这条是对的，保持）
```
