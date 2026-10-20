"""官方 MCP SDK 适配层；业务状态和文件操作留在 service 中。"""

from __future__ import annotations

import json
from functools import wraps
from inspect import signature
from pathlib import Path
from types import ModuleType
from typing import get_type_hints

from mcp.server import MCPServer
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from ..log import logger
from .schemas import McpError, McpModel
from .service import ArxmlMcpService
from .xml import McpServiceError


def _tool(service: ArxmlMcpService, method):
    @wraps(method)
    def execute(*args, **kwargs):
        try:
            with service.lock:
                result = method(*args, **kwargs)
                payload = result.model_dump(mode='json') if isinstance(result, McpModel) else {'result': result}
                return CallToolResult(
                    content=[TextContent(type='text', text=json.dumps(payload, ensure_ascii=False, indent=2))],
                    structured_content=payload,
                )
        except McpServiceError as exc:
            error = exc.error
        except (ValueError, TypeError, OSError) as exc:
            error = McpError(code='INVALID_REQUEST', message=str(exc), suggestion='检查文件、XML、参数和当前工程状态后重试；本次失败编辑未发布。')
        except Exception:
            logger.exception('MCP 工具 {} 执行失败', method.__name__)
            error = McpError(code='INTERNAL_ERROR', message='工具执行失败。', suggestion='查看服务 stderr 日志并报告问题；保存失败时先检查恢复清单。')
        return CallToolResult(is_error=True, content=[TextContent(type='text', text=error.model_dump_json(indent=2))])

    # 保留可读的类型化协议；适配函数的全局空间没有 service 中的前向引用。
    hints = get_type_hints(method, include_extras=True)
    original = signature(method)
    execute.__annotations__ = hints
    execute.__signature__ = original.replace(
        parameters=[parameter.replace(annotation=hints.get(name, parameter.annotation)) for name, parameter in original.parameters.items()],
        return_annotation=hints['return'],
    )
    return execute


def create_server(workspace: Path, *, binding: ModuleType) -> MCPServer:
    service = ArxmlMcpService(workspace, binding=binding)
    server = MCPServer(
        'k3q_arxml',
        instructions='describe_type 查询类型摘要，get_type_source 查询当前版本源码，均无需工程会话。处理启动目录内的 ARXML 时先 open_project 加载文件集合；查询目标与引用；编辑使用最新 revision；预览修改后显式调用 save_changes。引用检查仅覆盖已加载文件。',
    )
    readonly = {'get_skill_path', 'project_info', 'find_nodes', 'get_node', 'find_references', 'describe_type', 'get_type_source', 'validate_project', 'preview_changes'}
    for name in (
        'get_skill_path',
        'open_project',
        'project_info',
        'find_nodes',
        'get_node',
        'find_references',
        'describe_type',
        'get_type_source',
        'rename_node',
        'patch_xml',
        'validate_project',
        'preview_changes',
        'save_changes',
        'close_project',
    ):
        server.add_tool(
            _tool(service, getattr(service, name)),
            name=name,
            annotations=ToolAnnotations(read_only_hint=name in readonly, destructive_hint=name == 'save_changes', open_world_hint=False),
            structured_output=True,
        )
    return server
