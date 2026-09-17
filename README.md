# 园智汇 · AI 产业园区智慧运营管理平台

## ⚠️ 定位说明：这是一个 Prototype（原型平台）

本仓库是「**基于 AI Agent 的产业园区项目管理研究**」配套的**原型验证平台**，
目的是验证多园区、多租户运营场景下的**数据模型、权限体系与 AI Agent 编排思路**是否成立。

> **它只是原型，不代表最终产出产品**，也不是可直接投产的系统：
> 性能、安全、合规均未按生产标准打磨，数据为模拟生成的演示数据。

- 与"能否跑起来"无关：前后端、数据库、权限、AI 编排都是**真实实现**（不是静态页面、
  不是写死的示例值，指标全部由数据库实时聚合），但"真实实现"不等于"产品级交付"。
- 复盘与已知取舍见 [§七](#七已知取舍)，工程纪律与踩坑记录见 [docs/](docs/)。

---

## 🔗 在线演示

**<https://smartpark-prototype.app.workbuddy.host/>**

打开即用，登录页有三个一键填充的演示账号（密码统一 `Park@2026`）：

| 账号 | 视角 | 能看到什么 |
|---|---|---|
| `admin` | 集团管理员 · 全部园区 | 全部 22 个页面，198 个权限点 |
| `p1_manager` | 园区负责人 · 单园区 | 园区运营视角，无系统管理 |
| `tenant1` | 企业管理员 · 本企业 | 入驻企业自助视角 |

建议的体验动线（约 5 分钟）：

1. **数据驾驶舱** —— 点任一 KPI 卡片看计算口径；切换右上角园区，所有指标与图表同步重算。
2. **AI 智能体** —— 问「本月园区经营情况如何？有哪些风险需要关注？」，看它如何路由到
   经营分析AI、跨模块取数，并按八段式输出结论 + 证据链。
3. **安全管理** —— 安全指数的扣分模型逐项列明，可完整回溯。
4. **项目管理中心 → 任一项目** —— WBS、关键路径、挣值；把瀑布式项目切到「敏捷」视图会得到
   业务提示而不是报错。
5. 换 `tenant1` 登录一次 —— 菜单与数据范围立刻收窄，验证多租户数据隔离。

> 演示环境为按需启动的沙箱，**首次访问可能需要十几秒冷启动**；数据为模拟生成的演示数据。
> 若链接不可用，按下面「快速启动」在本地跑一份即可。
> 离线版演示见 `docs/demo/园智汇-平台演示.html`（11 张真实运行截图，自包含单文件）。

---

## 一、技术栈

| 层 | 选型 |
|---|---|
| 后端 | Python 3.11+ / FastAPI / SQLAlchemy 2.0 / Pydantic v2 |
| 数据库 | SQLite（演示默认，开箱即用）→ PostgreSQL（改一个环境变量即可切换） |
| 前端 | React 18 / TypeScript / Vite 5 / Tailwind CSS / React Router 6 |
| 可视化 | ECharts（趋势、漏斗、分布、账龄、甘特）+ 手写 2.5D 等轴测 SVG 数字孪生 |
| 认证 | JWT（HS256）+ RBAC 权限点 + 数据范围过滤双层模型 |

**规模**：132 个 API 操作 / 129 条路径 / 65 张表 / 17 个业务路由模块 /
22 个前端页面 / 15 个角色 / 198 个权限点 / 11 个 AI 子智能体 + 23 个工具。

面向**多园区、多租户**场景的一体化运营平台原型。整合空间资产、招商运营、企业经营、合同财务、
项目管理与物业运维，由 AI 智能体贯穿数据洞察、风险预警与决策建议；高风险动作强制走人工审批。

---

## 二、快速启动

> **最省事的方式：一个进程跑起来。** 后端会在 `frontend/dist` 存在时直接托管前端产物
> 并处理 SPA 路由回落，所以只要先构建一次前端，之后 `python run.py` 一个命令就能访问完整平台。

```bash
# 1) 后端依赖 + 生成演示数据
cd backend
python -m venv .venv
.venv/Scripts/activate           # Windows；macOS / Linux 用 source .venv/bin/activate
pip install -r requirements.txt
python run.py --seed             # 首次：生成演示数据（约 5 万行，4 个园区 24 个月经营数据）

# 2) 前端构建一次（产物会被后端托管）
cd ../frontend
npm install && npm run build

# 3) 启动（单端口）
cd ../backend
python run.py                    # → http://127.0.0.1:8010 ｜ 接口文档 /docs
```

**开发模式**（改前端代码热更新）则前后端各起一个：

```bash
cd backend  && python run.py     # → http://127.0.0.1:8010
cd frontend && npm run dev       # → http://127.0.0.1:5173（已配 /api 代理到 8010）
```

> 端口只在 `backend/app/core/config.py` 的 `BACKEND_PORT` 定义一次（默认 8010），
> `run.py` 与前端 vite 代理（`vite.config.ts` 的 `/api` target）都从同一约定出发。
> 若要换端口，改 `BACKEND_PORT` 环境变量后**同步**改 `vite.config.ts` 的 `target`，
> 否则开发模式下整站 `/api` 会 404（单端口模式下不受影响）。

### 3. 演示账号（密码统一 `Park@2026`）

| 账号 | 角色 | 数据范围 | 说明 |
|---|---|---|---|
| `admin` | 集团管理员 | 全部园区 | 198 个权限点，全模块可用 |
| `p1_manager` | 园区负责人 | 单园区 | 园区运营视角，看不到系统管理 |
| `tenant1` | 企业管理员 | 本企业 | 入驻企业自助视角，仅 9 个模块 |

登录页提供三个一键填充入口，便于快速切换视角验证数据隔离。

### 4. 想看演示但不方便跑环境？

`docs/demo/园智汇-平台演示.html` 是按 `docs/演示脚本.md` 录制的关键动线（11 张真实运行截图，
图片内联的自包含单文件），双击即可打开。

---

## 三、目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── api/v1/          17 个业务路由模块（132 个操作）
│   │   ├── core/            config / database / security / permissions / enums / audit
│   │   ├── models/          65 张表的 ORM 定义
│   │   ├── services/        跨模块聚合服务（驾驶舱、EVM、报表…）
│   │   ├── agent/           主 Agent 编排器 + 11 个子智能体 + 23 个工具
│   │   ├── schemas/         请求 / 响应模型
│   │   └── seed/            演示数据生成器（全部 is_demo=True）
│   ├── data/smartpark.db    SQLite 演示库（不入库，由 --seed 生成）
│   ├── run.py               启动入口（--seed 可重建演示数据）
│   └── check_*.py           ★ 八道静态 / 契约 / 工具层校验（见第五节）
├── frontend/
│   └── src/
│       ├── api/             client（统一鉴权/错误/query 序列化）+ 各模块 SDK
│       ├── components/      ui.tsx（设计系统）+ Charts.tsx（ECharts 封装）
│       ├── config/nav.ts    20 个一级菜单与权限点绑定
│       ├── context/         登录态与权限上下文
│       ├── layout/          侧边栏 + 顶栏 + 全局 AI 抽屉
│       └── pages/           22 个真实页面
├── tools/e2e/               ★ 浏览器巡检工具（生成批次 / 解析健康报告 / 打包演示页）
└── docs/
    ├── 演示脚本.md           分角色的演示动线
    └── demo/                录制的演示动线截图 + 自包含演示页
```

---

## 四、关键设计

### 4.1 权限：RBAC + 数据范围双模型

- **功能权限**：15 角色 × 9 动作（VIEW/ADD/EDIT/DELETE/IMPORT/EXPORT/APPROVE/AI/CONFIG）
  × 22 模块 = 198 权限点。
- **数据范围**：GROUP（集团）/ PARK（园区）/ DEPARTMENT / PROJECT / ENTERPRISE / SELF，
  由后端在每次查询时下推过滤条件，**不依赖前端隐藏**。
- 前端菜单与路由守卫按同一权限点收敛（`nav.ts` 的 `perm` 与 `App.tsx` 的
  `RequirePerm`），无权限时给出可读提示而非白屏；真正的边界始终在后端
  `auth.require(module, action)`。

### 4.2 AI 权限三级 + 八段式输出

| 级别 | 能力 | 约束 |
|---|---|---|
| L1 | 信息查询 | 只读 |
| L2 | 分析与建议 | 可生成建议、洞察、预警 |
| L3 | 高影响动作 | **必须人工审批，AI 不得自行执行**；前端显式阻断并引导至审批中心 |

所有 AI 输出统一为八段式：结论 / 关键数据 / 原因分析 / 建议措施 / 影响范围 / 风险 /
责任部门（角色）/ 决策状态，并附证据链与计算口径。

### 4.3 演示数据必须显式标注

需求硬性要求：所有模拟数据必须可见地标注「演示数据」。实现上双保险——
后端每个响应带 `data_label: "演示数据"`，前端以 `DemoBadge` / `PageHeader demo`
渲染角标与水印。

### 4.4 AI Agent 运行模式

`AGENT_MODE=rule`（默认）为**本地确定性推理**：同一问题在相同数据下必然得到同一结论，
可直接用于评审与回归；不依赖外部大模型，演示环境零外部依赖。
接入大模型时改为 `llm` 并补齐 provider 配置即可，编排层无需改动。

---

## 五、质量保障：八道自动校验

平台开发过程中反复出现三类**不会被编译器发现**的缺陷，因此把它们固化成脚本：

| 脚本 | 拦截的缺陷 | 典型后果 |
|---|---|---|
| `check_fields.py` | 组件属性 / 构造参数 / 字典键 / 推导式键 / 路由 | 前端运行时白屏 |
| `check_routes.py` | 前端调用了后端不存在的路由 | 运行时必然 404 |
| `check_permissions.py` | 前端权限键与后端 RBAC 模块名不一致 | 守卫恒为 false → 页面/按钮不可达 |
| `check_enum_columns.py` | 枚举列里存了展示用中文标签 | 统计静默归零 |
| `check_enum_mismatch.py` | 中文存值 × 英文比较的组合 | 同上，但只在真有英文比较时报警 |
| `check_tools.py` | **Agent 工具层内部异常**（把 23 个工具逐个真跑） | 工具抛错被包装成"数据不足"，整个业务能力静默失效 |
| `check_intent.py` | AI 意图路由误判（41 条问句用例，离线） | 问经营情况却回答项目分析 |
| `check_intent_e2e.py` | 同上，但走真实 HTTP（认证 → 路由 → 工具 → 落库） | 纯函数通过但链路仍可能断 |

```bash
cd backend
python smoke_test.py             # 端到端冒烟，含三方角色权限隔离验证（92 项）
python check_fields.py           # 四维字段校验
python check_routes.py           # 前后端路由交叉校验
python check_permissions.py      # 权限键一致性校验（前端 + 后端双向）
python check_enum_columns.py     # 枚举列中文值扫描
python check_enum_mismatch.py    # 中英错配风险判定
python check_tools.py            # Agent 工具层 23 个工具全量巡检
python check_intent.py           # 意图路由离线用例（41 条）
python check_intent_e2e.py       # 意图路由端到端（需服务已启动）
```

全部脚本退出码非 0 即代表存在缺陷，可直接接入 CI。

> `check_tools.py` 的价值最直接：`get_safety_risks` 曾因漏导入 `SafetyHazard`、
> `get_policy_matches` 曾因 `Policy.conditions` 存成字符串而抛错，两处都被
> `call_tool` 包装成"数据缺失：xxx"返回给前端，页面上看起来只是"没有数据"，
> 实际上是安全AI 与政策AI 整块失效。该脚本会把这两种情况判为 FAIL。

---

## 六、浏览器端到端验收

`tools/e2e/` 下有一套基于 `agent-browser` 的巡检工具，按路由逐个访问并采集
控制台错误与页面异常：

```bash
# 需先启动后端(8010) 与前端（dev 5173 或 preview 4173）
cd tools/e2e
python gen_tour2.py http://127.0.0.1:4173            # 生成 21 页巡检批次（自动匹配等待时长）
agent-browser --session park batch < tour2.json > tour2.out
python check_pages.py tour2.out                      # 输出页面健康报告

python gen_role_batch.py p1_manager Park@2026 role.json   # 按角色巡检
```

**等待时长按环境自动取值**：dev（5173）给 9s，构建产物（4173）给 5.5s。dev 模式要对每个
模块即时编译，多请求页面（驾驶舱/财务）首屏实测 3–7s，等待给短了会把"慢"误报成
`STILL_LOADING`。**正式验收请打 `vite build` + `npx vite preview`**，没有编译开销、结果稳定。

**关键：探针必须只看 `<main>`。** 早期版本用 `document.body.innerText` 的长度判断
页面是否"有内容"，而侧边栏 20 个菜单加顶栏本身就有 1000+ 字，于是两个真实缺陷
被判为健康：
- 合同管理页渲染抛错、`<main>` 完全为空；
- 安全页在「全部园区」下所有 KPI 都是 `0` / `—`。

现在的探针只统计 `<main>` 正文，并区分 `NEARLY_EMPTY`（真空白）、`STILL_LOADING`、
`BAD_PLACEHOLDER`（`undefined` / `NaN`）、`ALL_DASH`（**KPI 区几乎没有数字**且出现 ≥3 个
占位符）。`ALL_DASH` 必须同时看"有没有数字"——否则一个页面有几项真实指标、少数几项为空
也会被误报；表格里的空单元格则完全不算。

当前基线（对 `dist/` 构建产物验收）：**21/21 页全部渲染、0 FAIL、页面级 JS 异常 0 条**；
p1_manager 19 个可见路由全部通过，越权访问 `/system` 被正确拒绝且与其菜单隐藏一致；
tenant1 8/8 通过；控制台零 error（仅 vite / react-router 的版本提示）。

---

## 七、已知取舍

- **部署到反向代理后面时，`Authorization` 头可能被网关改写**：本项目在线上实测到
  网关会把 `Authorization` 覆盖掉，导致"登录成功但所有接口 401"。因此前端会**同时**发送
  `X-Token`，后端按「多来源候选、取第一个能验通的」处理（`app/core/security.py`）。
  本地直连不受影响。启动日志与 `/api/meta` 的 `runtime` 字段会打印实际生效的
  JWT / 密码哈希实现，便于排查环境差异。
- **未做路由级代码分割**：单包约 1.59 MB（gzip 510 KB）。22 页 SPA 均可再拆分为
  按需加载的分包，属可优化项，不影响功能。
- **能耗的「时段 / 峰谷」维度在演示数据中为空**：`energy_records.record_hour` 全为 NULL
  （演示数据是**月度**台账，`record_date` 只有 24 个月份，没有小时）。因此
  `night_consumption_ratio` 后端返回 `null`（不是 0）、明细表「时刻 / 时段 / 电价时段」
  显示 `—`，并给出 `has_hourly_detail=false` 与口径说明。
  **这是有意的**：返回 0 会被读成"夜间用电占比为零"，而事实是"没有小时级数据"。
  要让该维度真正可用，需要把 seeder 的月度记录改为覆盖最近 31 天的小时级记录
  （注意同时下掉当月的月度记录，否则 30 天窗口内会重复计数）。
- **`月经营收入` 的同比/环比波动大**：该指标口径是「本月**实收**」，当月尚未结束
  时与完整月份对比天然偏低，口径已在指标的 `basis` 中说明。
- **驾驶舱首屏在 dev 模式下约 1 秒**：`/dashboard/summary` 单次约 0.5s（已把账单聚合
  下推 SQL），dev server 还要即时编译，浏览器端实测 1–5s 不等；用 `vite build` +
  `vite preview` 会明显更快。
- **演示库为 SQLite**：高并发写场景请切 PostgreSQL（改 `DATABASE_URL` 即可）。

---

## 八、合规与边界

- AI 不执行任何写操作。所有 L3 高影响动作一律进入审批中心，由具备 `APPROVE`
  权限的角色人工决策，并留下完整审计日志。
- 全部关键操作（增删改、导入导出、登录登出、AI 调用、审批）写入审计日志，
  支持按模块、动作、结果、对象追溯变更前后值。
