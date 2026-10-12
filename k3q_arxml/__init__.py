"""ARXML 编辑库；使用前通过 CLI 生成当前版本的 autosar 模块。"""

from .arxml_file import ArxmlFile
from .arxml_object import ArxmlObject
from .k3q_arxml import IOArxml, logger

__all__ = ['ArxmlFile', 'ArxmlObject', 'IOArxml', 'logger']
