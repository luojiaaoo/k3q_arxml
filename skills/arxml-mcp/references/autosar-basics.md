# AUTOSAR 基础知识与编辑判断

本页面向 Classic Platform ARXML 的常见阅读和数据类型编辑，示例标签已对照仓库 4.2.2 XSD。它不是完整 AUTOSAR 规范，也不定义 Adaptive Platform 的类型和服务模型。处理其他版本时，重新核对该版本的规范、绑定和 XSD。

## 路径与名称

`/Types/Speed` 是具名对象的 AUTOSAR 路径，由包含关系中的 SHORT-NAME 组成。AR-PACKAGES、ELEMENTS 等 XML 容器不是路径段；磁盘文件名也不是路径段。因此，同一文件中的 XML XPath 与 AUTOSAR 对象路径是两种定位方式。

SHORT-NAME 用于对象标识，LONG-NAME 是另一项可读描述。UUID 是独立属性，不能用文件名、显示名称或 UUID 猜测引用路径。本 MCP 的重命名工具改 SHORT-NAME 及关联引用路径，不自动改其他业务文本。

同名对象可以位于不同的包中。始终用完整路径区分它们；只凭 `Speed` 这个名称批量处理容易影响无关对象。当前库会拒绝一个会话内重复的对象路径，不能把多个文件当成可自动合并的同名包片段。

## 数据类型：ADT、IDT 与基础类型

| 概念 | 常见 XML 标签 | 编辑时关注 |
| --- | --- | --- |
| ADT，应用数据类型 | APPLICATION-PRIMITIVE-DATA-TYPE、APPLICATION-ARRAY-DATA-TYPE、APPLICATION-RECORD-DATA-TYPE | 应用层数据语义及类型结构，不能只按名称判断类型 |
| IDT，实现数据类型 | IMPLEMENTATION-DATA-TYPE | 实现层类型结构与属性；具体类别和子元素以实际模型为准 |
| 基础类型 | SW-BASE-TYPE | 编码、大小等基础表示属性，不等同于 ADT 或 IDT |
| 类型映射集合 | DATA-TYPE-MAPPING-SET | 集合内 DATA-TYPE-MAP 关联应用类型与实现类型 |

ADT 与 IDT 表达数据类型的不同方面，`DataTypeMap` 建立两者的关联；不应依据名称相似就认定已存在映射。可参考 [AUTOSAR Software Component Template，CP R24-11](https://www.autosar.org/fileadmin/standards/R24-11/CP/AUTOSAR_CP_TPS_SoftwareComponentTemplate.pdf) 的数据类型章节；该来源用于概念解释，不能替代 4.2.2 的结构校验。

在仓库 4.2.2 XSD 中，DATA-TYPE-MAP 包含 APPLICATION-DATA-TYPE-REF 和 IMPLEMENTATION-DATA-TYPE-REF，均以 DEST 表明目标类型。修改某个类型名称时，应查询所有已加载入向引用，不能只查接口或只查映射集合。

`ADT_`、`IDT_` 前缀及具体后缀是本项目脚本可处理的命名约定，不是所有 AUTOSAR 工程必须遵循的标准规则。不要从名称前缀推断对象真实类型，也不要在用户未要求时自动整理名称。

## 接口、数据原型与引用

SenderReceiverInterface 中常见 DATA-ELEMENTS / VARIABLE-DATA-PROTOTYPE。数据原型通过 TYPE-TREF 关联类型。检查接口使用了哪个数据类型时，要读取引用目标，并在已加载对象中解析该路径；仅看到数据原型的 SHORT-NAME 不足以判断类型。

引用示例：

```xml
<TYPE-TREF xmlns="http://autosar.org/schema/r4.0"
           DEST="APPLICATION-PRIMITIVE-DATA-TYPE">/Types/Speed</TYPE-TREF>
```

这里的文本是目标对象路径，DEST 是目标类型标记。将它指向另一类对象时，必须同时检查该引用角色允许的目标类型；不能仅替换路径，也不能随意把 DEST 改为任意 XML 标签。使用 `describe_type` 查询当前角色的枚举，再校验目标对象。

标准或外部示例可能使用 BASE 和相对引用；当前库及 MCP 仅支持绝对引用路径。不要直接照搬相对引用示例，也不要未经任务授权批量改写引用基准。

## 元素顺序与验证边界

XML 元素顺序受目标 XSD 的 sequence / choice 约束。不要按字母顺序重排，也不要把 `describe_type` 的字段列表当成完整的插入位置规则。先读取同类有效节点或相关 XSD 片段，再选择 append 或相对插入；本 MCP 还会核对 xsdata 往返后的内容与顺序。[AUTOSAR XML Schema Production Rules，FO R20-11](https://www.autosar.org/fileadmin/standards/R20-11/FO/AUTOSAR_TPS_XMLSchemaProductionRules.pdf) 描述了从模型到 XSD 的结构规则，具体顺序仍以目标版本 XSD 为准。

XSD 可以检查结构、部分值约束与枚举；它不证明当前文件集合包含全部目标，也不证明模型满足全部 AUTOSAR 业务约束或能被某个 DaVinci 版本正确导入。已有未解析引用可能指向未加载文件，报告时区分“当前集合未解析”与“完整工程错误”。

## 本地依据与后续专题

- 安装包中的 `k3q_arxml/schemas/autosar_4_2_2/AUTOSAR_4-2-2.xsd`：按 `name="DATA-TYPE-MAP"`、`name="VARIABLE-DATA-PROTOTYPE"` 等搜索相应类型和关联组。可用 `python -c "from k3q_arxml.schemas import SCHEMAS; print(SCHEMAS['4.2.2'])"` 查询实际路径。
- [已提交 ARXML 样例](https://github.com/luojiaaoo/k3q_arxml/blob/v2.1.1/test/ThrottlePositionControlComposition.arxml)：观察实际层级、类型定义与引用，查询或练习时下载到临时副本。
- [MCP 编辑服务](https://github.com/luojiaaoo/k3q_arxml/blob/v2.1.1/k3q_arxml/mcp/service.py)：判断工具能力、引用检查及保存边界；工具返回的实际 schema 优先于本文中的示例。

技能复制安装后，无需保留原仓库目录；XSD 随 Python 包安装，样例和源码可按上面的版本链接查看。

后续专题可单独覆盖应用类型与实现类型映射、接口和端口、组件与连接器、数据约束与单位、版本及工具兼容性。只在掌握来源和具体任务后补充规则，并在 SKILL.md 中增加按需读取入口；不要先创建空白专题文件。
