# MIGRATION — 1.3.4 → 1.4.0（用户无感升级）

**直接覆盖插件升级即可，无需手动备份。** 1.4.0 启动时自动迁移，并在写盘前把
settings / memory / states 复制到内部备份目录；失败会安全退避，面板可见结果。

## 自动流程

1. 启动：`_load_settings()` 后、life loop 前执行 `migrate(plugin)`；
2. 迁移前自动备份到：
   `<plugin_data>/astrbot_plugin_biocore/backups/pre-migration-YYYYMMDD-HHMMSS/`
   ```text
   pre-migration-<stamp>/
     settings/   ui_settings.json（以及 legacy_ui_settings.json，如存在）
     memory/     *.json（旧记忆，原样）
     states/     *.json（旧状态，原样）
   ```
   日志：`[biocore] migrate backup: <path>`；
3. 原子写：所有迁移写盘均为 `tmp → os.replace`，失败不覆盖旧文件；
4. 若启动迁移失败（schema_version 未写成），首次打开面板 `page/status` 或
   `page/debug` 会自动再试一次；两次都失败 → 面板显示“迁移：有 N 条警告”，
   插件继续用默认值；
5. 面板调试页显示一行：`迁移：已完成（备份 → ...）` 或 `迁移：有 N 条警告`。

## 检查

- `ui_settings.json` 顶层 `schema_version=2`；
- accumulator：`theta` 人设推导值、`V>=0`、有 `cooldown_seconds/daily_cap/last_umo`；
- 记忆条目有 `storage_s/retrieval_s/access_count/arousal_at_encoding/hidden`；
- 面板打开后 **Ctrl+F5 强刷**（index.html 内联，旧缓存会显示旧 UI）。

## 一键回滚（无需手工翻找）

```powershell
# 停服，然后（在插件目录下）：
python -c "from biocore_model.migrate import restore; import json; print(json.dumps(restore(r'<plugin_data>\astrbot_plugin_biocore\backups\pre-migration-20261031-205100'), ensure_ascii=False))"
```

或带显式 data_dir：

```powershell
python -c "from biocore_model.migrate import restore; print(restore(r'<backup_dir>', type('P',(),{'data_dir':r'<plugin_data>\astrbot_plugin_biocore'})()))"
```

恢复范围：settings（含 legacy）/ memory / states；再启动插件即可。回滚脚本也是
tmp→replace，不会写坏文件。

## 迁移内容

- 设置：旧 `plugins/<plugin>/data/ui_settings.json` 比新 authority 新/新文件不存在时合并；
  被覆盖键记录在报告 `stats.overridden_keys`；
- accumulator：`V<0`→0；`theta` 缺失/仍 0.55→当前 params；补 cooldown/daily_cap；
  last_umo 从最新 state 推断；
- 旧记忆：只补缺失字段，不删条目、不改条数：
  `storage_s=0.45`、`access_count=1`、`arousal_at_encoding=0.4`、`hidden=False`；
  `retrieval_s=0.9/sqrt(1+age_days)`（0.05..0.95，按文件 mtime，越旧越低）。

## 注意

- 迁移不删除记忆；已删除的配置键由 AstrBot 自身提示 Config key removed；
- 跨机器恢复时 retrieval_s 会按文件 mtime 重新估算；
- 迁移幂等（schema_version=2），重复启动/面板重试不会重复改。
