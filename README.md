# BioCore 生物情绪核心

面向 AstrBot 的独立生物情绪层：首次读取当前人设并编译为数值档案，之后每轮只注入简短的表达意图，不直接把原始状态塞给 LLM。

- 插件名：`astrbot_plugin_biocore`
- 插件 ID：`Johnhmzm/astrbot_plugin_biocore`（`metadata.author/name`）
- 版本：以 `metadata.yaml` 为准（当前 `1.2.73`）
- 作者：`Johnhmzm`
- 仓库 / 市场源（GitHub）：https://github.com/Johnhmzm/astrbot_plugin_biocore
- 镜像（Gitee）：https://gitee.com/johnhim/astrbot_plugin_biocore
- Logo：`logo.png`（256×256）

## 插件市场

本 GitHub 仓库是 AstrBot 插件市场记录的源码仓库；市场 JSON 本身存放在 AstrBot 的注册表（`AstrBotDevs/AstrBot_Plugins_Collection`）中，**不在本插件仓库内**，请不要在这里添加市场 JSON 文件。

已按 [AstrBot 插件市场规范](https://docs.astrbot.app/dev/plugin-market/) 和 [发布指南](https://docs.astrbot.app/dev/star/plugin-publish.html) 检查：

- `plugin_id` = `metadata.author` + `/` + `metadata.name` = `Johnhmzm/astrbot_plugin_biocore`
- `metadata.yaml` 必填字段齐全：`name`、`author`、`version`、`repo`、`desc`
- `repo` 是公开的 HTTPS GitHub 地址，默认分支 `main`，仓库远低于 16 MB 发布上限
- `display_name`、`short_desc`、`astrbot_version`、`support_platforms`、`tags`、`social_link` 可选字段已填写
- `logo.png` 为 256×256（1:1）；AstrBot 会从插件目录读取该 Logo
- 持久化数据在 `data/plugin_data/` 下，不进入本仓库（见下方「数据」）

如果市场里暂时搜不到本插件，请通过 AstrBot Cloud 发布页提交：
https://cloud.astrbot.app/publish （需要 AstrBot Cloud 账号）。仅向本仓库添加文件不会自动创建或更新市场记录。

## 安装

推荐从 AstrBot 插件市场安装；也可以在 AstrBot 插件管理里填写 GitHub 仓库地址安装，或直接复制插件目录到：

```text
AstrBot/data/plugins/astrbot_plugin_biocore/
```

插件没有第三方 Python 依赖；`requirements.txt` 故意不写包，只使用 AstrBot 提供模块和 Python 标准库。

## 更新

AstrBot 的更新按钮是否可用，取决于插件当初的安装方式：

| 安装方式 | 是否可直接从市场 / 插件页更新 |
|---|---|
| 市场安装 | 是 |
| 仓库安装（GitHub URL，市场源） | 是，从 GitHub 拉取 |
| 仓库安装（Gitee 镜像） | 是，但 Gitee 不是市场源；市场更新需绑定 GitHub 市场记录 |
| 上传 / ZIP 安装（`install_method=upload`） | 否；AstrBot 对上传安装的插件禁用更新 |

### 如果是 ZIP 安装

做一次来源迁移即可，之后正常更新：

1. 保留 `AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/`，不要删除。
2. 在 AstrBot WebUI → 插件 → 已安装，使用 **更换插件来源 / 绑定市场源**，选择市场记录 `Johnhmzm/astrbot_plugin_biocore`。
3. 如果没有该操作，从市场或仓库地址 `https://github.com/Johnhmzm/astrbot_plugin_biocore` 覆盖安装一次。
4. 重载插件。之后安装来源变为市场/仓库，更新按钮即可用。

不需要卸载；如果确实卸载，请取消勾选 **删除数据**。


## 功能

- 首次运行时读取当前 AstrBot 人设，编译成数值档案并保存。
- 每次 LLM 请求时，把紧凑的 `[BioCore] ...` 表达意图附加到当前用户轮次（系统提示保持稳定）。
- LLM 回复后，把回复反馈给状态、记忆、目标和事件档案。
- Dashboard 页面：情绪概览、表达意图、人格/自我、活动会话、设置。

生物层不直接写 prompt 文本；只有解释层负责渲染 LLM 输入和解析输出。

## 数据

持久化数据放在 AstrBot 的插件数据目录，不放在插件代码目录：

```text
AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/
  persona_profile.json
  states/
  memory/
  archives/events.jsonl
  archives/insights.jsonl
  users/
  self_model.json
```

不要把这些数据复制进插件包或提交到仓库。

## 配置

行为参数在 **AstrBot 插件管理 → BioCore 配置** 中设置。Dashboard 设置页只保留 BioCore 专用 API 覆盖、记忆压缩、可视化、版本检查和备份。

## 安全默认值（公开部署前必读）

本仓库当前按私人使用默认发布：

- `safety_enabled: false`：不掩码敏感信息、不限制跨会话记忆、不强制拒答低置信记忆、不跳过投毒标记；
- `we_memory_enabled: false`：共同记忆默认不启用；
- 8 个提案型 LLM 函数默认关闭。

公开/多用户部署前，请在 AstrBot 插件配置中设置 `safety_enabled: true`，并按需开启 `we_memory_enabled` 与各 LLM 函数。私人单用户使用可以保持默认关闭。

## WebUI

![BioCore dashboard](preview.png)

安装后：AstrBot WebUI → 插件 → BioCore → Dashboard。

## 兼容性

- AstrBot：`>=4.16,<5`（`metadata.yaml` 中的 `astrbot_version`）
- 平台适配器：`aiocqhttp`（`metadata.yaml` 中的 `support_platforms`）
- 只使用 AstrBot 的 `filter.on_llm_request` / `filter.on_llm_response` 钩子；不接管消息事件、不生成回复、不替换人设、不接管其他插件记忆。
