"""ARXML 编辑库；使用前通过 CLI 生成当前版本的 autosar 模块。"""

from .arxml_file import ArxmlFile, get_xml_metadata, ref2str, str2ref
from .k3q_arxml import IOArxml
from .log import logger
from .schemas import ArxmlNamedNode, ArxmlNode, ArxmlRefNode
from .transaction import ArxmlTransaction

__all__ = ['ArxmlFile', 'ArxmlNamedNode', 'ArxmlNode', 'ArxmlRefNode', 'ArxmlTransaction', 'IOArxml', 'get_xml_metadata', 'logger', 'str2ref', 'ref2str']
