import argparse

# 参数设置
parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')
## arxml版本
parser.add_argument('-v', '--autosar_version', nargs='?', default='autosar_4_2_2', help='autosar version, default autosar_4_2_2')
## arxml文件
parser.add_argument('arxml_files', nargs='+', help='arxml file list')
args = parser.parse_args()
import pprint
from k3q_arxml import change_autosar_version

change_autosar_version(args.autosar_version)
from k3q_arxml import IOArxml, autosar, logger
import logging

logger.level = logging.DEBUG
io_arxml = IOArxml(filepaths=args.arxml_files)
# 修改adt
for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.ApplicationPrimitiveDataType).items():
    arxml_obj_interface.default.short_name.value = f'ADT_{arxml_obj_interface.default.short_name.value}'
    for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
        ref_obj.value = io_arxml.ref2ref_str([*((i := io_arxml.ref_str2ref(ref_obj.value))[:-1]), f'ADT_{i[-1]}'])

# 修改idt
for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.ImplementationDataType).items():
    arxml_obj_interface.default.short_name.value = f'IDT_{arxml_obj_interface.default.short_name.value}'
    for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
        ref_obj.value = io_arxml.ref2ref_str([*((i := io_arxml.ref_str2ref(ref_obj.value))[:-1]), f'IDT_{i[-1]}'])

io_arxml.flush_to_file()
