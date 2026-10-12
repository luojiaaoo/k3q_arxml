from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Tuple, TypeAlias, TypeVar, cast

if TYPE_CHECKING:
    from .arxml_file import ArxmlFile

Ref: TypeAlias = Tuple[str, ...]
T = TypeVar('T')


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
