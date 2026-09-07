"""Generate data/config.yaml from the legacy NoneBot QQ credentials."""

from __future__ import annotations

import ast
import json
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "data" / "config.yaml"
EXAMPLE_PATH = ROOT / "data" / "config.yaml.example"
LEGACY_ENV = ROOT / "fubuki" / "ansy" / ".env.prod"
WEBHOOK_URL = "/im/webhook/qqbot/qqbot01/"


def parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values

    pending_key: str | None = None
    pending_lines: list[str] = []
    quote: str | None = None

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\r")
        if pending_key is not None:
            pending_lines.append(line)
            if quote and line.rstrip().endswith(quote):
                values[pending_key] = "\n".join(pending_lines).strip().strip(quote)
                pending_key = None
                pending_lines = []
                quote = None
            continue

        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue

        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if value[:1] in {"'", '"'} and (len(value) == 1 or not value.endswith(value[0])):
            pending_key = key
            quote = value[0]
            pending_lines = [value]
            continue
        values[key] = value.strip("'\"")
    return values


def load_legacy_bot() -> dict[str, str]:
    env = parse_dotenv(LEGACY_ENV)
    raw_bots = env.get("QQ_BOTS", "").strip()
    bots: list[dict] = []
    if raw_bots:
        try:
            bots = json.loads(raw_bots)
        except json.JSONDecodeError:
            bots = ast.literal_eval(raw_bots)

    bot = bots[0] if bots else {}
    sandbox_raw = env.get("QQ_IS_SANDBOX", "true").strip().lower()
    return {
        "app_id": str(bot.get("id") or "YOUR_QQ_APP_ID"),
        "token": str(bot.get("token") or "YOUR_QQ_TOKEN"),
        "app_secret": str(bot.get("secret") or "YOUR_QQ_APP_SECRET"),
        "sandbox": sandbox_raw in {"1", "true", "yes"},
    }


def render_config(legacy: dict[str, str | bool]) -> str:
    sandbox = "true" if legacy["sandbox"] else "false"
    secret_key = secrets.token_hex(32)
    return f"""# 由 scripts/bootstrap_config.py 根据旧 NoneBot 配置生成。
# 请勿将本文件提交到 Git。大模型 API Key 请在 WebUI 中填写。

ims:
  - name: qq_official_bot
    enable: true
    adapter: qqbot
    config:
      app_id: "{legacy["app_id"]}"
      app_secret: "{legacy["app_secret"]}"
      token: "{legacy["token"]}"
      sandbox: {sandbox}
      webhook_url: {WEBHOOK_URL}
  - name: qq_user_bot
    enable: true
    adapter: onebot
    config:
      websocket_url: /im/websocket/onebot/qquser01/ws
      access_token: "{secrets.token_urlsafe(24)}"
      heartbeat_interval: 15

plugins:
  enable:
    - im_onebot_adapters

web:
  host: "0.0.0.0"
  port: 8080
  secret_key: "{secret_key}"
  password_file: ./data/web/password.hash

llms:
  api_backends:
    - name: deepseek-official
      adapter: deepseek
      enable: false
      config:
        api_key: ""
        api_base: "https://api.deepseek.com/v1"
      models:
        - deepseek-chat

defaults:
  llm_model: deepseek-chat

memory:
  persistence:
    type: file
    file:
      storage_dir: ./data/memory
  max_entries: 100
  default_scope: member

system:
  timezone: Asia/Shanghai

update:
  pypi_registry: https://pypi.org/simple
  npm_registry: https://registry.npmjs.org
"""


def main() -> int:
    force = "--force" in sys.argv
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)

    if CONFIG_PATH.exists() and not force:
        print(f"已存在 {CONFIG_PATH}，跳过生成。如需覆盖请使用 --force。")
        return 0

    legacy = load_legacy_bot()
    CONFIG_PATH.write_text(render_config(legacy), encoding="utf-8")
    print(f"已写入 {CONFIG_PATH}")
    print(f"QQ AppID: {legacy['app_id']}")
    print(f"沙盒模式: {legacy['sandbox']}")
    print(f"Webhook 路径: {WEBHOOK_URL}")
    if not EXAMPLE_PATH.exists():
        print(f"提示：可参考 {EXAMPLE_PATH}")
    print("下一步：在 WebUI 填写大模型 API Key，并到 QQ 开放平台配置 HTTPS 回调地址。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
