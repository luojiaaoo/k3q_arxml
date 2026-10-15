from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Tuple, TypeAlias, TypeVar, cast

if TYPE_CHECKING:
    from .arxml_file import ArxmlFile

Ref: TypeAlias = Tuple[str, ...]
T = TypeVar('T')


@dataclass
class ArxmlReference:
    """一处反向引用，保留实际引用节点及其来源位置。

    Attributes:
        xml_obj: 实际 XML 引用节点，通过 .value 读写目标路径字符串。
        owner_ref: 包含该引用的最近具名对象的路径。
        filename: 引用所在的 ARXML 文件路径。
    """

    xml_obj: Any
    owner_ref: Ref
    filename: str


@dataclass
class ArxmlObject(Generic[T]):
    """一个文件中的一个 ARXML 对象。"""

    xml_obj: T
    file: ArxmlFile
    ref: Ref

    @property
    def filename(self) -> str:
        return self.file.filepath

    @property
    def short_name(self) -> str:
        return cast(str, getattr(self.xml_obj, 'short_name').value)

    @property
    def is_ar_package(self) -> bool:
        from .autosar import ArPackage

        return isinstance(self.xml_obj, ArPackage)
