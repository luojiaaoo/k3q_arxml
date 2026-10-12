from __future__ import annotations

import pprint
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .arxml_file import ArxmlFile, Filename
from .arxml_file import logger as logger
from .arxml_object import ArxmlObject, Ref, T

if TYPE_CHECKING:
    from .autosar import Autosar


class IOArxml:
    """管理多个 ArxmlFile，汇总文件内的查询结果。"""

    def __init__(self, filepaths: Iterable[Filename]):
        self.files = {str(filepath): ArxmlFile(filepath) for filepath in filepaths}

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
    def references(self) -> dict[Ref, list[tuple[Any, Ref, str]]]:
        result: dict[Ref, list[tuple[Any, Ref, str]]] = {}
        for file in self.files.values():
            for ref in file.references:
                result.setdefault(ref, []).extend(file.ref_to_ref(ref))
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
            raise ValueError(f'{self.ref2ref_str(ref)} 存在于多个文件，请指定 filename 或使用 find()')
        return matches[0] if matches else None

    def ar(self, clazz: type[T], ref_prefix: Ref = ()) -> list[ArxmlObject[T]]:
        return [obj for file in self.files.values() for obj in file.ar(clazz, ref_prefix)]

    def ref_to_ref(self, ref: Ref) -> list[tuple[Any, Ref, str]]:
        return [row for file in self.files.values() for row in file.ref_to_ref(ref)]

    def scan_ref(self, debug_uuid: bool = False) -> None:
        for file in self.files.values():
            file.scan_ref()
        if debug_uuid:
            pprint.pp({filename: file.uuids for filename, file in self.files.items()})

    def create_arxml(self, filepath: Filename, arxml_obj: Autosar) -> ArxmlFile:
        file = ArxmlFile(filepath, root=arxml_obj)
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

    ref_str2ref = staticmethod(ArxmlFile.ref_str2ref)
    ref2ref_str = staticmethod(ArxmlFile.ref2ref_str)
