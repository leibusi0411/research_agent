# ADR-0047: Web UI 常驻 Settings 页面（演进 ADR-0030）

**日期**: 2026-09-08  
**状态**: ✅ 已实施  
**影响范围**: `api/app.py`, `web/src/App.tsx`, `web/src/pages/SettingsPage.tsx`（新增，替代 SetupPage）, `web/src/components/Sidebar.tsx`, `web/src/api.ts`

> 演进注记（2026-09-09，R-249）：追认实施时偏差——本文原述"未配置时用户落在 Settings 页"自实施（commit b91609c）起即未实现：`web/src/App.tsx` 无按 configured 重定向的逻辑，落地页恒为 Research（`web/tests/App.test.tsx:132-134` 断言 "Research is the landing page even without config"），后经 R-217 明确为既定行为（Research 未配置照常可用、启动调研才同步报 `config_missing`）。下文决策中的失实句已据此修订为现实；本 ADR 其余决策（API key 不回传、空密钥保留、保存全量写回的取舍等）不受影响。

## 背景

ADR-0030 规定 v1 Web UI 不设 Settings 页面，只在 User Config 缺失时显示 Setup 视图。TODO.md 将 "Settings page"（完整设置编辑器：模型、搜索 provider、工作区路径等）列为有意延期项。用户决定实现该延期项：配置不再是一次性的首次流程，而是随时可查看、可修改的常驻页面，左侧导航由此变为 4 个页面（Research / Tasks / Knowledge Base / Settings）。

## 决策

将 Setup 视图升级为常驻 **Settings Page**（路由 `/settings`），首次使用不再全屏接管：应用外壳（侧边栏 + 路由）始终渲染，未配置时用户落在 Research 页（外壳内照常展示与输入，启动调研才由 API 同步报 `config_missing`），Settings 随时可从侧边栏进入，保存后进入 Research 页。

### 关键设计选择

- **本 ADR 显式演进 ADR-0030**：ADR-0030 中"不设 Settings 页面"的决策被本 ADR 取代；其中"设置流程只收集和校验配置、不扫描 Knowledge Base、不建索引、不启动服务、不调用 provider"的约束仍然成立，Settings 保存动作沿用 `POST /api/setup/init` 的既有语义。
- **API key 永不回传浏览器**：新增 `GET /api/setup/config` 返回当前配置供表单预填，但三个 api_key 字段恒为空串，只以 `has_chat_api_key` / `has_embedding_api_key` / `has_search_api_key` 布尔值告知是否已保存（延续 ADR-0009 的密钥安全约束）。
- **空密钥 = 保留已存值**：`POST /api/setup/init` 收到空白 api_key 字段时，若已有配置则沿用保存的 key，否则报 `config_invalid`。表单中已保存的 key 输入框显示 "Saved — leave blank to keep" 占位符且改为非必填。
- **未配置不阻断浏览**：Research 页在未配置时照常展示和输入；此时启动调研由 API 同步返回 `config_missing` 报错（先于建任务检查，不走"202 启动后后台失败"），用户经侧边栏进入 Settings 补配置。CLI 初始化（`research-agent init`）不受影响。
- **保存即全量写回（已知取舍）**：保存沿用 `init_user_config` 的固定模板全量重写 `config.toml`。手工在配置文件中加入的 `[chat_model.<role>]` per-role 覆盖、`[research]` 与 `[web_tools]` 自定义值会在下次 Settings 保存时被重置为模板默认——这是 ADR-0009 "覆盖前提示" 约定在本场景的显式接受项（本地单用户工具、UI 可改回全部必需字段）；后续改进方向是保存前确认或写回时保留未知 section。
- **workspace 修改即时生效**：保存成功后使 API 层缓存的 CoreService 失效，下一个请求按新配置重建（进行中的旧任务继续落在旧工作区，不受影响）。

## 影响

- Web API 新增 `GET /api/setup/config`（config 缺失 → 404 `config_missing`；其余错误 → 400）。
- CONTEXT.md：新增 Settings Page 词条，Web API 词条相应修订（Setup View 词条由 Settings Page 取代）。
- TODO.md 移除 "Settings page" 延期项。
- 测试：`tests/test_api_surface.py` 新增 4 个（config 读取打码 ×2、空密钥保留 ×2）；`web/tests/App.test.tsx` 重写未配置流 + 新增预填流；`web/tests/e2e/app.spec.ts` 首启流程改为外壳内 Settings 流；顺带修复 `tests/test_local_research.py` 缺失的 `typing.Any` 导入（阻塞收集）与 `tests/test_api_connections.py` 未按 ADR-0042 skip 的真实 API 测试。
