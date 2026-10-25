# BioCore 生物情绪核心

Standalone biological emotion layer for AstrBot. It reads the current AstrBot persona once, compiles it into a numeric profile, and injects a compact expression intent instead of raw state.

- Plugin name: `astrbot_plugin_biocore`
- Plugin ID: `Johnhmzm/astrbot_plugin_biocore`（`metadata.author/name`）
- Version: 以 `metadata.yaml` 为准（当前 `1.2.73`）
- Author: `Johnhmzm`
- Repository / market source (GitHub): https://github.com/Johnhmzm/astrbot_plugin_biocore
- Mirror (Gitee): https://gitee.com/johnhim/astrbot_plugin_biocore
- Logo: `logo.png`（256×256）

## Plugin market

This GitHub repository is the source repository for the AstrBot plugin market record. The market JSON itself lives in AstrBot's registry (`AstrBotDevs/AstrBot_Plugins_Collection`), **not** inside this plugin repository — do not add a market JSON file here.

Checked against the [AstrBot plugin market spec](https://docs.astrbot.app/dev/plugin-market/) and [publish guide](https://docs.astrbot.app/dev/star/plugin-publish.html):

- `plugin_id` = `metadata.author` + `/` + `metadata.name` = `Johnhmzm/astrbot_plugin_biocore`
- Required `metadata.yaml` fields present: `name`, `author`, `version`, `repo`, `desc`
- `repo` is a public HTTPS GitHub URL, default branch `main`, archive well under the 16 MB publish limit
- `display_name`, `short_desc`, `astrbot_version`, `support_platforms`, `tags`, `social_link` are optional market fields and are present
- `logo.png` is 256×256 (1:1); AstrBot reads the logo file from the plugin directory
- Persistent data lives under `data/plugin_data/`, never in this repository (see `Data` below)

If the plugin is not yet visible in the market, submit it via the AstrBot Cloud publish page:
https://cloud.astrbot.app/publish （requires an AstrBot Cloud account）. Adding files to this repository alone does not create or update the market record.

## Install

Install from the AstrBot plugin market (recommended), from the GitHub repository in AstrBot's plugin manager, or copy this directory into:

```text
AstrBot/data/plugins/astrbot_plugin_biocore/
```

No third-party Python dependency is required; `requirements.txt` is intentionally empty of packages. AstrBot-provided modules and the Python standard library are used.

## Updating

AstrBot's update button depends on how the installed copy was added:

| Install method | Direct update from market / plugin page |
|---|---|
| Market install | Yes |
| Repository install (GitHub URL, market source) | Yes, pulls from GitHub |
| Repository install (Gitee mirror) | Yes, but this is not the market source; bind to the GitHub market record for market updates |
| Upload / zip install (`install_method=upload`) | No; AstrBot disables updates for upload-installed plugins |

### If it was installed from a zip

Do a one-time source migration, then future updates are normal:

1. Keep `AstrBot/data/plugin_data/astrbot_plugin_biocore_standalone/`; do not delete it.
2. In AstrBot WebUI -> Plugins -> Installed, use **Change plugin source / bind market source** and select the market record `Johnhmzm/astrbot_plugin_biocore`.
3. If that action is unavailable, install/overwrite once from the market or from the repository URL `https://github.com/Johnhmzm/astrbot_plugin_biocore`.
4. Reload the plugin. The install source becomes market/repository, and the update button works afterwards.

Uninstalling is not required. If you do uninstall, leave **delete data** unchecked.


## What it does

- On first run, compiles the active AstrBot persona into a numeric profile and stores it.
- On every LLM request, attaches a compact `[BioCore] ...` intent to the current user turn as transient content (system prompt stays stable).
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

- AstrBot: `>=4.16,<5` (also declared as `astrbot_version` in `metadata.yaml`)
- Platform adapters: `aiocqhttp` (declared as `support_platforms`)
- Only uses AstrBot's `filter.on_llm_request` / `filter.on_llm_response` hooks. It does not take over message events, generate replies, replace the persona, or take over other plugins' memory.
