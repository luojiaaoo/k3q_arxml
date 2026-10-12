from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, TypeAlias, cast

from lxml import etree
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.parsers.handlers import LxmlEventHandler
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from xsdata.formats.dataclass.serializers.writers import LxmlEventWriter

from .arxml_object import ArxmlObject, Ref, T

if TYPE_CHECKING:
    from .autosar import Autosar

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)10s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

Filename: TypeAlias = str | Path
Uuid: TypeAlias = str


class ArxmlFile:
    """负责单个文件的解析、索引和回写。"""

    def __init__(self, filepath: Filename, root: Autosar | None = None):
        try:
            from .autosar import SCHEMA_VERSION, Autosar
        except ModuleNotFoundError as exc:
            if exc.name != f'{__package__}.autosar':
                raise
            raise RuntimeError('尚未生成 AUTOSAR 绑定，请先运行 uv run python -m k3q_arxml generate <版本>；使用 versions 命令查看可用版本。') from exc

        self.filepath = str(filepath)
        self.schema_version = SCHEMA_VERSION
        self.xml_namespace = 'http://autosar.org/schema/r4.0'
        self.xml_schema_location = f'{self.xml_namespace} AUTOSAR_{SCHEMA_VERSION.replace(".", "-")}.xsd'
        self.clazz = Autosar
        self.indent = ' ' * 4
        self.objects: dict[Ref, ArxmlObject[Any]] = {}
        self.references: dict[Ref, list[tuple[Any, Ref]]] = {}
        self.uuids: dict[Uuid, Ref] = {}
        self.root: Autosar
        if root is None:
            self.parse()
        else:
            self.root = root
        self.scan_ref()

    def get_indent_from_file(self) -> str:
        """从文件中获取缩进格式。"""
        with open(self.filepath, 'r', encoding='utf-8') as f:
            while _line := f.readline():
                if re.match('^<AUTOSAR', _line):
                    while _line2 := f.readline():
                        if indent := re.search(r'^(\s*)<', _line2):
                            return indent.group(1)
        return ' ' * 4

    def get_schema_filename_from_file(self) -> str:
        """从根节点的 schemaLocation 中提取 AUTOSAR XSD 文件名。"""
        with open(self.filepath, 'rb') as f:
            _, root = next(etree.iterparse(f, events=('start',)))
        locations = root.get('{http://www.w3.org/2001/XMLSchema-instance}schemaLocation', '').split()
        schema = next((path for namespace, path in zip(locations[::2], locations[1::2]) if namespace == self.xml_namespace), None)
        if schema is None:
            raise ValueError(f'{self.filepath}：缺少 AUTOSAR 的 xsi:schemaLocation，无法核对 schema_version')
        return re.split(r'[/\\]', schema)[-1]

    def parse(self) -> Autosar:
        logger.info('>> parsing %s', self.filepath)
        schema_filename = self.get_schema_filename_from_file()
        expected_filename = f'AUTOSAR_{self.schema_version.replace(".", "-")}.xsd'
        if schema_filename != expected_filename:
            raise ValueError(f'{self.filepath}：文件声明 {schema_filename}，当前绑定 schema_version={self.schema_version}，需要 {expected_filename}')

        parser = XmlParser(context=XmlContext(), config=ParserConfig(), handler=LxmlEventHandler)
        ns_map = {}
        self.indent = self.get_indent_from_file()
        self.root = parser.parse(self.filepath, self.clazz, ns_map=ns_map)
        if (default_ns := ns_map[None]) != self.xml_namespace:
            logger.error('%s ns: %s', self.filepath, default_ns)
        return self.root

    def scan_ref(self) -> None:
        """沿用原扫描函数，只将结果包装为本文件的单个对象。"""
        objects, self.references, self.uuids = self.__scan_arobj_ref(self.root)
        self.objects = {ref: ArxmlObject(obj, self, ref) for ref, obj in objects.items()}

    def ref(self, ref: Ref) -> ArxmlObject[Any] | None:
        return self.objects.get(ref)

    def ar(self, clazz: type[T], ref_prefix: Ref = ()) -> list[ArxmlObject[T]]:
        return [cast(ArxmlObject[T], obj) for ref, obj in self.objects.items() if ref[: len(ref_prefix)] == ref_prefix and isinstance(obj.xml_obj, clazz)]

    def ref_to_ref(self, ref: Ref) -> list[tuple[Any, Ref, str]]:
        """返回引用对象、所在对象路径、文件名。"""
        return [(obj, owner, self.filepath) for obj, owner in self.references.get(ref, [])]

    def save(self) -> None:
        serializer = XmlSerializer(
            XmlContext(),
            config=SerializerConfig(indent=self.indent, schema_location=self.xml_schema_location, xml_declaration=True, ignore_default_attributes=True),
            writer=LxmlEventWriter,
        )
        content = serializer.render(self.root, ns_map={None: self.xml_namespace})
        with open(self.filepath, 'w', encoding='utf-8') as f:
            f.write(content)

    @staticmethod
    def ref_str2ref(ref_str: str) -> Ref:
        """将ref字符串转为ref元组"""
        return tuple(ref_str.split('/')[1:])

    @staticmethod
    def ref2ref_str(ref: Ref) -> str:
        """将ref元组转为ref字符串"""
        return '/' + '/'.join(ref)

    @classmethod
    def __scan_arobj_ref(
        cls, obj, ref=None, dict_ref_from_short_name=None, dict_uuid=None, dict_search_obj_use_ref=None
    ) -> Tuple[Dict[Ref, Any], Dict[Ref, List[Tuple[Any, Ref]]], Dict[Uuid, Ref]]:
        if dict_ref_from_short_name is None:
            dict_ref_from_short_name = {}
            dict_search_obj_use_ref = {}
            dict_uuid = {}
        if ref is None:
            ref = tuple()

        def _vars(_obj):
            try:
                return vars(_obj)
            except TypeError:
                return {}

        for k, v in _vars(obj).items():
            if callable(v) or v is None or isinstance(v, (int, float, str, bool, Enum)):
                continue
            # print(type(v))
            elif isinstance(v, Iterable):
                for i in v:
                    if hasattr(i, 'short_name') and 'autosar' in i.__class__.__module__:  # 搜索short_name节点
                        dict_ref_from_short_name[ref + (i.short_name.value,)] = i
                        if hasattr(i, 'uuid'):
                            dict_uuid[i.uuid] = ref + (i.short_name.value,)
                        cls.__scan_arobj_ref(i, ref + (i.short_name.value,), dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
                    else:
                        if hasattr(i, 'value') and hasattr(i, 'dest') and type(i).__name__.upper().endswith('REF'):  # ref实例
                            if (_ref := cls.ref_str2ref(i.value)) not in dict_search_obj_use_ref:
                                dict_search_obj_use_ref[_ref] = [(i, ref)]
                            else:
                                dict_search_obj_use_ref[_ref].append((i, ref))
                        cls.__scan_arobj_ref(i, ref, dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
            elif hasattr(v, 'short_name') and 'autosar' in v.__class__.__module__:  # 搜索short_name节点
                dict_ref_from_short_name[ref + (v.short_name.value,)] = v
                if hasattr(v, 'uuid'):
                    dict_uuid[v.uuid] = ref + (v.short_name.value,)
                cls.__scan_arobj_ref(v, ref + (v.short_name.value,), dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
            else:
                if hasattr(v, 'value') and hasattr(v, 'dest') and type(v).__name__.upper().endswith('REF'):  # ref实例
                    if (_ref := cls.ref_str2ref(v.value)) not in dict_search_obj_use_ref:
                        dict_search_obj_use_ref[_ref] = [(v, ref)]
                    else:
                        dict_search_obj_use_ref[_ref].append((v, ref))
                cls.__scan_arobj_ref(v, ref, dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
        return dict_ref_from_short_name, dict_search_obj_use_ref, dict_uuid
