# from k3q_arxml import IOArxml, autosar
from pathlib import Path
a = {Path('/aa'):111}
a[Path('aa')] = 222
print(a)