# 单文件 Python 库覆盖清单

## 目标

这个清单定义 `StaticPython` 的长期目标：

- 从干净 CPython 源树出发构建单文件静态 `python.exe`
- 目标版本至少覆盖 `3.11`、`3.12`、`3.13`
- 后续继续推进 `3.14`、`3.15`
- 集成当前 sandbox 已有的库
- 尽量覆盖常见开发、数据分析、Web、办公、Windows 自动化、轻量机器学习场景
- 明确排除超大件和高维护成本巨型栈

## 当前已经集成

### 第三方纯 Python 包

- `annotated_doc`
- `anyio`
- `asgiref`
- `attr`
- `attrs`
- `blinker`
- `bs4`
- `cattr`
- `cattrs`
- `certifi`
- `charset_normalizer`
- `click`
- `colorama`
- `comtypes`
- `Crypto`
- `dateutil`
- `django`
- `dotenv`
- `et_xmlfile`
- `flask`
- `h11`
- `httpcore`
- `httpx`
- `idna`
- `itsdangerous`
- `jinja2`
- `libui`
- `loguru`
- `markdown`
- `markdown_it`
- `markupsafe`
- `mdurl`
- `mistune`
- `mpmath`
- `networkx`
- `openpyxl`
- `packaging`
- `prompt_toolkit`
- `pygments`
- `pymysql`
- `pypdf`
- `pyperclip`
- `redis`
- `requests`
- `rich`
- `shellingham`
- `six`
- `sniffio`
- `soupsieve`
- `sqlparse`
- `sympy`
- `tabulate`
- `tenacity`
- `tomlkit`
- `tqdm`
- `typer`
- `typing_extensions`
- `tzdata`
- `urllib3`
- `wcwidth`
- `werkzeug`
- `win32_setctime`
- `xlsxwriter`

### 当前静态原生项目

- `_libui_core`
- `_pycryptodome_raw`

### 当前集成布局

- 第三方库已经按 `Lib/<库名>/setup.py` 解耦
- 每个库自己的补丁放在 `Lib/<库名>/**/*.patch`

### 当前强制 builtin / 静态链接的标准扩展

- `_ctypes`
- `_socket`
- `select`
- `pyexpat`
- `unicodedata`
- `_sqlite3`
- `_decimal`
- `winsound`
- `_asyncio`
- `_hashlib`
- `_overlapped`
- `_multiprocessing`
- `_ssl`
- `_bz2`
- `_lzma`
- `_wmi`
- `_zoneinfo`
- `_uuid`
- `_queue`

## 集成分级说明

| 标记 | 含义 |
| --- | --- |
| `I` | 已集成 |
| `P` | 纯 Python，主要是拷贝、冻结、验证 |
| `N` | 中等复杂度原生扩展，需要 `.vcxproj` / 静态库 / 链接调整 |
| `H` | 高复杂度原生扩展，通常涉及外部数值库、图像库或复杂依赖链 |
| `R` | 依赖 Rust 工具链 |
| `O` | 明确不在当前目标内 |

## Profiles

当前实际构建配置在根目录 `config.json`：

- `stdlib`
  - 只构建静态标准库和标准库 C 扩展
  - 不启用任何 `Lib/*/setup.py` 第三方库
- `full`
  - 当前默认 profile
  - 启用 `Lib/` 下所有第三方库集成

下面的 `base/web/docs/data/ml/windows/full` 是长期库覆盖规划分组，不等同于当前 `config.json` 里的最小发布 profile。

### `base`

面向通用脚本、CLI、配置、网络请求。

- `requests` `I`
- `urllib3` `I`
- `certifi` `I`
- `idna` `I`
- `charset_normalizer` `I`
- `packaging` `P`
- `python-dateutil` `P`
- `tzdata` `P`
- `click` `P`
- `typer` `P`
- `rich` `P`
- `prompt_toolkit` `P`
- `colorama` `P`
- `tabulate` `P`
- `tqdm` `P`
- `tenacity` `P`
- `attrs` `P`
- `cattrs` `P`
- `python-dotenv` `P`
- `tomlkit` `P`
- `loguru` `P`
- `six` `P`

### `web`

面向 Web 服务、模板、API 和 HTTP 客户端。

- `Jinja2` `P`
- `MarkupSafe` `N`
- `Flask` `P`
- `Werkzeug` `P`
- `itsdangerous` `P`
- `blinker` `P`
- `Django` `P`
- `asgiref` `P`
- `sqlparse` `P`
- `httpx` `P`
- `httpcore` `P`
- `anyio` `P`
- `sniffio` `P`
- `websockets` `N`
- `aiohttp` `N`
- `multidict` `N`
- `yarl` `N`
- `frozenlist` `N`
- `aiosignal` `P`
- `FastAPI` `P`
- `Starlette` `P`
- `Uvicorn` `P`
- `python-multipart` `P`
- `pydantic` `R`
- `pydantic-core` `R`

### `docs`

面向 HTML / Markdown / PDF / Office 文档。

- `beautifulsoup4` `P`
- `soupsieve` `P`
- `lxml` `H`
- `markdown` `P`
- `mistune` `P`
- `Pillow` `N`
- `reportlab` `H`
- `pypdf` `P`
- `pdfplumber` `P`
- `python-docx` `P`
- `openpyxl` `P`
- `XlsxWriter` `P`
- `et-xmlfile` `P`

### `data`

面向数据处理、文件交换、统计前的数据准备。

- `numpy` `H`
- `scipy` `H`
- `pandas` `H`
- `pyarrow` `H`
- `polars` `H`
- `duckdb` `N`
- `sqlalchemy` `P`
- `alembic` `P`
- `pymysql` `P`
- `redis` `P`
- `pymongo` `N`
- `orjson` `N`
- `ujson` `N`
- `msgpack` `N`
- `PyYAML` `N`
- `protobuf` `N`
- `regex` `N`
- `rapidfuzz` `N`

### `ml`

面向轻量科学计算、统计分析和传统机器学习。

- `sympy` `P`
- `mpmath` `P`
- `networkx` `P`
- `matplotlib` `H`
- `seaborn` `P`
- `scikit-learn` `H`
- `joblib` `P`
- `threadpoolctl` `P`
- `statsmodels` `H`
- `patsy` `P`
- `plotly` `P`
- `bokeh` `P`
- `altair` `P`

### `windows`

面向 Windows 自动化、系统调用和桌面使用。

- `libui` `I`
- `_libui_core` `I`
- `psutil` `N`
- `pywin32` `H`
- `comtypes` `P`
- `watchdog` `N`
- `pyperclip` `P`
- `portalocker` `P`
- `winshell` `P`

### `crypto`

面向常见加密和安全能力。

- `pycryptodome` `I`
- `cryptography` `R`
- `bcrypt` `N`
- `PyNaCl` `N`

## 目标全量清单

下表是当前计划覆盖的主清单。批次列对应实施路线图。

| 包 | 分类 | 等级 | 批次 | 备注 |
| --- | --- | --- | --- | --- |
| `certifi` | base | `I` | 已完成 | 当前 requests 栈 |
| `charset_normalizer` | base | `I` | 已完成 | 当前 requests 栈 |
| `Crypto` | crypto | `I` | 已完成 | 当前 pycryptodome 纯 Python 层 |
| `idna` | base | `I` | 已完成 | 当前 requests 栈 |
| `libui` | windows | `I` | 已完成 | 当前 GUI 层 |
| `requests` | base | `I` | 已完成 | 当前 requests 栈 |
| `urllib3` | base | `I` | 已完成 | 当前 requests 栈 |
| `packaging` | base | `P` | 2 | 优先级高 |
| `python-dateutil` | base/data | `P` | 2 | `pandas` 前置依赖 |
| `tzdata` | base/data | `P` | 2 | `zoneinfo` 兼容补充 |
| `click` | base | `P` | 2 | CLI 常用 |
| `typer` | base | `P` | 2 | 依赖 click |
| `rich` | base | `P` | 2 | CLI 常用 |
| `prompt_toolkit` | base | `P` | 2 | REPL / CLI 常用 |
| `colorama` | base | `P` | 2 | Windows 终端常用 |
| `tabulate` | base | `P` | 2 | 表格输出 |
| `tqdm` | base | `P` | 2 | 进度条 |
| `tenacity` | base | `P` | 2 | 重试逻辑 |
| `attrs` | base | `P` | 2 | 常用基础依赖 |
| `cattrs` | base | `P` | 2 | 常用基础依赖 |
| `python-dotenv` | base | `P` | 2 | 配置管理 |
| `tomlkit` | base | `P` | 2 | TOML 编辑 |
| `loguru` | base | `P` | 2 | 日志库 |
| `Jinja2` | web | `P` | 2 | 模板引擎 |
| `MarkupSafe` | web | `N` | 3 | 有 C speedups |
| `Flask` | web | `P` | 2 | Web 微框架 |
| `Werkzeug` | web | `P` | 2 | Flask 前置 |
| `itsdangerous` | web | `P` | 2 | Flask 前置 |
| `blinker` | web | `P` | 2 | Flask 信号 |
| `Django` | web | `P` | 2 | Web 框架 |
| `asgiref` | web | `P` | 2 | Django/ASGI |
| `sqlparse` | web | `P` | 2 | Django 依赖 |
| `httpx` | web | `P` | 2 | 现代 HTTP 客户端 |
| `httpcore` | web | `P` | 2 | httpx 前置 |
| `anyio` | web | `P` | 2 | httpx / async 前置 |
| `sniffio` | web | `P` | 2 | async 前置 |
| `beautifulsoup4` | docs | `P` | 2 | HTML 解析 |
| `soupsieve` | docs | `P` | 2 | bs4 前置 |
| `markdown` | docs | `P` | 2 | Markdown 生成 |
| `mistune` | docs | `P` | 2 | Markdown 解析 |
| `openpyxl` | docs/data | `P` | 2 | Excel 读写 |
| `XlsxWriter` | docs/data | `P` | 2 | Excel 生成 |
| `et-xmlfile` | docs/data | `P` | 2 | openpyxl 前置 |
| `sympy` | ml | `P` | 2 | 符号计算 |
| `mpmath` | ml | `P` | 2 | sympy 前置 |
| `networkx` | ml | `P` | 2 | 图计算 |
| `plotly` | ml | `P` | 2 | 交互式图表 |
| `bokeh` | ml | `P` | 2 | 图表 |
| `altair` | ml | `P` | 2 | 语义图表 |
| `sqlalchemy` | data | `P` | 2 | ORM / SQL |
| `alembic` | data | `P` | 2 | 迁移工具 |
| `pymysql` | data | `P` | 2 | MySQL 纯 Python |
| `redis` | data | `P` | 2 | Redis 客户端 |
| `comtypes` | windows | `P` | 2 | Windows COM |
| `pyperclip` | windows | `P` | 2 | 剪贴板 |
| `portalocker` | windows | `P` | 2 | 文件锁 |
| `winshell` | windows | `P` | 2 | Shell 封装 |
| `PyYAML` | data | `N` | 3 | 可先纯 Python，后续补 C |
| `psutil` | windows | `N` | 3 | 系统监控 |
| `regex` | data | `N` | 3 | 增强正则 |
| `Pillow` | docs/ml | `N` | 3 | 图像处理 |
| `msgpack` | data | `N` | 3 | 高效序列化 |
| `protobuf` | data | `N` | 3 | 协议序列化 |
| `rapidfuzz` | data | `N` | 3 | 模糊匹配 |
| `websockets` | web | `N` | 3 | WebSocket |
| `aiohttp` | web | `N` | 3 | async HTTP |
| `multidict` | web | `N` | 3 | aiohttp 前置 |
| `yarl` | web | `N` | 3 | aiohttp 前置 |
| `frozenlist` | web | `N` | 3 | aiohttp 前置 |
| `aiosignal` | web | `P` | 3 | aiohttp 前置 |
| `duckdb` | data | `N` | 3 | 嵌入式分析数据库 |
| `orjson` | data | `N` | 3 | 高性能 JSON |
| `ujson` | data | `N` | 3 | 高性能 JSON |
| `bcrypt` | crypto | `N` | 3 | 常见密码哈希 |
| `PyNaCl` | crypto | `N` | 3 | libsodium 绑定 |
| `numpy` | data/ml | `H` | 4 | 数值基础 |
| `scipy` | data/ml | `H` | 4 | 科学计算核心 |
| `pandas` | data/ml | `H` | 4 | 数据分析核心 |
| `matplotlib` | ml | `H` | 4 | 先支持 `Agg` 后端 |
| `seaborn` | ml | `P` | 4 | 依赖 pandas/matplotlib |
| `scikit-learn` | ml | `H` | 4 | 传统机器学习 |
| `joblib` | ml | `P` | 4 | sklearn 前置 |
| `threadpoolctl` | ml | `P` | 4 | sklearn 前置 |
| `statsmodels` | ml | `H` | 4 | 统计建模 |
| `patsy` | ml | `P` | 4 | statsmodels 前置 |
| `pyarrow` | data | `H` | 4 | Arrow/Parquet |
| `polars` | data | `H` | 4 | Rust 数据框 |
| `reportlab` | docs | `H` | 4 | PDF 生成 |
| `lxml` | docs | `H` | 4 | libxml2/libxslt |
| `pypdf` | docs | `P` | 4 | 纯 Python PDF |
| `pdfplumber` | docs | `P` | 4 | PDF 抽取 |
| `python-docx` | docs | `P` | 4 | Word 文档 |
| `pymongo` | data | `N` | 4 | MongoDB 客户端 |
| `FastAPI` | web | `P` | 5 | 依赖 pydantic 链 |
| `Starlette` | web | `P` | 5 | FastAPI 前置 |
| `Uvicorn` | web | `P` | 5 | ASGI Server |
| `python-multipart` | web | `P` | 5 | 表单上传 |
| `pydantic` | web | `R` | 5 | v2 依赖 Rust |
| `pydantic-core` | web | `R` | 5 | Rust 核心 |
| `cryptography` | crypto | `R` | 5 | Rust + OpenSSL |
| `pywin32` | windows | `H` | 5 | Windows 专项大项 |

## 当前明确排除

这些库不进入当前 builder 目标范围：

- `torch`
- `tensorflow`
- `jax`
- `opencv-python`
- `onnxruntime`
- `xgboost`
- `lightgbm`
- `spacy`
- `playwright`
- `selenium`

原因：

- 体积过大
- 外部运行时或二进制依赖过重
- 静态单文件 Windows 发行版维护成本不成比例

## 约束与设计原则

1. 默认优先把包冻结进 `Lib`，只有必须时才引入新的原生静态工程。
2. 纯 Python 依赖优先级高于原生扩展依赖。
3. 原生扩展优先选择能产出单个 `.lib` 或单个 builtin 模块的方案。
4. 所有新增集成都必须支持从干净 CPython 源树重复执行。
5. 不依赖 VS GUI 手工操作。
6. 每个批次都要保留可验证、可回退、可文档化的中间状态。
7. `matplotlib` 初期只要求文件输出后端可用，不以交互 GUI 后端为前提。
8. `3.11`、`3.12`、`3.13` 是第一阶段硬目标；`3.14`、`3.15` 允许先达到“可 patch / 可 dry-run”，后续再拉齐完整编译。
