from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from k3q_arxml import autosar


def print_arxml_obj(filepath):
    xml_context = XmlContext()
    clazz = autosar.Autosar
    parser = XmlParser(context=xml_context, config=ParserConfig())
    ns_map = {}  # 保存命名空间的映射关系
    print(parser.parse(filepath, clazz, ns_map=ns_map))
