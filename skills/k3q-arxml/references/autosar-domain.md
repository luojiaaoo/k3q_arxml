# AUTOSAR 领域知识

> **待补充**——本文件预留给 AUTOSAR 领域知识（概念解释、建模惯例、常见对象与引用关系等）。
> 后续在此追加内容时保持下列小节结构，每条知识注明适用的 schema 版本（若与版本相关）。

## 暂定目录

### 1. 核心概念

（待补充：AR-PACKAGE / SHORT-NAME / 引用 DEST / UUID 等基础概念的约定）

### 2. 常见对象与典型结构

（待补充：SwBaseType、ApplicationDataType（Primitive/Array/Record）、ImplementationDataType、SenderReceiverInterface、PortPrototype、Composition 等对象的典型层级与字段含义）

### 3. 引用关系速查

（待补充：常见 *-REF 字段的 DEST 约束、引用目标类型、改名/迁移时需要同步的引用集合）

### 4. 命名与建模惯例

（待补充：SHORT-NAME 命名规则之外的团队/项目惯例、前缀后缀约定）

### 5. 版本差异

（待补充：4.2.2 与 00043~00052 之间与建模相关的结构差异）

---

## 编写约定

- 每条知识写清「是什么 / 什么时候用 / 操作时注意什么」，避免只贴 XML 不解释。
- 涉及具体字段时给出 XML 标签名与 Python 绑定字段名（如 `TYPE-TREF` / `type_tref`），便于脚本与 MCP 两种路径对照。
- 需要查证字段定义时用 MCP 的 `describe_type` / `get_type_source`，不要凭记忆写。
