# Windows 使用指南

## 安装

1. 在 GitHub Release 下载 `network-agent-<version>-windows-x64.zip`。不要下载 GitHub 自动生成的 `Source code` 压缩包。
2. 将压缩包完整解压到普通目录，例如 `D:\Apps\network-agent`。不要直接在压缩包预览窗口中运行，也不要放到需要管理员权限的系统目录。
3. 安装 64 位 Python 3.12+，安装时启用 Python Launcher。
4. 安装 Node.js 18+ LTS。
5. 双击 `start.bat`。这是 Windows 唯一需要操作的启动入口；首次启动会创建 `.venv` 并安装依赖，耗时取决于网络，后续启动只在依赖锁文件变化时更新。内部 PowerShell 脚本由 BAT 自动调用，不需要手工打开。

启动成功后统一访问 `http://127.0.0.1:5173`。`8010` 仅提供后端 API，不是第二套前端，也不会保存另一份数据。

## 启停和日志

- 启动：双击 `start.bat`
- 停止：双击 `stop.bat`
- 后端日志：`logs\backend-8010.log` 和 `logs\backend-8010.err.log`
- 前端日志：`logs\frontend-5173.log` 和 `logs\frontend-5173.err.log`
- 首次安装或启动器错误：`logs\startup-error.log`

启动失败时 `start.bat` 会自动用记事本打开 `startup-error.log`，无需再到目录里手工寻找。

脚本只会接管命令行属于当前项目目录的 8010/5173 监听进程。端口被其他程序占用时会直接报出 PID，不会结束不相关进程。

## 常见问题

### Python 或 Node.js 未找到

在新的命令提示符中确认：

```bat
py -3.12 --version
node --version
npm --version
```

安装后如果仍找不到，请注销并重新登录 Windows，让 PATH 生效。

### 首次安装失败

确认网络可以访问 PyPI 和 npm。关闭 Network Agent 后删除 `.venv`、`.runtime` 和 `frontend\node_modules`，再双击 `start.bat`，即可重新建立依赖环境。不要删除 `workspaces`，其中保存本地工作区数据。

### 局域网设备无法访问

启动脚本默认监听 `0.0.0.0`。首次启动时允许 Windows Defender 防火墙放行 Python 和 Node.js 的专用网络访问，然后使用 Windows 主机的局域网 IP 加端口 5173 访问。不要把 8010 直接暴露到不可信网络。

### 修改端口或只在本机监听

在命令提示符中设置环境变量后启动：

```bat
set FRONTEND_PORT=5173
set BACKEND_PORT=8010
set FRONTEND_HOST=127.0.0.1
set BACKEND_HOST=127.0.0.1
start.bat
```

### 自动化启动

无人值守场景可设置 `NETWORK_AGENT_NO_PAUSE=1`，或直接调用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start.ps1 -NoBrowser
```

## Windows 工具执行

- `exec.run` 在 Windows 使用 `cmd.exe /d /s /c`，在 macOS/Linux 使用 Bash。
- PowerShell 命令使用系统的 `powershell.exe`，也支持已安装的 `pwsh.exe`。
- 非零退出码、超时和命令错误会作为失败结果返回给 Agent，便于其修正参数或选择替代命令。
- 普通查询、巡检、连接和只读命令保持可用；删除、格式化、关机等破坏性操作仍受高风险审批约束。
