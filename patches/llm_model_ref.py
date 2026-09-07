"""模型引用：平台/模型名，避免不同后端同名冲突。



格式：{backend}/{api_model_id}

api_model_id 可以自带厂商前缀（如百炼 ZHIPU/GLM-5.3-Flash），因此不能简单按第一个 / 切开。

只把「已注册后端名」当作平台前缀。

"""



from __future__ import annotations



from typing import Iterable, Optional, Tuple



_BACKEND_NAMES: Tuple[str, ...] = ()





def set_backend_names(names: Iterable[str]) -> None:

    """由 LLMManager 在加载配置时写入，供 split 识别平台前缀。"""

    global _BACKEND_NAMES

    cleaned = {str(n).strip() for n in names if n and str(n).strip()}

    _BACKEND_NAMES = tuple(sorted(cleaned, key=len, reverse=True))





def backend_names() -> Tuple[str, ...]:

    return _BACKEND_NAMES





def split_model_ref(

    ref: str, backends: Optional[Iterable[str]] = None

) -> Tuple[Optional[str], str]:

    """拆成 (backend|None, api_model_id)。



    仅当首段（或多段前缀）匹配已知后端名时才拆开。

    否则整串视为上游 API 模型名（例如 ZHIPU/GLM-5.3-Flash）。

    """

    text = (ref or "").strip()

    if not text:

        return None, ""

    if "/" not in text:

        return None, text



    names = [str(n).strip() for n in (backends if backends is not None else _BACKEND_NAMES) if n and str(n).strip()]

    names = sorted(set(names), key=len, reverse=True)

    for b in names:

        prefix = f"{b}/"

        if text.startswith(prefix):

            rest = text[len(prefix) :]

            if rest:

                return b, rest



    # 无已知后端前缀：整串都是 API model id

    return None, text





def api_model_name(ref: str, backends: Optional[Iterable[str]] = None) -> str:

    """发给上游 API 的模型名（可含厂商/）。"""

    _, model = split_model_ref(ref, backends)

    return model





def qualify_model(backend: str, model: str) -> str:

    """后端名 + API 模型名 → 内部引用。保留 model 内的厂商前缀。"""

    backend = (backend or "").strip()

    model = (model or "").strip()

    if not model:

        return backend

    if not backend:

        return model

    if model.startswith(backend + "/"):

        return model

    # model 若已是「其它已知后端/…」则取其 api 段再挂到目标后端

    other, rest = split_model_ref(model)

    if other and rest:

        return f"{backend}/{rest}"

    return f"{backend}/{model}"





def normalize_model_ref(ref: str, default_backend: Optional[str] = None) -> str:

    """已有平台前缀则规范化；否则挂上 default_backend。"""

    backend, model = split_model_ref(ref)

    if backend:

        return qualify_model(backend, model)

    if default_backend and model:

        return qualify_model(default_backend, model)

    return model


