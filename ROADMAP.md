# StaticPython Roadmap

## 当前状态

- 已完成 `build.py` 与各库 `setup.py` 的职责解耦：库自己的源码准备、补丁、构建工具自举、验证逻辑尽量都下沉到 `Core/*/setup.py` 或 `Lib/*/setup.py`
- 已支持基于 PyPI 元数据的自动依赖闭包：选择顶层库时，会结合 `requires_dist`、marker 和当前目标 Python 版本自动补齐依赖
- 已支持 artifact-first 的 GitHub Actions 工作流：默认总是上传 artifact，只有 `publish_release=true` 才发布 Release
- 已完成 frozen data 分片，full profile 不再依赖把超大冻结数据硬塞进单个 `Python/frozen.c`
- 已加入 focused test config 机制，`config.test-*.json` 只用于本地增量回归，并已在 `.gitignore` 中忽略

## 已落地能力

### 构建鲁棒性

- `freeze_modules.py` 的 Windows 输出已经做成 ASCII-safe，规避 `cp1252` 下的 `UnicodeEncodeError`
- stdlib 验证已经去掉对第三方 `tzdata` 的隐式依赖，改为内嵌 `TZif` 夹具验证 `zoneinfo`
- JupyterLab 在 frozen runtime 下的 manager fallback 已打通，`/lab` 验证也升级为真实 HTTP smoke
- `NumPy` 现在会在库内自举 `Cython`，Meson `setup` 不再依赖外部环境预装 `cython` / `cython3`
- `pyzmq` 现在也在库内自举 `Cython`，不再依赖 GitHub Actions host Python 预装 `cython`
- `numpy`、`pandas`、`pyzmq` 的本地 `Cython` 缓存已按 host Python 版本隔离，避免 3.11 / 3.12 增量测试互相污染

### 已集成的高优先级主流库

- `numpy`
- `pandas`
- `PIL`
- `IPython`
- `ipykernel`
- `jupyterlab`
- `notebook`
- `pyzmq`
- `requests`
- `httpx`
- `aiohttp`
- `flask`
- `django`
- `sqlalchemy`
- `selenium`
- `plotly`
- `openpyxl`

### 已补入并验证过的一批常用依赖/工具库

- `attrs`
- `cattrs`
- `jinja2`
- `jsonschema`
- `jupyter_server`
- `jupyter_client`
- `jupyter_core`
- `jupyterlab_server`
- `notebook_shim`
- `traitlets`
- `tornado`
- `psutil`
- `pyrsistent`
- `dateutil`
- `tzdata`
- `chardet`
- `xmltodict`
- `requests_toolbelt`
- `responses`
- `freezegun`
- `faker`
- `docutils`
- `jsonpickle`
- `humanize`
- `pycparser`

### 已覆盖但此前 roadmap 漏写的一批常用中小型库

- Web / API 方向：`starlette`、`uvicorn`、`websockets`、`python_multipart`
- 序列化 / 交换格式：`protobuf`、`msgpack`、`ujson`、`yaml`
- 数据库 / 缓存 / 服务端常见客户端：`redis`、`pymongo`、`pymysql`
- 文本 / 文档 / 解析：`bs4`、`pypdf`、`regex`、`rapidfuzz`、`lark`、`markdown`
- CLI / 工具 / 测试：`rich`、`typer`、`tqdm`、`pytest`、`black`
- 其他仍然算常用且体量可控的库：`sympy`、`networkx`、`fsspec`

## 已知现状说明

- 当前仓库 `Lib/` 下已有约 `200` 个第三方 integration 目录，代码层面已经明显超出早期 README 中提到的 `163` 个 integration 快照
- README 里的 `163/163`、`165` 个验证步骤，是某次 3.13 增量验证的历史结果，不再代表当前代码总量
- 本地用 `Python 3.11` 已成功复现并修复 `numpy` 的 `cython` 缺失问题
- 本地用 `Python 3.12` 再跑同一条 `numpy` 路径时，`cython` 探测同样已经通过；后续失败是当前机器上的 VS/分页文件环境问题，不是这次修复引入的新逻辑回归

## 下一阶段优先级

### P0：先把已有库 verify 做深

- 继续把现有主流库从“可导入”提升到“尽量多功能路径可运行”
- 优先补强：
  - `jupyterlab` / `notebook` / `jupyter_server`
  - `IPython` / `ipykernel`
  - `numpy`
  - `pandas`
  - `PIL`
  - `pyzmq`
- verify 设计原则：
  - 优先真实行为，不只做 import
  - 能做 HTTP 请求就做 HTTP 请求
  - 能做数组/表格/图像/序列化 roundtrip 就做 roundtrip
  - 能覆盖资源文件、模板文件、entry point、数据文件时一并覆盖

### P1：继续推进最常用第三方库

- 新增库时按“主流程度 + 依赖闭包完整性”排序，不按简单程度排序
- 每次处理顶层库前，先确认它依赖树里已有库是否已经稳定
- 如果 PyPI 元数据不够，需要补显式依赖或特殊 source hook，再收回库自己的 `setup.py`

### P2：持续清理状态文档

- 每次新增主流库或完成关键 verify 增强，都同步更新本文件
- 如果 README 的历史快照继续和当前代码偏差变大，再单独压缩重写 README 的“当前验证结论”段落
