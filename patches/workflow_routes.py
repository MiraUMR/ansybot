import os
from typing import List

from quart import Blueprint, g, jsonify, request

from kirara_ai.workflow.core.block.registry import BlockRegistry
from kirara_ai.workflow.core.workflow import WorkflowRegistry
from kirara_ai.workflow.core.workflow.builder import WorkflowBuilder

from ...auth.middleware import require_auth
from .models import BlockInstance, Wire, WorkflowDefinition, WorkflowInfo, WorkflowList, WorkflowResponse

workflow_bp = Blueprint("workflow", __name__)

OFFICIAL_IM = "qq_official_bot"
USER_IM = "qq_user_bot"
SOYO_IM = "qq_soyo"

# chat:soyo 只走素世号；其它 chat 工作流保持官方+爱音双发
ANON_DUAL_PREFIXES = ("chat:anon", "chat:normal", "system:world_state")


def _workflow_full_id(builder: WorkflowBuilder) -> str:
    group = getattr(builder, "group_id", None) or ""
    wid = getattr(builder, "workflow_id", None) or getattr(builder, "id", None) or ""
    name = getattr(builder, "name", "") or ""
    full = f"{group}:{wid}" if group and wid else str(wid or name)
    return full


def ensure_dual_im_send(
    builder: WorkflowBuilder,
    block_registry: BlockRegistry,
    workflow_key: str = "",
) -> None:
    """按工作流补全发送适配器，避免 WebUI 保存后丢掉 NapCat 发送块。"""
    send_class = block_registry.get("internal:send_message")
    converter_class = block_registry.get("internal:chat_response_converter")
    if not send_class or not converter_class:
        return

    converters = [node for node in builder.nodes if node.spec.block_class is converter_class]
    if not converters:
        return

    sends = [node for node in builder.nodes if node.spec.block_class is send_class]
    if not sends:
        return

    key = (workflow_key or _workflow_full_id(builder) or "").lower()
    if "soyo" in key:
        wanted_ims = [SOYO_IM]
        add_specs = [("SendSoyoBot", SOYO_IM, {"x": 2140, "y": 140})]
    else:
        wanted_ims = [OFFICIAL_IM, USER_IM]
        add_specs = [
            ("SendOfficialBot", OFFICIAL_IM, {"x": 2140, "y": 60}),
            ("SendUserBot", USER_IM, {"x": 2140, "y": 220}),
        ]

    by_im = {node.spec.kwargs.get("im_name"): node for node in sends}
    prev_current = builder.current
    builder.current = None

    def add_send(name: str, im_name: str, position: dict) -> None:
        unique = name
        suffix = 1
        while unique in builder.nodes_by_name:
            suffix += 1
            unique = f"{name}_{suffix}"
        builder.chain(send_class, name=unique, im_name=im_name)
        builder.update_position(unique, position)
        by_im[im_name] = builder.nodes_by_name[unique]
        builder.current = None

    for name, im_name, position in add_specs:
        if im_name not in by_im:
            add_send(name, im_name, position)

    builder.current = prev_current

    existing = set(builder.wire_specs)
    for converter in converters:
        for im_name in wanted_ims:
            node = by_im.get(im_name)
            if not node:
                continue
            wire = (converter.name, "msg", node.name, "msg")
            if wire not in existing:
                builder.force_connect(converter.name, node.name, "msg", "msg")
                existing.add(wire)


def builder_to_definition(
    builder: WorkflowBuilder,
    block_registry: BlockRegistry,
    group_id: str,
    workflow_id: str,
) -> WorkflowDefinition:
    blocks: List[BlockInstance] = []
    for node in builder.nodes:
        blocks.append(
            BlockInstance(
                type_name=block_registry.get_block_type_name(node.spec.block_class),
                name=node.name,
                config=node.spec.kwargs,
                position=node.position or {"x": 0, "y": 0},
            )
        )

    wires: List[Wire] = []
    for source_name, source_output, target_name, target_input in builder.wire_specs:
        wires.append(
            Wire(
                source_block=source_name,
                source_output=source_output,
                target_block=target_name,
                target_input=target_input,
            )
        )

    return WorkflowDefinition(
        group_id=group_id,
        workflow_id=workflow_id,
        name=builder.name,
        description=builder.description,
        blocks=blocks,
        wires=wires,
        metadata=getattr(builder, "metadata", None),
    )


def apply_definition_to_builder(
    builder: WorkflowBuilder,
    workflow_def: WorkflowDefinition,
    block_registry: BlockRegistry,
) -> None:
    builder.description = workflow_def.description
    for block_def in workflow_def.blocks:
        block_class = block_registry.get(block_def.type_name)
        if not block_class:
            raise ValueError(f"Block type {block_def.type_name} not found")

        if not builder.head:
            builder.use(block_class, name=block_def.name, **block_def.config)
        else:
            builder.chain(block_class, name=block_def.name, **block_def.config)

        builder.update_position(block_def.name, block_def.position)

    builder.wire_specs = []
    for wire in workflow_def.wires:
        builder.force_connect(
            wire.source_block,
            wire.target_block,
            wire.source_output,
            wire.target_input,
        )
    ensure_dual_im_send(
        builder,
        block_registry,
        f"{workflow_def.group_id}:{workflow_def.workflow_id}",
    )


@workflow_bp.route("", methods=["GET"])
@require_auth
async def list_workflows():
    """获取所有工作流列表"""
    registry: WorkflowRegistry = g.container.resolve(WorkflowRegistry)

    workflows = []
    for workflow_id, builder in registry._workflows.items():
        # 从 workflow_id 解析 group_id
        group_id, wf_id = workflow_id.split(":", 1)

        workflows.append(
            WorkflowInfo(
                group_id=group_id,
                workflow_id=wf_id,
                name=builder.name,
                description=builder.description,
                block_count=len(builder.nodes_by_name),
                metadata=getattr(builder, "metadata", None),
            )
        )
    workflows.sort(key=lambda x: f"{x.group_id}:{x.workflow_id}")
    return WorkflowList(workflows=workflows).model_dump()


@workflow_bp.route("/<group_id>/<workflow_id>", methods=["GET"])
@require_auth
async def get_workflow(group_id: str, workflow_id: str):
    """获取特定工作流的详细信息"""
    registry: WorkflowRegistry = g.container.resolve(WorkflowRegistry)
    block_registry: BlockRegistry = g.container.resolve(BlockRegistry)
    full_id = f"{group_id}:{workflow_id}"
    builder = registry.get(full_id)
    if not builder:
        return jsonify({"error": "Workflow not found"}), 404

    assert isinstance(builder, WorkflowBuilder)
    workflow_def = builder_to_definition(builder, block_registry, group_id, workflow_id)
    return WorkflowResponse(workflow=workflow_def).model_dump()


@workflow_bp.route("/<group_id>/<workflow_id>", methods=["POST"])
@require_auth
async def create_workflow(group_id: str, workflow_id: str):
    """创建新的工作流"""
    data = await request.get_json()
    workflow_def = WorkflowDefinition(**data)

    registry: WorkflowRegistry = g.container.resolve(WorkflowRegistry)
    block_registry: BlockRegistry = g.container.resolve(BlockRegistry)

    # 检查工作流是否已存在
    full_id = f"{group_id}:{workflow_id}"
    if registry.get(full_id):
        return jsonify({"error": "Workflow already exists"}), 400

    # 创建工作流构建器
    try:
        builder = WorkflowBuilder(workflow_def.name)
        apply_definition_to_builder(builder, workflow_def, block_registry)

        file_path = registry.get_workflow_path(group_id, workflow_id)
        builder.save_to_yaml(file_path, g.container)
        registry.register(group_id, workflow_id, builder)

        saved = builder_to_definition(builder, block_registry, group_id, workflow_id)
        return saved.model_dump()
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@workflow_bp.route("/<group_id>/<workflow_id>", methods=["PUT"])
@require_auth
async def update_workflow(group_id: str, workflow_id: str):
    """更新现有工作流"""
    data = await request.get_json()
    workflow_def = WorkflowDefinition(**data)

    registry: WorkflowRegistry = g.container.resolve(WorkflowRegistry)
    block_registry: BlockRegistry = g.container.resolve(BlockRegistry)

    # 检查工作流是否存在
    full_id = f"{group_id}:{workflow_id}"
    if not registry.get(full_id):
        return jsonify({"error": "Workflow not found"}), 404

    # 更新工作流
    try:
        builder = WorkflowBuilder(workflow_def.name)
        apply_definition_to_builder(builder, workflow_def, block_registry)

        file_path = registry.get_workflow_path(group_id, workflow_id)
        if os.path.exists(file_path):
            os.remove(file_path)
        new_file_path = registry.get_workflow_path(
            data["group_id"], data["workflow_id"]
        )
        builder.save_to_yaml(new_file_path, g.container)

        registry.unregister(group_id, workflow_id)
        registry.register(data["group_id"], data["workflow_id"], builder)

        saved = builder_to_definition(
            builder, block_registry, data["group_id"], data["workflow_id"]
        )
        return saved.model_dump()
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@workflow_bp.route("/<group_id>/<workflow_id>", methods=["DELETE"])
@require_auth
async def delete_workflow(group_id: str, workflow_id: str):
    """删除工作流"""
    registry: WorkflowRegistry = g.container.resolve(WorkflowRegistry)

    # 检查工作流是否存在
    full_id = f"{group_id}:{workflow_id}"
    if not registry.get(full_id):
        return jsonify({"error": "Workflow not found"}), 404

    try:
        # 从注册表中移除
        registry._workflows.pop(full_id, None)

        # 删除文件
        file_path = registry.get_workflow_path(group_id, workflow_id)
        if os.path.exists(file_path):
            os.remove(file_path)

        return jsonify({"message": "Workflow deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 400
