import asyncio
from typing import Optional, cast

import aiohttp
import requests
from pydantic import BaseModel, ConfigDict

from kirara_ai.llm.adapter import AutoDetectModelsProtocol, LLMBackendAdapter
from kirara_ai.llm.format.message import (LLMChatContentPartType, LLMChatImageContent, LLMChatMessage,
                                          LLMChatTextContent, LLMToolCallContent, LLMToolResultContent)
from kirara_ai.llm.format.request import LLMChatRequest
from kirara_ai.llm.format.response import Function, LLMChatResponse, Message, ToolCall, Usage
from kirara_ai.llm.model_ref import api_model_name
from kirara_ai.logger import get_logger
from kirara_ai.media import MediaManager
from kirara_ai.tracing import trace_llm_chat

logger = get_logger("OpenAIAdapter")

async def convert_parts_factory(messages: LLMChatMessage, media_manager: MediaManager) -> list[dict]:
    if messages.role == "tool":
        # typing.cast 指定类型，避免mypy报错
        results = cast(list[LLMToolResultContent], messages.content)
        # 保证 content 为一个字符串
        return [{"role": "tool", "tool_call_id": result.id, "content": str(result.content)} for result in results]
    else:
        parts = []
        elements = cast(list[LLMChatContentPartType], messages.content)
        for element in elements:
            if isinstance(element, LLMChatTextContent):
                parts.append(element.model_dump(mode="json"))
            elif isinstance(element, LLMChatImageContent):
                media = media_manager.get_media(element.media_id)
                if media is None:
                    raise ValueError(f"Media {element.media_id} not found")
                parts.append({
                    "type": "image_url",
                    "image_url": {
                        "url": await media.get_base64_url()
                    }
                })
            elif isinstance(element, LLMToolCallContent):
                # 忽略tool_call_content，openai api不需要。
                # 保留这个判断分支，防止openai api接口出现变动。
                continue
        return [{"role": messages.role, "content": parts}]

def convert_llm_chat_message_to_openai_message(messages: list[LLMChatMessage], media_manager: MediaManager, loop: asyncio.AbstractEventLoop) -> list[dict]:
    results = loop.run_until_complete(
        asyncio.gather(*[convert_parts_factory(msg, media_manager) for msg in messages])
    )
    # 扁平化结果, 展开所有列表
    return [item for sublist in results for item in sublist]

def resolve_tool_calls_from_response(tool_calls: Optional[list[dict]]):
    if tool_calls is None:
        return None
    else:
        return [ToolCall(
            id=call["id"],
            type=call["type"],
            function=Function(
                name=call["function"]["name"],
                # openai api 的 arguments 值是一个长得像dict的字符串, 交给 pydantic 验证器转换
                arguments=call["function"].get("arguments", None)
            )
        ) for call in tool_calls]

class OpenAIConfig(BaseModel):
    api_key: str
    api_base: str = "https://api.openai.com/v1"
    model_config = ConfigDict(frozen=True)


class OpenAIAdapter(LLMBackendAdapter, AutoDetectModelsProtocol):
    media_manager: MediaManager
    
    def __init__(self, config: OpenAIConfig):
        self.config = config
    @trace_llm_chat
    def chat(self, req: LLMChatRequest) -> LLMChatResponse:
        api_url = f"{self.config.api_base}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        data = {
            "messages": convert_llm_chat_message_to_openai_message(req.messages, self.media_manager, loop),
            "model": api_model_name(req.model or ""),
            "frequency_penalty": req.frequency_penalty,
            "max_tokens": req.max_tokens,
            "presence_penalty": req.presence_penalty,
            "response_format": req.response_format,
            "stop": req.stop,
            "stream": req.stream,
            "stream_options": req.stream_options,
            "temperature": req.temperature,
            "top_p": req.top_p,
            # tool pydantic 模型按照 openai api 格式进行的建立。所以这里直接dump
            "tools": [tool.model_dump() for tool in req.tools] if req.tools else None,
            "tool_choice": "auto" if req.tools else None,
            "logprobs": req.logprobs,
            "top_logprobs": req.top_logprobs,
        }

        # Remove None fields
        data = {k: v for k, v in data.items() if v is not None}

        # DashScope / 智谱 thinking models may return empty or slow content unless thinking is off.
        # Direct@ 尖峰：即使仍开启思维链，也把预算压到 200，避免规则冲突下 reasoning 爆炸。
        api_base = self.config.api_base or ""
        model_l = (req.model or "").lower()
        if (
            "dashscope.aliyuncs.com" in api_base
            or "阿里" in (req.model or "")
            or "deepseek" in model_l
        ):
            data["enable_thinking"] = False
            data["thinking_budget"] = 200
        if "bigmodel.cn" in api_base:
            data["thinking"] = {"type": "disabled"}
        
        logger.debug(f"Request: {data}")

        # 套餐卡住/上游挂起时尽快失败，避免多请求堆积后乱序串回复
        try:
            response = requests.post(api_url, json=data, headers=headers, timeout=45)
        except requests.Timeout as e:
            raise RuntimeError(f"LLM timeout model={req.model}: {e}") from e
        except requests.RequestException as e:
            raise RuntimeError(f"LLM request failed model={req.model}: {e}") from e
        try:
            response.raise_for_status()
            response_data: dict = response.json()
        except Exception as e:
            body = (response.text or "")[:800]
            logger.error(f"Response status={response.status_code}: {body}")
            # 带上状态码与 body，供上层识别额度/限流并切换模型
            raise RuntimeError(
                f"LLM HTTP {response.status_code} model={req.model}: {body}"
            ) from e
        logger.debug(f"Response: {response_data}")

        choices = response_data.get("choices", [{}])
        first_choice = choices[0] if choices else {}
        message: dict = first_choice.get("message", {})
        
        # 检测tool_calls字段是否存在和是否不为None. tool_call时content字段无有效信息，暂不记录
        content: list[LLMChatContentPartType] = []
        if tool_calls := message.get("tool_calls", None):
            content = [LLMToolCallContent(
                id=call["id"],
                name=call["function"]["name"],
                parameters=call["function"].get("parameters", None)
            ) for call in tool_calls]
        else:
            content = [LLMChatTextContent(text=message.get("content", ""))]

        usage_data = response_data.get("usage", {}) or {}
        prompt_tokens = int(usage_data.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage_data.get("completion_tokens", 0) or 0)
        total_tokens = int(usage_data.get("total_tokens", 0) or 0)
        details = usage_data.get("prompt_tokens_details") or {}
        cached_tokens = 0
        if isinstance(details, dict):
            cached_tokens = int(details.get("cached_tokens", 0) or 0)
        usage_bits = [
            f"prompt 消耗了 {prompt_tokens} token",
            f"completion 消耗了 {completion_tokens} token",
            f"合计 {total_tokens} token",
        ]
        if cached_tokens:
            usage_bits.append(f"cached 消耗了 {cached_tokens} token")
        # debug：避免与 ChatCompletionBlock 的 token 拆分日志看起来像「双倍计费」
        logger.debug(f"token usage model={req.model} " + "，".join(usage_bits))

        return LLMChatResponse(
            model=req.model,
            usage=Usage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
            message=Message(
                content=content,
                role=message.get("role", "assistant"),
                # tool_calls=[
                #     ToolCall(
                #         model = "openai",
                #         id=tool_call["id"], 
                #         type=tool_call["type"],
                #         function=Function(name = tool_call["function"]["name"], arguments=tool_call["function"].get("arguments", None))
                #     ) for tool_call in message.get("tool_calls")
                # ] if message.get("tool_calls", None) else None,
                tool_calls = resolve_tool_calls_from_response(response_data.get("tool_calls", None)),
                finish_reason=first_choice.get("finish_reason", ""),
            ),
        )

    async def auto_detect_models(self) -> list[str]:
        api_url = f"{self.config.api_base}/models"
        async with aiohttp.ClientSession(trust_env=True) as session:
            async with session.get(
                api_url, headers={"Authorization": f"Bearer {self.config.api_key}"}
            ) as response:
                response.raise_for_status()
                response_data = await response.json()
                return [model["id"] for model in response_data["data"]]