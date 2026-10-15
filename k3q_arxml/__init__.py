"""ARXML 编辑库；使用前通过 CLI 生成当前版本的 autosar 模块。"""

from .arxml_file import ArxmlFile, get_xml_metadata, ref_str2ref, ref2ref_str
from .arxml_object import ArxmlObject, ArxmlReference
from .k3q_arxml import IOArxml
from .log import logger

__all__ = ['ArxmlFile', 'ArxmlObject', 'ArxmlReference', 'IOArxml', 'get_xml_metadata', 'logger', 'ref_str2ref', 'ref2ref_str']
