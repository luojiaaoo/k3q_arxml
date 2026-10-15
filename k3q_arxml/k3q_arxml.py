from __future__ import annotations

import pprint
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .arxml_file import ArxmlFile, Filename, ref_str2ref, ref2ref_str
from .arxml_object import ArxmlObject, ArxmlReference, Ref, T

if TYPE_CHECKING:
    from .autosar import Autosar


class IOArxml:
    """管理多个 ArxmlFile，汇总文件内的查询结果。"""

    def __init__(self, filepaths: Iterable[Filename]):
        self.files = {str(filepath): ArxmlFile().parse_file(filepath) for filepath in filepaths}

    def get_file(self, filename: Filename) -> ArxmlFile:
        return self.files[str(filename)]

    @property
    def objects(self) -> dict[Ref, list[ArxmlObject[Any]]]:
        result: dict[Ref, list[ArxmlObject[Any]]] = {}
        for file in self.files.values():
            for ref, obj in file.objects.items():
                result.setdefault(ref, []).append(obj)
        return result

    @property
    def references(self) -> dict[Ref, list[ArxmlReference]]:
        result: dict[Ref, list[ArxmlReference]] = {}
        for file in self.files.values():
            for ref, rows in file.references.items():
                result.setdefault(ref, []).extend(ArxmlReference(xml_obj=obj, owner_ref=owner, filename=file.filepath) for obj, owner in rows)
        return result

    def find(self, ref: Ref) -> list[ArxmlObject[Any]]:
        """返回不同文件中具有该路径的所有对象。"""
        return [obj for file in self.files.values() if (obj := file.ref(ref)) is not None]

    def ref(self, ref: Ref, filename: Filename | None = None) -> ArxmlObject[Any] | None:
        """查找唯一对象；同路径有多个对象时，需指定文件或使用 find()。"""
        if filename is not None:
            return self.get_file(filename).ref(ref)
        matches = self.find(ref)
        if len(matches) > 1:
            raise ValueError(f'{ref2ref_str(ref)} 存在于多个文件，请指定 filename 或使用 find()')
        return matches[0] if matches else None

    def ar(self, clazz: type[T], ref_prefix: Ref = ()) -> list[ArxmlObject[T]]:
        return [obj for file in self.files.values() for obj in file.ar(clazz, ref_prefix)]

    def ref_to_ref(self, ref: Ref) -> list[ArxmlReference]:
        """跨所有已加载文件查找指向指定 AUTOSAR 路径的引用节点。

        Args:
            ref: 被引用目标的完整路径元组，例如 ('Package', 'Type')。
                目标对象可以位于其他文件，也可以尚未加载。

        Returns:
            ArxmlReference 列表，无引用时返回空列表。
            每项的 .xml_obj 是实际 XML 引用节点，通过 .xml_obj.value 读写目标路径；
            .owner_ref 是包含该引用的最近具名对象的路径，.filename 是引用所在文件路径。
            同一来源对象中的多处引用分别返回，不合并。

        修改引用或对象名称、结构后，应先调用 scan_ref() 更新索引再查询。
        """
        return [ArxmlReference(xml_obj=obj, owner_ref=owner, filename=file.filepath) for file in self.files.values() for obj, owner in file.references.get(ref, [])]

    def scan_ref(self, debug_uuid: bool = False) -> None:
        for file in self.files.values():
            file.scan_ref()
        if debug_uuid:
            pprint.pp({filename: file.uuids for filename, file in self.files.items()})

    def create_arxml(
        self,
        filepath: Filename,
        arxml_obj: Autosar,
        xml_namespace: str | None = None,
        xml_schema_location: str | None = None,
        indent: str = ' ' * 4,
        leading_comments: str = '',
    ) -> ArxmlFile:
        file = ArxmlFile().parse_autosar(filepath, arxml_obj, xml_namespace, xml_schema_location, indent, leading_comments=leading_comments)
        self.files[str(filepath)] = file
        return file

    def flush_to_file(self) -> None:
        for file in self.files.values():
            file.save()

    def print(self, print_filepath: Filename | None = None) -> None:
        if print_filepath is None:
            for file in self.files.values():
                pprint.pprint(file.root, width=40, indent=1, underscore_numbers=True)
        else:
            with open(print_filepath, 'w', encoding='utf-8') as stream:
                for file in self.files.values():
                    stream.write(f'=== {file.filepath} ===\n')
                    pprint.pprint(file.root, stream=stream, width=40, indent=1, underscore_numbers=True)

    ref_str2ref = staticmethod(ref_str2ref)
    ref2ref_str = staticmethod(ref2ref_str)
