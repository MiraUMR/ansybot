from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from kirara_ai.config.global_config import LLMBackendConfig


class LLMBackendInfo(LLMBackendConfig):
    """LLM后端信息"""



class LLMBackendList(BaseModel):
    """LLM后端列表"""

    backends: List[LLMBackendInfo]


class LLMBackendResponse(BaseModel):
    """LLM后端响应"""

    error: Optional[str] = None
    data: Optional[LLMBackendInfo] = None


class LLMBackendListResponse(BaseModel):
    """LLM后端列表响应"""

    error: Optional[str] = None
    data: Optional[LLMBackendList] = None


class LLMBackendCreateRequest(LLMBackendConfig):
    """创建LLM后端请求"""



class LLMBackendUpdateRequest(LLMBackendConfig):
    """更新LLM后端请求"""



class LLMAdapterTypes(BaseModel):
    """可用的LLM适配器类型列表"""

    types: List[str]


class LLMAdapterConfigSchema(BaseModel):
    """LLM适配器配置模式"""

    error: Optional[str] = None
    configSchema: Optional[Dict[str, Any]] = None


class LLMPriorityInfo(BaseModel):
    """模型调用优先级"""

    text: List[str] = Field(default_factory=list)
    vision: List[str] = Field(default_factory=list)
    available: List[str] = Field(default_factory=list, description="当前已注册可选模型")
    added: List[str] = Field(
        default_factory=list,
        description="本次自动从模型管理并入优先级的模型",
    )


class LLMPriorityResponse(BaseModel):
    error: Optional[str] = None
    data: Optional[LLMPriorityInfo] = None


class LLMPriorityUpdateRequest(BaseModel):
    text: List[str] = Field(default_factory=list)
    vision: List[str] = Field(default_factory=list)
