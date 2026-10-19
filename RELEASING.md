# 发布指南（PyPI）

面向维护者，说明打包、发行验证与 PyPI 发布步骤。用户安装与使用见 [README.md](README.md)。命令在仓库根目录执行，示例使用 Windows PowerShell。

发行名为 `k3q-arxml`（Python 导入名 `k3q_arxml`），包版本由 `pyproject.toml` 的 `[project].version` 决定。Git 标签不会自动改变包版本；`git push` 只更新 Git 仓库，上传 PyPI 还需要构建并发布发行文件。

## 打包配置

`pyproject.toml` 中与打包相关的关键配置：

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.uv]
package = false

[tool.hatch.build.targets.wheel]
packages = ["k3q_arxml"]

[tool.hatch.build.targets.sdist]
include = [
    "/k3q_arxml",
    "/README.md",
    "/LICENSE",
    "/pyproject.toml",
]
```

- wheel 包含 Python 库、MCP 子包、全部真实 `autosar_<版本>.py`、统一入口 `script/serve_mcp.py`、所有 XSD 及关联 `xml.xsd`，以及完整技能目录（安装后位于 `k3q_arxml/assets/skills/k3q-arxml`）。
- `tool.uv.package = false` 保持仓库通过源码运行，`uv sync` 不自动安装项目自身，避免 Windows Python 3.11 在中文路径下读取可编辑安装 `.pth` 时出现编码错误；`uv build` 仍正常构建发行包。
- `[project.scripts]` 声明覆盖全部可用版本的 `k3q-arxml-mcp-<版本>` 命令，全部指向 `k3q_arxml.script.serve_mcp:main`，版本仅由命令名称决定。`k3q_arxml/cli.py` 仅为内部工具，不注册开发 CLI。
- 用户可从仓库或已安装包的 `k3q_arxml/assets/skills/k3q-arxml` 复制完整技能目录到智能体的技能目录。安装包内路径查看：

  ```powershell
  uv run python -c "from importlib.resources import files; print(files('k3q_arxml').joinpath('assets', 'skills', 'k3q-arxml'))"
  ```

  安装 Python 包不会自动复制 Skill 或注册 MCP。构建规则见 [Hatchling 文档](https://hatch.pypa.io/latest/config/build/)。

## 发布前验证与版本号

先准备开发环境：

```powershell
uv sync --locked
uv run python -c "from k3q_arxml.schemas import autosar_4_2_2 as autosar; print(autosar.SCHEMA_VERSION)"
```

发布包携带全部版本独立绑定。没有 `autosar.py` 兼容入口；发布前检查模块 `SCHEMA_VERSION` 与文件名对应。

首次准备发行资源，或更新 XSD、xsdata 版本及生成规则后，重新生成绑定：

```powershell
uv run python k3q_arxml.cli.py
# 只重建指定版本：uv run python k3q_arxml/cli.py --versions 00044 --jobs 1
```

修改 `[project].version` 后更新锁文件，并执行完整回归：

```powershell
uv lock
uv sync --locked
uv run pytest -v
uv run ruff check k3q_arxml tests demo
uv run ruff format --check k3q_arxml tests demo
uv lock --check
git diff --check
git status --short
```

- 确认测试**实际执行**，MCP stdio 回归必须实际执行，不能以跳过充当通过。
- PyPI 已上传的发行文件不能用不同内容覆盖，即使删除也不能重用该文件名（见 [PyPI 帮助](https://pypi.org/help/#file-name-reuse)）。若目标版本号已占用，选择新版本并同步替换后文目录、文件名和安装命令中的版本号。
- 新增打包配置后，将 `pyproject.toml` 与更新后的 `uv.lock` 一起纳入本次发布提交。

## 构建与检查发行文件

使用本次版本的独立输出目录，避免上传旧版本文件（以下以 `2.2.0` 为例）：

```powershell
uv build --no-sources --out-dir dist/2.2.0
uvx --from twine twine check --strict dist/2.2.0/*.whl dist/2.2.0/*.tar.gz
uv run python -m zipfile -l dist/2.2.0/k3q_arxml-2.2.0-py3-none-any.whl
uv run python -m tarfile -l dist/2.2.0/k3q_arxml-2.2.0.tar.gz
```

应得到一个 wheel 和一个 sdist。确认两者包含：覆盖全部 schema 的 `autosar_<版本>.py`、`script/serve_mcp.py`、MCP 子包、全部 XSD 和完整技能目录 `k3q_arxml/assets/skills/k3q-arxml`；wheel 的 console_scripts 中仅包含覆盖全部 schema 的版本专用命令，且都映射到同一启动函数。不应包含临时 ARXML、备份或恢复清单。

## 独立环境安装验证

在独立临时环境安装 wheel，避免误用仓库源码：

```powershell
$wheel = (Resolve-Path 'dist/2.2.0/k3q_arxml-2.2.0-py3-none-any.whl').Path
$checkDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-release-' + [guid]::NewGuid())
uv venv $checkDir --python 3.11
$checkPython = Join-Path $checkDir 'Scripts/python.exe'
uv pip install --python $checkPython "$wheel"
& $checkPython -I -c "from k3q_arxml import IOArxml; from k3q_arxml.schemas import autosar_4_2_2 as autosar; from k3q_arxml.cli import SCHEMAS; print(autosar.SCHEMA_VERSION); print(SCHEMAS); assert SCHEMAS and all(p.is_file() for p in SCHEMAS.values())"
& $checkPython -I -c "from k3q_arxml.script.serve_mcp import main; assert callable(main)"
& $checkPython -I -c "from importlib.resources import files; p = files('k3q_arxml').joinpath('assets', 'skills', 'k3q-arxml'); print(p); assert p.joinpath('SKILL.md').is_file()"
```

`-I` 避免当前目录及 `PYTHONPATH` 中的源码遮住已安装包。还应在这个环境中用真实 MCP 客户端完成一次连接和工具发现；测试编辑、保存时只使用临时模型副本。另建环境安装 sdist，确认它也能构建和导入。

## 可选：先上传 TestPyPI

分别注册 [TestPyPI](https://test.pypi.org/account/register/) 和 [PyPI](https://pypi.org/account/register/) 账号，按站点要求完成验证和双因素认证。两个站点的账号、项目与 API token 相互独立。

在 TestPyPI 的账号设置创建 API token。首次创建项目时可使用具有相应账号权限的 token，项目创建后使用项目范围 token。下面通过隐藏输入读取 token，不将实际 token 写进文件：

```powershell
$publishSecret = Read-Host 'TestPyPI API token' -AsSecureString
$env:UV_PUBLISH_TOKEN = [System.Net.NetworkCredential]::new('', $publishSecret).Password
try {
    uv publish --publish-url https://test.pypi.org/legacy/ dist/2.2.0/*.whl dist/2.2.0/*.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'TestPyPI 上传失败' }
} finally {
    Remove-Item Env:UV_PUBLISH_TOKEN
}
```

上传成功后，在另一个临时环境中验证测试站上的包。为避免从 TestPyPI 解析完整依赖树，先从正式 PyPI 安装与本次 wheel 相同的依赖，再只替换测试包：

```powershell
$testDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-testpypi-' + [guid]::NewGuid())
uv venv $testDir --python 3.11
$testPython = Join-Path $testDir 'Scripts/python.exe'
uv pip install --python $testPython "$wheel"
uv pip install --python $testPython --no-deps --reinstall --index-url https://test.pypi.org/simple/ 'k3q-arxml==2.2.0'
& $testPython -I -c "from k3q_arxml import IOArxml; from k3q_arxml.schemas import autosar_4_2_2 as autosar; print(autosar.SCHEMA_VERSION)"
```

安装命令失败时先停止后续验证，不能把原有本地 wheel 的导入成功当作 TestPyPI 安装成功。测试站的上传和安装地址不同，前者是 `/legacy/`，后者是 `/simple/`。更多说明见 [PyPA 发布教程](https://packaging.python.org/en/latest/tutorials/packaging-projects/)。

## 上传正式 PyPI

完成发行文件检查和独立环境安装验证后，先提交发布内容、创建版本标签（如 `v2.2.0`）并推送远程仓库，再使用正式 PyPI 创建的 token 上传已经验证过的同一组文件。配置了 TestPyPI 时，可先完成上一节的测试发布。

```powershell
$publishSecret = Read-Host 'PyPI API token' -AsSecureString
$env:UV_PUBLISH_TOKEN = [System.Net.NetworkCredential]::new('', $publishSecret).Password
try {
    uv publish --publish-url https://upload.pypi.org/legacy/ dist/2.2.0/*.whl dist/2.2.0/*.tar.gz
    if ($LASTEXITCODE -ne 0) { throw 'PyPI 上传失败' }
} finally {
    Remove-Item Env:UV_PUBLISH_TOKEN
}
```

发布完成后，从仓库外的新环境安装并验证：

```powershell
$releaseDir = Join-Path ([System.IO.Path]::GetTempPath()) ('k3q-arxml-pypi-' + [guid]::NewGuid())
uv venv $releaseDir --python 3.11
$releasePython = Join-Path $releaseDir 'Scripts/python.exe'
uv pip install --python $releasePython 'k3q-arxml==2.2.0'
& $releasePython -I -c "from k3q_arxml import IOArxml; from k3q_arxml.schemas import autosar_4_2_2 as autosar; print(autosar.SCHEMA_VERSION)"
```

确认 PyPI 页面、安装结果与远程发布提交及标签对应。后续更新按「新版本号 → 验证 → 构建 → 推送提交与标签 → 可选 TestPyPI → 正式 PyPI」重复；自动发布可后续接入 [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)，不需要把长期 token 存入仓库。
