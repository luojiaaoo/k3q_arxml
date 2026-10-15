from __future__ import annotations

import re
from dataclasses import Field, fields, is_dataclass
from typing import Any, cast

from lxml import etree
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.parsers.handlers import LxmlEventHandler
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from xsdata.formats.dataclass.serializers.writers import LxmlEventWriter

from .log import logger
from .schemas import ArxmlFormat, ArxmlHeader, ArxmlNamedNode, ArxmlRefNode, Filepath, T, TupleRef, Uuid

try:
    from .autosar import SCHEMA_VERSION, Autosar
except ModuleNotFoundError as exc:
    if exc.name != f'{__package__}.autosar':
        raise
    raise RuntimeError('尚未生成 AUTOSAR 绑定，请先运行 uv run python -m k3q_arxml generate <版本>；使用 versions 命令查看可用版本。') from exc


def get_xml_metadata(schema_version: str) -> dict[str, str]:
    xml_namespace = 'http://autosar.org/schema/r4.0'
    xml_schema_location = f'{xml_namespace} AUTOSAR_{schema_version.replace(".", "-")}.xsd'
    return {'xml_namespace': xml_namespace, 'xml_schema_location': xml_schema_location}


def ref_str2ref(ref_str: str) -> TupleRef:
    """将 /Package/Type 形式的绝对引用路径转换为 ('Package', 'Type') 元组。"""
    return tuple(ref_str.split('/')[1:])


def ref2ref_str(ref: TupleRef) -> str:
    """将 ('Package', 'Type') 形式的路径元组转换为 /Package/Type 引用字符串。"""
    return '/' + '/'.join(ref)


class ArxmlFile:
    """负责单文件加载、索引初始化、节点增量更新和回写。"""

    def __init__(self):
        self.filepath: Filepath | None = None  # 解析或创建文件后保存为绝对路径。
        self.parse_schema_version = SCHEMA_VERSION  # 当前绑定用于解析的 AUTOSAR 版本。
        self.header: ArxmlHeader | None = None  # XML 根节点的 namespace 与 schema 声明。
        self.format: ArxmlFormat | None = None  # XML 回写的格式设置。
        self.objects: dict[TupleRef, ArxmlNamedNode[Any]] = {}  # 按 AUTOSAR 路径索引的对象。
        self.references: dict[TupleRef, list[ArxmlRefNode]] = {}  # 按目标路径索引的引用节点，包含所在文件和来源路径。
        self.uuids: dict[Uuid, TupleRef] = {}  # 按 UUID 索引的对象路径。
        # 字段定义按类型缓存，供本实例的多次扫描复用；不缓存对象的实际值。
        self._field_cache: dict[type, tuple[Field[Any], ...]] = {}
        self.root: Autosar  # 当前文件对应的 AUTOSAR 根对象。

    def read_file_metadata(self) -> tuple[ArxmlFormat, ArxmlHeader]:
        """读取 XML header、缩进格式和根节点前的注释。"""

        def get_indent_from_file() -> str:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                while _line := f.readline():
                    if re.match('^<AUTOSAR', _line):
                        while _line2 := f.readline():
                            if indent := re.search(r'^(\s*)<', _line2):
                                return indent.group(1)
            return ' ' * 4

        def get_leading_comments(root: etree._Element) -> str:
            comments = []
            sibling = root.getprevious()
            while sibling is not None:
                if isinstance(sibling, etree._Comment):
                    comments.append(etree.tostring(sibling, encoding='unicode', with_tail=False))
                sibling = sibling.getprevious()
            return '\n'.join(reversed(comments))

        with open(self.filepath, 'rb') as f:
            _, root = next(etree.iterparse(f, events=('start',)))
        format_info = ArxmlFormat(indent=get_indent_from_file(), leading_comments=get_leading_comments(root))
        namespace = etree.QName(root).namespace
        schema_location = root.get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation')
        if namespace is None:
            raise ValueError(f'{self.filepath}：XML 根节点缺少 namespace')
        if schema_location is None:
            raise ValueError(f'{self.filepath}：缺少 AUTOSAR 的 xsi:schemaLocation，无法核对 schema_version')
        header = ArxmlHeader(xml_namespace=namespace, xml_schema_location=schema_location)
        return format_info, header

    def parse_file(self, filepath: Filepath) -> ArxmlFile:
        """加载 ARXML 文件，并全量扫描一次以建立初始索引。"""
        self.filepath = filepath.resolve()
        logger.info('>> parsing {}', self.filepath)
        self.format, self.header = self.read_file_metadata()
        if self.header.file_schema_version != self.parse_schema_version:
            logger.warning(
                '{}: schema mismatch: file schema_version={}, current binding parse_schema_version={}',
                self.filepath,
                self.header.file_schema_version,
                self.parse_schema_version,
            )

        parser = XmlParser(context=XmlContext(), config=ParserConfig(), handler=LxmlEventHandler)
        ns_map = {}
        self.root = parser.parse(str(self.filepath), Autosar, ns_map=ns_map)
        self.scan_ref()
        return self

    def parse_autosar(
        self,
        filepath: Filepath,
        autosar_obj: Autosar,
        xml_namespace: str | None = None,
        xml_schema_location: str | None = None,
        indent: str = ' ' * 4,
        leading_comments: str = '',
    ) -> ArxmlFile:
        """使用 AUTOSAR 根对象初始化文件信息，并全量建立索引。"""
        if xml_namespace is None or xml_schema_location is None:
            metadata = get_xml_metadata(self.parse_schema_version)
            xml_namespace = xml_namespace or metadata['xml_namespace']
            xml_schema_location = xml_schema_location or metadata['xml_schema_location']
        self.filepath = filepath.resolve()
        self.root = autosar_obj
        self.header = ArxmlHeader(xml_namespace=xml_namespace, xml_schema_location=xml_schema_location)
        self.format = ArxmlFormat(indent=indent, leading_comments=leading_comments)
        self.scan_ref()
        return self

    def scan_ref(self) -> None:
        """加载阶段全量扫描 root，建立对象、反向引用和 UUID 的初始索引。

        parse_file() / parse_autosar() 加载时调用一次；后续编辑由 update_node() 增量维护。
        本方法从 root 重新生成全部包装和三份索引，不读取或合并已有索引。
        扫描及包装全部成功后统一替换索引；失败时保留原索引，不撤销 XML 对象修改。
        """
        assert self.filepath is not None
        objects, references, uuids = self.__scan_arobj_ref(self.root)
        wrapped_objects = {ref: ArxmlNamedNode(filepath=self.filepath, xml_obj=obj, ref=ref) for ref, obj in objects.items()}
        self.objects, self.references, self.uuids = wrapped_objects, references, uuids

    def update_node(self, node: ArxmlNamedNode[Any]) -> None:
        """加载完成后，增量更新 node 及其整棵子树的对象、反向引用和 UUID 索引。

        node 使用当前文件查询返回的有效包装；node.ref 是上次登记的路径，xml_obj 是修改后的对象。
        支持修改名称、UUID、引用，以及增删、替换、移动子节点。修改范围必须包含在
        node.xml_obj 内；删除、替换或移动该根对象本身时，应更新包含这些变化的共同
        具名祖先。通过父对象的字段或列表修改 XML 结构，包装的 ref 由本方法维护。

        这里只刷新索引，引用的 .value 按实际内容登记；重命名时仍需调用方同步引用文本。
        成功后复用原包装，并同步根节点及仍保留的后代包装的 ref。失败时保留旧索引和包装路径，
        不撤销已发生的 XML 对象修改，也不写回文件。
        """
        # 1. 直接从包装获取旧路径和 XML 对象。
        old_ref = node.ref

        def in_old_subtree(ref: TupleRef) -> bool:
            return ref[: len(old_ref)] == old_ref

        # 2. 用旧父路径扫描修改后的整棵子树，新的 SHORT-NAME 由扫描器追加。
        objects, references, uuids = self.__scan_arobj_ref(node.xml_obj, parent_ref=old_ref[:-1])
        # 原 XML 对象复用原包装；新增或替换的对象才创建包装。此时暂不改动旧包装的 ref。
        existing_nodes = {id(current.xml_obj): current for ref, current in self.objects.items() if in_old_subtree(ref)}
        wrapped_objects: dict[TupleRef, ArxmlNamedNode[Any]] = {}
        for ref, obj in objects.items():
            existing = existing_nodes.pop(id(obj), None)
            wrapped_objects[ref] = existing if existing is not None else ArxmlNamedNode(filepath=node.filepath, xml_obj=obj, ref=ref)

        # 3. 检查新路径是否占用了其他分支，并在旧位置插入整棵新子树。
        # 保留文件内的对象顺序，后面才能按原扫描顺序处理重复 UUID。
        for ref in objects:
            if ref in self.objects and not in_old_subtree(ref):
                raise ValueError(f'{self.filepath}: 路径 {ref2ref_str(ref)} 与其他分支冲突')
        merged_objects: dict[TupleRef, ArxmlNamedNode[Any]] = {}
        for ref, current in self.objects.items():
            if ref == old_ref:
                merged_objects.update(wrapped_objects)
            elif not in_old_subtree(ref):
                merged_objects[ref] = current

        # 4. 按来源路径移除旧子树的引用，不能按目标路径删除，否则会丢失外部入向引用。
        # 创建新的列表，避免后续步骤失败时已经改动旧索引；空的目标分组不保留。
        merged_references: dict[TupleRef, list[ArxmlRefNode]] = {}
        for target_ref, rows in self.references.items():
            retained = [row for row in rows if not in_old_subtree(row.owner_ref)]
            if retained:
                merged_references[target_ref] = retained
        for target_ref, rows in references.items():
            merged_references.setdefault(target_ref, []).extend(rows)

        # 5. 在原子树位置合入新 UUID，其他对象按原顺序登记，保持后出现者覆盖前者。
        # 不能只删除旧 UUID 再 update：删除重复 UUID 的最后一个对象时，需要恢复前一个。
        merged_uuids: dict[Uuid, TupleRef] = {}
        for ref, current in self.objects.items():
            if ref == old_ref:
                merged_uuids.update(uuids)
            elif not in_old_subtree(ref):
                uuid = getattr(current.xml_obj, 'uuid', None)
                if uuid is not None and uuid != '':
                    merged_uuids[uuid] = ref

        # 6. 全部成功后同步包装路径并发布三份索引，下一次可继续直接通过 node.ref 定位。
        for ref, current in wrapped_objects.items():
            current.ref = ref
        self.objects, self.references, self.uuids = merged_objects, merged_references, merged_uuids

    def ref(self, ref: TupleRef) -> ArxmlNamedNode[Any] | None:
        """按完整 AUTOSAR 路径查找当前文件中的对象。

        Args:
            ref: 由各级 SHORT-NAME 组成的路径元组，例如 ('Package', 'Type')，
                对应 XML 引用路径 /Package/Type；只匹配完整路径。

        Returns:
            找到时返回 ArxmlNamedNode，通过其 .xml_obj 访问实际 XML 对象；
            路径不存在时返回 None。

        直接修改节点后，调用 update_node(node) 增量更新索引再查询；使用 IOArxml.edit() 时退出后自动完成。
        """
        return self.objects.get(ref)

    def ar(self, clazz: type[T], ref_prefix: TupleRef = ()) -> list[ArxmlNamedNode[T]]:
        """按 XML 对象类型和路径前缀查询当前文件中的对象。

        Args:
            clazz: 要查找的 AUTOSAR 类型，例如 autosar.SwBaseType，包含其子类。
            ref_prefix: 由各级 SHORT-NAME 组成的路径前缀；默认为 ()，查询整个文件。
                例如 ('Package',) 匹配该包自身及其所有层级的子对象，
                不匹配名称仅以 Package 开头的其他包。

        Returns:
            同时满足类型和路径条件的 ArxmlNamedNode 列表，无匹配时返回空列表。
            每项的 .xml_obj 是实际 XML 对象，可直接读取或修改其属性。

        直接修改节点后，调用 update_node(node) 增量更新索引再查询；使用 IOArxml.edit() 时退出后自动完成。
        """
        return [cast(ArxmlNamedNode[T], obj) for ref, obj in self.objects.items() if ref[: len(ref_prefix)] == ref_prefix and isinstance(obj.xml_obj, clazz)]

    def save(self) -> None:
        if self.header is None:
            raise ValueError('尚未读取 XML header')
        serializer = XmlSerializer(
            XmlContext(),
            config=SerializerConfig(indent=self.format.indent, schema_location=self.header.xml_schema_location, xml_declaration=True, ignore_default_attributes=True),
            writer=LxmlEventWriter,
        )
        content = serializer.render(self.root, ns_map={None: self.header.xml_namespace})
        if self.format.leading_comments:
            declaration, body = content.split('\n', 1)
            content = f'{declaration}\n{self.format.leading_comments}\n{body}'
        with open(self.filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    def _get_fields(self, node: Any) -> tuple[Field[Any], ...]:
        """按节点类型获取 dataclass 字段定义，缓存供本实例的后续扫描复用。

        调用方需先确认 node 是 dataclass 实例。字段定义包含继承字段，
        缓存不保存实例值；实际内容仍由调用方通过 getattr() 读取。
        """
        node_type = type(node)
        if node_type not in self._field_cache:
            self._field_cache[node_type] = fields(node_type)
        return self._field_cache[node_type]

    def __scan_arobj_ref(self, obj: Any, parent_ref: TupleRef = ()) -> tuple[dict[TupleRef, Any], dict[TupleRef, list[ArxmlRefNode]], dict[Uuid, TupleRef]]:
        """遍历 dataclass 声明字段并递归扫描，返回对象、反向引用和 UUID 三组索引。

        只扫描传入 obj 的子树并返回结果，不直接修改文件索引。scan_ref() 传入 root 做全量初始化，
        update_node() 传入 node.xml_obj 和旧父路径做局部扫描，再将结果合入现有索引。
        路径只追加 SHORT-NAME，无名容器沿用父路径。
        例如 /Pkg/Owner 中的引用 .value 为 /Types/Speed，则记录：
            references[('Types', 'Speed')] = [ArxmlRefNode(filepath=self.filepath, xml_obj=引用节点, owner_ref=('Pkg', 'Owner'))]
        记录的 .xml_obj 保留原引用节点，可通过 .xml_obj.value 修改引用并回写；这里只登记目标路径，
        不查找目标对象，也不沿引用跳到其他对象。

        按 XML 树的包含关系递归，不做循环检测。使用 Python 默认递归深度限制。
        """
        from .autosar import Ref

        objects: dict[TupleRef, Any] = {}
        references: dict[TupleRef, list[ArxmlRefNode]] = {}
        uuids: dict[Uuid, TupleRef] = {}

        def _object_ref(node: Any, ref: TupleRef) -> TupleRef:
            """登记具名对象及其 UUID，并返回包含当前 SHORT-NAME 的新路径。"""

            # Identifier.value 才是 SHORT-NAME 文本；只检查组成路径所需的基本条件。
            name = getattr(node.short_name, 'value', None)
            if not isinstance(name, str) or not name.strip() or '/' in name:
                raise ValueError(f'{self.filepath}: {ref2ref_str(ref)} ({type(node).__qualname__}.short_name): SHORT-NAME 必须是非空且不含 / 的字符串')
            # 新建路径元组，不改变父节点路径或兄弟节点正在使用的路径。
            named_ref = (*ref, name)
            # 保存实际 XML 对象，由 scan_ref() 创建包装，或由 update_node() 复用、创建包装。
            objects[named_ref] = node
            uuid = getattr(node, 'uuid', None)
            # UUID 是可选属性；缺失 UUID 的节点仍登记在 objects 中。
            if uuid is not None and uuid != '':
                if not isinstance(uuid, str):
                    raise ValueError(f'{self.filepath}: {ref2ref_str(named_ref)} ({type(node).__qualname__}.uuid): UUID 必须是字符串')
                uuids[uuid] = named_ref
            return named_ref

        def _add_reference(node: Ref, ref: TupleRef) -> None:
            """将一处 XML 引用加入按目标路径组织的反向引用索引。"""

            value = node.value
            # 先确认是绝对路径；否则下面的转换会把相对路径的第一段错误地丢掉。
            if not isinstance(value, str) or not value.startswith('/'):
                raise ValueError(f'{self.filepath}: {ref2ref_str(ref)} ({type(node).__qualname__}.value): 引用必须是非空绝对路径，不支持相对引用或 BASE 解析')
            target_ref = ref_str2ref(value)
            # '/'、'/Types/'、'/Types//Speed' 转换后含空字符串，不能作为有效目标路径。
            if not all(target_ref):
                raise ValueError(f'{self.filepath}: {ref2ref_str(ref)} ({type(node).__qualname__}.value): 引用路径不能包含空路径段')
            # target_ref 是引用目标，ref 是引用所属对象；同一目标的每处引用都保留。
            # setdefault() 为首次遇到的目标建立列表，append() 将本处引用追加到列表末尾。
            assert self.filepath is not None
            references.setdefault(target_ref, []).append(ArxmlRefNode(filepath=self.filepath, xml_obj=node, owner_ref=ref))

        def _scan(node: Any, ref: TupleRef) -> None:
            if isinstance(node, (list, tuple)):
                # 列表的话，继续向下搜索
                for child in node:
                    _scan(child, ref)
                return

            # 不是数据类，跳过
            if isinstance(node, type) or not is_dataclass(node):
                return

            # 发现是路径节点，登记对象和 UUID
            if hasattr(node, 'short_name'):
                ref = _object_ref(node, ref)

            # 发现是引用节点，登记反向引用
            if isinstance(node, Ref):
                _add_reference(node, ref)

            # fields() 包含继承字段，普通和 slots dataclass 均适用；不会遍历临时 Python 属性。
            for model_field in self._get_fields(node):
                # 字段定义包含名称和 XML 元数据；getattr() 读取当前实例的实际值。
                value = getattr(node, model_field.name)
                if value is None:
                    continue
                if isinstance(value, (list, tuple)) or (is_dataclass(value) and not isinstance(value, type)):
                    _scan(value, ref)

        _scan(obj, parent_ref)
        return objects, references, uuids
