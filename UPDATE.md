# BioCore 插件更新说明

当前版本：以 `metadata.yaml` 为准（当前 **1.3.0**）。完整更新日志见 [CHANGELOG.md](CHANGELOG.md)。

> 发版口径：本地 `1.3.0` 为发版目标；公开仓库/市场记录在正式发布前保持 `1.2.99`，发布时再同步。

## 1.3.0 升级提示

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
