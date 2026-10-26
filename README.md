# BioCore · 拟态生物情绪核心

`BioCore` 是面向 AstrBot 的**本地拟态生物情绪核心**：读取当前人设并维护数值档案，在对话过程中模拟情感、压力、能量、信任、记忆事件和关系轨迹，再由解释层转成简短的表达意图注入 LLM 请求。

这里的“拟态”指**行为层模拟**：模仿生物情绪系统的功能结构，不声称复刻神经元、内分泌或意识。

它不生成回复、不替换人设、不改写聊天历史，也不代表临床诊断、真实意识或现实因果；它只是一个可观察、可调整的本地状态与表达提示层。

- 插件名：`astrbot_plugin_biocore`
- 插件 ID：`Johnhmzm/astrbot_plugin_biocore`（`metadata.author/name`）
- 当前版本：以 `metadata.yaml` 为准（当前 `1.2.97`）
- 作者：`Johnhmzm`
- GitHub：<https://github.com/Johnhmzm/astrbot_plugin_biocore>
- Gitee 镜像：<https://gitee.com/johnhim/astrbot_plugin_biocore>
- Logo：`logo.png`（256×256）

![BioCore Dashboard](preview.png)

## 拟态机制：模仿生物的什么

BioCore 不是生物本体。这里的“拟态”是**行为/功能层模拟**：用可计算状态模仿生物情绪系统的功能结构，而不是复刻神经元、内分泌或意识。

### 模仿的生物行为

- 情绪产生与变化：事件触发评价，形成核心情感与情绪频谱。
- 情绪衰减与恢复：情绪回到基线，压力与能量参与恢复。
- 压力反应与稳态调节：偏离设定点后产生需求、压力和恢复过程。
- 趋近、回避与停顿：状态转成表达/行动意图。
- 记忆巩固与遗忘：重要事件被归档、总结，边缘细节会淡出。
- 回忆与再激活：记忆可被召回并影响当前状态。
- 关系建立、冲突与修复：信任、亲近、冲突、修复形成轨迹。
- 依恋与缺席反应：对重要对象的稳定联系和缺失感。
- 自我叙事：把经历整合成对“我是谁”的连续描述。

### 机制映射

| 生物行为 / 机制 | BioCore 的拟态实现 | 边界 |
|---|---|---|
| 核心情感 | PAD：valence / arousal / dominance，加 social / trust / stress / energy | 不是神经递质或脑区活动 |
| 认知评价 | appraisal：novelty / goal relevance / coping / agency | 不是大脑成像或临床评估 |
| 情绪频谱 | emotion / compound + 强度与不确定性 | 不是临床情绪量表 |
| 情绪衰减 | decay / baseline / 稳态回归 | 参数化近似，不是真实生理曲线 |
| 压力与恢复 | stress / energy / allostasis | 不是内分泌或免疫系统 |
| 内感受与驱动 | drives / set-points / need pyramid | 不是真实饥饿、疲劳或疼痛 |
| 记忆巩固 | importance / event summary / archive | 不是 engram 或突触固化 |
| 遗忘 | peripheral forgetting / decay | 不是真实神经遗忘 |
| 回忆 | memory index / recall count / 时间线 | 不是海马体检索 |
| 关系 | trust / closeness / conflict / repair | 行为代理，不是依恋理论本体 |
| 社会世界 | destination / social map | 不是心理理论或社会认知本体 |
| 自我模型 | self_model / narrative | 不是意识或自由意志 |
| 表达倾向 | 解释层 → 简短表达意图 | 不生成回复、不改写历史 |

### 不模仿的部分

```text
不模仿神经元放电
不模仿内分泌/激素
不模仿真实记忆痕迹（engram）
不声称意识、自由意志或临床情绪
不声称真实因果
```

一句话：BioCore 模仿的是生物情绪系统的**功能结构**与**可观察行为**，用可计算状态近似，不声称生物本体。

## 功能

- **一次性人设编译（可选）**：开启 `persona_compile` 且配置 Provider 时，首次运行读取 AstrBot 当前人设并编译为数值档案缓存，之后不再每轮解析人设文本；该 LLM 功能默认关闭，关闭时保留已有/默认档案。
- **拟态状态**：维护 valence / arousal / dominance / social / trust / stress / energy 等连续状态，并带衰减、稳态和基础动力学。状态更新是确定性的，LLM 不直接写状态。
- **解释层**：唯一负责把数值状态转成 LLM 可读的紧凑表达意图（`[BC]`）；回复中的模型输出由解释层校验后再交给生物层。
- **记忆与事件**：本地记忆索引、记忆巩固、重要事件归档、事件总结和事件时间线；支持旧数据兼容与回退。
- **关系与用户模型**：按会话/用户维护信任、亲近、冲突、修复等关系轨迹，以及自我模型摘要。
- **Dashboard**：在 AstrBot WebUI 内查看情绪概览、表达意图、人格自我、活动会话/记忆、设置和备份。
- **可选 LLM 总结**：事件总结、记忆总结等 LLM 辅助功能可以关闭；关系洞察、日记、幽默提示等提案型功能默认关闭。关闭 LLM 总结后，插件仍可依靠本地确定性逻辑运行。

## 安装

### 从 AstrBot 插件市场安装

上架后，在 AstrBot WebUI → 插件市场搜索 **BioCore 拟态生物情绪核心** 并安装。

### 从 GitHub 安装

在 AstrBot WebUI → 插件管理使用仓库地址：

```text
https://github.com/Johnhmzm/astrbot_plugin_biocore
```

也可以手动克隆到 AstrBot 插件目录，安装后重载 AstrBot：

```text
AstrBot/data/plugins/astrbot_plugin_biocore_standalone/
```

### 依赖与要求

- AstrBot：`>=4.16,<5`
- 平台：`aiocqhttp`
- Python 依赖：无第三方包；使用 AstrBot 提供的模块和 Python 标准库
- 可选：本地图片识别需要自行配置 `llama-server` 和 VLM 模型路径（见下方配置），留空则不启用

## 更新

市场安装或 GitHub 仓库安装时，优先使用 AstrBot 的更新按钮；ZIP 上传安装的更新按钮可能不可用，需要先切换/绑定市场源或覆盖安装一次。

更新不会删除持久化数据；请勿勾选“删除数据”。版本号以 `metadata.yaml` 为准，详细更新记录见 [CHANGELOG.md](CHANGELOG.md) 与 [UPDATE.md](UPDATE.md)。

## 配置

在 **AstrBot WebUI → 插件 → BioCore → 配置** 中调整。常用项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `safety_enabled` | `false` | 私人使用默认关闭；公开/多用户部署前建议设为 `true`，启用敏感信息掩码、跨会话限制、低置信记忆拒答等保护 |
| `we_memory_enabled` | `false` | 共同记忆/多用户共享记忆默认关闭；仅在明确需要时开启 |
| `llm_only_reply_summary` | `true` | 严格模式：LLM 仅用于回复与总结，其他提案型功能保持关闭 |
| `event_summary` / `memory_summary` | 开启 | 事件/记忆总结；可在 LLM 功能开关中关闭 |
| 其他 LLM 功能 | 默认关闭 | `relationship_impression`、`insight`、`diary`、`humor_hint` 等默认不启用 |
| `bc_prompt_mode` | `telemetry` | 默认注入紧凑状态 telemetry；切换到 `semantic` 可查看自然语言 brief |
| `summary_max_chars` | `0` | 默认不设硬上限；异常/安全场景可设置上限 |
| `image_llama_server` / `image_llama_model` / `image_llama_mmproj` | 空 | 可选本地 VLM 路径；仅本地图片识别模式，使用通用多模态 API 时留空 |
| `image_service_port` | `0` | 本地 llama-server 端口；0=不启用，仅本地 VLM 模式，不是通用 API 地址 |

Dashboard 设置页还提供 BioCore 专用 API 覆盖、记忆压缩、可视化图层、版本检查和备份。

## 使用

插件没有需要记忆的聊天命令；它通过 AstrBot 的 LLM 请求/响应钩子自动工作：

1. 安装并重载插件；
2. 正常与机器人对话；
3. 插件在请求中附加紧凑的生物状态表达意图，在回复后解析模型返回的标签并更新本地状态；
4. 打开 **AstrBot WebUI → 插件 → BioCore → Dashboard** 查看状态、记忆和关系。

它不会接管消息、不会自行回复、不会替换人设，也不会接管其他插件的记忆。

## 数据与隐私

持久化数据保存在 AstrBot 的插件数据目录，不在插件代码目录，也不会提交到仓库：

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

- 默认不包含任何外部遥测、统计上报或下载行为。
- 只有在启用对应 LLM 功能且配置了 Provider 时，相关摘要/洞察请求才会发送给该 Provider；发送内容限于该功能所需的事件/记忆摘要，不包含完整聊天上下文。
- `safety_enabled: false` 是私人使用默认值；公开部署前建议开启，并按需配置敏感信息掩码和跨会话记忆限制。
- 更新/卸载前请备份上述数据目录。

## 平台与兼容性

- AstrBot `>=4.16,<5`
- 平台适配器：`aiocqhttp`
- 使用 AstrBot 的 `on_llm_request` / `on_llm_response` 钩子；不接管消息事件、不生成回复、不替换人设、不接管其他插件记忆
- 不依赖数据库迁移脚本；旧数据按字段缺失回退

## FAQ

**Q：为什么机器人回复看起来没有变化？**  
A：BioCore 是隐藏状态/表达意图层，不会强制生成或改写回复；它的影响取决于当前 LLM、提示和上下文，属于渐进式表达倾向，不是直接命令。

**Q：必须配置 LLM 吗？**  
A：核心状态、记忆和 Dashboard 可以在本地运行；事件/记忆总结等 LLM 辅助功能可以关闭。

**Q：会读取或上传我的聊天记录吗？**  
A：默认不上传。只有在启用具体 LLM 功能并配置 Provider 时，相关摘要请求才会发给该 Provider；本地数据保存在 `plugin_data`。

**Q：这是临床情绪诊断或真实意识吗？**  
A：不是。它是一套面向角色表达的可调数值状态模型，不提供医疗/心理诊断，也不声称真实意识或现实因果。

**Q：支持哪些平台？**  
A：当前 metadata 声明 `aiocqhttp`；AstrBot 版本要求 `>=4.16,<5`。

**Q：更新会丢数据吗？**  
A：正常市场/仓库更新不会；持久化数据在 `plugin_data`。升级前仍建议备份。

## 更新日志

- 当前版本：`1.2.97`（以 `metadata.yaml` 为准）
- 详细历史见 [CHANGELOG.md](CHANGELOG.md) 与 [UPDATE.md](UPDATE.md)
- 版本更新由 AstrBot 插件市场/GitHub 源同步；市场记录版本必须与 `metadata.yaml` 一致

## 许可证

本项目采用 **GNU Affero General Public License v3.0（AGPL-3.0）**。

Copyright (C) 2026 Johnhmzm

你可以使用、修改、分发本项目，但分发或通过网络提供服务时必须按 AGPL-3.0 公开完整对应源码，衍生作品也必须继续使用 AGPL-3.0。完整条款见 [LICENSE](LICENSE) 或 <https://www.gnu.org/licenses/agpl-3.0.html>。

本项目不提供任何担保；使用前请自行评估。

## 相关链接

- GitHub：<https://github.com/Johnhmzm/astrbot_plugin_biocore>
- Gitee 镜像：<https://gitee.com/johnhim/astrbot_plugin_biocore>
- 问题反馈：<https://github.com/Johnhmzm/astrbot_plugin_biocore/issues>