from xsdata.formats.dataclass.context import XmlContext
from xsdata.formats.dataclass.parsers import XmlParser
from xsdata.formats.dataclass.parsers.config import ParserConfig
from xsdata.formats.dataclass.serializers import XmlSerializer
from xsdata.formats.dataclass.serializers.config import SerializerConfig
from typing import Union, List
import logging

logger = logging.getLogger(__name__)

class InputOutput:
    def __init__(self, clazz_autosar):
        self.xml_schema_location = None
        self.xml_namesapce = None
        self.xml_context = XmlContext()
        self.clazz_autosar = clazz_autosar

    def parse(self, filepath: Union[str, List]):
        logger.info(f'parsing {filepath}')
        parser = XmlParser(context=self.xml_context, config=ParserConfig())
        ns_map = {}
        from ..utilities.arxml_util import merge_arxml
        if isinstance(filepath, str):
            autosar = parser.parse(filepath, self.clazz_autosar, ns_map=ns_map)
        else:
            autosar = parser.from_bytes(merge_arxml(filepath), self.clazz_autosar, ns_map=ns_map)
        # auto get schema_location namespace
        if self.xml_namesapce is None:
            self.xml_namesapce = ns_map[None]
            with open(filepath if isinstance(filepath, str) else filepath[0], 'r', encoding='utf-8') as f:
                import re
                line_second = re.findall(r'"' + self.xml_namesapce + r' (.+?)"', ''.join([f.readline() for _ in range(3)]))
                self.xml_schema_location = line_second[0]
        return autosar

    def render(self, xml_obj):
        logger.info(f'rendering')
        serializer = XmlSerializer(self.xml_context, config=SerializerConfig(
            indent="  ",
            schema_location=f"{self.xml_namesapce} {self.xml_schema_location}",
            xml_declaration=True,
            ignore_default_attributes=True,
        ))
        return serializer.render(xml_obj, ns_map={None: self.xml_namesapce})
