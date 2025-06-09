from k3q_arxml import IOArxml, autosar

io_arxml = IOArxml(filepaths=['test/model_merge.arxml'])
for ref_s, arxml_ref_obj_filename_ref in io_arxml.ref_to_arxml_ref_obj_filename_ref.items():
    is_ApplicationDataTypeRef = False
    obj_s = io_arxml.ref(ref=ref_s).default
    for arxml_ref_obj, filename, ref in arxml_ref_obj_filename_ref:
        if isinstance(arxml_ref_obj, autosar.DataTypeMap.ApplicationDataTypeRef):
            arxml_ref_obj.value = arxml_ref_obj.value + '_OIB'
            is_ApplicationDataTypeRef = True
    if is_ApplicationDataTypeRef:
        obj_s.short_name.value = obj_s.short_name.value + '_OIB'
io_arxml.flush_to_file()
