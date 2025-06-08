from k3q_arxml import IOArxml, autosar

io_arxml = IOArxml(filepaths=['test/model_merge.arxml'])
for ref_s, t_obj_ref, filename in io_arxml.ref_to_arxml_obj_ref.items():
    is_ApplicationDataTypeRef = False
    obj_s = io_arxml.ref(ref=ref_s).default
    for obj, _ in t_obj_ref:
        if isinstance(obj, autosar.DataTypeMap.ApplicationDataTypeRef):
            obj.value = obj.value + '_OIB'
            is_ApplicationDataTypeRef = True
    if is_ApplicationDataTypeRef:
        print(ref_s, '需要修改')
        obj_s.short_name.value = obj_s.short_name.value + '_OIB'
io_arxml.flush_to_file()
