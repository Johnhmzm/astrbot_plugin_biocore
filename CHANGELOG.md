# Changelog

本项目的重要变更记录。版本号以 `metadata.yaml` 为准。

## [1.2.98] - 2026-10-26

### Added
- 补全记忆层闭环：confidence↔召回、importance↔召回、stability↔复习、inhibition↔召回、assoc↔召回；G8 重要度读时 30 天半衰（下限 0.15）、G7 关联 30 天半衰、G11 事件重复计数半衰、G12 working_set 2h TTL、B12 换出、G15 反思树 90 天软遗忘、G9 schema 一致度衰减、G1 calibration→置信（±0.05）。
- 生物层对偶补齐：敏化 ×1.0–1.25、7 种调节策略（含 label_emotion「命名情绪」）、恢复 speed 0.8–1.2、信息缺口好奇 +0.10·gap。
- Dashboard 只读投影：稳态/昼夜/allostatic 面板、召回元数据条、calibration chips、有效值/存储值标注、orb 有效 merge_count。
- 设置 → 球体图层新增「显示图例」小开关（默认开，并入「记忆球 / 记忆节点」行），可隐藏球下方图例。

### Changed
- 关系→稳态闭环（C6）接线，仍保留一轮延迟。
- 默认 LLM 调用收敛：llm_only_reply_summary 默认开启，只保留 event_summary / memory_summary 两个摘要调用；event_ranking 改确定性管线（event_ranking_llm 默认关）。需要全部 LLM 能力的用户关闭该项即可恢复。
- 已废弃配置项不再读取（保留默认回退），旧配置无需手动清理。

### Fixed
- 清理若干死配置与未使用字段；校准（calibration）从“只记录”改为真正回写置信度。

### 兼容性
- 配置向后兼容：新增项全部带默认值，旧 config.json 不用改；被移除的死配置项会被忽略。
- 数据向后兼容：继续使用 data/plugin_data/astrbot_plugin_biocore_standalone/（不修改目录名，避免丢档）；旧记忆/状态 JSON 缺新字段时按默认值读取。
- 无新增依赖；AstrBot 版本要求不变（>=4.16,<5）。
- 升级后默认 LLM 行为会变（见 Changed 第 2 条），属预期变更。

## [1.2.97] - 2026-10-26

### Changed
- 品牌与说明改为“拟态生物情绪核心”：明确是行为层拟态，模仿生物情绪系统的功能结构，不声称复刻神经元、内分泌或意识。
- README 新增“拟态机制”章节，说明围绕 PAD 核心情感、稳态/内感受、认知评价与情绪频谱、事件记忆、关系轨迹、解释层六层展开。

## [1.2.96] - 2026-10-26

### Fixed
- 通用图片识别不再因为本地 VLM 未配置而被阻断：只有填写 image_llama_server + image_llama_model 时才启动/检查本地 llama-server。
- AstrBot 通用多模态 Provider 现在可以直接用于 image_caption，无需 image_service_port。

### Documentation
- 明确 image_service_port 是本地 llama-server 的绑定端口，不是通用图片 API 地址；默认 0=不启用本地 VLM，只有填写 image_llama_server/model 且端口>0 才启动本地服务。

## [1.2.95] - 2026-10-26

### Added
- 记忆球之间加入视觉引力：质量与范围由事件重要度决定，位移平滑且限制最大偏移，不会被拉进中心球或互相重叠。
- 设置 → 球体图层新增「记忆球引力」开关（默认开启）。

### Changed
- 记忆球体不透明度提高到 0.85–0.96，环最高 0.80，球体始终比环更实，混合色更清晰。

### Documentation
- 明确 `image_service_port` / `image_llama_*` 仅用于可选本地 VLM llama-server，不是通用 API 接口；使用 AstrBot 通用多模态 Provider 时无需配置。

## [1.2.94] - 2026-10-26

### Added
- 事件总结返回全部识别情绪的四信号（intensity / confidence / centrality / evidence），不把强度归一化为 1。
- 记忆球按多信号评分成环：p≥.15、confidence≥.50、share≥.10 或 centrality≥.70，按 score 排序并累计到 0.85。
- 球体支持混合色：只有成环情绪影响球色，环内按 intensity 归一化。
- 设置新增「球体颜色模式」：mixed（默认）/ primary。

### Changed
- 环数按实际成环情绪动态 0–N，不再固定最多 3 条或硬凑。
- 旧事件无情绪层数据时只画已知 1 条，不伪造比例。

## [1.2.92] - 2026-10-26

### Changed
- 去掉 orbit 环的 10% 移动高光弧，环整圈颜色/alpha 均匀，不再出现一块深色。

## [1.2.91] - 2026-10-26

### Changed
- 记忆球 orbit 环速度按事件情绪强度变化：基础速度提高，高强度事件明显更快。
- 新事件归档记录 `emotion_intensity`，旧事件用 importance 回退。

## [1.2.90] - 2026-10-26

### Added
- 事件标题纳入总结且可编辑（标题 ≤80 字）。
- 旧事件缺少次情绪时支持重新总结补齐；无数据时环用推断次色并标注“次情绪：推断（示意）”。
- 会话记忆事件卡显示小总结/大总结/状态徽标，并支持重新总结、编辑总结。

## [1.2.89] - 2026-10-26

### Added
- 记忆球环样式：3D 椭圆轨道（默认）与 360° 实线圆（静止）可切换，开关位于“设置 → 球体图层”首位。
- 用户关系卡底部新增“关联事件”。
- 聚焦面板滚动条改为 8px 透明轨道 + 渐变滑块。

### Fixed
- 记忆球环基础可见度提高，alpha≥.55、线宽≥1.8。
- 修复记忆球 focus 面板标题横向溢出/双滚动条。

## [1.2.88] - 2026-10-26

### Added
- 会话 canonical key 合并，修复同一会话冒号/下划线导致的下拉重复。
- 事件重复归档清理：跨 key 去重、合并 source_texts/importance/history，写 dedupe_log。
- 会话记忆卡增加重新总结/编辑总结。
- 补全情绪中文映射、中心球颜色上下限。
- 聚焦面板支持历史总结折叠、加载状态恢复。

## [1.2.87] - 2026-10-26

### Added
- 事件标题清洗与可编辑。
- 旧事件次情绪补齐/未知态。
- 会话卡大小总结与状态同步。

## [1.2.86] - 2026-10-26

### Changed
- 聚焦面板恢复单一滚动容器与主题渐变滚动条。
- 大总结完整显示，不再 600/400 截断。
- 记忆球环改为完整 360°，importance 用线宽表达。

## [1.2.85] - 2026-10-26

### Fixed
- 重新总结/保存成功后清理 loading，按钮与编辑框恢复。
- 旧总结写入 summary_history，聚焦面板可折叠查看。

## [1.2.84] - 2026-10-26

### Fixed
- 记忆球 size/alpha 与轨道环改为连续深度因子，消除过 z=0 的突变。
- 聚焦非选中球 dim 改为约 200ms 平滑过渡。

## [1.2.83] - 2026-10-26

### Added
- 聚焦面板新增「重新总结」「编辑总结」。
- page/event_summary API：regenerate/update，原子重写 events.jsonl。

## [1.2.82] - 2026-10-26

### Fixed
- 旧事件聚焦面板不再直出原始长文：legacy 状态 + 原始摘录≤200。
- 事件总结增加 summary_status：llm / fallback / legacy。

## [1.2.81] - 2026-10-26

### Added
- 点击记忆球聚焦：相机跟随、自动放大、左侧显示该记忆详细总结。