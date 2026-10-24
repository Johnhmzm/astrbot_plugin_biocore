# BioCore 插件更新说明

当前版本：**v1.2.5**

## 数据位置

持久化数据在 AstrBot 的 plugin_data 目录：

AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/

包含：

persona_profile.json
api_config.json
settings.json
states/
memory/
image_cache.json
archives/
users/
self_model.json

旧版放在插件目录内的 data/，首次启动会自动迁移。

## 更新前备份

复制整个：

AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/

## 更新

推荐走 AstrBot 更新源：

Gitee: https://gitee.com/johnhim/astrbot_plugin_biocore

或手动覆盖：

main.py
interpretation.py
metadata.yaml
_conf_schema.json
README.md
UPDATE.md
preview.png
pages/
skills/

不要删除 data/plugin_data 下的持久化数据。

## 卸载注意

AstrBot 卸载会删除插件代码目录；持久化数据在 plugin_data，默认保留。
