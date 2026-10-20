from __future__ import annotations

import pprint
from collections.abc import Iterable
from types import ModuleType
from typing import Any

from .arxml_file import ArxmlFile, ref2str
from .schemas import ArxmlNamedNode, ArxmlRefNode, Filepath, T, TupleRef
from .validation import validate_paths


class IOArxml:
    """管理多个 ArxmlFile，汇总文件内的查询结果。"""

    def __init__(self, filepaths: Iterable[Filepath], *, binding: ModuleType):
        self.binding = binding
        self.files: dict[Filepath, ArxmlFile] = {}
        for filepath in filepaths:
            filepath = filepath.resolve()
            if filepath not in self.files:
                self.append(filepath)

    def ref(self, ref: TupleRef) -> ArxmlNamedNode[Any] | None:
        """查找唯一对象；同路径有多个对象时抛出异常。"""
        match = None
        for file in self.files.values():
            obj = file.ref(ref)
            if obj is None:
                continue
            if match is not None:
                raise ValueError(f'{ref2str(ref)} 存在于多个文件')
            match = obj
        return match

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
            使用 .set_dest(路径元组) 修改该引用节点的目标路径；
            .owner_ref 是包含该引用的最近具名对象的路径。
            同一来源对象中的多处引用分别返回，不合并。

        修改引用后调用 .xml_obj.edited()，更新最近具名节点的索引后再查询。
        直接修改后，对该具名节点调用所属文件的 update_node() 增量更新索引。
        """
        return [row for file in self.files.values() for row in file.index.references.get(ref, [])]

    def append(self, filepath: Filepath) -> ArxmlFile:
        """加载 ARXML 并加入管理，拒绝重复文件及重复的 schema 叶子路径；不写回文件。"""
        filepath = filepath.resolve()
        if filepath in self.files:
            raise ValueError(f'{filepath} 已加载，不能重复添加')
        if not filepath.exists():
            raise FileNotFoundError(f'{filepath} 不存在')
        if filepath.is_dir():
            raise IsADirectoryError(f'{filepath} 是目录，不能作为 ARXML 文件加载')
        if not filepath.is_file():
            raise ValueError(f'{filepath} 不是普通文件')
        file = ArxmlFile(binding=self.binding).parse_file(filepath)
        return self.add_file(file)

    def add_file(self, file: ArxmlFile) -> ArxmlFile:
        """加入已解析文件，复用与 append 相同的工程路径校验；失败时不修改工程。"""
        filepath = file.filepath
        if filepath is None or file.binding is not self.binding:
            raise ValueError('文件必须已解析且使用当前工程的 schema 绑定')
        if filepath in self.files:
            raise ValueError(f'{filepath} 已加载，不能重复添加')
        validate_paths((str(item.filepath), item.root) for item in [*self.files.values(), file])
        self.files[filepath] = file
        return file

    def flush_to_file(self) -> None:
        """仅保存已标记修改且尚未回写的文件。"""
        validate_paths((str(file.filepath), file.root) for file in self.files.values())
        for file in self.files.values():
            if file._dirty:
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
