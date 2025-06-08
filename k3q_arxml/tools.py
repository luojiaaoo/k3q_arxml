## 直接搜索代码中的dest: Optional字符串
import os

def to_pascal_case(input_string):
    words = input_string.split('-')
    pascal_case_words = [word.capitalize() for word in words]
    pascal_case_string = ''.join(pascal_case_words)
    return pascal_case_string
def get_leaf_clazz(_autosar):
    version = _autosar.__package__.split('.')[-1]
    filepath = os.path.join(os.path.dirname(__file__),'arxml_binding',version,version + '.py')
    with open(filepath,'r') as f:
        last_line = ''
        for line in f.readlines():
            line = line.strip()
            if line.startswith('dest: Optional') and last_line.startswith('class') and last_line.endswith('Ref(Ref):'):
                enum_clazz_name = line.split('[')[-1].split(']')[0]
                for i in eval(f'_autosar.{enum_clazz_name}'):
                    try:
                        eval(f'_autosar.{to_pascal_case(i.value)}')
                    except:
                        print(enum_clazz_name, i.value)
            last_line = line
    