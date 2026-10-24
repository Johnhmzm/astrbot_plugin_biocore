# AstrBot BioCore Plugin (standalone)

独立的一份生物情绪层：不依赖 Desktop/deepseek 主项目，不共享主项目状态。

## 安装

把整个目录复制到 AstrBot 的 data/plugins，然后重启 AstrBot：

data/plugins/astrbot_plugin_biocore_standalone/

插件名：astrbot_plugin_biocore

## 第一次运行

第一次 on_llm_request 时：

1. 读取当前会话的 AstrBot 人设
2. 用当前 provider 做一次 LLM 编译
3. 人设文本转成数值 profile
4. 写入插件自己的 data/persona_profile.json
5. 用这份 profile 初始化 BioCore

之后只读 profile，不再每轮解析人设。

如果 AstrBot 人设为空或 provider 不可用，会使用安全默认 profile。

## 每轮

on_llm_request：

用户文本 -> 本地事件 -> BioCore 状态
-> 追加 [BioCore] intent 到 system_prompt

on_llm_response：

回复文本 -> feedback -> 更新 trust/stress
-> 写 data/states/<session>.json

LLM 只看到：

[BioCore] emotion=sadness energy=low
stress=tense trust=0.42 intent=hold expression=normal

不暴露原始数值、波纹、神经元。

## 配置开关

enabled：总开关，默认 true
inject_intent：是否注入 [BioCore]，默认 true
proactive_reply：主动回复，默认 false（预留，BioCore 本身不主动发消息）
memory_dedup_embedding：记忆 embedding 排重，默认 false（预留给上层记忆插件）
first_run_persona_compile：首次人设编译，默认 true
max_intent_chars：注入文本上限，默认 180

## WebUI

![BioCore Dashboard](preview.png)


安装后打开 AstrBot WebUI → 插件 → BioCore → Dashboard。

页面显示：

当前情绪意图
压力 / 能量 / 信任 / 唤醒
情绪轨道球
人格基线
活动会话

页面只读，不修改人设或记忆。

## 兼容性

只使用：

filter.on_llm_request
filter.on_llm_response

不接管消息事件、不生成回复、不替换人设、不流式、不接管其他插件记忆。

## 数据目录

data/persona_profile.json
data/states/*.json

与主项目完全分开；分享插件时不需要带 data/。
