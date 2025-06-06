from src import k3q_arxml
from pprint import  pp

io_arxml = k3q_arxml.IOArxml(filepaths=['test/model_merge.arxml'])
io_arxml.ref(('Implementations', 'HWIO')).resource_consumption = k3q_arxml.autosar.ResourceConsumption(
    short_name=k3q_arxml.autosar.Identifier(value='resourceConsumption'))
io_arxml.ref(('Implementations', 'HWIO', 'src')).artifact_descriptors = k3q_arxml.autosar.Code.ArtifactDescriptors(
    autosar_engineering_object=[k3q_arxml.autosar.AutosarEngineeringObject()])
io_arxml.ref(('InterfaceTypes', 'HWIOInput', 'Read', 'Value')).type_tref.value = '/ImplementationTypes/SInt32'
io_arxml.ref_to_ref(ref=('Atomic', 'TQMS', 'TQMS'))
dict(io_arxml.ar(clazz=k3q_arxml.autosar.ResourceConsumption))
io_arxml.flush_to_file()
