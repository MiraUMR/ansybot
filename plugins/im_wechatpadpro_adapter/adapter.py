"""
WeChatPadPro 个人微信适配器
基于 WeChatPadPro (iPad 协议) 接入个人微信账号。

接入方式：
  - 接收消息：WeChatPadPro 通过 Webhook 推送到 Kirara
  - 发送消息：Kirara 调用 WeChatPadPro REST API
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import random
from typing import Optional

import aiohttp
from fastapi import Request, Response
from pydantic import BaseModel, Field

from kirara_ai.im.adapter import IMAdapter
from kirara_ai.im.message import IMMessage, TextMessage
from kirara_ai.im.sender import ChatSender, ChatType
from kirara_ai.logger import get_logger
from kirara_ai.web.app import WebServer
from kirara_ai.workflow.core.dispatch.dispatcher import WorkflowDispatcher


logger = get_logger("WeChatPadPro-Adapter")
MAX_REPLY_CHARS = 100


class WeChatPadProConfig(BaseModel):
    """WeChatPadPro 适配器配置"""

    base_url: str = Field(
        default="http://wechatpadpro:8080",
        title="WeChatPadPro 服务地址",
        description="WeChatPadPro HTTP API 的根地址，如 http://wechatpadpro:8080",
    )
    admin_key: str = Field(
        default="",
        title="Admin Key",
        description="WeChatPadPro 的管理员密钥（ADMIN_KEY），用于调用发送消息等 API",
    )
    token_key: str = Field(
        default="",
        title="Token Key",
        description="WeChatPadPro 的普通用户密钥（TOKEN_KEY），Webhook 模式可留空",
    )
    webhook_secret: str = Field(
        default="",
        title="Webhook 签名密钥",
        description="用于验证 WeChatPadPro 推送的 Webhook 签名，留空则不验证",
    )
    webhook_path: str = Field(
        default="/wechat-elderly/webhook",
        title="Webhook 接收路径",
        description="Kirara 接收 WeChatPadPro 推送消息的 URL 路径",
    )
    reply_delay_min_ms: int = Field(
        default=2000,
        title="最短回复延迟（毫秒）",
        description="模拟真人打字节奏，回复前随机延迟的最小值",
    )
    reply_delay_max_ms: int = Field(
        default=5000,
        title="最长回复延迟（毫秒）",
        description="模拟真人打字节奏，回复前随机延迟的最大值",
    )


class WxMsgData(BaseModel):
    """WeChatPadPro Webhook 消息数据（字段名兼容多种推送格式）"""

    msgId: Optional[str] = None
    fromUser: Optional[str] = None
    FromUserName: Optional[str] = None
    toUser: Optional[str] = None
    ToUserName: Optional[str] = None
    msgType: Optional[int] = None
    MsgType: Optional[int] = None
    content: Optional[str] = None
    Content: Optional[str] = None
    groupId: Optional[str] = None
    groupMemberWxid: Optional[str] = None
    nickName: Optional[str] = None
    PushContent: Optional[str] = None
    createTime: Optional[int] = None


class WxWebhookPayload(BaseModel):
    event_type: Optional[str] = None
    TypeName: Optional[str] = None
    timestamp: Optional[int] = None
    signature: Optional[str] = None
    data: Optional[WxMsgData] = None
    Data: Optional[WxMsgData] = None


class WeChatPadProAdapter(IMAdapter):
    """WeChatPadPro 个人微信适配器（iPad 协议）"""

    dispatcher: WorkflowDispatcher
    web_server: WebServer

    def __init__(self, config: WeChatPadProConfig):
        self.config = config
        self._session: Optional[aiohttp.ClientSession] = None
        self._bot_wxid: Optional[str] = None
        self.is_running = False

    async def start(self) -> None:
        logger.info("WeChatPadPro 适配器启动中...")
        headers = {"Content-Type": "application/json"}
        if self.config.admin_key:
            headers["X-Access-Token"] = self.config.admin_key
        self._session = aiohttp.ClientSession(headers=headers)
        await self._fetch_bot_wxid()
        self._register_webhook()
        self.is_running = True
        logger.info("WeChatPadPro 适配器已就绪，Webhook 路径：%s", self.config.webhook_path)

    async def stop(self) -> None:
        self.is_running = False
        if self._session and not self._session.closed:
            await self._session.close()
        logger.info("WeChatPadPro 适配器已停止")

    def _register_webhook(self) -> None:
        app = self.web_server.app
        adapter_ref = self

        @app.post(self.config.webhook_path)
        async def receive_wechat_message(request: Request) -> Response:
            try:
                body = await request.body()
                if adapter_ref.config.webhook_secret:
                    sig_header = request.headers.get("X-Signature", "") or request.headers.get(
                        "X-Hub-Signature-256", ""
                    )
                    expected = hmac.new(
                        adapter_ref.config.webhook_secret.encode(),
                        body,
                        hashlib.sha256,
                    ).hexdigest()
                    if sig_header.startswith("sha256="):
                        sig_header = sig_header[7:]
                    if sig_header and not hmac.compare_digest(sig_header, expected):
                        logger.warning("Webhook 签名验证失败，已拒绝")
                        return Response(status_code=403)

                payload = WxWebhookPayload.model_validate_json(body)
                asyncio.create_task(adapter_ref._handle_incoming(payload))
                return Response(status_code=200)
            except Exception as exc:
                logger.error("Webhook 处理异常：%s", exc)
                return Response(status_code=500)

    async def _handle_incoming(self, payload: WxWebhookPayload) -> None:
        event = (payload.event_type or payload.TypeName or "message").lower()
        if event not in ("message", "onmessage", "addmsg", ""):
            if "msg" not in event:
                return
        data = payload.data or payload.Data
        if not data:
            return

        msg_type = data.msgType if data.msgType is not None else data.MsgType
        if msg_type not in (None, 1):
            return

        from_user = data.fromUser or data.FromUserName or ""
        if self._bot_wxid and from_user == self._bot_wxid:
            return

        content = (data.content or data.Content or "").strip()
        if not content:
            return
        # 群聊常见格式：wxid:\n文本
        if ":\n" in content and (from_user.endswith("@chatroom") or bool(data.groupId)):
            sender_part, text_part = content.split(":\n", 1)
            content = text_part.strip()
            member_wxid = data.groupMemberWxid or sender_part
        else:
            member_wxid = data.groupMemberWxid or from_user

        is_group = bool(data.groupId) or from_user.endswith("@chatroom")
        display = data.nickName or member_wxid or "用户"
        if is_group:
            group_id = data.groupId or from_user
            sender = ChatSender.from_group_chat(
                user_id=member_wxid or "unknown",
                group_id=group_id,
                display_name=display,
            )
        else:
            sender = ChatSender.from_c2c_chat(
                user_id=from_user or member_wxid or "unknown",
                display_name=display,
            )

        msg = IMMessage(
            sender=sender,
            message_elements=[TextMessage(text=content)],
            raw_message=payload.model_dump(),
        )
        await self.dispatcher.dispatch(self, msg)

    async def send_message(self, message: IMMessage, recipient: ChatSender) -> None:
        text_parts = [
            el.text for el in (message.message_elements or []) if isinstance(el, TextMessage) and el.text
        ]
        content = "\n".join(text_parts).strip() or (getattr(message, "content", None) or "").strip()
        if not content:
            return
        content = _truncate_reply(content)

        if recipient.chat_type == ChatType.GROUP and recipient.group_id:
            to_user = recipient.group_id
        else:
            to_user = recipient.user_id
        if not to_user:
            logger.warning("发送消息缺少目标 wxid，已跳过")
            return

        min_ms = max(0, int(self.config.reply_delay_min_ms or 0))
        max_ms = max(min_ms, int(self.config.reply_delay_max_ms or min_ms))
        if max_ms > 0:
            await asyncio.sleep(random.randint(min_ms, max_ms) / 1000.0)

        await self._send_text(to_user, content)

    async def _send_text(self, to_user: str, content: str) -> None:
        if not self._session:
            logger.error("HTTP session 未初始化，无法发送消息")
            return
        url = f"{self.config.base_url.rstrip('/')}/api/v1/message/send"
        payload = {"toUserName": to_user, "content": content, "msgType": 1}
        try:
            async with self._session.post(url, json=payload) as resp:
                result = await resp.json(content_type=None)
                code = result.get("code")
                if code not in (0, 200, None) and result.get("Success") is not True:
                    logger.warning("发送消息失败，to=%s，响应：%s", to_user, result)
                else:
                    logger.debug("消息已发送，to=%s", to_user)
        except Exception as exc:
            logger.error("发送消息异常，to=%s：%s", to_user, exc)

    async def _fetch_bot_wxid(self) -> None:
        if not self._session:
            return
        try:
            url = f"{self.config.base_url.rstrip('/')}/api/v1/personal/GetProfile"
            async with self._session.get(url) as resp:
                result = await resp.json(content_type=None)
                data = result.get("data") or result.get("Data") or {}
                wxid = data.get("wxid") or data.get("UserName") or data.get("userName")
                if wxid:
                    self._bot_wxid = wxid
                    logger.info("Bot wxid：%s", wxid)
        except Exception as exc:
            logger.warning("获取 bot wxid 失败（忽略）：%s", exc)

    def convert_to_message(self, raw) -> IMMessage:
        if isinstance(raw, IMMessage):
            return raw
        return IMMessage(
            sender=ChatSender.from_c2c_chat(user_id="unknown", display_name="用户"),
            message_elements=[TextMessage(text=str(raw or ""))],
            raw_message=raw if isinstance(raw, dict) else {},
        )


def _truncate_reply(text: str) -> str:
    text = text.strip()
    if len(text) <= MAX_REPLY_CHARS:
        return text
    cut = text[:MAX_REPLY_CHARS]
    for mark in ("。", "！", "？", ".", "!", "?"):
        idx = cut.rfind(mark)
        if idx >= 20:
            return cut[: idx + 1]
    return cut
