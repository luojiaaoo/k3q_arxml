import argparse
from pathlib import Path


def main() -> None:
    # 参数设置
    parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')

    # arxml文件
    parser.add_argument('arxml_files', nargs='+', type=Path, help='arxml file list')

    args = parser.parse_args()

    from k3q_arxml import ArxmlTransaction, IOArxml, str2ref, ref2str
    from k3q_arxml.schemas.autosar_4_2_2 import autosar_4_2_2 as autosar
    from k3q_arxml.log import configure_logging

    for filepath in args.arxml_files:
        path = Path(filepath)
        content = path.read_text(encoding='utf-8')
        content = content.replace('ADT_', '')
        content = content.replace('IDT_', '')
        path.write_text(content, encoding='utf-8')

    configure_logging('DEBUG')

    io_arxml = IOArxml(filepaths=args.arxml_files, binding=autosar)

    # 修改adt
    for obj in io_arxml.ar(clazz=autosar.ApplicationPrimitiveDataType):
        ref_interface = obj.ref
        i = obj.xml_obj
        references = io_arxml.ref_to_ref(ref_interface)
        with ArxmlTransaction() as transaction:
            i.short_name.value = f'ADT_{i.short_name.value}'
            transaction.add(i)
            for reference in references:
                ref_obj = reference.xml_obj
                i = str2ref(ref_obj.value)
                ref_obj.value = ref2str([*i[:-1], f'ADT_{i[-1]}'])
                transaction.add(ref_obj)

    for obj in io_arxml.ar(clazz=autosar.ApplicationArrayDataType):
        ref_interface = obj.ref
        i = obj.xml_obj
        references = io_arxml.ref_to_ref(ref_interface)
        with ArxmlTransaction() as transaction:
            i.short_name.value = f'ADT_{i.short_name.value}'
            transaction.add(i)
            for reference in references:
                ref_obj = reference.xml_obj
                i = str2ref(ref_obj.value)
                ref_obj.value = ref2str([*i[:-1], f'ADT_{i[-1]}'])
                transaction.add(ref_obj)

    for obj in io_arxml.ar(clazz=autosar.ApplicationRecordDataType):
        ref_interface = obj.ref
        i = obj.xml_obj
        references = io_arxml.ref_to_ref(ref_interface)
        with ArxmlTransaction() as transaction:
            i.short_name.value = f'ADT_{i.short_name.value}'
            transaction.add(i)
            for reference in references:
                ref_obj = reference.xml_obj
                i = str2ref(ref_obj.value)
                ref_obj.value = ref2str([*i[:-1], f'ADT_{i[-1]}'])
                transaction.add(ref_obj)

    # 修改idt
    for obj in io_arxml.ar(clazz=autosar.ImplementationDataType):
        ref_interface = obj.ref
        i = obj.xml_obj
        references = io_arxml.ref_to_ref(ref_interface)
        with ArxmlTransaction() as transaction:
            i.short_name.value = f'IDT_{i.short_name.value}'
            transaction.add(i)
            for reference in references:
                ref_obj = reference.xml_obj
                i = str2ref(ref_obj.value)
                ref_obj.value = ref2str([*i[:-1], f'IDT_{i[-1]}'])
                transaction.add(ref_obj)

    io_arxml.flush_to_file()


if __name__ == '__main__':
    main()
