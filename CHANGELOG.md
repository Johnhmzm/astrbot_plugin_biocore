# 1.4.0 - 2026-10-31

⚠️ 本版本改动较大（主流程切换 + 数据迁移），可能存在不稳定；建议先备份、观察一天。
⚠️ 自主主动回复默认关闭，如需启用请在面板「设置 → 自主」中打开。

- **主流程**：pipeline 默认 active，回复提示词由新主线组装（状态/关系/间隔/意图/语气/人设图例）。
- **模块化**：BioCore 拆为 11 个 mixin + blocks 组装层（可按块启用/关闭）。
- **记忆**：双强度模型（storage/retrieval）、测试效应、软遗忘、同簇去冗余、每小时维护。
- **情绪**：数值空间判定（6 原型 + softmax），标签仅作读法；表达层支持混合语气。
- **反馈**：模型输出 7 维评价 dims → 权重矩阵 → 状态增量（词表仅兜底）。
- **自主**：10 秒常驻循环；节奏由人设推导（theta/tau/cooldown）；主动消息记录与开场去重。
- **迁移**：1.3.4 → 1.4.0 自动迁移（原子写、自动备份、失败重试、面板可见、restore 回滚）。
- **面板**：流水线为主视图（按模块分组）、调试页（needs/情绪分布/迁移状态）、设置页记忆分组。
- 升级失败可回滚，详见 `docs/MIGRATION.md`（自动备份 `backups/pre-migration-<时间戳>/`，`restore` 一键恢复）。

# 1.3.5（beta）

- 设置页重构：6 标签（API/生物/记忆/模型/球体/系统）+ 简单/高级视图 + 11 个功能开关（旧键自动映射）。
- 自主行为：新增设置页（表达意图→自主行为），阈值/最大字数可调，状态接 status.autonomy。
- 人格：编译用人设下拉、当前人设显示、编译两次点击即完成；人设不再显示 default。
- LLM：15 个功能收敛为 2 个开关（图片描述/归档批量）+ 全局路由 + 今日预算；归档改后台批量。
- 单次调用协议：行为规则写进提示词、`<bc>` 标签反注；旁路 LLM 默认关（[实验]）。
- 泄漏兜底：协议回显剥离 + leak_guard 指标（protocol_echo/prompt_rule_echo/tag_missing/tag_invalid）。
- 构建守卫：面板越界/重复 id/未定义常量/危险赋值/内联幂等 5 类检查。
- 兼容层：localStorage schema=2、旧开关→新开关迁移、旧键保留。

# 1.3.4

修复「情绪标签 + 内容泄露」仍复现的根因（1.3.3 的守卫只覆盖部分路径）：

- **回写条件错误**：on_llm_response 只在解析出 update 时才把 cleaned 文本写回 response；模型输出未知标签（如 care）→ update 为 None → 原始文本（含标签/裸 JSON）照常发送。现在无论 update 是否存在，只要 cleaned 变化就回写 completion_text 与 result_chain。
- **裸 JSON 只在句尾剥离**：{"e":...} 夹在正文中间时不会被 sanitize 清理；现在任意位置的裸标签 JSON 都会剥离。
- **标签别名校验**：shy/embarrassed/calm/happy/care/concern 等近似值映射到白名单（fear/neutral/joy…），避免 affect 更新被静默丢弃。
- 协议强化：e 只允许 6 个白名单值；禁止输出推理/候选比较/自述；标签只出现一次且必须隐藏。
- 版本号同步：metadata / main register / dashboard / README / UPDATE / 市场记录。

# 1.3.3 - 2026-10-28

### Fixed
- 修复模型输出的裸 JSON（如 {"e":"care","i":0.68}）与未闭合 <bc> 标签泄漏到用户可见回复：新增最终出口守卫 biocore_model/sanitize.py（声明式模式清单 + 保护 URL/媒体标签 + 固定兜底 + 幂等 + Traceback 守卫）。
- 未知情绪标签（如 care）解析层丢弃并计数，不再落库或泄漏。

## 1.3.2 - 2026-10-28

### Added
- `text` 提示词模式（`bc_prompt_mode=text`，默认仍 `telemetry`）：数值转档位词、标签 e/c/n/plan/reg 保留、顺序固定（她此刻→对你→这一轮）、≤150 字；多情绪（1 主 + 1 次 + 强度）、事件联系（事件链边最强 1–2 条，写成「A → B，她读成同一件事」）、边界小数仅在阈值±0.05 或 0.5/0.75 附近给出；固定图例（≤2 行）只进 system 固定前缀，可用 `bc_text_legend_enabled=false` 关闭。
- 模型层模块化：渲染迁入 `biocore_model/render.py`（telemetry/semantic 与 1.3.1 逐字节一致），新增 `biocore_model/services.py` 统一外部调用超时/计数网关；`interpretation.py` 保留同名薄 wrapper，旧 import/eval 不变。
- 增量 eval 基建：`scripts/run_evals.py` 按 8 组 + 文件哈希只跑受影响组（失败组必重跑，`.eval_cache.json` 本地缓存）；`scripts/_eval_common.py` 统一 eval bootstrapping；`scripts/eval_render.py` 57 checks。

### Changed
- **物理删除 tombstone 脱敏**：硬删除的 tombstone 只保留 `路径 + sha256 + 字节数 + 已删除`，不再包含原文/二进制；软删除 tombstone 同样只保留 id/status/sha256；Dashboard 墓碑投影不再返回原文；删除后不可从 tombstone 还原。
- 默认提示词模式不变（`telemetry`）；关闭新增开关即回到 1.3.1 渲染行为。

## 1.3.1

- 上架合规：注入改为临时 content part（TextPart.mark_as_temp），不再修改 req.system_prompt；数据目录统一为 astrbot_plugin_biocore（含旧目录自动迁移并保留备份）。

## [1.3.0] - 2026-10-27

### Added
- 记忆聚焦「重新判定」：按 W/W_her/K 重算已归档事件；结论为只归档/不该记时降级（importance 0.15、memory_point=false），不物理删除，可用「恢复」撤销；关闭判定开关时不修改记录。
- 未接线项补齐（默认关）：relationship_impression / tom_probe / diary / relationship_narrative 进入 [BC] hint；多跳召回 `memory_chain_multihop`（hop≤2/fan≤3/新增≤6）；`refusal_brevity_enabled` 降低回复长度与主动度；`workspace_token` 仅在自主循环开启时注入 [BC]。
- 回复侧只读统计：`reply_consistency`（回复与意图一致性）、`llm_telemetry`（各函数失败/降级/回退计数）、`token_usage`（provider 提供则累计，否则标记不可用）。
- 新增 eval_wire_fixes.py（56 checks）；全量 eval 76/76。
- **模型层完善**：[BC] 单块放 system 尾部 + 字符预算 `bc_budget_chars=700`（480–800），只去浪费（空块/重复行/无消费者 hint/过期旧摘要），不裁剪有价值内容；不裁头部与 memory evidence；hint 独立 `[BH]` 行（≤140 字/轮 1 条）放 [BC] 之后；注入 trace（`bc_trace_enabled` 默认关）；最近 5 轮逐字去重（默认开，无损）；解析稳健（坏 JSON 一次修复、未知键/标签计数、白名单可配、残留剥离）；确定性反向检查 F1（默认开、0 LLM、只读）、复读检测 F3（默认关）、软边界负反馈 `soft_bounded`（默认关）、thought note 仅本轮不落盘、触发式反思 F2（默认关、日限 3）、路径依赖监控（默认关只读）、迎合检测（默认开只读）。
- **Dashboard**：「重新判定」按钮、「修正记忆点」菜单、事实钉住 toggle（钉住/取消钉住 + 球/列表 pin 标记）、L1 信号只读折叠块（conflict/rumination/anchor/sycophancy）、模型层注入 trace 与费用行；全部只读或用户主动操作。
- **准确性**：双时态 `valid_at/invalid_at`（默认关）、calibration 自适应 ±0.15（默认关）、cross-encoder 重排 `rerank_enabled`（默认关、失败回退）、事实钉住 `memory_pin_enabled`（默认开，pin 不被 80 条截断 + `/page/memory/pin` API）、溢出确定性归档（默认关）、心境一致性扩展与情绪门控（默认关）、single vs power_law A/B 输出。
- **省钱**：真实 usage 优先/缺失用 chars/2.2 估算并标记；费用表可配；`state.token_usage` + Dashboard 费用行；召回预算（默认关）；「省钱模式」预设（默认关：预算 300/top-k 3/单条 100 字/句级排重/hint 关）；A/B 护栏断言 must-have top-1 不丢；`docs/BIOCORE-COST-SAVINGS-v1.md` 含算例与宿主历史限制。
- **L1 生理前提**：`conflict_ema`、`rumination_ema`、`anchor_weight`、`identity_threat→stress`（行为开关默认关，snapshot 只读）；`soft_bounded` 负反馈替代硬 clip（默认关）。
- 新增 eval_thinking_loop（70）/ eval_accuracy_v131（30）/ eval_token_budget（26）/ eval_l1_thinking（34）；全量 eval **83/83**。

### Changed
- **默认行为有意的三处变化**：① `[BC]` 单块放 system 尾部（原来拼在 system prompt 内），字符预算 `bc_budget_chars=700`，只去浪费、不裁剪；② hint 独立 `[BH]` 行放在 `[BC]` 之后（≤140 字/轮 1 条）；③ `memory_pin_enabled=true`，钉住条目不再被 80 条上限挤掉。
- 只读默认开：F1 反向检查仅记录 trace（`think_selfcheck_trace_enabled=true`，**不注入**）；`think_selfcheck_hint_enabled=false`（注入提示默认关）；`token_budget` 费用统计只读。
- 新增机制默认关：F3 复读、F2 反思、路径监控、软边界、双时态、自适应 calibration、重排、心境/情绪门控、召回预算、省钱模式、conflict/rumination/anchor/identity 行为影响。
- `bc_budget_enabled=false` 时完全绕过预算/重排/hint 提取，回到 1.2.99 逐位行为（golden 测试覆盖）。
- 流式：本 AstrBot 版本不向插件暴露 partial/streaming 回调，不实现假流式，限制写入文档。

### Fixed
- 修复 Windows 下 `node -e` 命令过长导致 WinError 206 的 eval harness 失败（改用临时文件执行）。

### 兼容性
- 配置/数据向后兼容；关闭新增开关即回到 1.2.99 行为。
- 「重新判定」只改事件标记与重要度，不删除、不改原文；旧事件无 worthiness_inputs 时用 worthiness_from_parts 兜底。

## [1.2.99] - 2026-10-27
### Added
- 记忆点判定：W / W_her / K 多角度加权 + 三向闸门（生成记忆点 / 只归档 / 不生成），默认开启；事件记录写入 worthiness 明细（I/S/C/G/PE/R/P/N）。
- Dashboard「修正记忆点」：标记重要 / 标记不重要 / 编辑标签 / 恢复，原子写回、不物理删除。
- L1 学习：调节策略 Q 学习（N≥5 门槛、单步 ≤0.02）、trust 自适应学习率（Nassar 近似）、`/biocore learning` 与 reset。
- 噪声→自主行为：就绪度 threshold/max_chars/impulse、后台 tick、私聊门槛、冷却 30min、每日 3 条、0–8 静默（默认关）。
- 最小自主循环：显著性→候选→价值（目标梯度/延迟折扣/努力成本）→仲裁→反馈（默认关、token-only）。
- 记忆注意力：L17 激活概率门控 / L18 fan 惩罚 / L19 容量 4（默认关）；显著度乘子与句级排重（默认关）。
- 事件连锁：事件-事件边（同会话/时间邻近/因果词、≤3 边、30 天半衰）+ 1 跳召回 + 链接预算；多跳 experimental 默认关。
- Dashboard 只读面板：自主就绪度、学习状态、事件链。
- embedding：LRU512 缓存、超时可配（默认 1500ms，100–15000）、sensitive 内容不送 embedding。

### Changed
- 默认行为变化：`bio_learning=true`（Q/trust 会随经验更新）；记忆保持默认 `single`（1.2.98 旧指数）；`memory_worthiness_enabled=true`（琐碎事件不再生成记忆点）。
- 新增机制默认关：`proactive_autonomy/proactive_send`、注意力 L17–L19、事件链、自主循环；主动发送仅私聊。

### Fixed
- 修复 embedding 路径 `self._sha256` 崩溃（生产必现 AttributeError）。
- 修复 embedding 缓存 key 与 payload 截断长度不一致。
- 修复 eval_attention_three 因时间漂移导致的偶发失败。

### 兼容性
- 配置向后兼容：新增项全部带默认值，旧 config.json 不用改。
- 数据向后兼容：目录不变；旧记忆/状态缺新字段按默认读取。
- 关闭 `memory_worthiness_enabled` 可完全回到 1.2.98 归档逻辑。
- 无新增默认 LLM 调用；AstrBot 版本要求不变（>=4.16,<5）。

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

## 主动行为与学习默认（review BLOCK-04/09）

- 默认不主动发送；只有 proactive_autonomy=true + proactive_send=true 且私聊才可能发送，受 30min 冷却/每日3条/0–8点静默限制。
- bio_learning 默认 true（小步长、硬边界）；需要完全冻结学习时设 bio_learning=false；/biocore learning reset 可恢复默认。
- retention_model 默认 single（1.2.98 旧指数）；power_law/multi_scale 为实验模型，A/B 后再切换。
