"""独立于 MCP 协议的工程会话、查询和编辑服务。"""

from __future__ import annotations

import difflib
import re
from collections import Counter
from dataclasses import fields, is_dataclass
from enum import Enum
from functools import cached_property
from pathlib import Path
from threading import RLock
from typing import Annotated, Literal
from uuid import uuid4

from lxml import etree
from pydantic import Field
from xsdata.formats.dataclass.context import XmlContext

from .. import autosar
from ..arxml_file import ArxmlFile, ref2str, str2ref
from ..k3q_arxml import IOArxml
from ..schemas import PACKAGE_ROOT, SCHEMAS, ArxmlHeader, ArxmlNamedNode
from .persistence import check_recovery, checked_path, digest, save_files
from .schemas import (
    McpCloseResult,
    McpDiagnostic,
    McpDiffLine,
    McpEditResult,
    McpFileInfo,
    McpNodeDetail,
    McpNodeInfo,
    McpNodePage,
    McpPatchOperation,
    McpPreview,
    McpProjectInfo,
    McpProjectState,
    McpReferenceInfo,
    McpReferencePage,
    McpSavedFile,
    McpSaveResult,
    McpTypeField,
    McpTypeInfo,
    McpValidationResult,
)
from .xml import NS, NAMESPACE, apply_patch, clone_file, fail, parse_object, read_xml, replace_object, select_element, semantic_xml, walk_named

Offset = Annotated[int, Field(ge=0, description='分页起点，从 0 开始。')]
Limit = Annotated[int, Field(ge=1, le=200, description='每页数量，最多 200。')]
Revision = Annotated[int, Field(ge=0, description='最近查询得到的工程 revision；修改后需使用新值。')]


def _path(ref: str, *, root: bool = False) -> tuple[str, ...]:
    if root and ref == '/':
        return ()
    if not ref.startswith('/') or any(not item for item in ref.split('/')[1:]):
        fail('INVALID_REF', f'不是有效的 AUTOSAR 绝对路径：{ref}', '使用 /Package/Type；文件根仅在支持文档编辑的工具中使用 /。')
    return str2ref(ref)


def _tag(obj) -> str:
    return getattr(getattr(type(obj), 'Meta', None), 'name', type(obj).__name__)


def _xpath(element: etree._Element, owner: etree._Element) -> str:
    parts = []
    while element is not owner:
        parent = element.getparent()
        siblings = [child for child in parent if child.tag == element.tag]
        parts.append(f'ar:{etree.QName(element).localname}[{siblings.index(element) + 1}]')
        element = parent
    return './' + '/'.join(reversed(parts)) if parts else '.'


def _references(root: etree._Element, owner_ref: tuple[str, ...] = (), owner: etree._Element | None = None):
    name = root.find('ar:SHORT-NAME', NS)
    if name is not None:
        owner_ref = (*owner_ref, name.text or '')
        owner = root
    owner = root if owner is None else owner
    local = etree.QName(root).localname
    if local.endswith('REF') and not len(root) and (root.text or '').startswith('/'):
        yield root, owner_ref, owner
    for child in root:
        if isinstance(child.tag, str):
            yield from _references(child, owner_ref, owner)


class ArxmlMcpService:
    """每个 stdio 进程管理自己的会话，不对外暴露活动 XML 对象。"""

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        if not self.workspace.is_dir():
            fail('INVALID_WORKSPACE', '工作目录不存在。', '请用户检查服务启动目录。')
        self.projects: dict[str, McpProjectState] = {}
        self.lock = RLock()
        self.context = XmlContext()
        self._type_roles: dict[str, list[tuple[type, str]]] | None = None
        self._schema_path = SCHEMAS.get(autosar.SCHEMA_VERSION)
        if self._schema_path is None:
            fail('SCHEMA_NOT_FOUND', '找不到当前绑定对应的本地 XSD。', '请用户检查当前运行环境中的绑定与 XSD 文件是否完整。')

    @cached_property
    def schema(self) -> etree.XMLSchema:
        """首次加载工程时编译 XSD，后续校验复用；MCP 握手和获取手册无需编译。"""
        return etree.XMLSchema(etree.parse(str(self._schema_path), etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)))

    def get_skill_path(self) -> str:
        """获取本 MCP 使用手册（arxml-mcp Skill）的目录；无需参数或工程会话。

        操作 ARXML 前应优先阅读使用手册。如果尚未加载 arxml-mcp Skill，先调用本工具，
        再读取返回目录中的 SKILL.md，并按任务需要读取 references。
        建议将整个 arxml-mcp 目录复制安装到智能体的 skills 目录，便于后续自动发现和加载；无需重新创建技能。
        本工具仅返回目录路径，不读取或解析手册内容。
        """
        root = PACKAGE_ROOT / 'skills' / 'arxml-mcp'
        if not root.is_dir():
            root = PACKAGE_ROOT.parent / 'skills' / 'arxml-mcp'
        if not (root / 'SKILL.md').is_file():
            fail('SKILL_NOT_FOUND', '找不到内置 arxml-mcp Skill。', '检查安装包或源码仓库附带的 skills/arxml-mcp 目录是否完整。')
        return str(root)

    def _project(self, project_id: str) -> McpProjectState:
        if project_id not in self.projects:
            fail('PROJECT_NOT_FOUND', '工程会话不存在或已关闭。', '调用 open_project 创建新会话。')
        return self.projects[project_id]

    def _files(self, project: McpProjectState, overrides: dict[str, ArxmlFile] | None = None) -> dict[str, ArxmlFile]:
        return {file_id: (overrides or {}).get(file_id, project.io.files[path]) for file_id, path in project.paths.items()}

    def _node(self, project: McpProjectState, ref: str, file_id: str | None = None) -> tuple[str, ArxmlFile, ArxmlNamedNode | None]:
        path = _path(ref, root=True)
        if not path and not file_id:
            fail('FILE_ID_REQUIRED', '访问文件根 / 必须提供 file_id。', '从 project_info 获取文件标识。')
        if file_id and file_id not in project.paths:
            fail('FILE_NOT_FOUND', f'未知 file_id：{file_id}', '从 project_info 获取已加载的文件标识。')
        for current_id, file in self._files(project).items():
            if file_id and current_id != file_id:
                continue
            node = file.ref(path) if path else None
            if not path or node is not None:
                return current_id, file, node
        fail('NODE_NOT_FOUND', f'节点不存在：{ref}', '调用 find_nodes 查找当前节点路径。')

    def _summary(self, project: McpProjectState, file_id: str, node: ArxmlNamedNode | None) -> McpNodeInfo:
        return McpNodeInfo(
            file_id=file_id,
            ref=ref2str(node.ref) if node else '/',
            xml_tag=_tag(node.xml_obj) if node else 'AUTOSAR',
            short_name=node.short_name if node else None,
            revision=project.revision,
        )

    def _revision(self, project: McpProjectState, revision: int) -> None:
        if project.revision != revision:
            fail('STALE_REVISION', f'当前 revision={project.revision}，请求 revision={revision}。', '重新查询工程状态和目标节点，然后使用最新 revision。')
        check_recovery(self.workspace)

    def _diagnostics(self, files: dict[str, ArxmlFile], baseline: dict[str, bytes] | None = None) -> list[McpDiagnostic]:
        diagnostics = []
        objects: dict[tuple[str, ...], tuple[str, str]] = {}
        trees = {file_id: read_xml(file.render()) for file_id, file in files.items()}
        for file_id, root in trees.items():
            file = files[file_id]
            if file.header.file_schema_version != file.parse_schema_version:
                diagnostics.append(
                    McpDiagnostic(
                        code='SCHEMA_MISMATCH',
                        severity='warning',
                        message=f'文件声明版本 {file.header.file_schema_version} 与当前绑定 {file.parse_schema_version} 不一致；已使用当前绑定继续解析，兼容性以解析和 XSD 校验结果为准。',
                        file_id=file_id,
                        ref='/',
                    )
                )
            if not self.schema.validate(root):
                diagnostics.extend(McpDiagnostic(code='XSD_ERROR', severity='error', message=error.message, file_id=file_id, line=error.line) for error in self.schema.error_log)
            for ref, element in walk_named(root):
                if ref in objects:
                    diagnostics.append(
                        McpDiagnostic(code='DUPLICATE_PATH', severity='error', message=f'{ref2str(ref)} 与 {objects[ref][0]} 的节点重复。', file_id=file_id, ref=ref2str(ref))
                    )
                objects[ref] = file_id, etree.QName(element).localname

        # 既有未解析引用及类型问题保留警告；新增加的相同问题按数量检测。
        allowances: Counter = Counter()
        if baseline:
            baseline_trees = {key: read_xml(content) for key, content in baseline.items()}
            baseline_objects = {ref: etree.QName(element).localname for root in baseline_trees.values() for ref, element in walk_named(root)}
            for file_id, root in baseline_trees.items():
                for element, _, _ in _references(root):
                    target = str2ref(element.text)
                    dest = element.get('DEST')
                    if target not in baseline_objects:
                        allowances[('UNRESOLVED_REFERENCE', file_id, element.text, dest)] += 1
                    elif dest and dest != baseline_objects[target]:
                        allowances[('DEST_MISMATCH', file_id, element.text, dest)] += 1
        for file_id, root in trees.items():
            for element, owner_ref, owner in _references(root):
                target = str2ref(element.text)
                dest = element.get('DEST')
                code = 'UNRESOLVED_REFERENCE' if target not in objects else ('DEST_MISMATCH' if dest and dest != objects[target][1] else None)
                if code is None:
                    continue
                key = code, file_id, element.text, dest
                severity = 'warning' if baseline is None or allowances[key] > 0 else 'error'
                allowances[key] -= 1
                message = f'已加载文件中不存在引用目标 {element.text}。' if code == 'UNRESOLVED_REFERENCE' else f'DEST={dest} 与目标标签 {objects[target][1]} 不一致。'
                diagnostics.append(McpDiagnostic(code=code, severity=severity, message=message, file_id=file_id, ref=ref2str(owner_ref), xpath=_xpath(element, owner)))
        return diagnostics

    def _publish(self, project: McpProjectState, candidates: dict[str, ArxmlFile]) -> list[str]:
        diagnostics = self._diagnostics(self._files(project, candidates), project.baseline)
        errors = [item for item in diagnostics if item.severity == 'error' and (item.file_id in candidates or item.code != 'XSD_ERROR')]
        if errors:
            fail(
                'VALIDATION_FAILED',
                '\n'.join(f'{item.code} [{item.file_id}] {item.ref or item.line or ""}: {item.message}' for item in errors[:20]),
                '根据位置修正整批操作，再重新提交；当前会话未修改。',
            )
        changed = [file_id for file_id, file in candidates.items() if file.root != project.io.files[project.paths[file_id]].root]
        for file_id in changed:
            # 原文可能含有 0 / 0.0 等词法差异，使用同一绑定的序列化结果判断是否恢复原值。
            candidates[file_id]._dirty = candidates[file_id].render() != project.rendered_baseline[file_id]
            project.io.files[project.paths[file_id]] = candidates[file_id]
        if changed:
            project.revision += 1
            project.preview_token = None
        return changed

    def open_project(
        self,
        filepaths: Annotated[
            list[str], Field(min_length=1, max_length=1000, description='需要一起查询及同步引用的文件路径数组，例如 ["SWC.arxml"]；相对路径以 workspace 为基准。')
        ],
    ) -> McpProjectInfo:
        """加载明确指定的 ARXML 文件集合，不写盘；版本不匹配仅告警，继续尝试使用当前绑定解析。"""
        check_recovery(self.workspace)
        paths = {}
        baseline = {}
        rendered_baseline = {}
        io = IOArxml([])
        seen_refs = set()
        load_diagnostics = []
        for index, value in enumerate(filepaths):
            supplied = Path(value)
            path = checked_path(self.workspace, supplied if supplied.is_absolute() else self.workspace / supplied)
            if path in io.files:
                fail('DUPLICATE_FILE', f'重复文件：{path}', '每个实际文件只加载一次。')
            content = path.read_bytes()
            root = read_xml(content)
            namespace = etree.QName(root).namespace
            schema_location = root.get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation')
            if root.tag != f'{{{NAMESPACE}}}AUTOSAR' or not schema_location:
                fail('SCHEMA_MISMATCH', '缺少 AUTOSAR 根节点、命名空间或 schemaLocation。', '检查文件头部的 AUTOSAR schema 声明。')
            header = ArxmlHeader(xml_namespace=namespace, xml_schema_location=schema_location)
            for ref, _ in walk_named(root):
                if ref in seen_refs:
                    fail('DUPLICATE_PATH', f'对象路径重复：{ref2str(ref)}', '拆分文件集合或修正重复的节点路径。')
                seen_refs.add(ref)
            file_id = f'f{index + 1}'
            if not self.schema.validate(root):
                load_diagnostics.extend(
                    McpDiagnostic(code='XSD_ERROR', severity='error', message=error.message, file_id=file_id, line=error.line) for error in self.schema.error_log
                )
            obj = parse_object(root, autosar.Autosar)
            comments = []
            previous = root.getprevious()
            while previous is not None:
                if isinstance(previous, etree._Comment):
                    comments.append(etree.tostring(previous, encoding='unicode', with_tail=False))
                previous = previous.getprevious()
            indent = re.search(rb'\n([ \t]+)<', content)
            file = ArxmlFile().parse_autosar(
                path, obj, header.xml_namespace, header.xml_schema_location, indent.group(1).decode() if indent else '    ', '\n'.join(reversed(comments))
            )
            io.files[path] = file
            paths[file_id] = path
            baseline[file_id] = content
            rendered_baseline[file_id] = file.render()
        project = McpProjectState(uuid4().hex, io, paths, baseline, rendered_baseline, load_diagnostics=load_diagnostics)
        project.load_diagnostics.extend(item for item in self._diagnostics(self._files(project)) if item.code != 'XSD_ERROR')
        self.projects[project.project_id] = project
        return self.project_info(project.project_id)

    def project_info(self, project_id: str) -> McpProjectInfo:
        """返回工程修订号、文件标识、未保存状态及加载时诊断。"""
        project = self._project(project_id)
        return McpProjectInfo(
            project_id=project_id,
            revision=project.revision,
            schema_version=autosar.SCHEMA_VERSION,
            files=[McpFileInfo(file_id=key, filepath=str(file.filepath), object_count=len(file.index.objects), dirty=file._dirty) for key, file in self._files(project).items()],
            diagnostics=project.load_diagnostics,
        )

    def find_nodes(
        self, project_id: str, xml_tag: str | None = None, name: str | None = None, ref_prefix: str = '/', file_id: str | None = None, offset: Offset = 0, limit: Limit = 50
    ) -> McpNodePage:
        """按 XML 标签精确匹配、名称子串和路径前缀查找具名节点；不确定标签时先省略 xml_tag 查询，不能用 SW-C 等片段匹配。"""
        project = self._project(project_id)
        prefix = _path(ref_prefix, root=True)
        if file_id and file_id not in project.paths:
            fail('FILE_NOT_FOUND', f'未知 file_id：{file_id}', '调用 project_info 获取文件标识。')
        matches = []
        for key, file in self._files(project).items():
            if file_id and key != file_id:
                continue
            for ref, node in file.index.objects.items():
                if ref[: len(prefix)] != prefix or (xml_tag and _tag(node.xml_obj) != xml_tag) or (name and name not in node.short_name):
                    continue
                matches.append(self._summary(project, key, node))
        return McpNodePage(
            project_id=project_id,
            revision=project.revision,
            items=matches[offset : offset + limit],
            total=len(matches),
            next_offset=offset + limit if offset + limit < len(matches) else None,
        )

    def get_node(
        self,
        project_id: str,
        ref: str,
        file_id: str | None = None,
        include_xml: bool = False,
        xpath: str | None = None,
        xml_offset: Offset = 0,
        xml_limit: Annotated[int, Field(ge=1, le=100_000)] = 16_000,
    ) -> McpNodeDetail:
        """读取节点摘要；include_xml=true 时分页返回 XML。xpath 限定节点内一个元素，ar: 表示 AUTOSAR 命名空间。"""
        project = self._project(project_id)
        key, file, node = self._node(project, ref, file_id)
        xml = None
        if include_xml or xpath:
            xml = node.content if node else file.render()
            if xpath:
                xml = etree.tostring(select_element(read_xml(xml), xpath), encoding='unicode', with_tail=False)
        total = len(xml) if xml else 0
        return McpNodeDetail(
            project_id=project_id,
            revision=project.revision,
            node=self._summary(project, key, node),
            xml=xml[xml_offset : xml_offset + xml_limit] if xml is not None else None,
            total_chars=total,
            next_offset=xml_offset + xml_limit if xml_offset + xml_limit < total else None,
        )

    def find_references(self, project_id: str, ref: str, offset: Offset = 0, limit: Limit = 50) -> McpReferencePage:
        """查询已加载文件中的入向引用；xpath 相对于 owner_ref，可用于局部编辑。"""
        project = self._project(project_id)
        _path(ref)
        items = []
        for file_id, file in self._files(project).items():
            if str2ref(ref) not in file.index.references:
                continue
            for element, owner_ref, owner in _references(read_xml(file.render())):
                if element.text == ref:
                    items.append(
                        McpReferenceInfo(
                            file_id=file_id,
                            owner_ref=ref2str(owner_ref),
                            target_ref=ref,
                            xml_tag=etree.QName(element).localname,
                            xpath=_xpath(element, owner),
                            dest=element.get('DEST'),
                        )
                    )
        return McpReferencePage(
            project_id=project_id,
            revision=project.revision,
            items=items[offset : offset + limit],
            total=len(items),
            next_offset=offset + limit if offset + limit < len(items) else None,
        )

    def describe_type(self, xml_tag: str, python_type: str | None = None) -> McpTypeInfo:
        """查询 XML 标签的字段、枚举与 compound choices。同名标签有多种绑定时，从 alternative_types 选取 python_type 进一步查询。"""
        classes = [clazz for clazz in vars(autosar).values() if isinstance(clazz, type) and is_dataclass(clazz) and getattr(getattr(clazz, 'Meta', None), 'name', None) == xml_tag]
        if not classes or python_type:
            if self._type_roles is None:
                self._type_roles = {}
                pending = [value for value in vars(autosar).values() if isinstance(value, type) and is_dataclass(value)]
                visited = set()
                while pending:
                    kind = pending.pop()
                    if kind in visited:
                        continue
                    visited.add(kind)
                    pending.extend(value for value in vars(kind).values() if isinstance(value, type) and is_dataclass(value))
                    for item in fields(kind):
                        names = [item.metadata.get('name')]
                        names.extend(choice.get('name') for choice in item.metadata.get('choices', ()))
                        for name in names:
                            if name:
                                self._type_roles.setdefault(name, []).append((kind, item.name))
            for parent, field_name in self._type_roles.get(xml_tag, []):
                for var in self.context.build(parent).get_all_vars():
                    if var.name != field_name:
                        continue
                    for option in list(var.elements.values()) or [var]:
                        if option.local_name == xml_tag:
                            classes.extend(kind for kind in option.types if is_dataclass(kind))
        classes = sorted(set(classes), key=lambda item: item.__qualname__)
        if not classes:
            fail('TYPE_NOT_FOUND', f'当前绑定中没有标签类型：{xml_tag}', '使用 XML 标签名，例如 SW-BASE-TYPE，而不是 Python 类名。')
        clazz = next((kind for kind in classes if kind.__qualname__ == python_type), None) if python_type else classes[0]
        if clazz is None:
            fail('TYPE_NOT_FOUND', f'{xml_tag} 没有绑定类型 {python_type}。', '从 describe_type 返回的 alternative_types 或父字段的 type_names 中选择。')
        items = []
        for var in self.context.build(clazz).get_all_vars():
            for item in list(var.elements.values()) or [var]:
                enums = [kind for kind in item.types if isinstance(kind, type) and issubclass(kind, Enum)]
                items.append(
                    McpTypeField(
                        xml_name=item.local_name,
                        kind='attribute' if item.is_attribute else ('text' if item.is_text else 'element'),
                        python_field=var.name,
                        type_names=[kind.__qualname__ for kind in item.types],
                        required=var.required,
                        repeated=var.list_element,
                        enum_values=[str(member.value) for kind in enums for member in kind],
                    )
                )
        return McpTypeInfo(xml_tag=xml_tag, python_type=clazz.__qualname__, fields=items, alternative_types=[kind.__qualname__ for kind in classes])

    def rename_node(self, project_id: str, ref: str, new_name: str, revision: Revision, file_id: str | None = None) -> McpEditResult:
        """ref 必须为当前已存在的旧路径，new_name 仅传新 SHORT-NAME；同步已加载文件中指向它及后代的引用，成功后使用新 revision 和路径查询。"""
        project = self._project(project_id)
        self._revision(project, revision)
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', new_name):
            fail('INVALID_NAME', 'SHORT-NAME 必须以英文字母开头，只包含字母、数字和下划线。', '提供符合 AUTOSAR SHORT-NAME 约束的名称。')
        old_ref = _path(ref)
        key, _, _ = self._node(project, ref, file_id)
        new_ref = (*old_ref[:-1], new_name)
        all_refs = {path for file in project.io.files.values() for path in file.index.objects}
        old_subtree = {path for path in all_refs if path[: len(old_ref)] == old_ref}
        for path in old_subtree:
            destination = (*new_ref, *path[len(old_ref) :])
            if destination in all_refs and destination not in old_subtree:
                fail('DUPLICATE_PATH', f'重命名后的路径已存在：{ref2str(destination)}', '选择未占用的名称；当前会话尚未修改。')
        affected = {key}
        for current_id, file in self._files(project).items():
            if any(target[: len(old_ref)] == old_ref for target in file.index.references):
                affected.add(current_id)
        files = self._files(project)
        candidates = {current_id: clone_file(files[current_id]) for current_id in project.paths if current_id in affected}
        target = candidates[key].ref(old_ref)
        target.xml_obj.short_name.value = new_name
        updates = {current_id: set() for current_id in candidates}
        updates[key].add(old_ref)
        count = 0
        for current_id, file in candidates.items():
            # 在旧索引上一次性收集引用，修改期间不重建活动索引。
            for target_ref, rows in file.index.references.items():
                if target_ref[: len(old_ref)] == old_ref:
                    destination = (*new_ref, *target_ref[len(old_ref) :])
                    for row in rows:
                        row.set_dest(destination)
                        updates[current_id].add(row.owner_ref)
                        count += 1
        # 从旧路径选择互不重叠的最小刷新范围；祖先刷新同时覆盖其下的改名和引用。
        for current_id, refs in updates.items():
            roots = []
            for owner_ref in sorted(refs, key=len):
                if not any(owner_ref[: len(parent)] == parent for parent in roots):
                    roots.append(owner_ref)
            if () in roots:
                candidates[current_id] = clone_file(candidates[current_id])
            else:
                for owner_ref in roots:
                    candidates[current_id].update_node(candidates[current_id].ref(owner_ref))
        changed = self._publish(project, candidates)
        return McpEditResult(project_id=project_id, revision=project.revision, affected_files=changed, new_ref=ref2str(new_ref), updated_references=count)

    def patch_xml(
        self, project_id: str, ref: str, operations: Annotated[list[McpPatchOperation], Field(min_length=1, max_length=100)], revision: Revision, file_id: str | None = None
    ) -> McpEditResult:
        """原子提交节点内的一批 XML 操作；XPath 按顺序在当前候选树执行。现有 SHORT-NAME 修改请使用 rename_node。文件根 / 需 file_id。"""
        project = self._project(project_id)
        self._revision(project, revision)
        key, original, node = self._node(project, ref, file_id)
        candidate = clone_file(original)
        old = candidate.ref(node.ref).xml_obj if node else candidate.root
        root = read_xml(ArxmlNamedNode(xml_obj=old, ref=node.ref).content if node else candidate.render())
        apply_patch(root, operations)
        replacement = parse_object(root, type(old))
        if node:
            actual = read_xml(ArxmlNamedNode(xml_obj=replacement, ref=node.ref).content)
            candidate = replace_object(candidate, old, replacement)
        else:
            candidate = ArxmlFile().parse_autosar(
                original.filepath, replacement, original.header.xml_namespace, original.header.xml_schema_location, original.format.indent, original.format.leading_comments
            )
            actual = read_xml(candidate.render())
        if semantic_xml(root) != semantic_xml(actual):
            fail('LOSSY_ROUND_TRIP', '修改的 XML 在绑定往返后发生元素、文本、属性或顺序变化。', '检查 describe_type 和 XSD；不能提交当前绑定无法保留的 XML。')
        changed = self._publish(project, {key: candidate})
        return McpEditResult(project_id=project_id, revision=project.revision, affected_files=changed)

    def validate_project(self, project_id: str) -> McpValidationResult:
        """校验当前会话的 XSD、重复路径、已加载目标及 DEST；既有外部引用只作为警告。"""
        project = self._project(project_id)
        diagnostics = self._diagnostics(self._files(project), project.baseline)
        return McpValidationResult(project_id=project_id, revision=project.revision, valid=not any(item.severity == 'error' for item in diagnostics), diagnostics=diagnostics)

    def preview_changes(
        self,
        project_id: str,
        offset: Offset = 0,
        limit: Limit = 50,
        diff_mode: Annotated[
            Literal['file', 'model'], Field(description='file 展示磁盘原文到待保存文件的完整差异；model 对比同一绑定序列化后的内容，省略已有的格式及数值规范化差异。')
        ] = 'file',
    ) -> McpPreview:
        """分页查看未保存差异；默认 file 包含全部写盘变化，model 聚焦本次对象修改。保存前查看 file 视图；各视图及分页共用当前 revision 的凭据。"""
        project = self._project(project_id)
        lines = []
        affected = []
        serialization_changed = []
        for key, file in self._files(project).items():
            if not file._dirty:
                continue
            affected.append(key)
            original = project.baseline[key]
            before = original.decode(read_xml(original).getroottree().docinfo.encoding or 'utf-8').lstrip('\ufeff').splitlines()
            rendered_before = project.rendered_baseline[key].splitlines()
            if before != rendered_before:
                serialization_changed.append(key)
            if diff_mode == 'model':
                before = rendered_before
            after = file.render().splitlines()
            for text in difflib.unified_diff(before, after, fromfile=str(file.filepath), tofile=str(file.filepath)):
                # 单行压缩 XML 也必须有界返回，不能仅按行数限制响应。
                lines.extend(McpDiffLine(file_id=key, text=text[start : start + 2000], continuation=start > 0) for start in range(0, max(1, len(text)), 2000))
        if project.preview_token is None:
            project.preview_token = uuid4().hex
        return McpPreview(
            project_id=project_id,
            revision=project.revision,
            preview_token=project.preview_token,
            affected_files=affected,
            lines=lines[offset : offset + limit],
            total_lines=len(lines),
            next_offset=offset + limit if offset + limit < len(lines) else None,
            diagnostics=self.validate_project(project_id).diagnostics,
            diff_mode=diff_mode,
            serialization_changed_files=serialization_changed,
        )

    def save_changes(self, project_id: str, preview_token: str) -> McpSaveResult:
        """显式写回已预览的修订，保留原文件备份；外部文件修改、过期预览和校验错误阻止保存。用户确认由客户端负责。"""
        project = self._project(project_id)
        if not project.preview_token or preview_token != project.preview_token:
            fail('STALE_PREVIEW', '保存凭据不存在或已过期。', '调用 preview_changes 查看最新修改后，再使用其 preview_token 保存。')
        for key, path in project.paths.items():
            if checked_path(self.workspace, path) != path or digest(path.read_bytes()) != digest(project.baseline[key]):
                fail('FILE_CONFLICT', f'已加载文件被外部修改：{path}', '重新加载并合并外部改动，再进行预览和保存。')
        diagnostics = self.validate_project(project_id).diagnostics
        dirty = {key: file for key, file in self._files(project).items() if file._dirty}
        errors = [item for item in diagnostics if item.severity == 'error' and (item.file_id in dirty or item.code != 'XSD_ERROR')]
        if errors:
            fail('VALIDATION_FAILED', '\n'.join(item.message for item in errors[:20]), '修正错误并重新预览。')
        contents = {project.paths[key]: file.render().encode('utf-8') for key, file in dirty.items()}
        backups, manifest = save_files(self.workspace, contents, {project.paths[key]: project.baseline[key] for key in dirty})
        saved = [McpSavedFile(file_id=key, filepath=str(project.paths[key]), backup_path=str(backups[project.paths[key]])) for key in dirty]
        for key, file in dirty.items():
            project.baseline[key] = contents[project.paths[key]]
            project.rendered_baseline[key] = contents[project.paths[key]].decode('utf-8')
            file._dirty = False
        project.load_diagnostics = [item for item in project.load_diagnostics if item.file_id not in dirty]
        project.preview_token = None
        project.revision += 1
        return McpSaveResult(project_id=project_id, revision=project.revision, files=saved, recovery_manifest=str(manifest) if manifest else None)

    def close_project(self, project_id: str, discard_changes: bool = False) -> McpCloseResult:
        """释放会话；未保存修改只有在 discard_changes=true 时才会丢弃。"""
        project = self._project(project_id)
        if any(file._dirty for file in project.io.files.values()) and not discard_changes:
            fail('UNSAVED_CHANGES', '工程存在未保存修改。', '先预览并保存，或明确指定 discard_changes=true。')
        del self.projects[project_id]
        return McpCloseResult(project_id=project_id)
