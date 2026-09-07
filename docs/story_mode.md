# 故事模式说明

引导式多 Bot 故事：按**群**持久化状态，由发起人用 `@Bot + 引导句` 推进，结束后把记忆点写入双方长期设定。

---

## 一句话流程

群友 `@Bot（可双开）+ 启动词/场景` → 建会话 → 仅发起人 `@指定Bot + 引导` 推进 → 回复末尾抽 `<memory_point>` → 发起人 `@Bot end|结束|stop` → 写入世界状态并清会话。

---

## 怎么用（群友视角）

### 开始

1. 必须在**群聊**里。
2. 至少 `@` 一个已知角色（素世 / 爱音，可用 CQ:@ 或文本别名）。
3. 正文里带上启动词或场景子串（见下表）。
4. 任意群友都可开；开场者 QQ = 本场 `initiator`。

**启动词**（`start_keywords`）：

- `开始故事` / `故事开始` / `进入故事`

**场景子串**（`start_scenes`，命中其一即可）：

- `逛庙会` / `去逛庙会`
- `夏日祭典` / `夏日祭`
- `一起去看live` / `去看live` / `看live`

**示例**：

```text
@素世 @爱音 去逛庙会
@素世 开始故事
@爱音 夏日祭典
```

普通 `@素世 你喜欢吃什么` **不会**进故事，走日常对话。

### 推进

- **只有发起人**的引导有效；别人说话会被丢掉（`discard`）。
- 参与中的 Bot **自己说话**也会被丢掉，避免 Bot 互聊搅局。
- 每轮必须 `@` 本轮要发言的那个 Bot，再写引导句。
- 未 @ 到的 Bot 本轮不回。

**示例**：

```text
@素世 庙会入口好多人，你先说两句。
@爱音 你拉着 soyorin 去买苹果糖。
```

开场首发言人 = `@` 提及顺序里的第一个参与 Bot。

### 结束

剥掉 @ 后的正文（去标点）须**整句等于**下列之一（大小写不敏感）：

- `end` / `结束` / `stop`

注意：

- 「就这样 / 先这样 / 知道了」**不会**结束故事。
- **仅发起人**可结束；他人发结束词 → 丢弃。
- 实践上需 `@Bot 结束` 一类，才能进 `@` 工作流；纯发「结束」可能只走记忆 fallback。

结束后 Bot 输出确认句（故事已结束，关键情节已记录），会话文件删除。

---

## 内部怎么跑

### 入口与分流

没有独立的 story 分发规则。仍走原有 `chat:soyo` / `chat:anon`（@ 进站）。

`DialogueContext.execute` 最前调用 `_route_story_mode`：

| `action` | `message_mode` | 行为 |
|---|---|---|
| `start` / `turn` | `story` | 注入故事 prompt，正常生成 |
| `end` | `story_end` | `finalize_story` 后清会话，固定收束文案 |
| `discard` | `discard` | 输出 `[NO_REPLY]` |
| `none` | — | 不拦截，继续 peer / direct / env |

故事轮：`skip_chat_memory=true`、`extract_priority=skip`；近期聊天记忆对 `story` / `story_end` / `discard` 清空。

### 人设注入

`message_mode=story` 时互斥网关只注入：

- `base`（身份）
- `story` 模块（`soyo_story.md` / `anon_story.md`）

不并行注入 Companion / Trigger / Scene。  
`story_end` / `discard` 不叠加 `mode_phone`。

系统侧另有：

- `[SYSTEM: STORY MODE]` 轮次引导（引子、协同、接住上一轮、禁止日常收束、要求 memory_point）
- `[P0: STORY MODE LOCK ACTIVE]` 覆盖日常「接话/收束」惯性

### 会话存储

| 项 | 说明 |
|---|---|
| 路径 | `data/world_state/_story/{group_id}.yaml` |
| 主要字段 | `initiator_qq`、`group_id`、`story_prompt`、`participating_bots`、`turn_count`、`memory_points`、`active`、`current_speaker` |
| `story_prompt` | 去掉 @ 后，再剥掉 `start_keywords`（**不剥**场景子串） |

### 发言人解析

1. 本轮 `@` 到的、且在 `participating_bots` 里的第一个；
2. 否则沿用 `current_speaker`（仍参与时）；
3. 否则 `participating_bots[0]`。

本进程角色 ≠ 目标发言人 → `discard`。

### 记忆点与长期设定

**进行中**：模型在回复末尾写：

```text
<memory_point>……</memory_point>
```

系统剥离标签（用户看不见），去重写入 session；`turn_count` +1，更新 `current_speaker`。故事轮不做常规 LLM 长期抽取。

**结束时** `finalize_story`：

- `summary = "；".join(memory_points)`（空则「故事已结束（无额外记忆点）。」）
- 键名：`story_{YYYYMMDDHHMM}_{bots排序}`（截断 ≤40）
- 对每个参与角色写入其世界状态 `set_fact(..., source="story")`
- `active=false`，删除会话文件

---

## 配置

文件：`data/persona/story_triggers.yaml`

| 键 | 代码是否读取 | 用途 |
|---|---|---|
| `start_keywords` | 是 | 启动词子串 |
| `start_scenes` | 是 | 场景子串 |
| `end_tokens` | 是 | 结束整句匹配 |
| `start_patterns` | 否（文档示例） | 不参与匹配逻辑 |
| `end_commands` | 否（文档示例） | 不参与匹配逻辑 |
| `guide_prefix` | 否（文档示例） | 不参与匹配逻辑 |

改关键词后需重启 / 重建容器使进程重载（触发器有进程内缓存）。

---

## 关键代码路径

| 路径 | 作用 |
|---|---|
| `plugins/group_world_state/story.py` | 状态机、触发、Session、finalize |
| `plugins/group_world_state/blocks.py` | `_route_story_mode`、PersonaLayers、prompt |
| `plugins/group_world_state/parser.py` | `strip_memory_points` |
| `plugins/group_world_state/style_guard.py` | story 的 P0 |
| `data/persona/story_triggers.yaml` | 启停配置 |
| `data/persona/soyo/modules/soyo_story.md` | 素世故事人设 |
| `data/persona/anon/modules/anon_story.md` | 爱音故事人设 |
| `data/workflows/chat/soyo.yaml` / `anon.yaml` | 工作流接线 |
| `data/world_state/_story/` | 运行时会话 |
| `scripts/verify_narrative_guard.py` | 相关行为断言 |

---

## 常见注意

1. **双 Bot 开场**：两边工作流都可能进站，状态机决定谁真回；未点名的一方 `discard`。
2. **推进必须 @**：没有独立 story 规则，靠原有 `@` 进站；不 @ 可能进不了故事轮。
3. **日常收束词无效**：故事里禁止用「就这样 / 知道了」封场；结束只用 `end` / `结束` / `stop`。
4. **记忆靠标签**：忘记写 `<memory_point>` 则结束时 summary 可能只有默认空说明。
