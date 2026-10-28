---
name: biocore-memory
description: Use the host-neutral BioCore memory engine from DSH/CLI (remember, recall, forget, checkup). No astrbot, no bio layer.
---

# BioCore Memory (DSH / CLI)

## When to use
- Persistent memory outside AstrBot (DSH sessions, scripts, local agents).
- Deterministic store inspection/repair.
- This is memory-only. Do **not** simulate a biological layer (emotion/affect/relationships); the agent only supplies **memory-relevant judgments**.

## Agent supplies memory judgments (not affect)
Before `remember`, estimate a small JSON and pass it as `--worth`:
```json
{"importance": 0.7, "self_relevance": 0.4, "mainline": 0.2, "self_defining": false}
```
- `importance` 0–1: is this worth keeping at all (0.2 trivia, 0.8 clearly important).
- `self_relevance` 0–1: about the user's identity/relationship, not just facts.
- `mainline` 0–1: relates to ongoing goals/promises.
- `self_defining`: milestone / identity-relevant event.
All optional; omit what you cannot judge.

## Four operations
1. **remember** — one text; optional tags/source/worth.
2. **recall** — query by text; returns ranked ids/snippets; <0.35 returns nothing, tier=expand/hint.
3. **forget / pin / unpin** — soft-delete by id, or protect from eviction.
4. **checkup** — read-only health; exit 1 when actions remain.

## CLI (PowerShell)
```powershell
cd C:\Users\Administrator\Desktop\deepseek\astrbot_plugin_biocore_standalone
$py = "C:\Users\Administrator\.astrbot_launcher\instances\4200c1fe-c355-4eed-bed3-30878989b5ad\venv\Scripts\python.exe"
$store = "C:\Users\Administrator\.dsh\memory_store"

& $py -m biocore_memory.adapters.dsh_cli --store $store remember "小夏周五去医院复查" --tags health,小夏 --worth '{"importance":0.75,"self_relevance":0.6}'
& $py -m biocore_memory.adapters.dsh_cli --store $store recall "医院复查" --limit 3
& $py -m biocore_memory.adapters.dsh_cli --store $store forget <id>
& $py -m biocore_memory.adapters.dsh_cli --store $store checkup
```

## Store / privacy
- Engine file: `<store>/memory.json`; atomic writes; `.corrupt.bak` on failure.
- No astrbot imports, no prompt writes, no LLM calls inside the engine, no network.
- Redact secrets before remember.
