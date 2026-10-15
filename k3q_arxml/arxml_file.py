from __future__ import annotations

import re
from collections.abc import Iterable
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Tuple, TypeAlias, cast

from lxml import etree
from pydantic import BaseModel
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.parsers.handlers import LxmlEventHandler
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from xsdata.formats.dataclass.serializers.writers import LxmlEventWriter

from .arxml_object import ArxmlObject, Ref, T
from .log import logger

if TYPE_CHECKING:
    from .autosar import Autosar

Filename: TypeAlias = str | Path
Uuid: TypeAlias = str


class ArxmlFormat(BaseModel):
    """保存 XML 回写时使用的格式设置。"""

    indent: str = ' ' * 4
    leading_comments: str = ''  # 包含 <!-- --> 的 XML 注释，多条注释按原顺序换行连接。


class ArxmlHeader(BaseModel):
    """保存 XML 根节点的命名空间和 schema 声明，并计算文件版本。"""

    xml_namespace: str
    xml_schema_location: str

    @property
    def file_schema_version(self) -> str:
        locations = self.xml_schema_location.split()
        schema = next((path for namespace, path in zip(locations[::2], locations[1::2]) if namespace == self.xml_namespace), None)
        if schema is None:
            raise ValueError('XML 根节点缺少 AUTOSAR 的 xsi:schemaLocation，无法核对 schema_version')
        filename = re.split(r'[/\\]', schema)[-1]
        if not filename.startswith('AUTOSAR_') or not filename.endswith('.xsd'):
            raise ValueError(f'无法从 xsi:schemaLocation 提取 AUTOSAR schema_version：{filename}')
        return filename.removeprefix('AUTOSAR_').removesuffix('.xsd').replace('-', '.')


def get_xml_metadata(schema_version: str) -> dict[str, str]:
    xml_namespace = 'http://autosar.org/schema/r4.0'
    xml_schema_location = f'{xml_namespace} AUTOSAR_{schema_version.replace(".", "-")}.xsd'
    return {'xml_namespace': xml_namespace, 'xml_schema_location': xml_schema_location}


def ref_str2ref(ref_str: str) -> Ref:
    """将 /Package/Type 形式的绝对引用路径转换为 ('Package', 'Type') 元组。"""
    return tuple(ref_str.split('/')[1:])


def ref2ref_str(ref: Ref) -> str:
    """将 ('Package', 'Type') 形式的路径元组转换为 /Package/Type 引用字符串。"""
    return '/' + '/'.join(ref)


class ArxmlFile:
    """负责单个文件的解析、索引和回写。"""

    def __init__(self):
        try:
            from .autosar import SCHEMA_VERSION, Autosar
        except ModuleNotFoundError as exc:
            if exc.name != f'{__package__}.autosar':
                raise
            raise RuntimeError('尚未生成 AUTOSAR 绑定，请先运行 uv run python -m k3q_arxml generate <版本>；使用 versions 命令查看可用版本。') from exc

        self.filepath = ''  # 当前 ARXML 文件的路径。
        self.parse_schema_version = SCHEMA_VERSION  # 当前绑定用于解析的 AUTOSAR 版本。
        self.header: ArxmlHeader | None = None  # XML 根节点的 namespace 与 schema 声明。
        self.clazz = Autosar  # 用于反序列化根节点的 AUTOSAR 类型。
        self.format: ArxmlFormat | None = None  # XML 回写的格式设置。
        self.objects: dict[Ref, ArxmlObject[Any]] = {}  # 按 AUTOSAR 路径索引的对象。
        self.references: dict[Ref, list[tuple[Any, Ref]]] = {}  # 按目标路径索引的反向引用及其来源路径。
        self.uuids: dict[Uuid, Ref] = {}  # 按 UUID 索引的对象路径。
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

    def parse_file(self, filepath: Filename) -> ArxmlFile:
        self.filepath = str(filepath)
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
        self.root = parser.parse(self.filepath, self.clazz, ns_map=ns_map)
        self.scan_ref()
        return self

    def parse_autosar(
        self,
        filepath: Filename,
        autosar_obj: Autosar,
        xml_namespace: str | None = None,
        xml_schema_location: str | None = None,
        indent: str = ' ' * 4,
        leading_comments: str = '',
    ) -> ArxmlFile:
        if xml_namespace is None or xml_schema_location is None:
            metadata = get_xml_metadata(self.parse_schema_version)
            xml_namespace = xml_namespace or metadata['xml_namespace']
            xml_schema_location = xml_schema_location or metadata['xml_schema_location']
        self.filepath = str(filepath)
        self.root = autosar_obj
        self.header = ArxmlHeader(xml_namespace=xml_namespace, xml_schema_location=xml_schema_location)
        self.format = ArxmlFormat(indent=indent, leading_comments=leading_comments)
        self.scan_ref()
        return self

    def scan_ref(self) -> None:
        """沿用原扫描函数，只将结果包装为本文件的单个对象。"""
        objects, self.references, self.uuids = self.__scan_arobj_ref(self.root)
        self.objects = {ref: ArxmlObject(obj, self, ref) for ref, obj in objects.items()}

    def ref(self, ref: Ref) -> ArxmlObject[Any] | None:
        """按完整 AUTOSAR 路径查找当前文件中的对象。

        Args:
            ref: 由各级 SHORT-NAME 组成的路径元组，例如 ('Package', 'Type')，
                对应 XML 引用路径 /Package/Type；只匹配完整路径。

        Returns:
            找到时返回 ArxmlObject，通过其 .xml_obj 访问实际 XML 对象；
            路径不存在时返回 None。

        修改对象名称或结构后，应先调用 scan_ref() 更新索引再查询。
        """
        return self.objects.get(ref)

    def ar(self, clazz: type[T], ref_prefix: Ref = ()) -> list[ArxmlObject[T]]:
        """按 XML 对象类型和路径前缀查询当前文件中的对象。

        Args:
            clazz: 要查找的 AUTOSAR 类型，例如 autosar.SwBaseType，包含其子类。
            ref_prefix: 由各级 SHORT-NAME 组成的路径前缀；默认为 ()，查询整个文件。
                例如 ('Package',) 匹配该包自身及其所有层级的子对象，
                不匹配名称仅以 Package 开头的其他包。

        Returns:
            同时满足类型和路径条件的 ArxmlObject 列表，无匹配时返回空列表。
            每项的 .xml_obj 是实际 XML 对象，可直接读取或修改其属性。

        修改对象名称或结构后，应先调用 scan_ref() 更新索引再查询。
        """
        return [cast(ArxmlObject[T], obj) for ref, obj in self.objects.items() if ref[: len(ref_prefix)] == ref_prefix and isinstance(obj.xml_obj, clazz)]

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
                            if (_ref := ref_str2ref(i.value)) not in dict_search_obj_use_ref:
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
                    if (_ref := ref_str2ref(v.value)) not in dict_search_obj_use_ref:
                        dict_search_obj_use_ref[_ref] = [(v, ref)]
                    else:
                        dict_search_obj_use_ref[_ref].append((v, ref))
                cls.__scan_arobj_ref(v, ref, dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
        return dict_ref_from_short_name, dict_search_obj_use_ref, dict_uuid
