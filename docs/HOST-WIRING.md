# 宿主链路：从对话到生物层，以及今晚查出的四处断点

## 链路

```
DSH 会话
  → lib/modules/core-turn.js     构造 turn_start payload（含 body_state）
  → lib/py-bridge.js             JSON 动作 → 常驻 worker
  → python/biocore_runtime/service.py   dispatch
  → pipeline.turn_start          身体推进、状态渲染、记忆注入
  → pipeline.turn_end            模型评分 → 学习（Q 表 / 蘑菇体）
```

## 四处断点（2026-11-10 修复）

| # | 断点 | 现象 |
| --- | --- | --- |
| 1 | 插件未写进 profile `bundles` | 全站 `/api/biocore/*` 404，且无任何报错 |
| 2 | 部署目录是旧版本 + 手工贴文件 | npm 上是 0.5.12，跑的是 0.5.5 |
| 3 | `lib/py/bridge.py` 只在存储目录找 `core_config.json` | memory_inject 恒失败：no summarizer block |
| 4 | `pipeline._load_runtime_config` 同一个毛病 | 事件层拿不到 summarizer |

配置实际在 `<data>/core_config.json`，而记忆在 `<data>/memory`——两处都要向上找一层。

## 三条纪律

1. **推送后用 SHA 比对**，不要看 `git push` 输出：被拒绝时同样会打印 `main -> main`
2. **发版前跑 `scripts/check_release_hygiene.ps1`**：密钥、截图、数据目录、超大文件
3. **装完插件必须重启实例**，模块在进程内存里，热替换文件不生效

## 验证顺序（由内向外）

```
pytest tests                     701 项，先绿
node host_e2e.mjs                走 node→bridge→worker，验 turn_start/memoryInject/turn_end
GET /api/biocore/stats           验插件已注册
真实对话                          验状态行与记忆是否进入提示词
```
