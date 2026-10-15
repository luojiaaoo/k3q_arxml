"""ARXML 数据模型及可用 AUTOSAR XSD 的发现。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Generic, Tuple, TypeAlias, TypeVar, cast

from pydantic import BaseModel
from xsdata.formats.dataclass.models.generics import DerivedElement
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from xsdata.formats.dataclass.serializers.writers import LxmlEventWriter
from xsdata.utils.namespaces import split_qname

if TYPE_CHECKING:
    from .autosar import Ref  # noqa: F401 -- 用于基类的前向引用。

TupleRef: TypeAlias = Tuple[str, ...]
Filepath: TypeAlias = Path
Uuid: TypeAlias = str
T = TypeVar('T')


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


@dataclass
class ArxmlNode(Generic[T]):
    """保存 ARXML 节点所在文件的路径和实际 XML 对象。"""

    filepath: Filepath
    xml_obj: T


@dataclass
class ArxmlNamedNode(ArxmlNode[T]):
    """带有 SHORT-NAME 的 ARXML 节点，xml_obj 为实际 XML 对象。

    ref 保存该包装上次登记的完整路径；作为 update_node() 入参时，成功后同步该节点的 ref。
    索引更新使用新包装，后续编辑子节点时重新查询其包装。
    """

    ref: TupleRef

    @property
    def content(self) -> str:
        """按需序列化当前 XML 节点及其子节点，不缓存 XML 字符串。"""
        serializer = XmlSerializer(config=SerializerConfig(xml_declaration=False, ignore_default_attributes=True), writer=LxmlEventWriter)
        qname = serializer.context.build(type(self.xml_obj)).target_qname
        namespace, _ = split_qname(qname)
        return serializer.render(DerivedElement(qname=qname, value=self.xml_obj), ns_map={None: namespace} if namespace else None)

    @property
    def short_name(self) -> str:
        return cast(str, getattr(self.xml_obj, 'short_name').value)


@dataclass
class ArxmlRefNode(ArxmlNode['Ref']):
    """一处反向引用，保存实际 XML 引用节点及其来源位置。

    Attributes:
        xml_obj: 实际 XML 引用节点，通过 .xml_obj.value 修改引用目标。
        filepath: 引用所在文件的路径。
        owner_ref: 包含该引用的最近具名对象的路径。
    """

    owner_ref: TupleRef


PACKAGE_ROOT = Path(__file__).resolve().parent
SCHEMA_ROOT = PACKAGE_ROOT / 'schemas'


def discover_schemas(root: Path = SCHEMA_ROOT) -> dict[str, Path]:
    """扫描 autosar_* 目录，只列出存在对应主 XSD 文件的版本。"""
    schemas = {}
    for directory in sorted(root.glob('autosar_*')):
        version = directory.name.removeprefix('autosar_')
        schema = directory / f'AUTOSAR_{version.replace("_", "-")}.xsd'
        if schema.is_file():
            schemas[version.replace('_', '.')] = schema
    return schemas


SCHEMAS = discover_schemas()
