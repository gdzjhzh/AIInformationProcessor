# CapsWriter

CapsWriter 的仓库内正式位置放在 `services/capswriter/`。

这里跟踪的是：
- Windows Service 的安装脚本和配置模板
- 后续如果要把本地 vendored runtime 收进统一目录，可放到 `runtime/`

这里不跟踪的是：
- `WinSW` 包装器二进制 `CapsWriterService.exe`
- 运行时生成的 `CapsWriterService.xml`
- 服务日志
- 本机实际下载的 CapsWriter runtime

## 当前状态

当前这台机器上已经安装成功的 Windows Service，最初是从旧路径
`backups/vendor/capswriter/service/`
注册进去的。

这次迁移先做“仓库内规范化”，不直接改动已运行的服务实例，避免把当前可用状态打断。

如果要把已安装服务正式切换到新的 canonical 路径，请用管理员 PowerShell 运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\AIInformationProcessor\services\capswriter\windows-service\install_capswriter_service.ps1 -StartService
```

## 目录约定

- `windows-service/`: 跟 Windows Service 相关的可追踪资产
- `runtime/`: 本机下载或手动放置的 CapsWriter runtime，默认不进 Git

## Runtime 查找顺序

安装脚本会按这个顺序找 `CapsWriter-Offline`：

1. 环境变量 `CAPSWRITER_APP_DIR`
2. `services/capswriter/runtime/CapsWriter-Offline`
3. `backups/vendor/capswriter/app/CapsWriter-Offline`

这样做是为了允许仓库结构先统一，同时兼容当前已经跑起来的老路径。
