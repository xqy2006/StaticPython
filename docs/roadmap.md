# 3.11+ 单文件 Python 实施路线图

## 总目标

完善 `StaticPython`，使其能够：

- 从干净 CPython 源树开始工作
- 不依赖 VS GUI 手工点选
- 至少覆盖 `CPython 3.11`、`3.12`、`3.13`
- 逐步拉齐 `3.14`、`3.15`
- 最终构建出内置当前 sandbox 已有库和目标清单中常用库的单文件静态 `python.exe`

## 当前起点

当前已经具备：

- 当前 sandbox 同款静态 `python.exe` 路线
- `libui` builtin 集成
- `pycryptodome` 静态原生集成
- 当前已接入的一整批第三方纯 Python 包冻结
- `3.12/3.13` 的主要补丁逻辑
- `getpath` 和 `_pyrepl` 的版本分支处理
- GitHub Actions 的自动下载和打包流程
- 第三方库按 `Lib/<库名>/setup.py` 解耦

当前不足：

- 还没有面向大规模库覆盖的 profiles / catalog / 批次管理
- `3.14`、`3.15` 还没有实际编译验证
- `3.11`、`3.12` 还没有在当前解耦架构下重新做一轮回归
- 还没有将大批常用第三方库分批集成

## 版本矩阵

### 第一阶段硬目标

- `3.11.x`
- `3.12.x`
- `3.13.x`

### 第二阶段扩展目标

- `3.14.x`
- `3.15.x`

### 版本策略

1. 任何版本差异优先通过“比较版本号 + 分支逻辑”处理，不写死单个小版本。
2. `>= 3.13` 继续使用 `_pyrepl` 路线。
3. `< 3.13` 使用 legacy 路线。
4. `>= 3.14`、`>= 3.15` 如遇新的 `PCbuild` / `freeze_modules` / `site.py` / `getpath` 差异，继续在 builder 内做条件补丁。

## 批次拆分

### Batch 0: 文档和目录基线

目标：

- 固化目标清单
- 固化分批路线
- 固化版本矩阵

任务：

- 写 `docs/libraries.md`
- 写 `docs/roadmap.md`
- 在 README 中补充新文档入口
- 记录当前已集成能力和后续批次边界

验收：

- 文档可独立说明项目目标
- 后续实现不再口头变更范围

### Batch 1: Builder 基础清理和干净源树兼容

目标：

- 让 builder 从干净 CPython 源树工作
- 整理硬编码元数据
- 先保证当前已集成库在 `3.11+` 路径上可重复执行

任务：

- 整理当前 manifest / metadata 结构
- 将第三方库改成 `Lib/<库名>/setup.py` + `Lib/<库名>/**/*.patch`
- 对干净 `3.11/3.12/3.13` 树做 `--skip-build` 验证
- 对 `3.14/3.15` 至少做 patch / dry-run 验证
- 修复版本差异导致的 patch 失败

验收：

- `build.py --help` 正常
- 在干净源树上可跑到 patch 完成
- 不依赖 sandbox 定制残留文件

### Batch 2: 纯 Python 基础生态

目标：

- 先补最容易冻结、价值最高的纯 Python 常用库

任务：

- 集成 `packaging`
- 集成 `python-dateutil`
- 集成 `tzdata`
- 集成 `click`
- 集成 `typer`
- 集成 `rich`
- 集成 `prompt_toolkit`
- 集成 `colorama`
- 集成 `tabulate`
- 集成 `tqdm`
- 集成 `tenacity`
- 集成 `attrs`
- 集成 `cattrs`
- 集成 `python-dotenv`
- 集成 `tomlkit`
- 集成 `loguru`
- 集成 `Jinja2`
- 集成 `Flask` 栈
- 集成 `Django` 栈
- 集成 `httpx` 栈
- 集成 `beautifulsoup4`
- 集成 `markdown`
- 集成 `openpyxl`
- 集成 `XlsxWriter`
- 集成 `sympy`
- 集成 `networkx`
- 集成 `sqlalchemy`
- 集成 `alembic`
- 集成 `pymysql`
- 集成 `redis`
- 集成 `comtypes`

验收：

- 导入验证覆盖这些包
- 对应包可显示 `origin='frozen'` 或 builtin 预期状态

### Batch 3: 中等复杂度原生扩展

目标：

- 处理常见但非数值重型的原生扩展

任务：

- `MarkupSafe`
- `PyYAML`
- `psutil`
- `regex`
- `Pillow`
- `msgpack`
- `protobuf`
- `rapidfuzz`
- `websockets`
- `aiohttp` 及其原生依赖
- `duckdb`
- `orjson`
- `ujson`
- `bcrypt`
- `PyNaCl`

验收：

- 每个库都有独立的集成笔记
- 新增 `.vcxproj` / 静态库可重复构建
- 链接后最终 exe 不引入第三方运行时 DLL

### Batch 4: 数值基础与数据分析主干

目标：

- 打通数据分析和轻量机器学习的基础链路

任务：

- `numpy`
- `scipy`
- `pandas`
- `matplotlib`
- `seaborn`
- `scikit-learn`
- `joblib`
- `threadpoolctl`
- `statsmodels`
- `patsy`
- `pyarrow`
- `reportlab`
- `lxml`
- `pypdf`
- `pdfplumber`
- `python-docx`
- `pymongo`

技术重点：

- 数值库静态链接方案
- OpenBLAS / LAPACK / Fortran 依赖评估
- `matplotlib` 先只做 `Agg` 后端
- `pandas` / `scipy` 的跨版本构建差异

验收：

- 能跑最小数据分析脚本
- 能生成 `png/pdf/xlsx/docx`
- 能执行基本 `numpy/pandas/matplotlib/sklearn` 烟雾测试

### Batch 5: Rust / 新一代 Web / Windows 专项大项

目标：

- 处理当前最复杂但实际常用的尾部大项

任务：

- `FastAPI`
- `Starlette`
- `Uvicorn`
- `python-multipart`
- `pydantic`
- `pydantic-core`
- `cryptography`
- `pywin32`
- `polars`

技术重点：

- Rust 工具链纳入 builder
- OpenSSL / libffi / Windows COM 特化
- `pywin32` 的 builtin 化拆解

验收：

- FastAPI 最小应用可启动
- `cryptography` 基本算法可用
- `pywin32` 关键模块可导入

### Batch 6: Profiles、发布形态和自动化验证

目标：

- 把 builder 变成可维护的产品，而不是一次性脚本

任务：

- 定义 `base/web/docs/data/ml/windows/full` profiles
- profile 选择进入 CLI
- profile 对应导入验证矩阵
- profile 对应 GitHub Actions matrix
- 生成集成报告
- 输出最终覆盖表和已验证版本表

验收：

- 同一个 builder 支持多 profile 构建
- GitHub Actions 能按版本和 profile 自动出包

## 每批统一要求

1. 代码变更必须记录到 `docs/`
2. 新增原生库必须有独立集成说明
3. 所有补丁必须幂等
4. 不允许依赖手工 VS GUI 点选
5. 每批结束后都要验证最终 exe 的导入表
6. 每批结束后都要更新当前状态文档

## 建议实现顺序

建议按下面顺序推进，不要跳批次：

1. Batch 0
2. Batch 1
3. Batch 2
4. Batch 3
5. Batch 4
6. Batch 5
7. Batch 6

原因：

- 纯 Python 包能最快扩大覆盖面
- 中等原生扩展能先把 builder 的 native pipeline 打磨稳定
- 数值栈和 Rust 栈都属于高维护区，必须放到后面

## 当前工作约定

从本轮开始：

- 以干净的 CPython 源码树为新兼容基线之一
- builder 的目标不再仅仅是“复刻当前 sandbox 状态”
- builder 的新目标是“可维护地逼近通用单文件 Python 发行版”
