# 故事模式说明（V1.5 主持人驱动）

群内 `@官方机器人（主持人）` 开场 → Web 表单推进 → 内部 LLM 演绎 → 主持人发群；结束后写入长期设定（奇幻标 dream）。

---

## 一句话流程

`@官方机器人 开始故事 [场景]` → 收到链接 → 发起人网页填写「角色 + 引导」→ 群内出现旁白 + RP 回复 → `@官方机器人 结束` 或网页点结束。

**Anon 日常出站不变**：爱音仍走 NapCat `qq_user_bot` / QQ `3845655536`。主持人只占用官方号做控制与故事调度发言。

---

## 怎么用

### 开始

1. 群聊中 `@官方机器人 开始故事`，可带场景词（如 `逛庙会` / `异世界冒险`）。
2. 主持人回复带 HMAC 鉴权的网页链接。
3. 仅链接中的发起人 QQ 可打开表单（错误 uid/token → 403）。

### 推进

- 网页选择本轮 `soyo` / `anon`，填写行动引导并提交。
- 后端组装极简 Story Prompt（仅 identity + `*_story.md` + SCENE/PREVIOUS/ACTION），直调 LLM。
- 主持人把「旁白模板 + 角色回复」发到群；页面向下刷新即可。

### 结束

- 群内：发起人 `@官方机器人 结束|end|stop`
- 或网页「结束故事」
- 记忆写入各方世界状态；`scene_type=fantasy`（命中异世界/奇幻等关键词）→ `source=story_dream` + `dream_` 键，**不进入日常事实注入**。

---

## 内部结构

| 组件 | 路径 |
|---|---|
| Host 状态机 | `plugins/group_world_state/host_manager.py` |
| SQLite | `data/db/kirara.db` ← `migrations/add_story_db.sql` |
| Web | `/api/story/form|submit|end` |
| Prompt | `prompt_assembler.py` + `data/persona/{bot}/modules/{bot}_story.md` |
| 工作流 | `data/workflows/chat/host.yaml` |
| 配置 | `data/persona/story_settings.yaml`、`STORY_HMAC_SECRET` |

群内存在 ACTIVE host session 时，旧版「@素世/@爱音 + 开始故事」会被压制，避免双轨。

---

## 旧 V1（已降级）

仍保留 `story.py` YAML 路径代码，但新流程不再写入 `_story/{gid}.yaml`。请优先使用主持人 + 网页。
