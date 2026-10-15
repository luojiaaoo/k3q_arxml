import argparse
from pathlib import Path


def main() -> None:
    # 参数设置
    parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')
    ## 添加的后缀名
    parser.add_argument('-s', '--suffix', required=True, help='suffix')
    ## 需要修改的SOA Interface Name
    parser.add_argument('-a', '--soa_interface_name', required=True, nargs='+', help='SOA InterfaceName list')
    ## arxml文件
    parser.add_argument('arxml_files', nargs='+', type=Path, help='arxml file list')
    args = parser.parse_args()

    from k3q_arxml import ArxmlTransaction, IOArxml, autosar, logger, ref_str2ref
    from k3q_arxml.log import configure_logging

    configure_logging('DEBUG')

    suffix = args.suffix
    soa_interface_name = args.soa_interface_name
    has_change_adt_prefix = []

    io_arxml = IOArxml(filepaths=args.arxml_files)
    for arxml_obj_interface in io_arxml.ar(clazz=autosar.SenderReceiverInterface):
        ref_interface = arxml_obj_interface.ref
        if ref_interface[-1] not in soa_interface_name:  # 不在SOA接口列表中，检查之前是否添加了后缀
            for variable_data_prototype in arxml_obj_interface.xml_obj.data_elements.variable_data_prototype:
                # 遍历多个VARIABLE-DATA-PROTOTYPE，每一个VARIABLE-DATA-PROTOTYPE对应一个adt
                ref_obj = variable_data_prototype.type_tref
                # 没有修改过或者本次已经修改过的，都跳过去
                if not ref_obj.value.endswith(suffix):
                    continue
                if ref_obj.value.rsplit(suffix, 1)[0] in has_change_adt_prefix:
                    logger.debug(f'{ref_obj.value} has been changed before')
                    continue
                logger.debug(f'restore {ref_obj.value} to {ref_obj.value[: -len(suffix)]}')
                ref_need_change = ref_str2ref(ref_obj.value)
                # 先收集旧路径的引用，再统一修改和刷新。
                adt = io_arxml.ref(ref_need_change).xml_obj
                references = io_arxml.ref_to_ref(ref_need_change)
                with ArxmlTransaction() as transaction:
                    adt.short_name.value = adt.short_name.value[: -len(suffix)]
                    transaction.add(adt)
                    for reference in references:
                        reference.xml_obj.value = reference.xml_obj.value[: -len(suffix)]
                        transaction.add(reference.xml_obj)
        else:
            for variable_data_prototype in arxml_obj_interface.xml_obj.data_elements.variable_data_prototype:
                # 遍历多个VARIABLE-DATA-PROTOTYPE，每一个VARIABLE-DATA-PROTOTYPE对应一个adt
                ref_obj = variable_data_prototype.type_tref
                # 保存修改记录
                has_change_adt_prefix.append(ref_obj.value.rsplit(suffix, 1)[0])
                if ref_obj.value.endswith(suffix):  # 已经修改过了，跳过
                    logger.debug(f'{ref_obj.value} has been changed')
                    continue
                logger.debug(f'change {ref_obj.value} to {ref_obj.value}{suffix}')
                ref_need_change = ref_str2ref(ref_obj.value)
                # 先收集旧路径的引用，再统一修改和刷新。
                adt = io_arxml.ref(ref_need_change).xml_obj
                references = io_arxml.ref_to_ref(ref_need_change)
                with ArxmlTransaction() as transaction:
                    adt.short_name.value += suffix
                    transaction.add(adt)
                    for reference in references:
                        reference.xml_obj.value += suffix
                        transaction.add(reference.xml_obj)

    io_arxml.flush_to_file()


if __name__ == '__main__':
    main()
