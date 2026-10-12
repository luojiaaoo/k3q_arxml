import argparse
import logging
from pathlib import Path


def main() -> None:
    # 参数设置
    parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')

    # arxml文件
    parser.add_argument('arxml_files', nargs='+', help='arxml file list')

    args = parser.parse_args()

    from k3q_arxml import IOArxml, autosar, logger

    for filepath in args.arxml_files:
        path = Path(filepath)
        content = path.read_text(encoding='utf-8')
        content = content.replace('ADT_', '')
        content = content.replace('IDT_', '')
        path.write_text(content, encoding='utf-8')

    logger.level = logging.DEBUG

    io_arxml = IOArxml(filepaths=args.arxml_files)

    # 修改adt
    for ref_interface in dict.fromkeys(obj.ref for obj in io_arxml.ar(clazz=autosar.ApplicationPrimitiveDataType)):
        for obj in io_arxml.find(ref_interface):
            i = obj.xml_obj
            i.short_name.value = f'ADT_{i.short_name.value}'
        for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
            i = io_arxml.ref_str2ref(ref_obj.value)
            ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'ADT_{i[-1]}'])

    for ref_interface in dict.fromkeys(obj.ref for obj in io_arxml.ar(clazz=autosar.ApplicationArrayDataType)):
        for obj in io_arxml.find(ref_interface):
            i = obj.xml_obj
            i.short_name.value = f'ADT_{i.short_name.value}'
        for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
            i = io_arxml.ref_str2ref(ref_obj.value)
            ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'ADT_{i[-1]}'])

    for ref_interface in dict.fromkeys(obj.ref for obj in io_arxml.ar(clazz=autosar.ApplicationRecordDataType)):
        for obj in io_arxml.find(ref_interface):
            i = obj.xml_obj
            i.short_name.value = f'ADT_{i.short_name.value}'
        for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
            i = io_arxml.ref_str2ref(ref_obj.value)
            ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'ADT_{i[-1]}'])

    # 修改idt
    for ref_interface in dict.fromkeys(obj.ref for obj in io_arxml.ar(clazz=autosar.ImplementationDataType)):
        for obj in io_arxml.find(ref_interface):
            i = obj.xml_obj
            i.short_name.value = f'IDT_{i.short_name.value}'
        for ref_obj, ref, filename in io_arxml.ref_to_ref(ref_interface):
            i = io_arxml.ref_str2ref(ref_obj.value)
            ref_obj.value = io_arxml.ref2ref_str([*i[:-1], f'IDT_{i[-1]}'])

    io_arxml.flush_to_file()


if __name__ == '__main__':
    main()
