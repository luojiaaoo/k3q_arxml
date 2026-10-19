"""ARXML 编辑库；各版本类型通过 autosar_<版本> 模块独立导入。"""

from .arxml_file import ArxmlFile, get_xml_metadata, ref2str, str2ref
from .k3q_arxml import IOArxml
from .log import logger
from .schemas import ArxmlNamedNode, ArxmlNode, ArxmlRefNode
from .transaction import ArxmlTransaction

__all__ = ['ArxmlFile', 'ArxmlNamedNode', 'ArxmlNode', 'ArxmlRefNode', 'ArxmlTransaction', 'IOArxml', 'get_xml_metadata', 'logger', 'str2ref', 'ref2str']
