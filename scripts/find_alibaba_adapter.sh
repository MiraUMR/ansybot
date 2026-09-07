#!/bin/bash
docker exec kirara-qq-bot python -c "import llm_preset_adapters.alibabacloud_adapter as a; print(a.__file__)"
