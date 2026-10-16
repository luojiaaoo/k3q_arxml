"""MCP 协议模型和会话状态，不依赖可选的 MCP SDK。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from ..k3q_arxml import IOArxml


class McpModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class McpPatchOperation(McpModel):
    """XPath 相对于选定节点，ar: 前缀表示当前 AUTOSAR namespace。"""

    op: Literal['set_text', 'set_attribute', 'remove_attribute', 'append', 'insert_before', 'insert_after', 'replace', 'delete']
    xpath: str = Field(min_length=1, max_length=4096)
    value: str | None = None
    attribute: str | None = None
    xml: str | None = Field(default=None, max_length=2_000_000)


class McpError(McpModel):
    code: str
    message: str
    suggestion: str


class McpDiagnostic(McpModel):
    code: str
    severity: Literal['error', 'warning']
    message: str
    file_id: str
    ref: str | None = None
    xpath: str | None = None
    line: int | None = None


class McpProjectResult(McpModel):
    project_id: str
    revision: int


class McpFileInfo(McpModel):
    file_id: str
    filepath: str
    object_count: int
    dirty: bool


class McpProjectInfo(McpProjectResult):
    schema_version: str
    files: list[McpFileInfo]
    diagnostics: list[McpDiagnostic] = Field(default_factory=list)
    reference_scope: str = '仅覆盖本会话中已加载的文件。'


class McpNodeInfo(McpModel):
    file_id: str
    ref: str
    xml_tag: str
    short_name: str | None
    revision: int


class McpNodePage(McpProjectResult):
    items: list[McpNodeInfo]
    total: int
    next_offset: int | None


class McpNodeDetail(McpProjectResult):
    node: McpNodeInfo
    xml: str | None = None
    total_chars: int = 0
    next_offset: int | None = None


class McpReferenceInfo(McpModel):
    file_id: str
    owner_ref: str
    target_ref: str
    xml_tag: str
    xpath: str
    dest: str | None = None


class McpReferencePage(McpProjectResult):
    items: list[McpReferenceInfo]
    total: int
    next_offset: int | None
    reference_scope: str = '仅覆盖本会话中已加载的文件。'


class McpTypeField(McpModel):
    xml_name: str
    kind: Literal['element', 'attribute', 'text']
    python_field: str
    type_names: list[str]
    required: bool
    repeated: bool
    enum_values: list[str]


class McpTypeInfo(McpModel):
    xml_tag: str
    python_type: str
    fields: list[McpTypeField]
    alternative_types: list[str] = Field(default_factory=list)
    note: str = '信息来自当前 xsdata 绑定；元素顺序和其他约束以本地 XSD 校验为准。'


class McpEditResult(McpProjectResult):
    affected_files: list[str]
    new_ref: str | None = None
    updated_references: int = 0
    reference_scope: str = '仅覆盖本会话中已加载的文件。'


class McpValidationResult(McpProjectResult):
    valid: bool
    diagnostics: list[McpDiagnostic]


class McpDiffLine(McpModel):
    file_id: str
    text: str
    continuation: bool = False


class McpPreview(McpProjectResult):
    preview_token: str
    affected_files: list[str]
    lines: list[McpDiffLine]
    total_lines: int
    next_offset: int | None
    diagnostics: list[McpDiagnostic]


class McpSavedFile(McpModel):
    file_id: str
    filepath: str
    backup_path: str


class McpSaveResult(McpProjectResult):
    files: list[McpSavedFile]
    recovery_manifest: str | None = None


class McpCloseResult(McpModel):
    project_id: str
    closed: bool = True


@dataclass
class McpProjectState:
    """仅保存在服务进程内，不作为 MCP 输出。"""

    project_id: str
    io: IOArxml
    paths: dict[str, Path]
    baseline: dict[str, bytes]
    revision: int = 0
    preview_token: str | None = None
    load_diagnostics: list[McpDiagnostic] = field(default_factory=list)
