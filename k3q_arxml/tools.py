from dataclasses import is_dataclass, fields
from typing import get_origin, get_args, Union, List, Optional, Any


# 有一个非常复杂的dataclass嵌套，我想知道A对象的子对象是否有short_name属性，这个子对象通过typing查找，但是我需要把所有的typing拆开遍历一遍，可能涉及list Union Optional，怎么保证可以遍历完
from typing import get_args, get_origin, List, Union, Optional, Type
from dataclasses import is_dataclass, fields

def has_short_name_attribute(obj):
    # if hasattr(obj, 'short_name'):
    #     return True
    for field in fields(obj):
        if has_short_name_in_field(field.type):
            print(field)
            return True
    return False

def has_short_name_in_field(field_type):
    origin = get_origin(field_type)
    if origin is None:
        # Base type
        if is_dataclass(field_type):
            if hasattr(field_type, 'short_name'):
                return True
            for sub_field in fields(field_type):
                if has_short_name_in_field(sub_field.type):
                    return True
        return False
    elif origin is Union or origin is Union:
        # Union type
        for arg in get_args(field_type):
            if has_short_name_in_field(arg):
                return True
        return False
    elif origin is list or origin is List:
        # List type
        arg = get_args(field_type)[0]
        return has_short_name_in_field(arg)
    elif origin is type(None):
        # None type
        return False
    else:
        raise TypeError(f"Unsupported type: {origin}")


def is_leaf(clazz):
    return not has_short_name_attribute(clazz)

import dataclasses
from typing import Type, List
import sys

def find_dataclasses_with_dest_and_ref(module) -> List[Type]:
    result = []
    for name, obj in vars(module).items():
        if dataclasses.is_dataclass(obj):
            if name.endswith('Ref'):
                if any(field.name == 'dest' for field in dataclasses.fields(obj)):
                    result.append(obj)
            result.extend(find_nested_dataclasses_with_dest_and_ref(obj))
    return result

def find_nested_dataclasses_with_dest_and_ref(cls) -> List[Type]:
    result = []
    for field in dataclasses.fields(cls):
        field_type = field.type
        if dataclasses.is_dataclass(field_type):
            if field_type.__name__.endswith('Ref'):
                if any(f.name == 'dest' for f in dataclasses.fields(field_type)):
                    result.append(field_type)
            result.extend(find_nested_dataclasses_with_dest_and_ref(field_type))
    return result




def find_all_ref_xml_obs(clazz):
    matching_classes = find_dataclasses_with_dest_and_ref(clazz)
    for cls in matching_classes:
        print(cls.__name__)