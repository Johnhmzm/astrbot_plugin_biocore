import json
import interpretation

SAMPLES = [
    "今天有点累，但还好。",
    "晚安，明天见。",
    "先接住情绪，再谈事情；想聊聊吗？",
    "标签只出现一次，必须隐藏。我们继续。",
    "在的。<bc>{\"e\":\"joy\",\"i\":0.4}</bc>",
    "好的。\n```json\n{\"e\":\"sad\",\"i\":0.5}\n```\n必须隐藏。",
    "这件事我一直隐藏着没说。",
    "标签格式说明。不要解释。正常内容。",
    "嗯。<bc>not json</bc>",
    "不确定时用问句确认；你还好吗？",
]
for index, raw in enumerate(SAMPLES, 1):
    visible, update = interpretation.parse_response(raw)
    print(json.dumps({"n": index, "rewritten": visible.strip() != raw.strip(), "visible": visible, "update": bool(update)}, ensure_ascii=False))
