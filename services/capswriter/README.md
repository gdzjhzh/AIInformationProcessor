# CapsWriter

CapsWriter 的仓库内正式位置放在 `services/capswriter/`。

这里跟踪的是：
- Windows Service 的安装脚本和配置模板
- 本机实际使用的 runtime canonical 位置约定为 `runtime/`

这里不跟踪的是：
- `WinSW` 包装器二进制 `CapsWriterService.exe`
- 运行时生成的 `CapsWriterService.xml`
- 服务日志
- 本机实际下载的 CapsWriter runtime

## 当前状态

当前仓库内的正式 Windows Service 资产已经位于：

- `services/capswriter/windows-service/`
- `services/capswriter/runtime/CapsWriter-Offline`

当前这台机器上的 `CapsWriterService` 已经重装并切到新的 canonical 路径：

- `services/capswriter/runtime/CapsWriter-Offline`

迁移完成后：

- `services/capswriter/runtime/CapsWriter-Offline` 是唯一的 canonical runtime
- 旧的 `backups/vendor/capswriter/*` 只属于迁移前遗留，不再作为当前运行依赖
- 本机上的旧 `backups/vendor/capswriter` 可以删除，避免继续堆放重复模型和下载包

如果要把已安装服务正式切换到新的 canonical 路径，请用管理员 PowerShell 运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File C:\code\AIInformationProcessor\services\capswriter\windows-service\install_capswriter_service.ps1 -StartService
```

## 目录约定

- `windows-service/`: 跟 Windows Service 相关的可追踪资产
- `runtime/`: 本机下载或手动放置的 CapsWriter runtime，默认不进 Git
- `runtime/downloads-archive/`: 本机保留的原始下载包归档，默认不进 Git

## Runtime 查找顺序

安装脚本会按这个顺序找 `CapsWriter-Offline`：

1. 环境变量 `CAPSWRITER_APP_DIR`
2. `services/capswriter/runtime/CapsWriter-Offline`
3. `backups/vendor/capswriter/app/CapsWriter-Offline`

第 3 条只保留为兼容旧机器或旧会话的迁移回退路径；当前这台机器已经完成切换，应优先维护第 1/2 条。
