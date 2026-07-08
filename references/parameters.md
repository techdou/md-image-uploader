# CLI 参数参考

所有脚本的完整命令行参数。中英对照，便于 Agent 快速查阅。

## upload_images.py（核心）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `target`（必填） | — | 要处理的 `.md`/`.html` 文件或目录（递归扫描）。 |
| `--provider` | `r2` | 图床标识：`r2` `oss` `cos` `qiniu` `minio` `b2`。对应配置文件中的 key。 |
| `--config` | `~/.md-image-uploader.json` | 配置文件路径。 |
| `--in-place` | 否 | 直接改写原文件。默认生成 `<name>.uploaded.<ext>`。 |
| `--dry-run` | 否 | 只扫描和报告，不上传、不写文件、不需要凭据。 |
| `--manifest` | 文档同级 `.upload-manifest.json` | manifest 路径。跨文档共享去重时指定。 |
| `--skip-uploaded` / `--no-skip-uploaded` | 开 | 命中 manifest 且文件未变则复用 URL。`--no-skip-uploaded` 强制重传。 |
| `--include-ext` | 全部图片类型 | 逗号分隔扩展名，如 `.png,.jpg`，只上传这些类型。 |
| `--strict` | 否 | 任一上传失败则退出码非零（用于 CI/质量门禁）。 |
| `--json` | 否 | 输出 JSON 报告到 stdout（机器可读）。 |
| `--retries` | `3` | 单文件上传失败的重试次数（指数退避）。 |

## estimate_upload.py（预估，无需凭据）

| 参数 | 说明 |
|---|---|
| `target`（必填） | 文件或目录。 |
| `--json` | 输出 JSON 数组，每项含 `local_images`/`total_size_bytes`/`missing`。 |

## check_links.py（验证替换结果）

| 参数 | 说明 |
|---|---|
| `target`（必填） | 已上传的文档或目录。 |
| `--verify-urls` | 对每个 hosted URL 发 HEAD 请求验证可达（需要网络）。 |
| `--strict` | 有残留本地路径或 URL 不可达时退出码非零。 |

## config_provider.py（配置凭据）

| 参数 | 说明 |
|---|---|
| `--provider` | 要配置的图床（`r2`/`oss`/`cos`/`qiniu`/`minio`/`b2`），默认 `r2`。 |
| `--config` | 配置文件路径，默认 `~/.md-image-uploader.json`。 |
| `--list` | 列出已配置的 provider，不交互。 |

## 退出码约定

所有脚本遵循统一退出码：

- `0`：成功，或非 strict 模式下有可恢复的失败。
- `1`：`--strict` 模式下存在上传失败或链接问题。
- `2`：输入错误（文件不存在、provider 未配置等）。
