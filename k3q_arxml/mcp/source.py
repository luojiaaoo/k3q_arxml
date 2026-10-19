"""按需索引当前版本的 XSD 定义和 Python 类，不执行源码或读取用户指定路径。"""

from __future__ import annotations

import ast
import tokenize
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from textwrap import dedent
from types import ModuleType
from typing import Literal

from lxml import etree

from .schemas import McpSourceLocation, McpTypeSource
from .xml import fail, read_xml

XSD_NAMESPACE = 'http://www.w3.org/2001/XMLSchema'


@dataclass
class SourceDefinition:
    location: McpSourceLocation
    text: str
    related: list[str]
    dependencies_indexed: bool = False


class SourceIndex:
    def __init__(self):
        self.definitions: dict[str, SourceDefinition] = {}
        self.names: dict[str, set[str]] = defaultdict(set)
        self.roles: dict[str, set[str]] = defaultdict(set)

    def find(self, name: str) -> list[str]:
        if name in self.definitions:
            return [name]
        return sorted(self.names.get(name) or self.roles.get(name) or ())

    def page(self, name: str, matches: list[str], *, schema_version: str, source: Literal['xsd', 'binding'], offset: int, limit: int, candidate_offset: int) -> McpTypeSource:
        if not matches:
            fail('SOURCE_NOT_FOUND', f'当前版本的 {source} 中找不到定义：{name}', '使用 XML 标签、XSD 定义名或 Python 限定类型名；也可传入候选或关联定义的 definition_id。')
        result = McpTypeSource(schema_version=schema_version, source=source, query=name, total_candidates=len(matches))
        if len(matches) != 1:
            result.candidates = [self.definitions[key].location for key in matches[candidate_offset : candidate_offset + 50]]
            result.next_candidate_offset = candidate_offset + 50 if candidate_offset + 50 < len(matches) else None
            return result
        definition = self.definitions[matches[0]]
        result.definition = definition.location
        result.content = definition.text[offset : offset + limit]
        result.total_chars = len(definition.text)
        result.next_offset = offset + limit if offset + limit < result.total_chars else None
        result.related_definitions = definition.related[:200]
        result.total_related_definitions = len(definition.related)
        return result


def index_xsd(schema_path: Path) -> SourceIndex:
    """只读取当前主 XSD 及同目录的 xml.xsd，不跟随 import/include 访问其他文件。"""
    index = SourceIndex()
    nodes = {}
    symbols: dict[tuple[str, str, str], str] = {}
    paths = [schema_path]
    if (schema_path.parent / 'xml.xsd').is_file():
        paths.append(schema_path.parent / 'xml.xsd')
    for path in paths:
        root = read_xml(path.read_bytes())
        for node in root:
            if not isinstance(node.tag, str) or not node.get('name') or etree.QName(node).namespace != XSD_NAMESPACE:
                continue
            name = node.get('name')
            kind = etree.QName(node).localname
            key = f'{path.name}#{kind}:{name}'
            location = McpSourceLocation(definition_id=key, name=name, kind=kind, filepath=str(path), line=node.sourceline)
            index.definitions[key] = SourceDefinition(location, etree.tostring(node, encoding='unicode', with_tail=False), [])
            symbols[root.get('targetNamespace', ''), kind, name] = key
            index.names[name].add(key)
            index.names[f'{kind}:{name}'].add(key)
            nodes[key] = node
            # 嵌套标签返回包含其声明的完整顶层定义，保留所在 sequence / choice 的上下文。
            for child in node.iter():
                if child.tag in {f'{{{XSD_NAMESPACE}}}element', f'{{{XSD_NAMESPACE}}}attribute'} and child.get('name'):
                    index.roles[child.get('name')].add(key)
    for key, node in nodes.items():
        related = set()
        for child in node.iter():
            if not isinstance(child.tag, str):
                continue
            for attribute in ('type', 'base', 'ref', 'memberTypes', 'substitutionGroup'):
                for value in child.get(attribute, '').split():
                    prefix, _, local = value.rpartition(':')
                    namespace = child.nsmap.get(prefix or None, '')
                    kinds = (etree.QName(child).localname,) if attribute == 'ref' else ('element',) if attribute == 'substitutionGroup' else ('complexType', 'simpleType')
                    for kind in kinds:
                        target = symbols.get((namespace, kind, local))
                        if target and target != key:
                            related.add(target)
        index.definitions[key].related = sorted(related)
    return index


def index_binding(binding: ModuleType) -> SourceIndex:
    """流式分词定位类边界，避免对数十万行绑定整体建立 AST。"""
    path = Path(binding.__file__).resolve()
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    index = SourceIndex()
    depth = 0
    scopes: list[tuple[str, int, int]] = []
    decorators: dict[int, int] = {}
    pending = None
    class_start = None
    statement_start = True
    iterator = iter(lines)
    for token in tokenize.generate_tokens(lambda: next(iterator, '')):
        if token.type == tokenize.INDENT:
            depth += 1
            if pending:
                scopes.append((*pending, depth))
                pending = None
        elif token.type == tokenize.DEDENT:
            depth -= 1
            while scopes and scopes[-1][2] > depth:
                name, start, _ = scopes.pop()
                end = token.start[0] - 1
                while end >= start and not lines[end - 1].strip():
                    end -= 1
                location = McpSourceLocation(definition_id=name, name=name, kind='class', filepath=str(path), line=start)
                index.definitions[name] = SourceDefinition(location, ''.join(lines[start - 1 : end]), [])
                index.names[name.rsplit('.', 1)[-1]].add(name)
        elif token.type == tokenize.NEWLINE:
            statement_start = True
        elif token.type not in {tokenize.NL, tokenize.COMMENT, tokenize.ENDMARKER}:
            if token.string == '@' and statement_start:
                decorators.setdefault(depth, token.start[0])
            elif token.type == tokenize.NAME and token.string == 'class':
                class_start = decorators.pop(depth, token.start[0])
            elif class_start is not None and token.type == tokenize.NAME:
                parent = scopes[-1][0] + '.' if scopes else ''
                pending = (parent + token.string, class_start)
                class_start = None
            elif statement_start:
                decorators.pop(depth, None)
            statement_start = False
    for name in index.definitions:
        clazz = binding
        for part in name.split('.'):
            clazz = getattr(clazz, part, None)
        if isinstance(clazz, type):
            xml_tag = getattr(getattr(clazz, 'Meta', None), 'name', None)
            if xml_tag:
                index.names[xml_tag].add(name)
    return index


def binding_dependencies(index: SourceIndex, key: str) -> None:
    """只解析选中类的片段，提取基类和字段注解中引用的类型。"""
    definition = index.definitions[key]
    if definition.dependencies_indexed:
        return
    tree = ast.parse(dedent(definition.text))
    expressions = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            expressions.extend(node.bases)
        elif isinstance(node, ast.AnnAssign):
            expressions.append(node.annotation)
    related = set()
    for expression in expressions:
        for node in ast.walk(expression):
            if isinstance(node, (ast.Name, ast.Attribute)):
                name = ast.unparse(node)
                matches = index.find(name)
                if not matches and '.' in key:
                    matches = index.find(key.rsplit('.', 1)[0] + '.' + name)
                related.update(matches)
    definition.related = sorted(related - {key})
    definition.dependencies_indexed = True
