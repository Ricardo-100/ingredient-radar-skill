# GitHub 托管与播放入口

项目源码、项目报告、征文和视频成片保存在本 GitHub 仓库中。

| 材料 | 公开地址 |
| --- | --- |
| 项目及报告书 | https://github.com/Ricardo-100/ingredient-radar-skill/blob/main/docs/PROJECT_REPORT.md |
| Demo 在线播放与视频下载 | https://github.com/Ricardo-100/ingredient-radar-skill/blob/main/docs/DEMO.md |
| 参赛征文 | https://github.com/Ricardo-100/ingredient-radar-skill/blob/main/docs/COMPETITION_ESSAY.md |

## 在 GitHub 直接播放

打开 [Demo 页面](DEMO.md) 即可点击内嵌播放器观看，项目 README 也提供同一视频。成片通过 GitHub 视频附件上传，下载版本继续保留在本仓库中。此方式不需要开启 GitHub Pages。

## 可选：启用独立网页播放器

本目录包含无需构建的静态播放器 `index.html`，视频与字幕使用同仓库相对路径。

有仓库 Pages 管理权限的用户可在 GitHub 中打开 **Settings → Pages**：

1. 在 **Build and deployment** 下选择 **Deploy from a branch**。
2. 选择 **main** 分支和 **/docs** 目录，保存。
3. 等待部署完成，使用 Pages 设置页面实际显示的已发布网址。

未配置自定义域名时，默认站点地址通常是 `https://ricardo-100.github.io/ingredient-radar-skill/`。这只是预期地址，需在部署成功后再填写到提交表单；不要仅凭本说明认为站点已上线。

说明文档：[GitHub 官方 Pages 发布来源配置](https://docs.github.com/en/pages/getting-started-with-github-pages/configuring-a-publishing-source-for-your-github-pages-site)。

## 更新材料

- 更新成片时，重新上传 GitHub 视频附件并同步替换 README 和 Demo 页面中的附件链接；同时更新仓库 MP4、封面、字幕、`manifest.json` 与说明中的规格。
- 宣传片制作工程、原始配音、生成工具与分镜记录只保留在本地。相关目录、运行输出及依赖缓存已加入 Git 忽略列表。
- 对新标签生成的运行记录可能含本机路径或用户输入；先整理成适合公开的材料，再加入版本控制。
