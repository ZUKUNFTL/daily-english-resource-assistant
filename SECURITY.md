# Security Policy

## Reporting

请通过 GitHub Security Advisory 私下报告安全问题，不要在公开 issue 中提交 API Key、Cookie、访问令牌、个人媒体或数据库文件。

## Local secrets

YouTube Data API Key 仅保存在本机 `data/settings.json`。该文件已被 `.gitignore` 排除。项目不接收账号密码、浏览器 Cookie 或任意下载器命令行参数。

## Download boundaries

下载器只处理受支持平台的 HTTP/HTTPS URL，并禁止播放列表批量下载。项目不绕过 DRM、登录、会员、地区限制或平台访问控制。
