from pathlib import Path
import yaml
from kirara_ai.config.global_config import GlobalConfig, LLMPriorityConfig
from kirara_ai.workflow.implementations.blocks.llm.chat import (
    _resolve_model_candidates,
    _load_llm_pools,
)

assert hasattr(LLMPriorityConfig, "model_fields") or hasattr(LLMPriorityConfig, "__fields__")
cfg = GlobalConfig(**yaml.safe_load(Path("data/config.yaml").read_text(encoding="utf-8")))
pools = _load_llm_pools()
print("priority.text", list(getattr(cfg.llms.priority, "text", [])))
print("priority.vision", list(getattr(cfg.llms.priority, "vision", [])))
print("from_pools_text", _resolve_model_candidates(config=cfg, pools=pools, preferred=None, vision=False, enable_failover=True))
print("from_pools_vision", _resolve_model_candidates(config=cfg, pools=pools, preferred=None, vision=True, enable_failover=True))
# empty pools -> use config priority
empty = {"text": [], "vision": [], "max_failover": 8}
print("from_config_text", _resolve_model_candidates(config=cfg, pools=empty, preferred=None, vision=False, enable_failover=True))
print("ok")
