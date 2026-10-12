from k3q_arxml import IOArxml, autosar

io_arxml = IOArxml(filepaths=['test/model_merge.arxml'])
io_arxml.ref(('Implementations', 'HWIO')).xml_obj.resource_consumption = autosar.ResourceConsumption(short_name=autosar.Identifier(value='resourceConsumption'))
io_arxml.ref(('Implementations', 'HWIO', 'src')).xml_obj.artifact_descriptors = autosar.Code.ArtifactDescriptors(autosar_engineering_object=[autosar.AutosarEngineeringObject()])
io_arxml.ref(('InterfaceTypes', 'HWIOInput', 'Read', 'Value')).xml_obj.type_tref.value = '/ImplementationTypes/SInt32'
io_arxml.ref_to_ref(ref=('Atomic', 'TQMS', 'TQMS'))
io_arxml.ar(clazz=autosar.ResourceConsumption)
io_arxml.flush_to_file()
