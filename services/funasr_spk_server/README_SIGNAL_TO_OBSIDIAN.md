# FunASR Integration

`services/funasr_spk_server/` 是 `Signal to Obsidian` 仓库内的 canonical FunASR 源码位置。

在这个仓库里，FunASR 的运行约定是：

- 源码和 Dockerfile 放在 `services/funasr_spk_server/`
- 主编排入口是 `deploy/compose.yaml`
- 运行数据放在 `deploy/data/funasr-spk-server/`
- `VideoTranscriptAPI` 默认通过 compose 内地址 `ws://funasr-spk-server:8767` 访问它

这意味着：

- 不再把 `backups/vendor/funasr_spk_server/docker-compose.yml` 当成主启动入口
- 不再把模型、日志、上传文件、SQLite 数据库放回源码目录

如果要在这套仓库里启动 transcript 栈，用：

```powershell
docker compose -f deploy/compose.yaml --profile transcript up -d --build funasr-spk-server video-transcript-api
```
