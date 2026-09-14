# Contributing

欢迎提交 issue 和 pull request。提交代码前请确保：

```powershell
$env:PYTHONPATH = "app"
.\.venv\Scripts\python.exe -m pytest -q
```

不要提交虚拟环境、模型、缓存、下载媒体、用户数据库、API Key 或构建产物。在线回归测试必须由 `ONLINE_REGRESSION=1` 显式启用，并只使用有权下载的公开测试资源。

本项目采用 GPL-3.0；提交代码即表示你同意按同一许可证提供贡献。
