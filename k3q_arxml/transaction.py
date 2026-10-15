"""收集 XML 对象，在上下文正常退出时统一通知编辑完成。"""

from __future__ import annotations

from types import TracebackType
from typing import Any, Self


class ArxmlTransaction:
    """延迟调用 edited()；不回滚对象修改，也不自动保存文件。

    正常退出时按添加顺序执行；某次 edited() 失败会停止后续调用，已完成的刷新保留。
    """

    def __init__(self) -> None:
        self._pending: dict[int, tuple[Any, bool]] = {}

    def add(self, xml_obj: Any, refresh_index: bool = True) -> None:
        """加入实际 XML 对象；重复添加只执行一次，任一次要求刷新就刷新索引。"""
        key = id(xml_obj)
        previous = self._pending.get(key)
        self._pending[key] = (xml_obj, refresh_index or (previous is not None and previous[1]))

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc_value: BaseException | None, traceback: TracebackType | None) -> None:
        try:
            if exc_type is None:
                for xml_obj, refresh_index in self._pending.values():
                    xml_obj.edited(refresh_index=refresh_index)
        finally:
            self._pending.clear()
