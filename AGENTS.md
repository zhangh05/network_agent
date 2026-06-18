# Agent Handoff

## 本地路径

```text
/Users/zhangh01/Desktop/network_agent
```

本仓库使用系统 `python3`，不要自行创建或切换到 `venv`、`.venv`。

## 启动

```bash
cd /Users/zhangh01/Desktop/network_agent
python3 backend/main.py --host 0.0.0.0 --port 8010

cd /Users/zhangh01/Desktop/network_agent/frontend
npm run dev -- --host 0.0.0.0
```

## 验证

优先运行与改动相关的测试。准备提交时再运行必要的组合门禁。

```bash
python3 -m pytest harness/<target_test>.py -q
cd frontend
npm test -- --run
npm run typecheck
npm run build
```

## 当前边界

- Agent 公共入口：`POST /api/agent/message`
- 知识实现：`agent/modules/knowledge/`
- 模型可调用工具：以 `tool_runtime/canonical_registry.py` 为准
- 工具名称空间：以 `tool_runtime/tool_namespace_data.py` 为准
- 用户文件：`workspaces/{workspace_id}/files/{upload|agent}/`
- 系统数据：`workspaces/{workspace_id}/sys/`
- 前端 API：`frontend/src/api/index.ts`
- 前端路由：`frontend/src/app/App.tsx`

不要新增重复实现、兼容分支或旁路工具调用。新增能力必须进入当前注册表、规划器、权限和审计链路。

## 工作约束

- 不提交 `config/providers/`、本地密钥、工作区运行数据、缓存或构建产物。
- 不删除或覆盖用户未要求处理的本地数据。
- 不用 `git checkout --`、`git reset --hard` 等命令覆盖现有改动。
- 修改前后端契约时，同时检查 API 类型、页面调用和契约测试。
- 修复报文分析时，验证“文件管理选择报文 -> `/packet?sid=...` -> 恢复会话”完整流程。
- 修改工具选择时，验证工具目录、分类路由、规划器和真实执行入口一致。
