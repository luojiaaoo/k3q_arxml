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

极简的 ARXML 编辑库，使用 Python、xsdata 和 lxml 实现。

代码分三层：`ArxmlObject` 包装一个节点，`ArxmlFile` 负责单个文件的解析、扫描和保存，`IOArxml` 负责管理多个文件和汇总查询结果。

## 安装与生成类型

项目使用 [uv](https://docs.astral.sh/uv/getting-started/installation/) 管理环境。在仓库根目录执行：

```console
uv sync --locked
uv run python -m k3q_arxml versions
uv run python -m k3q_arxml generate 4.2.2
```

仓库保留所有版本的 XSD，位于 `k3q_arxml/schemas/`，不再预生成、提交所有版本的 Python 绑定。生成命令使用 Click 实现，可在 Windows、Linux 和 macOS 上使用。

- 可用版本从 `schemas/autosar_*` 目录自动查找，以 `versions` 命令输出为准。新增版本时，放入对应的目录和主 XSD 即可，例如 `autosar_00053/AUTOSAR_00053.xsd`，无需修改版本列表。
- 每次只生成指定版本，输出为真实的 `k3q_arxml/autosar.py`，支持 IDE 补全和静态类型检查。
- 当前绑定未生成时，CLI 的帮助、版本列表和生成命令仍可使用；创建 `IOArxml` 会提示先生成。
- 生成成功后替换当前绑定；生成失败保留原有绑定。生成文件已加入 Git 忽略规则。
- 更换版本只需重新运行生成命令，例如 `uv run python -m k3q_arxml generate 00048`。随后使用新的 Python 进程；IDE 如仍显示旧类型，刷新语言服务。
- 选择与输入 ARXML 的 schema 相匹配的版本。当前只使用一个生成版本，不再提供 `change_autosar_version()`、旧版模块入口或懒加载代理。
- 导入文件时先核对 `xsi:schemaLocation` 声明的 AUTOSAR XSD 与当前绑定版本；版本不一致或缺少声明时抛出 `ValueError`，不会自动切换版本。

Python 开发版本固定为 3.11，运行依赖使用 xsdata 26.2、lxml 5.4.0 和 Click 8.2.1。Ruff 0.13.3 与 xsdata 的生成配置兼容。暂不配置包构建，从仓库根目录执行命令。

日志使用 Loguru，配置集中在 `k3q_arxml/log.py`，默认输出 INFO 及以上日志。需要调试输出时调用 `from k3q_arxml.log import configure_logging`，再执行 `configure_logging('DEBUG')`。

## 使用

先生成与仓库样例匹配的 4.2.2 绑定，再运行以下代码：

```python
from k3q_arxml import IOArxml, autosar

io_arxml = IOArxml(
    filepaths=['test/ThrottlePositionControlComposition.arxml'],
)

# 找出文件中所有的基础数据类型（XML 中的 SW-BASE-TYPE 节点）。
base_types = io_arxml.ar(clazz=autosar.SwBaseType)
for result in base_types:
    base_type = result.xml_obj  # 取出这个节点对应的 ARXML 对象。
    name = base_type.short_name.value  # 读取它的 SHORT-NAME 内容。
    print(result.ref, name)  # 打印这个数据类型的路径和名称。

# 按路径查找 BaseTypes 包；没有找到时返回 None。
package = io_arxml.ref(('AUTOSAR_Platform', 'BaseTypes'))
if package is not None:
    print(package.is_ar_package)  # 判断找到的对象是不是 AR-PACKAGE。

# 查找文件中哪些位置使用了 uint8 这个数据类型。
references = io_arxml.ref_to_ref(('AUTOSAR_Platform', 'BaseTypes', 'uint8'))
for reference in references:
    # xml_obj.value 是目标路径，owner_ref 和 filename 标明引用出现的位置。
    print(reference.xml_obj.value, reference.owner_ref, reference.filename)

# 如果修改了名称、引用或对象结构，重新扫描后再继续查询。
# io_arxml.scan_ref()

# 把读取到的全部内容输出到 model.txt，方便查看。
io_arxml.print(print_filepath='model.txt')

# 把修改保存回原来的 ARXML 文件。确认已备份后再取消下面的注释。
# io_arxml.flush_to_file()
```

上面的查询过程分为几步：

1. `autosar.SwBaseType` 表示要查找的节点类型，对应 XML 中的 `<SW-BASE-TYPE>`。
2. `ar()` 返回对象列表，每一项只对应一个文件里的一个节点。
3. `result.xml_obj` 取出实际的 ARXML 对象，`result.ref` 是路径，`result.file` 是所属文件。
4. `base_type.short_name.value` 读取这个对象的 `<SHORT-NAME>` 文本，也就是它的名称。

加载多个文件时，同一路径的节点分别保留。`io_arxml.find(path)` 返回全部匹配对象；`io_arxml.ref(path)` 返回唯一对象或 None，存在多个匹配时抛出异常，可以用 `io_arxml.ref(path, filename='文件路径')` 指定文件。对象上不再提供 `.default`、`.filter()` 或多对象遍历。

只处理一个文件时，可以直接使用文件层：

```python
from k3q_arxml import ArxmlFile, autosar

file = ArxmlFile().parse_file('test/ThrottlePositionControlComposition.arxml')
for result in file.ar(autosar.SwBaseType):
    print(result.ref, result.xml_obj.short_name.value)

# 修改名称或引用后调用 file.scan_ref() 更新索引，调用 file.save() 保存。
```

扫描仍使用原来的 `__scan_arobj_ref` 逻辑，只移到了 `arxml_file.py`。修改节点、引用或对象结构后仍需手动重新扫描；重命名仍需自行同步定义与引用。

如果要新建一个名称字段，可以这样写：

```python
# 创建一个值为 newName 的名称字段，后续可以赋给对象的 short_name。
identifier = autosar.Identifier(value='newName')
print(identifier.value)  # 输出 newName。
```

这里只创建了一个 Python 对象，还没有将它添加到 ARXML 或保存到文件。

## 编辑脚本

两个脚本使用当前已生成的绑定，无需传入或切换版本：

```console
uv run python chg_adt_name.py --help
uv run python chg_adt_idt_name.py --help
```

实际运行会原地修改输入文件。`chg_adt_idt_name.py` 会先全局移除文本中的 `ADT_` / `IDT_`，再为目标数据类型及引用添加前缀，使用前应备份文件。

根目录 `test.py`、`test3.py` 是历史手工示例，依赖未提交的 `test/model_merge.arxml`，不作为自动化测试入口。

## 开发与验证

```console
uv run python -m k3q_arxml generate 4.2.2
uv run python -m unittest discover -s tests -v
uv run ruff check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv run ruff format --check k3q_arxml tests chg_adt_name.py chg_adt_idt_name.py
uv lock --check
```

CLI 测试在临时目录中生成小型 schema，覆盖版本替换、失败保留和含空格及中文的路径。ARXML 测试使用样例的临时副本，验证解析回写、多文件路径和重命名引用；未生成 4.2.2 绑定时会跳过这些样例测试。

依赖和 Ruff 配置统一维护在 `pyproject.toml`，完整依赖树锁定在 `uv.lock`。使用 `uv add` / `uv remove` 管理依赖，开发依赖添加 `--dev`。运行依赖已包含生成 CLI；`uv sync --locked --no-dev` 也可使用生成命令。不要手动编辑生成的 `autosar.py` 或将其提交。
