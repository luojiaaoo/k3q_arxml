<p align="center">
	<img alt="logo" src="logo.png" style="width: 128px; height: 128px;">
</p>
<h1 align="center" style="margin: 30px 0 30px; font-weight: bold;">k3q_arxml</h1>
<p align="center">
    <a href="https://gitee.com/luojiaaoo/k3q_arxml"><img src="https://gitee.com/luojiaaoo/k3q_arxml/badge/star.svg?theme=dark"></a>
    <a href="https://github.com/luojiaaoo/k3q_arxml"><img src="https://img.shields.io/github/stars/luojiaaoo/k3q_arxml?style=social"></a>
    <img src="https://img.shields.io/badge/license-Apache%20License%202.0-blue.svg">
    <img src="https://img.shields.io/badge/python-=3.11-blue">
</p>

## 介绍

极简的arxml编辑库，纯python实现

## 用法

```python
# 导入pprint模块的pp函数，用于美化打印对象
# Import the pp function from pprint module for pretty-printing objects
from pprint import pp  

# 导入k3q_arxml库
# Import k3q_arxml library
import k3q_arxml

# 创建一个IOArxml实例，加载指定的ARXML文件（test/model_merge.arxml）
# Create an IOArxml instance and load specified ARXML file (test/model_merge.arxml)
io_arxml = k3q_arxml.IOArxml(filepaths=['test/model_merge.arxml'])

# 将ARXML文件的内容打印到控制台或保存到文件（model_merge.txt）
# Print ARXML content to console or save to file (model_merge.txt)
io_arxml.print(print_filepath='model_merge.txt')

# 刷新引用缓存数据。如果修改了数据并影响了引用关系，需要调用此方法更新缓存
# Refresh reference cache. Call this after modifications that affect references
io_arxml.scan_ref()

# 在路径('Implementations', 'HWIO')下添加或修改resource_consumption属性
# Add/modify resource_consumption under path ('Implementations', 'HWIO')
io_arxml.ref(('Implementations', 'HWIO')).default.resource_consumption = k3q_arxml.autosar.ResourceConsumption(
    short_name=k3q_arxml.autosar.Identifier(value='resourceConsumption'))

# 两种方式删除resource_consumption属性：1.使用del语句 2.将其设置为None
# Two ways to delete resource_consumption: 1. del statement 2. Set to None
del io_arxml.ref(('Implementations', 'HWIO')).default.resource_consumption
io_arxml.ref(('Implementations', 'HWIO')).default.resource_consumption = None

# 根据引用路径('Implementations', 'HWIO')查询对应的ARXML实例
# Query ARXML instance by reference path ('Implementations', 'HWIO')
io_arxml.ref(('Implementations', 'HWIO'))

# 查询哪些ARXML实例引用了路径('Implementations', 'HWIO')
# Find which instances reference path ('Implementations', 'HWIO')
io_arxml.ref_to_ref(('Implementations', 'HWIO'))

# 查询所有ResourceConsumption类型的实例
# Find all instances of ResourceConsumption type
io_arxml.ar(clazz=k3q_arxml.autosar.ResourceConsumption)

# 在路径('Implementations',)下查询ResourceConsumption类型的实例
# Find ResourceConsumption instances under path ('Implementations',)
io_arxml.ar(clazz=k3q_arxml.autosar.ResourceConsumption, ref_prefix=('Implementations',))

# 打印UUID与引用路径的映射关系，便于通过UUID快速定位引用路径
# Print UUID-to-reference mapping for debugging reference paths
io_arxml.scan_ref(debug_uuid=True)

# 将AUTOSAR版本从默认的autosar_00048切换到autosar_00052
# Switch AUTOSAR version from default autosar_00048 to autosar_00052
from k3q_arxml import change_autosar_version
change_autosar_version('autosar_4_2_2')
from k3q_arxml import IOArxml, autosar # 此时导入就是新版本的autosar

# 将修改后的数据写回原始ARXML文件
# Write modified data back to original ARXML file
io_arxml.flush_to_file()
```

> *技巧*
> 1. 手动添加完成后的arxml和原始arxml，都通过io_arxml.print函数打印在文件里
> 2. 通过对比软件对比源arxml和打印的arxml，找出需要修改的arxml内容
> 3. 该内容就是对象的定义代码，可以复制出来粘贴到代码里


