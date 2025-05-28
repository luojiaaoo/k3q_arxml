from pyarxml.autosar.input_output import InputOutput
from typing import Literal, List, Union, Optional, Dict, Tuple
from dataclasses import dataclass

import logging

logger = logging.getLogger(__name__)

autosar_version_literal = Literal[
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
    'autosar_00052'
]

# autosar = None

import os, sys

# 测试
lib_path = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(lib_path)
from pyarxml.autosar.autosar_4_2_2 import autosar_4_2_2 as autosar


class AutosarParam:
    ver: autosar_version_literal = None

    @classmethod
    def init(cls, autosar_version):
        global autosar
        cls.ver = autosar_version
        import importlib
        autosar = importlib.import_module(f'pyarxml.autosar.{autosar_version}.{autosar_version}')


class Arxml:

    def __init__(self, autosar_version: autosar_version_literal):
        AutosarParam.init(autosar_version=autosar_version)
        self.in_out = InputOutput(autosar.Autosar)

    def read_arxml(self, filepath: Union[List, str]) -> autosar.Autosar:
        '''parse arxml'''
        return self.in_out.parse(filepath)

    @staticmethod
    def get_ar_package(obj: Union[autosar.Autosar, autosar.ArPackage], short_name: str) -> Optional[autosar.ArPackage]:
        '''get obj of ar_package by short name'''

        def _get_ar_package(_obj, _short_name: str):
            for _ar_package in _obj.ar_packages.ar_package:
                if _ar_package.short_name.value == _short_name:
                    return _ar_package

        ar_package = _get_ar_package(obj, short_name)

        # 注入sub_ar_package方法
        def sub_ar_package(self, short_name) -> Optional[autosar.ArPackage]:
            return _get_ar_package(self, short_name)

        import types
        if ar_package is not None:
            ar_package.sub_ar_package = types.MethodType(sub_ar_package, ar_package)
        return ar_package

    @classmethod
    def get_dict_ref_obj(cls, obj, ref=None, dict_top: Dict = None) -> Dict[str, dataclass]:
        if dict_top is None:
            dict_top = {}
        if ref is None:
            ref = tuple()

        def _vars(_obj):
            try:
                return vars(_obj)
            except:
                return {}

        for k, v in _vars(obj).items():
            if callable(v):
                continue
            elif isinstance(v, List):
                for i in v:
                    if 'short_name' in _vars(i):
                        dict_top[ref + (i.short_name.value,)] = i
                        cls.get_dict_ref_obj(i, ref + (i.short_name.value,), dict_top)
                    else:
                        cls.get_dict_ref_obj(i, ref, dict_top)
            elif 'short_name' in _vars(v):
                dict_top[ref + (v.short_name.value,)] = v
                cls.get_dict_ref_obj(v, ref + (v.short_name.value,), dict_top)
            else:
                cls.get_dict_ref_obj(v, ref, dict_top)
        return dict_top

    @staticmethod
    def ref2str(ref: dataclass) -> str:
        return '/' + '/'.join(ref)

    @classmethod
    def get_all_ref_str(cls, dict_ref: Dict[str, dataclass]) -> List[str]:
        return [cls.ref2str(i) for i in dict_ref]

    @classmethod
    def retrieve_obj_based_on_ref_str(cls, dict_ref: Dict[str, dataclass], ref_str: str) -> Optional[dataclass]:
        for _ref, _obj in dict_ref.items():
            if cls.ref2str(_ref) == ref_str:
                return _obj
        return None
