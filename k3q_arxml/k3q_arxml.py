from __future__ import annotations

import pprint
from collections.abc import Iterable
from typing import Any

from .arxml_file import ArxmlFile, ref_str2ref, ref2ref_str
from .schemas import ArxmlNamedNode, ArxmlRefNode, Filepath, T, TupleRef


class IOArxml:
    """管理多个 ArxmlFile，汇总文件内的查询结果。"""

    def __init__(self, filepaths: Iterable[Filepath]):
        self.files: dict[Filepath, ArxmlFile] = {}
        for filepath in filepaths:
            filepath = filepath.resolve()
            if filepath not in self.files:
                self.append(filepath)

    def get_file(self, filename: Filepath) -> ArxmlFile:
        return self.files[filename.resolve()]

    @property
    def objects(self) -> dict[TupleRef, list[ArxmlNamedNode[Any]]]:
        result: dict[TupleRef, list[ArxmlNamedNode[Any]]] = {}
        for file in self.files.values():
            for ref, obj in file.objects.items():
                result.setdefault(ref, []).append(obj)
        return result

    @property
    def references(self) -> dict[TupleRef, list[ArxmlRefNode]]:
        result: dict[TupleRef, list[ArxmlRefNode]] = {}
        for file in self.files.values():
            for ref, rows in file.references.items():
                result.setdefault(ref, []).extend(rows)
        return result

    def find(self, ref: TupleRef) -> list[ArxmlNamedNode[Any]]:
        """返回不同文件中具有该路径的所有对象。"""
        return [obj for file in self.files.values() if (obj := file.ref(ref)) is not None]

    def ref(self, ref: TupleRef, filename: Filepath | None = None) -> ArxmlNamedNode[Any] | None:
        """查找唯一对象；同路径有多个对象时，需指定文件或使用 find()。"""
        if filename is not None:
            return self.get_file(filename).ref(ref)
        matches = self.find(ref)
        if len(matches) > 1:
            raise ValueError(f'{ref2ref_str(ref)} 存在于多个文件，请指定 filename 或使用 find()')
        return matches[0] if matches else None

    def ar(self, clazz: type[T], ref_prefix: TupleRef = ()) -> list[ArxmlNamedNode[T]]:
        return [obj for file in self.files.values() for obj in file.ar(clazz, ref_prefix)]

    def ref_to_ref(self, ref: TupleRef) -> list[ArxmlRefNode]:
        """跨所有已加载文件查找指向指定 AUTOSAR 路径的引用节点。

        Args:
            ref: 被引用目标的完整路径元组，例如 ('Package', 'Type')。
                目标对象可以位于其他文件，也可以尚未加载。

        Returns:
            ArxmlRefNode 列表，无引用时返回空列表。
            每项的 .xml_obj 是实际 XML 引用节点，通过 .xml_obj.value 读写目标路径；
            .owner_ref 是包含该引用的最近具名对象的路径，.filepath 是引用所在文件路径。
            同一来源对象中的多处引用分别返回，不合并。

        修改引用或对象名称、结构后，应先调用 scan_ref() 更新索引再查询。
        """
        return [row for file in self.files.values() for row in file.references.get(ref, [])]

    def scan_ref(self, debug_uuid: bool = False) -> None:
        for file in self.files.values():
            file.scan_ref()
        if debug_uuid:
            pprint.pp({filename: file.uuids for filename, file in self.files.items()})

    def append(self, filepath: Filepath) -> ArxmlFile:
        """加载已有的 ARXML 文件并加入管理，拒绝重复路径；不写回文件。"""
        filepath = filepath.resolve()
        if filepath in self.files:
            raise ValueError(f'{filepath} 已加载，不能重复添加')
        if not filepath.exists():
            raise FileNotFoundError(f'{filepath} 不存在')
        if filepath.is_dir():
            raise IsADirectoryError(f'{filepath} 是目录，不能作为 ARXML 文件加载')
        if not filepath.is_file():
            raise ValueError(f'{filepath} 不是普通文件')
        file = ArxmlFile().parse_file(filepath)
        self.files[filepath] = file
        return file

    def flush_to_file(self) -> None:
        for file in self.files.values():
            file.save()

    def print(self, print_filepath: Filepath | None = None) -> None:
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
