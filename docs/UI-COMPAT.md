# UI 兼容契约（UI-COMPAT）

## 稳定 id
- 设置标签：settingsBio / settingsMemory / settingsModel / settingsVisual / settingsSystem
- 功能开关：feat_memory_*、feat_expression_rules、feat_visual_*、feat_safety、feat_llm_image、feat_archive_batch
- 自主行为页：view-autonomy、autonomyEnabled、autonomySend、autonomyThresholdInput、autonomyMaxCharsInput、autonomySaveBtn
- 人格：personaTargetSelect、personaCompileBtn、personaCompileConfirmRow

## 已合并的旧键 → 新键
swShowNodes/swShowMemoryNodes → feat_visual_nodes；swShowLinks/swShowNodeLinks → feat_visual_links；swShowEmotionRings/swShowRipple → feat_visual_rings；fn_empathy_hint_enabled/fn_pragmatics_hint_enabled/fn_tom_probe_enabled/fn_humor_hint_enabled → feat_expression_rules；swCompress → feat_memory_compress；swHybridRetrieval → feat_memory_retrieval；swSafetyEnabled → feat_safety

## localStorage
- 旧键 → 新键：biocore_settings_tab / biocore_settings_view / biocore_orb_quality 保持不变并复制
- 开关：bio_feat_<id>；true 才迁移（只迁移开状态）
- schema 版本：biocore_ui_schema = 2（app.js 启动时一次性迁移，旧键保留）
- 人设：persona_id 为空 → personas[0]（跳过 default 占位）→ 旧 persona_name → 显示「跟随默认」，绝不显示 default
