# BioCore 插件更新说明

当前版本：以 `metadata.yaml` 为准（当前 **1.4.15**）。完整更新日志见 [CHANGELOG.md](CHANGELOG.md)。

> 发版口径：`1.4.15` 为发版目标；市场记录已同步为 `1.4.15`，公开仓库与市场在发布时同步。

## 1.4.15 升级提示

> ⚠️ 可能有问题；安全闸默认关闭，可在设置内开启；自主回复默认关闭。

- **表达层安全闸默认关闭**：新增三个开关（面板「设置 → 安全」）：边界闸（不诊断 / 不替代真实 / 不宣称意识）、危机处置（危机先安全）、安全总开关。默认值全部为 false，并且写死在 `biocore_model/boundary_gate.SAFETY_GATES_DEFAULT_ENABLED`；旧配置缺键时同样回退为关闭，不会因为缺键变成开启。
- **开关关系**：总开关关闭时一律不拦；单独打开边界闸只启三条边界；单独打开危机处置只启危机先安全；两者可同时开。命中时只删越界句（边界闸）或先给安全确认与求助渠道（危机处置），并打印一条 info 日志说明命中的规则。
- **不改提示词、不增加调用次数**：闸门只处理可见回复文本，不写 prompt、不新增 LLM 调用；默认关闭时行为与 1.4.14 完全一致。
- 注意：1.4.14 起「安全限制」默认值由开改为关（含敏感掩码/跨会话隔离/低置信拒答/投毒过滤）；需要这些能力请在设置里打开安全总开关。

## 1.4.14 升级提示

> ⚠️ 可能有 bug；自主主动回复默认关闭；老数据自动兼容（`memory_storage_backend` 默认 `auto`）。

- 记忆存储：新增 `memory_storage_backend`（默认 `auto`，可选 `json` / `sqlite`），面板可切换。`auto` 时已有健康 SQLite 库就用库，否则用 JSON；切到 `sqlite` 会自动备份 `memory/` 并导入现有 JSON，且每次写入同时保留 JSON 镜像，可随时切回 `json` 或回退旧版本。
- 健壮性：首次导入 SQLite 前备份整个 `memory/`；数据库损坏自动留 `*.corrupt.bak` 并从 JSON 重建；损坏的 JSON 跳过、不阻塞启动；面板「调试」可见当前后端与迁移状态。
- 新增 `predictive_enabled`（默认开，只读）：预测误差只用于下一轮多召回 ≤1 条与学习率放大（alpha 0.1–0.4），不写 prompt、不增加 LLM 调用。
- 新增 `needs_events_enabled`（默认开）：被拒绝/被忽视/被夸/被连接/达成目标等事件有界影响四种需求（单事件每项 ≤0.05），需求缺口会偏置下一轮表达；关闭后回到纯时间衰减。
- 修复：模型输出被截断时残留的 `{"dims"...` 片段可能泄漏到可见回复，现已从可见文本剥离。

## 1.4.13 升级提示

> ⚠️ 可能有 bug；自主主动回复默认关闭。

- 直接覆盖升级即可，无需手动迁移：启动迁移已幂等（schema_version 已是最新时跳过）。
- 新增可配置项 `dims_delta_limit`（默认 0.2）与 `dims_delta_limit_enabled`（默认开）：单条消息内所有 dims 造成的状态变化绝对值之和超过上限时按比例缩放（方向与通道比例不变），日志记录 raw/scaled；想恢复 1.4.12 的「每通道各自限幅、总量不设限」可关闭该项。
- 图记忆实体消歧：同一实体的不同叫法会按别名 + 相似度（≥0.85）合并成一个节点，新叫法自动记为别名；误并可用 `POST /astrbot_plugin_biocore/page/graph/merge`（`keep_id`/`drop_id`）手工合并。
- 面板「记忆元数据」新增「本轮使用的记忆」（TURN MEMORY，只读）：一次真实回复后显示最多 4 条（来源 + 选择原因）；重启后首轮回复前为空属正常。
- 内联状态标签新增可选 `entities[].aliases`；标签解析失败/低置信时仍走原 probe 回退，不阻塞回复。

## 1.4.12 升级提示

- 直接覆盖升级即可：启动自动迁移 1.3.4 数据（原子写、自动备份到 `backups/pre-migration-<时间戳>/`、失败重试、面板可见）；无需手动备份，回滚见 [docs/MIGRATION.md](docs/MIGRATION.md)。
- 主流程改为 pipeline active，模块拆为 11 个 mixin + blocks 组装；旧配置键自动映射/兼容。

## 1.3.4 升级提示

- 新增可选 `text` 提示词模式（`bc_prompt_mode=text`，默认仍 `telemetry`）：数值转文字档位、保留标签、固定顺序（她此刻→对你→这一轮）≤150 字；含多情绪（1 主+1 次+强度）、事件联系、固定图例（≤2 行，只进 system 前缀）。
- 物理删除 tombstone 已脱敏：只保留 `路径 + sha256 + 字节数 + 已删除`，删除后**不可从 tombstone 还原原文**（重要数据请先导出/备份）。
- 增量 eval 基建：`scripts/run_evals.py --changed/--full`，按组+文件哈希只跑受影响 eval；`scripts/eval_render.py` 57 checks。
- 默认行为与 1.3.1 一致（默认 `telemetry`）。回退：`bc_prompt_mode=telemetry`、`bc_text_legend_enabled=false`。

## 1.3.1 升级提示

- 记忆聚焦新增「重新判定」：按多角度 W/W_her/K 重算，结论为只归档/不该记时降级（importance 0.15、memory_point=false），可用「恢复」撤销。
- 未接线项补齐：impression/tom/diary/narrative 进入 [BC] hint；多跳召回、refusal 降长度、workspace_token 注入均可选（默认关）。
- 回复侧新增只读统计：回复一致性、LLM 失败/降级、token 用量；本 AstrBot 版本不暴露流式回调，不做假流式。
- 默认行为不变：新增功能默认关，只读统计不影响回复；默认 [BC] 无新增 token。
- 模型层：`[BC]` 默认放 system 尾部 + 字符预算 700，hint 改为独立 `[BH]` 行（≤140 字）；只去浪费、不裁剪（空块/重复行/无消费者 hint/过期旧摘要），不裁头部与记忆证据。
- 准确性：事实钉住默认开（重要记忆不被 80 条挤掉）；双时态、自适应 calibration、重排、心境/情绪门控默认关，A/B 后再开。
- 省钱：Dashboard 新增只读费用行（token 估算 + 可配价格表）；「省钱模式」预设默认关，开启后降低注入与召回预算。
- L1 新增只读信号 `conflict_ema / rumination_ema / anchor_weight`；行为影响默认关。
- 若升级后回复风格变化明显：先检查 `bc_budget_chars`、`think_selfcheck_trace_enabled`、`think_selfcheck_hint_enabled`、`memory_pin_enabled` 四项，可单独关闭回退。

## 1.2.99 升级提示
- 记忆点判定默认开启：琐碎事件（纯工具问答、低情绪/低关系增量）不再生成记忆点；如需恢复旧行为，关闭 `memory_worthiness_enabled`。
- `bio_learning=true` 默认开启：调节策略 Q 与 trust 学习率会随经验更新（小步长、有界，可关闭）。
- 记忆保持默认 `single`（与 1.2.98 一致）；`power_law` / `multi_scale` 为实验模型，A/B 后再切换。
- 主动发送、注意力 L17–L19、事件链、自主循环默认关；开启前请先看 README 的边界说明。
- 升级前建议备份 `plugin_data`。

## 1.2.98 升级提示
- 配置向后兼容：旧 config.json 不用改，新增项都有默认值；被移除的死配置项会被忽略。
- 默认 LLM 调用收敛：升级后只保留事件总结 / 记忆总结两个摘要调用；如需恢复全部 LLM 能力，关闭 `llm_only_reply_summary`。
- 数据目录仍是 `data/plugin_data/astrbot_plugin_biocore_standalone/`，更新不丢档；升级前建议备份。
- 球下图例可在 设置 → 球体图层 → 「记忆球 / 记忆节点」行右侧的「显示图例」开关隐藏。

## 数据位置

插件数据不放在插件代码目录，而是 AstrBot 的持续化插件数据目录：

```text
AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/
```

包含 persona_profile.json、states/、memory/、archives/、users/、self_model.json 等。

更新插件时不要删除这个目录。

## 更新方式

1. 优先从 AstrBot 插件市场安装/更新（market source 为 GitHub：`Johnhmzm/astrbot_plugin_biocore`）；
2. 也可在 AstrBot 插件管理使用 GitHub 仓库地址安装/更新；Gitee 仅作为镜像备用；
3. 更新后重载插件；
4. 打开 BioCore 设置 → 版本，检查当前安装版本（版本号以 `metadata.yaml` 为准）。

## 图片识别：两种模式

- **通用多模态 API（推荐）**：由 AstrBot Provider 处理图片，无需本节的 `image_*` 配置。
- **本地 VLM（可选）**：仅当填写 `image_llama_server` + `image_llama_model`，且 `image_service_port` > 0 时，插件才启动本地 `llama-server`；`image_service_port` 是该本地进程的 127.0.0.1 绑定端口，不是通用 API 地址。默认 0 表示不启用本地 VLM。

## 本机图片识别服务（仅本地模式）

插件不再内置本机绝对路径。需要本地 VLM 图片识别时，在 AstrBot 插件配置里填写：

- `image_llama_server`：llama-server 可执行文件路径
- `image_llama_model`：VLM 模型路径
- `image_llama_mmproj`：mmproj 路径（可选）
- `image_service_port`：本地 llama-server 端口，默认 0；0=不启用本地 VLM，只有填本地路径且端口>0 才启动

留空表示不启用本地图片服务；图片识别会优雅跳过，不影响文字聊天。

## 主动行为与学习默认（review BLOCK-04/09）

- 默认不主动发送；只有 proactive_autonomy=true + proactive_send=true 且私聊才可能发送，受 30min 冷却/每日3条/0–8点静默限制。
- bio_learning 默认 true（小步长、硬边界）；需要完全冻结学习时设 bio_learning=false；/biocore learning reset 可恢复默认。
- retention_model 默认 single（1.2.98 旧指数）；power_law/multi_scale 为实验模型，A/B 后再切换。
