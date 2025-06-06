import inspect
import logging
import pprint
from collections.abc import Iterable
from enum import Enum
from typing import List, Dict, Tuple, TypeAlias, Any
from typing import TYPE_CHECKING

from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.parsers.handlers import LxmlEventHandler
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from xsdata.formats.dataclass.serializers.writers import LxmlEventWriter

from .lazy_import import LazyImport

autosar = LazyImport(f'{__package__}.autosar.autosar_00048')
if TYPE_CHECKING:
    from .autosar import autosar_00048 as autosar

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)10s | %(name)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger(__name__)

Filename: TypeAlias = str
Ref: TypeAlias = Tuple[str, ...]
Uuid: TypeAlias = str


class IOArxml:
    def __init__(self, filepaths: List[Filename]):
        # 储存文件对应的xml实例
        self.filename_to_arxml: Dict[Filename, autosar.Autosar] = {}
        # 储存ref path对应的文件名，非实时，需要scan_ref更新
        self.ref_to_filename: Dict[Ref, Filename] = {}
        # 储存ref path对应的xml实例，非实时，需要scan_ref更新
        self.ref_to_arxml_obj: Dict[Ref, Any] = {}
        # 搜索哪些ref path引用到了输入参数的ref path，返回refA->（用到refA的RefB->RefB的Ref标签xml实例）的嵌套字典，需要scan_ref更新
        self.ref_to_arxml_obj_ref: Dict[Ref, List[Tuple[Any, Ref]]] = {}
        self.filepaths = filepaths
        r4_schema_ver_suffix = ver if (ver := autosar.__name__.split('.')[-1])[-5:].isdigit() else ver.replace('_', '-')
        self.xml_schema_location = f'http://www.autosar.org/schema/r4.0 autosar_{r4_schema_ver_suffix}.xsd'
        self.xml_namespace = 'http://autosar.org/schema/r4.0'
        self.clazz = autosar.Autosar
        self.parse()
        self.scan_ref()

    def parse(self):
        logger.info(f'############# Parse {" ".join(self.filepaths)}')
        xml_context = XmlContext()
        parser = XmlParser(context=xml_context, config=ParserConfig(), handler=LxmlEventHandler)
        for filepath in self.filepaths:
            logger.info(f'>> parsing {filepath}')
            ns_map = {}  # 保存命名空间的映射关系
            self.filename_to_arxml[filepath] = parser.parse(filepath, self.clazz, ns_map=ns_map)
            if (default_ns := ns_map[None]) != self.xml_namespace:  # 检查默认命名空间是否为预期的r4命名空间
                logger.error(f'{filepath} ns: {default_ns}')
        return self.filename_to_arxml

    def ref(self, ref: Tuple[str, ...]) -> Any:
        """根据ref path返回xml实例"""
        find_ref = lambda t: self.ref_to_arxml_obj.get(t, None)
        return find_ref(ref)

    def ref_to_ref(self, ref: Tuple[str, ...]) -> List[Tuple[Any, Ref]]:
        """
        搜索哪些ref path引用到了输入参数的ref path，返回refA->（用到refA的RefB->RefB的Ref标签xml实例）的嵌套字典
        可能因为人为添加引用，导致更新filename_to_ref2ref未更新，默认强制每次都全局搜索一遍
        """
        find_ref2ref = lambda t: self.ref_to_arxml_obj_ref.get(t, [])
        return find_ref2ref(ref)

    def ar(self, clazz, ref_prefix: Tuple[str, ...] = tuple()) -> Dict[Ref, Any]:
        """根据类对象和ref前缀搜索对应的（ref字符串，xml实例）组成的字典"""
        find_clazz = lambda t: {ref: ref_to_arxml_obj for ref, ref_to_arxml_obj in self.ref_to_arxml_obj.items() if
                                ref[: len(t)] == t and isinstance(ref_to_arxml_obj, clazz)}
        return find_clazz(ref_prefix)

    def locate_filename(self, ref: Ref) -> Filename:
        """根据ref path返回文件名"""
        return self.ref_to_filename[ref]

    def scan_ref(self, debug_uuid=False) -> None:
        """搜索所有ref path"""
        stack = inspect.stack()
        caller_name = stack[1].function
        logger.info(f'############# Scan ref, trigger by {caller_name}')
        filename_to_uuid: Dict[Filename, Dict[Uuid, Ref]] = {}
        self.ref_to_filename: Dict[Ref, Filename] = {}
        self.ref_to_arxml_obj: Dict[Ref, Any] = {}
        for filepath in self.filepaths:
            ref2obj, ref_to_obj_ref, uuid2ref = self.__scan_arobj_ref(self.filename_to_arxml[filepath])
            filename_to_uuid[filepath] = uuid2ref
            for ref, obj in ref2obj.items():
                if ref in self.ref_to_filename:
                    logger.error(f'{filepath} ref {ref} already exists in {self.ref_to_filename[ref]}')
                    raise ValueError()
                self.ref_to_filename[ref] = filepath
                self.ref_to_arxml_obj[ref] = obj
            self.ref_to_arxml_obj_ref = ref_to_obj_ref
        if debug_uuid:
            pprint.pp(filename_to_uuid)
        logger.info('############# Scan ref is done')

    def create_arxml(self, filepath: Filename, arxml_obj: autosar.Autosar) -> None:
        logger.info(f'############# Create {filepath}')
        self.filepaths.append(filepath)
        self.filename_to_arxml[filepath] = arxml_obj

    def flush_to_file(self):
        logger.info('############# Flush to arxml file')
        xml_context = XmlContext()
        serializer = XmlSerializer(
            xml_context,
            config=SerializerConfig(
                indent='  ',
                schema_location=self.xml_schema_location,
                xml_declaration=True,
                ignore_default_attributes=True,
            ),
            writer=LxmlEventWriter,
        )
        for filepath, arxml_obj in self.filename_to_arxml.items():
            with open(filepath, 'w', encoding='utf-8') as f:
                logger.info(f'>> Flushing {filepath}')
                arxml_content = serializer.render(arxml_obj, ns_map={None: self.xml_namespace})
                f.write(arxml_content)

    def print(self, print_filepath: Filename = None):
        logger.info(f'############# Printing python format to {print_filepath}')
        if print_filepath is None:
            for filename, arxml_obj in self.filename_to_arxml.items():
                pprint.pprint(arxml_obj, width=40, indent=1, underscore_numbers=True)
        else:
            with open(print_filepath, 'w', encoding='utf-8') as f:
                for filename, arxml_obj in self.filename_to_arxml.items():
                    f.write(f'=== {filename} ===\n')
                    pprint.pprint(arxml_obj, stream=f, width=40, indent=1, underscore_numbers=True)

    @staticmethod
    def ref_str2ref(ref_str: str) -> Ref:
        """将ref字符串转为ref元组"""
        return tuple(ref_str.split('/')[1:])

    @staticmethod
    def ref2ref_str(ref: Ref) -> str:
        """将ref字符串转为ref元组"""
        return '/' + '/'.join(ref)

    @classmethod
    def __scan_arobj_ref(
            cls, obj, ref=None, dict_ref_from_short_name=None, dict_uuid=None, dict_search_obj_use_ref=None
    ) -> Tuple[Dict[Ref, Any], Dict[Ref, List[Tuple[Any, Ref]]], Dict[Uuid, Ref]]:
        if dict_ref_from_short_name is None:
            dict_ref_from_short_name = {}
            dict_search_obj_use_ref = {}
            dict_uuid = {}
        if ref is None:
            ref = tuple()

        def _vars(_obj):
            try:
                return vars(_obj)
            except:
                return {}

        for k, v in _vars(obj).items():
            if callable(v) or v is None or isinstance(v, (int, float, str, bool, Enum)):
                continue
            # print(type(v))
            elif isinstance(v, Iterable):
                for i in v:
                    if hasattr(i, 'short_name') and 'autosar' in i.__class__.__module__:  # 搜索short_name节点
                        dict_ref_from_short_name[ref + (i.short_name.value,)] = i
                        if hasattr(i, 'uuid'):
                            dict_uuid[i.uuid] = ref + (i.short_name.value,)
                        cls.__scan_arobj_ref(i, ref + (i.short_name.value,), dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
                    else:
                        if hasattr(i, 'value') and hasattr(i, 'dest') and type(i).__name__.endswith('Ref'):  # ref实例
                            if (_ref := cls.ref_str2ref(i.value)) not in dict_search_obj_use_ref:
                                dict_search_obj_use_ref[_ref] = [(i, ref)]
                            else:
                                dict_search_obj_use_ref[_ref].append((i, ref))
                        cls.__scan_arobj_ref(i, ref, dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
            elif hasattr(v, 'short_name') and 'autosar' in v.__class__.__module__:  # 搜索short_name节点
                dict_ref_from_short_name[ref + (v.short_name.value,)] = v
                if hasattr(v, 'uuid'):
                    dict_uuid[v.uuid] = ref + (v.short_name.value,)
                cls.__scan_arobj_ref(v, ref + (v.short_name.value,), dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
            else:
                if hasattr(v, 'value') and hasattr(v, 'dest') and type(v).__name__.endswith('Ref'):  # ref实例
                    if (_ref := cls.ref_str2ref(v.value)) not in dict_search_obj_use_ref:
                        dict_search_obj_use_ref[_ref] = [(v, ref)]
                    else:
                        dict_search_obj_use_ref[_ref].append((v, ref))
                cls.__scan_arobj_ref(v, ref, dict_ref_from_short_name, dict_uuid, dict_search_obj_use_ref)
        return dict_ref_from_short_name, dict_search_obj_use_ref, dict_uuid
