"""基于 schema 绑定的节点分类与路径唯一性校验，供文件、工程和协议层共用。"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import fields, is_dataclass
from functools import cache
from typing import Any

from xsdata.formats.dataclass.context import XmlContext

from .schemas import TupleRef

_context = XmlContext()


@cache
def _structure(clazz: type) -> tuple[frozenset[type], bool]:
    children = set()
    dynamic = False
    for var in _context.build(clazz).get_element_vars():
        for option in list(var.elements.values()) or [var]:
            dynamic |= option.any_type or option.is_wildcard
            children.update(kind for kind in option.types if is_dataclass(kind))
    return frozenset(children), dynamic


@cache
def is_schema_leaf(clazz: type) -> bool:
    """具名类型在 schema 中无法包含具名后代时才是叶子，与实例字段值无关。

    穿过无名包装及 choices 检查可达类型；引用文本不作为包含关系。
    递归类型按已访问集合终止；开放内容可能容纳具名节点，按中间类型处理。
    """
    if not is_dataclass(clazz) or 'short_name' not in clazz.__dataclass_fields__:
        return False
    children, dynamic = _structure(clazz)
    if dynamic:
        return False
    pending = list(children)
    visited = set()
    while pending:
        kind = pending.pop()
        if kind in visited:
            continue
        visited.add(kind)
        if 'short_name' in kind.__dataclass_fields__:
            return False
        children, dynamic = _structure(kind)
        if dynamic:
            return False
        pending.extend(children)
    return True


def iter_named_nodes(root: Any, parent_ref: TupleRef = ()) -> Iterator[tuple[TupleRef, Any]]:
    """遍历声明字段的实际包含关系，保留被路径索引覆盖的同名实例。"""
    if isinstance(root, (list, tuple)):
        for child in root:
            yield from iter_named_nodes(child, parent_ref)
    elif is_dataclass(root) and not isinstance(root, type):
        if hasattr(root, 'short_name'):
            parent_ref = (*parent_ref, root.short_name.value)
            yield parent_ref, root
        for item in fields(root):
            yield from iter_named_nodes(getattr(root, item.name), parent_ref)


class DuplicatePathError(ValueError):
    """schema 叶子类型的完整 SHORT-NAME 路径冲突。"""

    def __init__(self, ref: TupleRef, first: str, second: str):
        self.ref = ref
        self.first = first
        self.second = second
        super().__init__(f'/{"/".join(ref)} 的 schema 叶子节点同时存在于 {first} 和 {second}')


def duplicate_paths(roots: Iterable[tuple[str, Any]], parent_ref: TupleRef = ()) -> Iterator[DuplicatePathError]:
    """统一检查同文件和跨文件路径；仅 schema 叶子类型参与唯一性约束。"""
    seen = {}
    for source, root in roots:
        for ref, node in iter_named_nodes(root, parent_ref):
            if is_schema_leaf(type(node)):
                if ref in seen:
                    yield DuplicatePathError(ref, seen[ref], source)
                seen[ref] = source


def validate_paths(roots: Iterable[tuple[str, Any]], parent_ref: TupleRef = ()) -> None:
    error = next(duplicate_paths(roots, parent_ref), None)
    if error is not None:
        raise error
