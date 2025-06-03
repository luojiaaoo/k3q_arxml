import logging
from typing import List, Union, Optional, Dict, Tuple
from dataclasses import dataclass, fields
from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from .autosar import autosar_00048 as autosar

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)10s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)


class IOArxml:

    def __init__(self, filepaths: List[str]):
        self.filename_to_arxml: Dict[str, autosar.Autosar] = {}
        self.filename_to_ref: Dict[str, Dict] = {}
        self.filepaths = filepaths
        r4_schema_ver_suffix = ver if (ver := autosar.__name__.split('.')[-1])[-5:].isdigit() else ver.replace('_', '-')
        self.xml_schema_location = f'http://www.autosar.org/schema/r4.0 autosar_{r4_schema_ver_suffix}.xsd'
        self.xml_namespace = 'http://autosar.org/schema/r4.0'
        self.clazz = autosar.Autosar

    def parse(self):
        logger.info(f'############# parsing {" ".join(self.filepaths)}')
        xml_context = XmlContext()
        parser = XmlParser(context=xml_context, config=ParserConfig())
        for filepath in self.filepaths:
            logger.info(f'>> parsing {filepath}')
            ns_map = {}  # 保存命名空间的映射关系
            self.filename_to_arxml[filepath] = parser.parse(filepath, self.clazz, ns_map=ns_map)
            if (default_ns := ns_map[None]) != self.xml_namespace:  # 检查默认命名空间是否为预期的r4命名空间
                logger.error(f'{filepath} ns: {default_ns}')
        return self.filename_to_arxml

    def scan_refs(self):
        logger.info(f'############# scan cache {" ".join(self.filepaths)}')
        for filepath in self.filepaths:
            logger.info(f'>> scan cache {filepath}')
            self.filename_to_ref[filepath] = self.__scan_ref(self.filename_to_arxml[filepath])
        return self.filename_to_ref

    def create_arxml(self, filepath: str, arxml_obj: autosar.Autosar):
        logger.info(f'############# createing {filepath}')
        self.filename_to_arxml[filepath] = arxml_obj

    def flush_all(self):
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

    def print(self, print_filepath):
        import pprint
        with open(print_filepath, 'w', encoding='utf-8') as f:
            for filename, arxml_obj in self.filename_to_arxml.items():
                f.write(f'=== {filename} ===')
                pprint.pprint(arxml_obj, stream=f, width=999999, underscore_numbers=True)

    @classmethod
    def __scan_ref(cls, obj, ref=None, dict_top: Dict = None) -> Dict[str, dataclass]:
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
                    if hasattr(i, 'short_name'):
                        dict_top[ref + (i.short_name.value,)] = i
                        cls.__scan_ref(i, ref + (i.short_name.value,), dict_top)
                    else:
                        cls.__scan_ref(i, ref, dict_top)
            elif hasattr(v, 'short_name'):
                dict_top[ref + (v.short_name.value,)] = v
                cls.__scan_ref(v, ref + (v.short_name.value,), dict_top)
            else:
                cls.__scan_ref(v, ref, dict_top)
        return dict_top

# class Ref:
#     def __init__(self, io_arxml: IOArxml):
#         self.io_arxml = io_arxml
#
#     def get_arpkg_ref(self, io_arxml):
#         ref_to_ar_package = {}
#
#         def drill(obj, prefix=None):
#             if isinstance(obj, autosar.Autosar):  # 如果是Autosar对象，设置前缀为'/'
#                 prefix = '/'
#                 if hasattr(obj, 'ar_packages'):  # 如果有ar_packages，则继续下钻
#                     for i in obj.ar_packages.ar_package:
#                         drill(i, prefix)
#             else:  # 如果是ar_package对象
#                 prefix = f'{prefix}/{obj.short_name.value}'
#                 ref_to_ar_package[prefix] = obj
#                 if hasattr(obj, 'ar_packages'):  # 如果有ar_packages，则继续下钻
#                     for i in obj.ar_packages.ar_package:
#                         drill(i, prefix)
#
#         for filepath, arxml_obj in io_arxml.filename_to_arxml.items():
#             return io_arxml.filename_to_arxml[filepath]
#
#
# class Arxml:
#     def __init__(self, filepaths: List[str]):
#         self.io_arxml = IOArxml(filepaths)

#     @property
#     def refpath_to_ar_package(self, filepath):
#         _refpath_to_ar_package = {}

#         def drill(obj, prefix=None):
#             if isinstance(obj, autosar.Autosar):  # 如果是Autosar对象，设置前缀为'/'
#                 prefix = '/'
#                 if hasattr(obj, 'ar_packages'):  # 如果有ar_packages，则继续下钻
#                     for i in obj.ar_packages.ar_package:
#                         drill(i, prefix)
#             else:  # 如果是ar_package对象
#                 prefix = f'{prefix}/{obj.short_name.value}'
#                 _refpath_to_ar_package[prefix] = obj
#                 if hasattr(obj, 'ar_packages'):  # 如果有ar_packages，则继续下钻
#                     for i in obj.ar_packages.ar_package:
#                         drill(i, prefix)

#         for filepath, arxml_obj in self.io_arxml.filename_to_arxml.items():
#             return self.io_arxml.filename_to_arxml[filepath]
