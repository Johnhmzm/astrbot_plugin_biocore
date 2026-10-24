# BioCore 插件更新说明

当前版本：v0.6.3

## 数据位置

新版数据已移到 AstrBot 的持久化插件目录：

```
AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/
```

里面包含：

- persona_profile.json
- api_config.json
- settings.json
- states/
- memory/
- image_cache.json

旧版放在插件目录内的 `data/`，首次启动会自动迁移到上面的持久化目录。

## 更新前备份

复制整个持久化数据目录：

```
data/plugin_data/astrbot_plugin_biocore_standalone/
```

## 更新

1. 停止或在 AstrBot 插件管理中停用旧版 BioCore。
2. 解压新 zip。
3. 用新包中的以下内容覆盖旧插件目录：
   - main.py
   - metadata.yaml
   - _conf_schema.json
   - README.md
   - UPDATE.md
   - preview.png
   - pages/
4. 不要删除 data/plugin_data 下的持久化数据。
5. 重新启用插件，或重启 AstrBot。

## 卸载注意

AstrBot 卸载插件会删除插件代码目录。  
新版把数据放在 `data/plugin_data` 下，  
默认卸载不会删除这份数据；  
如果卸载时勾选“删除数据”，才会清掉。

## 验证

插件管理里版本应显示：

`v0.6.3`

打开插件页，设置页应能看到 API 接入、知识库和记忆条数。
