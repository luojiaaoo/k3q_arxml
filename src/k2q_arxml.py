import logging
from typing import List, Union, Optional, Dict
from dataclasses import dataclass
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from .autosar import autosar_00045 as autosar


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)10s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


class ReadArxml:
    filename_to_arxml = dict()

    def __init__(self):
        r4_schema_ver_suffix = ver if (ver := autosar.__name__.split('.')[-1])[-5:].isdigit() else ver.replace('_', '-')
        self.xml_schema_location = f'http://www.autosar.org/schema/r4.0 autosar_{r4_schema_ver_suffix}.xsd'
        self.xml_namespace = 'http://autosar.org/schema/r4.0'
        self.clazz = autosar.Autosar

    def parse(self, filepaths: List) -> Dict[str, autosar.Autosar]:
        logger.info(f'############# parsing {" ".join(filepaths)}')
        xml_context = XmlContext()
        parser = XmlParser(context=xml_context, config=ParserConfig())
        for filepath in filepaths:
            logger.info(f'>> parsing {filepath}')
            ns_map = {}  # 保存命名空间的映射关系
            self.filename_to_arxml[filepath] = parser.parse(filepath, self.clazz, ns_map=ns_map)
            if (default_ns := ns_map[None]) != self.xml_namespace:  # 检查默认命名空间是否为预期的r4命名空间
                logger.error(f'{filepath} ns: {default_ns}')
        return self.filename_to_arxml

    def flush(self):
        logger.info('############# Flushing cache to arxml file')
        xml_context = XmlContext()
        serializer = XmlSerializer(
            xml_context,
            config=SerializerConfig(
                indent='  ',
                schema_location=self.xml_schema_location,
                xml_declaration=True,
                ignore_default_attributes=True,
            ),
        )
        for filepath, arxml_obj in self.filename_to_arxml.items():
            with open(filepath, 'w', encoding='utf-8') as f:
                logger.info(f'>> Flushing {filepath}')
                arxml_content = serializer.render(arxml_obj, ns_map={None: self.xml_namespace})
                f.write(arxml_content)


class Arxml:
    def read_arxml(self, filepath: Union[List, str]) -> autosar.Autosar:
        """parse arxml"""
        return self.in_out.parse(filepath)

    @staticmethod
    def get_ar_package(obj: Union[autosar.Autosar, autosar.ArPackage], short_name: str) -> Optional[autosar.ArPackage]:
        """get obj of ar_package by short name"""

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
