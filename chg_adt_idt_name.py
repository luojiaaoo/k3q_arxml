import argparse
import logging
from pathlib import Path

from k3q_arxml import change_autosar_version


# 参数设置
parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')

# arxml版本
parser.add_argument('-v', '--autosar_version', nargs='?', default='autosar_4_2_2', help='autosar version, default autosar_4_2_2')

# arxml文件
parser.add_argument('arxml_files', nargs='+', help='arxml file list')

args = parser.parse_args()


for filepath in args.arxml_files:
    path = Path(filepath)
    content = path.read_text(encoding='utf-8')
    content = content.replace('ADT_', '')
    content = content.replace('IDT_', '')
    path.write_text(content, encoding='utf-8')


change_autosar_version(args.autosar_version)

from k3q_arxml import IOArxml, autosar, logger


logger.level = logging.DEBUG


io_arxml = IOArxml(filepaths=args.arxml_files)


# 修改adt
for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.ApplicationPrimitiveDataType).items():
    for i, _ in arxml_obj_interface:
        i.short_name.value = f'ADT_{i.short_name.value}'
    for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
        i = io_arxml.ref_str2ref(ref_obj.value)
        ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'ADT_{i[-1]}'])


for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.ApplicationArrayDataType).items():
    for i, _ in arxml_obj_interface:
        i.short_name.value = f'ADT_{i.short_name.value}'
    for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
        i = io_arxml.ref_str2ref(ref_obj.value)
        ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'ADT_{i[-1]}'])


for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.ApplicationRecordDataType).items():
    for i, _ in arxml_obj_interface:
        i.short_name.value = f'ADT_{i.short_name.value}'
    for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
        i = io_arxml.ref_str2ref(ref_obj.value)
        ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'ADT_{i[-1]}'])


# 修改idt
for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.ImplementationDataType).items():
    for i, _ in arxml_obj_interface:
        i.short_name.value = f'IDT_{i.short_name.value}'
    for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
        i = io_arxml.ref_str2ref(ref_obj.value)
        ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'IDT_{i[-1]}'])


io_arxml.flush_to_file()
