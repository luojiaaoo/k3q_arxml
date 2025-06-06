from src import k3q_arxml
from pprint import  pp

io_arxml = k3q_arxml.IOArxml(filepaths=['test/model_merge.arxml'])
for ref_s, ref_t2obj in io_arxml.ref_to_ref2arxml_obj.items():
    is_ApplicationDataTypeRef = False
    obj_s = io_arxml.ref(ref=ref_s)
    for _, obj in ref_t2obj.items():
        if isinstance(obj, k3q_arxml.autosar.DataTypeMap.ApplicationDataTypeRef):
            obj.value = obj.value+'_OIB'
            is_ApplicationDataTypeRef = True
    if is_ApplicationDataTypeRef:
        print(ref_s,'需要修改')
        obj_s.short_name.value = obj_s.short_name.value+'_OIB'
io_arxml.flush_to_file()