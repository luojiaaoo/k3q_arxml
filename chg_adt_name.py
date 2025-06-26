import argparse

# 参数设置
parser = argparse.ArgumentParser(description='change ApplicationDataTypeRef name')
## 添加的后缀名
parser.add_argument('-s', '--suffix', required=True, help='suffix')
## arxml版本
parser.add_argument('-v', '--autosar_version', nargs='?', default='autosar_4_2_2', help='autosar version, default autosar_4_2_2')
## 需要修改的SOA Interface Name
parser.add_argument('-a', '--soa_interface_name', required=True, nargs='+', help='SOA InterfaceName list')
## arxml文件
parser.add_argument('arxml_files', nargs='+', help='arxml file list')
args = parser.parse_args()

from k3q_arxml import change_autosar_version

change_autosar_version(args.autosar_version)
from k3q_arxml import IOArxml, autosar, logger
import logging

logger.level = logging.DEBUG

suffix = args.suffix
soa_interface_name = args.soa_interface_name

io_arxml = IOArxml(filepaths=args.arxml_files)
for ref_interface, arxml_obj_interface in io_arxml.ar(clazz=autosar.SenderReceiverInterface).items():

    arxml_obj_interface: autosar.SenderReceiverInterface = arxml_obj_interface
    if ref_interface[-1] not in soa_interface_name:  # 不在SOA接口列表中，检查之前是否添加了后缀
        for variable_data_prototype in arxml_obj_interface.default.data_elements.variable_data_prototype:
            # 遍历多个VARIABLE-DATA-PROTOTYPE，每一个VARIABLE-DATA-PROTOTYPE对应一个adt
            ref_obj = variable_data_prototype.type_tref
            if not ref_obj.value.endswith(suffix):
                continue
            logger.debug(f'restore {ref_obj.value} to {ref_obj.value[:-len(suffix)]}')
            ref_need_change = io_arxml.ref_str2ref(ref_obj.value)
            # 修改ADT名字
            io_arxml.ref(ref_need_change).default.short_name.value = io_arxml.ref(ref_need_change).default.short_name.value[:-len(suffix)]
            # 修改用到这个ADT的引用
            for ref_ref_obj, _, _ in io_arxml.ref_to_ref(ref_need_change):
                ref_ref_obj.value = ref_ref_obj.value[:-len(suffix)]
    else:
        for variable_data_prototype in arxml_obj_interface.default.data_elements.variable_data_prototype:
            # 遍历多个VARIABLE-DATA-PROTOTYPE，每一个VARIABLE-DATA-PROTOTYPE对应一个adt
            ref_obj = variable_data_prototype.type_tref
            if ref_obj.value.endswith(suffix):  # 已经修改过了，跳过
                logger.debug(f'{ref_obj.value} has been changed')
                continue
            logger.debug(f'change {ref_obj.value} to {ref_obj.value}{suffix}')
            ref_need_change = io_arxml.ref_str2ref(ref_obj.value)
            # 修改ADT名字
            io_arxml.ref(ref_need_change).default.short_name.value += suffix
            # 修改用到这个ADT的引用
            for ref_ref_obj, _, _ in io_arxml.ref_to_ref(ref_need_change):
                ref_ref_obj.value += suffix

io_arxml.flush_to_file()
