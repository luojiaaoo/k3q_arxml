from typing import TYPE_CHECKING

from .k3q_arxml import IOArxml, autosar, logger
from .lazy_import import LazyImport

if TYPE_CHECKING:
    from .arxml_binding import (
        autosar_4_2_2,
        autosar_00043,
        autosar_00044,
        autosar_00045,
        autosar_00046,
        autosar_00047,
        autosar_00048,
        autosar_00049,
        autosar_00050,
        autosar_00051,
        autosar_00052,
    )
_arxml_binding = [
    'autosar_4_2_2',
    'autosar_00043',
    'autosar_00044',
    'autosar_00045',
    'autosar_00046',
    'autosar_00047',
    'autosar_00048',
    'autosar_00049',
    'autosar_00050',
    'autosar_00051',
    'autosar_00052',
]
__all__ = [
    'IOArxml',
    'autosar',
    'change_autosar_version',
    'logger',
    *_arxml_binding,
]

for name in _arxml_binding:
    globals()[name] = LazyImport(__package__ + '.arxml_binding.' + name)


def change_autosar_version(version: str) -> None:
    global autosar
    from . import k3q_arxml

    autosar = LazyImport(f'{__package__}.arxml_binding.{version}')
    k3q_arxml.autosar = autosar
