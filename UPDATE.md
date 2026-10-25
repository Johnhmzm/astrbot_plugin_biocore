# BioCore 插件更新说明

当前版本：以 `metadata.yaml` 为准（当前 **1.2.73**）

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

## 本机图片识别服务

插件不再内置本机绝对路径。需要本地 VLM 图片识别时，在 AstrBot 插件配置里填写：

- `image_llama_server`：llama-server 可执行文件路径
- `image_llama_model`：VLM 模型路径
- `image_llama_mmproj`：mmproj 路径（可选）
- `image_service_port`：端口，默认 8091

留空表示不启用本地图片服务；图片识别会优雅跳过，不影响文字聊天。
