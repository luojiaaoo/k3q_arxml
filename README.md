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
from pprint import pp # 可以美化打印对象，不然全打印在一行
import k3q_arxml
# 加载arxml文件
io_arxml = k3q_arxml.IOArxml(filepaths=['test/model_merge.arxml'])

# 打印arxml字符串绑定的python arxml实例
io_arxml.print(print_filepath='model_merge.txt')

# 刷新ref缓存数据，因为ref/ar/ref_to_ref/locate_filename访问的都是缓存数据，如果修改了数据后，影响到了ref，就需要主动刷新
io_arxml.scan_ref()

# 增/改
io_arxml.ref(('Implementations', 'HWIO')).resource_consumption = k3q_arxml.autosar.ResourceConsumption(
    short_name=k3q_arxml.autosar.Identifier(value='resourceConsumption'))

# 删
del io_arxml.ref(('Implementations', 'HWIO')).resource_consumption
io_arxml.ref(('Implementations', 'HWIO')).resource_consumption = None

# 查
## 根据ref查arxml实例
io_arxml.ref(('Implementations', 'HWIO'))
## 根据ref查哪些arxml实例用到了该ref
io_arxml.ref_to_ref(('Implementations', 'HWIO'))
## 根据标签查arxml实例（该需要带有short_name属性）
io_arxml.ar(clazz=k3q_arxml.autosar.ResourceConsumption)
## 根据标签查arxml实例，但限定ref路径下查找（该需要带有short_name属性）
io_arxml.ar(clazz=k3q_arxml.autosar.ResourceConsumption, ref_prefix=('Implementations',))

# 辅助函数
## 控制台打印uuid到ref的映射关系，能通过uuid快速定位ref路径，辅助编码
io_arxml.scan_ref(debug_uuid=True)
## 获取路径在那个arxml文件里
io_arxml.locate_filename(ref=('Implementations',))

# 切换autosar_00052版本，默认为autosar_00048
from autosar import autosar_00052
k3q_arxml.autosar = autosar_00052

# 回写到文件
io_arxml.flush_to_file()
```

> *技巧*
> 1. 手动添加完成后的arxml和原始arxml，都通过io_arxml.print函数打印在文件里
> 2. 通过对比软件对比源arxml和打印的arxml，找出需要修改的arxml内容
> 3. 该内容就是对象的定义代码，可以复制出来粘贴到代码里


