---
name: biocore-dev
description: >-
  BioCore AstrBot plugin development entry point. Use for ANY BioCore work:
  biological/emotion layer changes, interpretation layer (render/parse), memory
  and event archive, dashboard pages, packaging/deploying, or questions about the
  model spec and paper map. Enforces the boundary: biological layer never writes
  prompts; only the interpretation layer may render LLM input or parse LLM output.
---

# BioCore 开发入口

先用这个 skill 定边界，再读长文档，避免每次重新解释。

## 三条铁律

1. 生物层只存状态、记忆、事件、用户、自我模型；不拼 prompt。
2. 解释层是唯一能构造 LLM 输入、解析 LLM 输出的地方。
3. LLM 不能直接改生物层；必须经过解释层校验。

## 当前结构

```text
astrbot_plugin_biocore_standalone/
  main.py               AstrBot 接线 + 现有实现（过渡期）
  pages/dashboard/      概览 / 意图 / 人格 / 会话 / 设置
  data/plugin_data/...  持久化数据，不在包内
docs/
  BIOCORE-MODEL-SPEC-v1.md    模型规格
  BIOCORE-PAPER-MAP-v1.md     论文落点
scripts/
  build_biocore.ps1           干净构建 + 可选部署/重启
  eval_biocore.py             状态不变量与场景评估
```

## 构建 / 部署

```powershell
cd <插件根目录>
& scripts\build_biocore.ps1
& scripts\build_biocore.ps1 -Deploy
& scripts\build_biocore.ps1 -Deploy -Restart
```

构建产物：

```text
dist/astrbot_plugin_biocore_standalone.zip
```

## 数据位置

```text
AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/
  persona_profile.json
  states/
  memory/
  image_cache.json
  archives/events.jsonl
  archives/insights.jsonl
  users/
  self_model.json
```

包内绝不能含：

```text
data/
memory/
states/
api_config.json
settings.json
image_cache.json
__pycache__
```

## 改代码前先看

- 状态/方程/schema：`docs/BIOCORE-MODEL-SPEC-v1.md`
- 论文依据：`docs/BIOCORE-PAPER-MAP-v1.md`
- 评估：`scripts/eval_biocore.py`

## 常用检查

```text
py_compile main.py
node --check pages/dashboard/app.js
node --check pages/dashboard/orb.js
python scripts/eval_biocore.py
```

## 禁止

```text
往 main.py 继续堆 prompt 拼接
让 BioCore.context() 直接生成多段 [BioCore ...]
让 on_llm_response 直接 apply raw dict
把 data/ 打进插件包
```