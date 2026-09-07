#!/usr/bin/env python3
from pathlib import Path

p = Path("/opt/kirara-ai/data/workflows/chat/normal.yaml")
text = p.read_text(encoding="utf-8")

old_user = "text: '{user_name}对你说：{user_msg}'"
new_user = "text: '{user_name}在群{group_name}对你说：{user_msg}'"
if old_user in text:
    text = text.replace(old_user, new_user, 1)
    print("updated user_prompt")
elif "{group_name}对你说" in text or "在群{group_name}" in text:
    print("user_prompt already has group_name")
else:
    print("WARN: user_prompt pattern not found")

marker = "你现在在群「{group_name}」"
if marker in text:
    print("system prompt already has group context")
else:
    insert = (
        "# 当前群聊\\n"
        "你现在在群「{group_name}」（群号 {group_id}）。只根据这个群正在发生的对话和本群记忆回复，不要把另一个群的群友、话题或称呼带到这里。\\n\\n"
        "# 当前信息"
    )
    if "# 当前信息\\n现在时间" in text:
        text = text.replace("# 当前信息\\n现在时间", insert + "\\n现在时间", 1)
        print("updated system prompt (escaped)")
    elif "# 当前信息\n现在时间" in text:
        text = text.replace(
            "# 当前信息\n现在时间",
            "# 当前群聊\n你现在在群「{group_name}」（群号 {group_id}）。只根据这个群正在发生的对话和本群记忆回复，不要把另一个群的群友、话题或称呼带到这里。\n\n# 当前信息\n现在时间",
            1,
        )
        print("updated system prompt (literal)")
    else:
        print("WARN: current-info marker not found")

p.write_text(text, encoding="utf-8")
print("done")
