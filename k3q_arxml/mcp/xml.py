"""MCP 使用的隔离对象复制、安全 XML 和局部修改。"""

from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import fields, is_dataclass
from typing import Any

from lxml import etree
from xsdata.exceptions import ParserError
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.parsers.handlers import LxmlEventHandler

from ..arxml_file import ArxmlFile
from .schemas import McpError, McpPatchOperation

NAMESPACE = 'http://autosar.org/schema/r4.0'
NS = {'ar': NAMESPACE}


class McpServiceError(Exception):
    """可直接返回给模型的业务错误。"""

    def __init__(self, code: str, message: str, suggestion: str):
        self.error = McpError(code=code, message=message, suggestion=suggestion)
        super().__init__(message)


def fail(code: str, message: str, suggestion: str) -> None:
    raise McpServiceError(code, message, suggestion)


def read_xml(content: bytes | str) -> etree._Element:
    """先安全解析，xsdata 只接收已解析的树，不再自行读取外部资源。"""
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    try:
        root = etree.fromstring(content.encode('utf-8') if isinstance(content, str) else content, parser)
    except (etree.XMLSyntaxError, ValueError) as exc:
        fail('INVALID_XML', str(exc), '检查 XML 是否完整、命名空间和字符转义是否正确。')
    if root.getroottree().docinfo.doctype or any(isinstance(item, etree._Entity) for item in root.iter()):
        fail('UNSAFE_XML', '不支持 DTD 或实体声明。', '移除 DTD 和实体，使用明确的 XML 文本。')
    return root


def parse_object(root: etree._Element, clazz: type) -> Any:
    parser = XmlParser(
        context=XmlContext(),
        config=ParserConfig(fail_on_unknown_properties=True, fail_on_unknown_attributes=True, fail_on_converter_warnings=True),
        handler=LxmlEventHandler,
    )
    # LxmlEventHandler 会清理所遍历元素，不能将调用者的树直接交给它。
    try:
        return parser.parse(deepcopy(root), clazz)
    except (ParserError, ValueError, TypeError) as exc:
        fail('BINDING_ERROR', str(exc), '使用 describe_type 检查标签、属性及枚举；未知内容不会被静默忽略。')


def clone_value(value: Any) -> Any:
    """只复制声明字段，排除 parent 和绑定到旧文件的 edited 闭包。"""
    if is_dataclass(value) and not isinstance(value, type):
        return type(value)(**{item.name: clone_value(getattr(value, item.name)) for item in fields(value)})
    if isinstance(value, list):
        return [clone_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(clone_value(item) for item in value)
    if isinstance(value, dict):
        return {key: clone_value(item) for key, item in value.items()}
    return value


def clone_file(file: ArxmlFile) -> ArxmlFile:
    return ArxmlFile(binding=file.binding).parse_autosar(
        file.filepath,
        clone_value(file.root),
        file.header.xml_namespace,
        file.header.xml_schema_location,
        file.format.indent,
        file.format.leading_comments,
    )


def semantic_xml(node: etree._Element) -> tuple:
    """比较展开名称、属性、文本和子元素顺序，忽略排版空白及前缀选择。"""
    children = [child for child in node if isinstance(child.tag, str)]
    mixed = bool((node.text or '').strip()) or any((child.tail or '').strip() for child in children)
    text = node.text
    if children and not mixed and not (text or '').strip():
        text = None
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        text,
        tuple((semantic_xml(child), child.tail if mixed else ((child.tail or '').strip() or None)) for child in children),
    )


def walk_named(root: etree._Element, parent_ref: tuple[str, ...] = ()):
    """按 XML 包含关系取得路径，不使用可能已覆盖重复路径的对象索引。"""
    name = root.find('ar:SHORT-NAME', NS)
    ref = (*parent_ref, name.text or '') if name is not None else parent_ref
    if name is not None:
        yield ref, root
    for child in root:
        if isinstance(child.tag, str):
            yield from walk_named(child, ref)


def select_element(root: etree._Element, xpath: str) -> etree._Element:
    """只允许从当前子树选择一个元素，禁止父、兄弟及绝对路径逃逸。"""
    # 限定 XPath 语法而不是用字符串替换修复模型输入。
    if xpath.startswith('/') or re.search(r'\.\.|::|\||\$|[A-Za-z_-]+\s*\(', xpath):
        fail('INVALID_XPATH', 'XPath 必须限制在目标子树内，不支持轴、函数、变量或绝对路径。', '使用 .、./ar:TAG、.//ar:TAG 和位置或文本谓词。')
    try:
        matches = root.xpath(xpath, namespaces=NS)
    except etree.XPathError as exc:
        fail('INVALID_XPATH', str(exc), '为 AUTOSAR 标签使用 ar: 前缀，并检查 XPath 语法。')
    if not isinstance(matches, list) or len(matches) != 1 or not isinstance(matches[0], etree._Element) or not isinstance(matches[0].tag, str):
        count = len(matches) if isinstance(matches, list) else 0
        fail(
            'XPATH_MATCH_COUNT',
            f'XPath {xpath} 匹配到 {count} 项，必须且只能匹配一个 XML 元素。',
            "先用 get_node(include_xml=true) 检查结构和 ar: 命名空间；包内类型通常位于 ./ar:ELEMENTS 下，支持 [@UUID='值'] 属性谓词。多项匹配时用 SHORT-NAME 或位置谓词唯一定位。",
        )
    selected = matches[0]
    if selected is not root and root not in selected.iterancestors():
        fail('INVALID_XPATH', '选择结果位于目标子树以外。', '使用相对于当前节点的 XPath。')
    return selected


def _fragment(xml: str | None) -> etree._Element:
    if not xml:
        fail('INVALID_OPERATION', '此操作需要 xml 参数。', '提供一个带 AUTOSAR 命名空间的完整元素。')
    root = read_xml(xml)
    if etree.QName(root).namespace != NAMESPACE:
        fail('INVALID_NAMESPACE', '新增 XML 必须使用 AUTOSAR namespace。', f'在片段根标签声明 xmlns="{NAMESPACE}"。')
    return root


def apply_patch(root: etree._Element, operations: list[McpPatchOperation]) -> None:
    # 保留仍存活元素的 SHORT-NAME；新增和删除是独立的结构操作。
    original_names = {element: element.findtext('ar:SHORT-NAME', namespaces=NS) for _, element in walk_named(root)}
    for operation in operations:
        selected = select_element(root, operation.xpath)
        if operation.op == 'set_text':
            if operation.value is None or len(selected):
                fail('INVALID_OPERATION', 'set_text 需要 value，且只能用于不含子元素的节点。', '选择叶节点并提供 value；结构修改请使用 XML 操作。')
            if selected.tag == f'{{{NAMESPACE}}}SHORT-NAME':
                fail('RENAME_REQUIRED', '现有 SHORT-NAME 必须通过 rename_node 修改。', '调用 rename_node 以同步关联引用。')
            selected.text = operation.value
        elif operation.op in {'set_attribute', 'remove_attribute'}:
            if not operation.attribute:
                fail('INVALID_OPERATION', '属性操作需要 attribute 参数。', '提供属性名，例如 UUID 或 DEST。')
            if operation.op == 'set_attribute':
                if operation.value is None:
                    fail('INVALID_OPERATION', 'set_attribute 需要 value。', '提供新属性文本。')
                selected.set(operation.attribute, operation.value)
            else:
                if operation.attribute not in selected.attrib:
                    fail('ATTRIBUTE_NOT_FOUND', f'属性 {operation.attribute} 不存在。', '先调用 get_node 确认属性。')
                del selected.attrib[operation.attribute]
        elif operation.op == 'append':
            selected.append(_fragment(operation.xml))
        else:
            parent = selected.getparent()
            if parent is None:
                fail('INVALID_OPERATION', '不能删除、替换目标根节点或在根节点外插入。', '选择其具名祖先或文件根 /，再编辑其中的子节点。')
            if operation.op == 'delete':
                parent.remove(selected)
            elif operation.op == 'replace':
                replacement = _fragment(operation.xml)
                if selected in original_names and replacement.findtext('ar:SHORT-NAME', namespaces=NS) != original_names[selected]:
                    fail('RENAME_REQUIRED', '替换具名节点不能改变其 SHORT-NAME。', '重命名请使用 rename_node。')
                before_paths = {ref for ref, _ in walk_named(selected)}
                after_paths = {ref for ref, _ in walk_named(replacement)}
                if before_paths != after_paths:
                    fail('RENAME_REQUIRED', 'replace 不能改变其中具名节点的路径集合。', '重命名使用 rename_node；结构增删使用 delete 与 append/insert 操作。')
                parent.replace(selected, replacement)
            elif operation.op == 'insert_before':
                selected.addprevious(_fragment(operation.xml))
            elif operation.op == 'insert_after':
                selected.addnext(_fragment(operation.xml))
    for element, name in original_names.items():
        if element is root or root in element.iterancestors():
            if element.findtext('ar:SHORT-NAME', namespaces=NS) != name:
                fail('RENAME_REQUIRED', '现有节点的 SHORT-NAME 被修改或移除。', '调用 rename_node；结构删除请选择整个具名节点。')


def replace_object(file: ArxmlFile, old: Any, new: Any) -> ArxmlFile:
    """替换实际父字段中的对象，并刷新覆盖替换范围的最近具名祖先。"""
    parent = old.arxml_parent
    if parent is None:
        fail('INVALID_OPERATION', '文件根替换必须重新初始化文件。', '使用 ref=/ 的文档编辑入口。')
    for item in fields(parent):
        value = getattr(parent, item.name)
        if value is old:
            setattr(parent, item.name, new)
            break
        if isinstance(value, list) and any(child is old for child in value):
            value[next(index for index, child in enumerate(value) if child is old)] = new
            break
    else:
        fail('INVALID_OPERATION', '无法在父对象字段中定位节点。', '重新查询节点后再尝试。')
    named = parent
    while named is not None and not hasattr(named, 'short_name'):
        named = named.arxml_parent
    if named is None:
        # 顶层包等没有具名祖先；这是新的候选文件初始化，不复用旧包装。
        return ArxmlFile(binding=file.binding).parse_autosar(
            file.filepath, file.root, file.header.xml_namespace, file.header.xml_schema_location, file.format.indent, file.format.leading_comments
        )
    named.edited()
    return file
