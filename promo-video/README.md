# 成分雷达 · 60 秒宣传片

1920 × 1080，30 fps，中文旁白、嵌入字幕与原创轻电子配乐。画面采用深松绿与浅绿，包含标签与目标输入、每份营养折算、原图依据和 GitHub 入口。

[已发布成片与说明](../docs/DEMO.md) · [项目报告](../docs/PROJECT_REPORT.md) · [参赛征文](../docs/COMPETITION_ESSAY.md)

## 预览与导出

在本目录运行：

~~~bash
npm install
npm run dev
npm run render
~~~

默认导出到仓库的 output/promo-video/ingredient-radar-promo-60s-1080p.mp4。

在 Studio 中选择 IngredientRadarPromo 查看完整视频；Scenes 中可单独编辑七个场景。

## 内容来源

演示数字与结果图来自仓库合成标签 samples/sample_wafer.jpg、固化抽取 evals/fixtures/POS-01.json 及实际脚本输出 output/promo-demo/。这是已有抽取结果的回放；对话画面明确标为流程示意，不代表项目有独立 App。

原片素材在 public/，台词及制作依据见 PRODUCTION.md。中文语音已合成并保存在 public/soundtrack.wav；普通预览与重渲染不调用语音服务。

## 可选：重新生成素材与配音

已有素材可直接预览与重渲染。若需重新生成，先安装 FFmpeg 并确保 `ffmpeg` / `ffprobe` 在 PATH 中，然后在**仓库根目录**运行：

~~~bash
python -m pip install Pillow numpy qrcode
python -m pip install --target output/video-tools edge-tts
python -X utf8 scripts/main.py samples/sample_wafer.jpg --agent-json evals/fixtures/POS-01.json --goal cut --allergen 花生 --out-dir output/promo-demo --json
python -X utf8 promo-video/tools/prepare_media.py
python -X utf8 promo-video/tools/captions.py
~~~

重新合成配音会将宣传台词发送到 Microsoft Edge 语音服务。已存在的分段配音会被复用；修改台词后需先移走 `output/promo-video/` 中对应的分段 MP3 再重新生成。

## 创意与技术参考

使用 Creative Production 的广告、准确内容及确定性导出规范，参考 [Remotion 官方技能](https://github.com/remotion-dev/skills/tree/main/skills/remotion-best-practices) 实现动画。音乐由项目代码合成。视频文件与视觉检查帧位于 output/promo-video/。
