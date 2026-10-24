# AstrBot BioCore Plugin

Standalone biological emotion layer for AstrBot. It reads the current AstrBot persona once, compiles it into a numeric profile, and injects a compact expression intent instead of raw state.

- Plugin name: `astrbot_plugin_biocore`
- Version: `1.2.5`
- Author: `Johnhmzm`
- Primary update source: https://gitee.com/johnhim/astrbot_plugin_biocore
- GitHub market mirror: https://github.com/Johnhmzm/astrbot_plugin_biocore

## Install

Install from the GitHub/Gitee repository in AstrBot's plugin manager, or copy this directory into:

```text
AstrBot/data/plugins/astrbot_plugin_biocore_standalone/
```

No third-party Python dependency is required; `requirements.txt` is intentionally empty of packages. AstrBot-provided modules and the Python standard library are used.

## What it does

- On first run, compiles the active AstrBot persona into a numeric profile and stores it.
- On every LLM request, injects a compact `[BioCore] ...` intent into the system prompt.
- On LLM response, feeds the reply back into state, memory, goals and event archives.
- Dashboard pages: overview, expression intent, persona/self, active sessions and settings.

The biological layer never writes prompt text directly; only the interpretation layer renders LLM input / parses output.

## Data

Persistent data lives in AstrBot's plugin-data directory, not inside the plugin:

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

Do not copy this data into the plugin package or commit it to the repository.

## Configuration

Behavior parameters are configured from **AstrBot plugin management -> BioCore config**. The dashboard settings page only keeps BioCore-specific API overrides, memory compression, visualization, version checks and backup.

## WebUI

![BioCore dashboard](preview.png)

After installation: AstrBot WebUI -> Plugins -> BioCore -> Dashboard.

## Compatibility

Only uses AstrBot's `filter.on_llm_request` / `filter.on_llm_response` hooks. It does not take over message events, generate replies, replace the persona, or take over other plugins' memory.
