from pathlib import Path
import yaml
from kirara_ai.config.global_config import GlobalConfig
from kirara_ai.workflow.implementations.blocks.llm.chat import (
    _resolve_model_candidates,
    _load_llm_pools,
    _default_model_id,
)

cfg = GlobalConfig(**yaml.safe_load(Path("data/config.yaml").read_text(encoding="utf-8")))
pools = _load_llm_pools()
print("default", _default_model_id(cfg))
print("text", _resolve_model_candidates(config=cfg, pools=pools, preferred=None, vision=False, enable_failover=True))
print("vision", _resolve_model_candidates(config=cfg, pools=pools, preferred=None, vision=True, enable_failover=True))
print("ok")
