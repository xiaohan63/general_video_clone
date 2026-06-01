# Video Clone Automation

一个面向“输入原视频，输出仿写克隆视频”的可扩展项目骨架。

当前版本先把 5 个阶段的接口、配置、目录结构和 CLI 跑通，并把第 1/2/3 步接入了可替换的 OpenAI 兼容 provider：

1. 爆款视频剧本解析与仿写
2. 基于剧本做关键帧与素材图规划
3. 生成素材图与关键帧参考图
4. 基于参考图生成视频片段
5. 拼接视频片段为完整长视频

默认 mock 配置仍然保留，方便先本地串链路；同时新增了使用 Yunwu 的真实接入样例配置：

- [configs/pipeline.example.json](/Users/xiaohan/Desktop/clone/configs/pipeline.example.json)：全链路 mock 示例
- [configs/pipeline.openrouter.example.json](/Users/xiaohan/Desktop/clone/configs/pipeline.openrouter.example.json)：第 1 步使用 Yunwu Gemini，第 2 步使用 Yunwu 的示例

## 目录结构

```text
.
├── configs/
├── data/
│   ├── input/
│   ├── intermediate/
│   └── output/
├── prompts/
├── src/video_clone_automation/
│   ├── cli.py
│   ├── config.py
│   ├── models.py
│   ├── registry.py
│   ├── pipelines/
│   ├── providers/
│   ├── stages/
│   └── utils/
└── pyproject.toml
```

## 快速开始

```bash
cd /Users/xiaohan/Desktop/clone
python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step all
```

如果本地没有安装成包，也可以这样运行：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step all
```

## 本地前端页面

项目内置了一个轻量本地 Web 控制台，用于上传输入视频、填写画面比例和 query、查看并编辑各 step 的模型与 prompt、启动 pipeline，并在生成后查看剧本、人物图、场景图、道具图、参考图、分幕视频和成片视频。

```bash
PYTHONPATH=src python3 -m video_clone_automation.web --host 127.0.0.1 --port 8765
```

打开：

```text
http://127.0.0.1:8765
```

页面保存配置时会按视频名称生成 `configs/pipeline.{video_name}.json`，并把编辑后的 prompt 写入 `prompts/web/{video_name}/`，避免直接覆盖全局 prompt 模板。

## 第 1 步真实调用

1. 安装依赖：

```bash
pip install -e .
```

2. 设置环境变量：

```bash
export YUNWU_API_KEY="你的 key"
```

或者在项目根目录创建 `.env` 文件：

```bash
YUNWU_API_KEY="你的 key"
```

3. 准备输入视频：

把原视频放到：

```text
data/input/dahuaxiyou.mp4
```

4. 修改第 1 步 query：

编辑 [configs/pipeline.openrouter.example.json](/Users/xiaohan/Desktop/clone/configs/pipeline.openrouter.example.json) 中的 `steps.step1.user_query`。

如需切换输出视频画面比例，编辑同一配置中的 `video.aspect_ratio`，例如 `"9:16"` 或 `"16:9"`。该值会写入场景图和分幕关键帧 prompt，并作为最终视频生成 API 的 `aspect_ratio` 参数传入；角色图和道具图不会受它影响。

如需生成多个视频，不需要新建 pipeline 代码。建议为每个视频复制一份配置文件，只改 `video.name`、`steps.step1.input_video` 和 `steps.step1.user_query`。配置中的 `{video_name}` 会自动替换成安全的文件夹名，因此每个视频的中间文件、图片和视频会分别写入：

- `data/intermediate/{video_name}/`
- `data/output/{video_name}/`

默认 `skip_if_exists` 为 `true`。如果对应 step 的输出 JSON 或清单已经存在，CLI 会直接复用本地文件，不再重新调用模型、生图或生视频 API。要强制重新生成某一步，把该 step 的 `skip_if_exists` 改为 `false`，或删除对应输出文件。

第 4 步会额外检查完整性：如果剧本里有 3 个分幕，但本地视频清单只有 1 个已完成分幕，CLI 会复用已完成的分幕，只补生成缺失的 2 个分幕。

5. 运行第 1 步：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.openrouter.example.json --step step1
```

输出会写到：

- `data/intermediate/{video_name}/step1_rewritten_script.json`

6. 运行第 2 步：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.openrouter.example.json --step step2
```

输出会写到：

- `data/intermediate/{video_name}/step2_visual_plan.json`

7. 运行第 3 步：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.openrouter.example.json --step step3
```

输出会写到：

- `data/intermediate/{video_name}/step3_generated_assets.json`
- `data/output/{video_name}/step3/assets/`
- `data/output/{video_name}/step3/reference_images/`

8. 运行第 4 步：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.openrouter.example.json --step step4
```

输出会写到：

- `data/output/{video_name}/step4_video_segments.json`
- `data/output/{video_name}/final_video_manifest.json`
- `data/output/{video_name}/step4/video_segments/`

9. 运行第 5 步，把第 4 步生成的视频片段拼接成长视频：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.openrouter.example.json --step step5
```

输出会写到：

- `data/output/{video_name}/final_video.mp4`
- `data/output/{video_name}/final_video_manifest.json`

第 5 步依赖本机 `ffmpeg`。如果片段编码一致，会优先使用无损 `-c copy` 拼接；如果直接拼接失败，会默认重新编码后再输出完整长视频。

运行时 CLI 会默认输出实时进度，例如当前 step、素材图序号、关键帧序号、视频片段序号，以及视频 API 的 task_id 和轮询状态。进度日志写到 stderr，最终 JSON summary 仍写到 stdout。若只想保留最终 summary，可加 `--no-progress`：

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.openrouter.example.json --step all --no-progress
```

如需先测试单个分幕，可在 [configs/pipeline.openrouter.example.json](/Users/xiaohan/Desktop/clone/configs/pipeline.openrouter.example.json) 的 `steps.step4` 中临时添加：

```json
"segment_ids": [1]
```

说明：

- 本地视频会自动转成 base64 data URL 后发给 OpenRouter。
- 当前第 1 步使用 JSON Schema 强约束输出结构，schema 在 [step1_rewrite.schema.json](/Users/xiaohan/Desktop/clone/schemas/step1_rewrite.schema.json)。
- OpenRouter 视频输入文档说明了 `video_url` 支持 URL 或 base64 data URL；对于本地视频，base64 是推荐方式。

## 运行单步

```bash
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step step1
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step step2
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step step3
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step step4
PYTHONPATH=src python3 -m video_clone_automation.cli run --config configs/pipeline.example.json --step step5
```

## 可扩展设计

- 每一步都单独有 stage 模块，方便拆开重写。
- prompt 路径全部走配置，不写死在代码里。
- provider 通过注册表创建，后续可以替换成 OpenAI、可灵、你自己的 HTTP API，或者自定义类。
- 第 1 步支持 `single_pass` 和 `two_pass` 两种模式：
  - `single_pass`：直接“视频 + query => 最终 JSON 剧本”
  - `two_pass`：先反解分析，再把分析结果带入仿写
- 第 1 步 schema、prompt、model、query、超时、reasoning 开关都能独立替换。

## 下一步建议

优先把第 1 步接实：

1. 你给我第 1 步的 prompt。
2. 你给我第 1 步打算调用的 API 形式。
3. 我把 `mock_llm` 换成真实的脚本解析 / 仿写实现，并固定输出 JSON 结构。
