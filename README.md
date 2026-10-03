# task26100538

大文件断点传输库（纯 Python + SQLite，无外部服务依赖）。

## 能力

- `TransferEngine.register(source, target, manifest)`：登记传输任务。`Manifest`
  为可信内容清单（文件总长度 + 按 64 MiB 顺序分块的 SHA-256，末块按实际长度）。
  任务 id 由清单内容派生，重新打开库后凭 id 即可继续，无需再次提供清单。
- `TransferEngine.resume(task_id)`：继续执行。逐块读取源文件、校验摘要、写入
  暂存文件并持久化已确认进度；全部确认后通过 `os.replace` 原子发布到目标路径。
- `TransferEngine.status(task_id)`：查询已确认进度（从文件头起连续校验成功的
  完整块）与完成状态。只有新版已发布才报告 `complete`。

## 保证

- 进度按块确认：部分写入、读取失败、摘要不匹配都不会推进进度；已确认数据
  落盘（fsync）并记录在 SQLite 中，中断后保留。
- 发布前目标保持原状（原文件不变 / 不存在则不创建）；发布是旧版到新版的一次
  原子切换，不暴露中间内容。
- 全部数据确认后，即使源文件被移走，仍可完成发布。

## 示例

```python
from resumable_transfer import Manifest, TransferEngine

manifest = Manifest(total_size=size, digests=chunk_sha256_list)
with TransferEngine("state.db") as engine:
    task_id = engine.register("/src/image.bin", "/dst/image.bin", manifest)
    status = engine.resume(task_id)   # 可反复调用直至 status.complete
```

## 测试

```sh
python3 -m pytest tests/ -v
```
