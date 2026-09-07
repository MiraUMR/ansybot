# QQ 聊天机器人（Kirara AI）

本仓库已从 NoneBot2（`fubuki/ansy`）切换为 [Kirara AI](https://kirara-docs.app.lss233.com/)。机器人同时接入：

- **QQ 开放平台官方机器人 + Webhook**：群内被 @ 或 `/chat` 时回复
- **NapCat（用户 QQ + OneBot）**：能收到全群消息，未 @ 时约 15% 概率插话

官方文档：

- [快速开始](https://kirara-docs.app.lss233.com/guide/getting-started.html)
- [连接聊天平台（QQ）](https://kirara-docs.app.lss233.com/guide/configuration/im.html)
- [连接大语言模型](https://kirara-docs.app.lss233.com/guide/configuration/llm.html)
- [更新 Kirara AI](https://kirara-docs.app.lss233.com/guide/configuration/update.html)

## 和旧机器人的差异

| | 旧：NoneBot2 `fubuki/ansy` | 新：Kirara AI |
| --- | --- | --- |
| 协议 | QQ 官方适配器，WebSocket | QQ 开放平台，Webhook |
| 能力 | 群管插件 + 关键词回复 | 大模型对话、工作流、记忆 |
| 配置 | `.env.prod` | WebUI + `data/config.yaml` |

旧工程仍保留在 `fubuki/ansy`，仅作备份，不再作为启动入口。群管 / 加群验证等 NoneBot 插件能力不会自动迁移，需要的话请在 Kirara 插件市场自行扩展。

## 环境要求

- Windows
- Python **3.12+**
- QQ 开放平台机器人（沙盒可用）
- 公网 HTTPS 地址（QQ 回调只允许端口 `80` / `443` / `8080` / `8443`，且通常要求 HTTPS）

## 启动

1. 双击 `初始化.cmd`  
   会创建虚拟环境、安装 `kirara-ai`，并从旧配置 `fubuki/ansy/.env.prod` 生成 `data/config.yaml`。
2. 双击 `启动.cmd`  
   看到 `WebUI 管理平台本地访问地址：http://127.0.0.1:8080` 即表示启动成功。
3. 浏览器打开管理后台：
   - 云服务器：<https://ansy.love/qqbot/>（独立前缀，不占用网站 `/`、`/api/`）
   - 本机调试：<http://127.0.0.1:8080>

更新版本：双击 `更新.cmd`（等价于 `pip install -U kirara-ai`，`data` 目录会保留）。

## 必须完成的配置

### 1. 大语言模型

在 WebUI：`模型管理 → 添加适配器`。

推荐先用 DeepSeek（也可改用任意 OpenAI 兼容接口）：

- Adapter：`deepseek` 或 `openai`
- Api Base：`https://api.deepseek.com/v1`
- Api Key：你的密钥
- 模型：`deepseek-chat`

保存后把该后端设为启用，并在「默认模型」中选中。

### 2. QQ 开放平台回调

初始化脚本会预填现有机器人凭证：

- AppID：见 `data/config.yaml`
- Sandbox：开启
- Webhook（填到 QQ 开放平台）：

```text
https://ansy.love/im/webhook/qqbot/qqbot01/
```

管理后台（与现有网站隔离）：

```text
https://ansy.love/qqbot/
```

旧机器人使用 **WebSocket**。Kirara 使用 **Webhook**。云上已通过 nginx 把 `/im/webhook/` 和 `/qqbot/` 反代到 Kirara，网站原来的 `/`、`/api/` 不变。

然后：

1. 勾选沙盒，保存 Kirara 中的 QQ 适配器。WebUI 应显示机器人头像和昵称。
2. 在开放平台「回调配置」填写上面的 HTTPS 地址。
3. 「添加事件」勾选单聊、群聊相关事件（文档要求约 11 项）。
4. 按平台入驻文档完成沙盒配置后即可对话。

监听地址已设为 `0.0.0.0:8080`。如果本机没有公网 IP，请用 Kirara 内置 frp、反向代理，或把服务部署到已备案的云服务器。

群聊默认规则：被 @ 或消息以 `/chat` 开头会必回。未 @ 插话按群分开：`1035893116` 明确提到 MyGO 人物时约 5%，其它闲聊约 1%；`1071033510` 约 15%。近期聊天和长期关系都按群隔离。私聊会直接回复。可用 `/help`、`/清空记忆`、`/长期记忆`。

### 3. NapCat 用户号（收全群消息）

官方机器人在群里只能收到 @。要让 bot 偶尔接未 @ 的话，需要再挂一个 **用户 QQ**（建议用小号，不要用常用号）。

云上扫码登录：

1. 打开 NapCat WebUI（token 见服务器 `/opt/kirara-ai/.env` 的 `WEBUI_TOKEN`）：

```text
http://38.22.235.136:6099/webui
```

2. 用要当 bot 的 QQ 扫码。登录成功后把该号拉进目标群。
3. Kirara 日志出现 `Bot <QQ> Connected` 即表示 OneBot 已接通。

未 @ 的插话会以 **这个用户号** 的身份发出，和官方机器人是两个号。`chat:normal` 工作流里有两个发送块：官方机器人（`qq_official_bot`）和 NapCat 用户号（`qq_user_bot`）。在 WebUI 里改提示词后保存即可，系统会自动补回用户号发送块，不要只留一个适配器。

扫码完成后如果 Kirara 仍未连上，在服务器执行：

```bash
python3 /opt/kirara-ai/scripts/sync_napcat_onebot.py /opt/kirara-ai/napcat/config
docker restart napcat-qq
```

### 4. 按群长期设定（关系会随剧情变）

内置「记忆」只是最近一段聊天，人设不会跟着改。长期设定是另一份按群保存的事实，例如 A 群已经告白、B 群还在暗恋。

对话后会根据这一轮内容自动写入本群长期设定（群友看不见抽取过程）。角色没接话时，只有出现告白、交往等关键词才会抽取，避免每条水贴都打一次模型。也可以自己改：

```text
/长期记忆
/长期记忆 设定 relationship 已经向素世告白，目前在交往
/长期记忆 删除 relationship
/长期记忆 清空
```

网页（先登录 WebUI）：侧边栏「长期设定」，或 <https://ansy.love/qqbot/world-state>  
文件：`data/world_state/<群号>.yaml`，可选配置见 `data/world_state/_config.example.yaml`。

`/清空记忆` 只清近期聊天，不会清长期设定。

## 目录

```text
初始化.cmd / 启动.cmd / 更新.cmd   Windows 入口（对齐官方部署包习惯）
requirements.txt                    pip 依赖
data/config.yaml.example            配置模板（不含密钥）
data/dispatch_rules/rules.yaml      消息调度规则
data/persona/                       人设拆分文本（核心 / 本群关系 / 补充设定 / 当场上下文）
scripts/bootstrap_config.py         从旧 NoneBot 配置生成 config.yaml
scripts/sync_napcat_onebot.py       扫码后把反向 WS 写入 NapCat 账号配置
docker-compose.yml                  Kirara + NapCat
plugins/group_world_state/          按群长期设定插件
napcat/                             NapCat 配置与 QQ 会话
fubuki/ansy/                        旧 NoneBot 工程（已停用）
```

## Docker

```bash
docker compose up -d
```

会同时启动 Kirara（`127.0.0.1:8080`）和 NapCat WebUI（`127.0.0.1:6099`）。镜像数据目录挂载到 `./data`，QQ 会话挂载到 `./napcat/QQ`。先完成本地初始化生成 `data/config.yaml`，再启动容器。
