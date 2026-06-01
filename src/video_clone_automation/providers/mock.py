from __future__ import annotations

from pathlib import Path
from typing import Any

from video_clone_automation.providers.base import ImageProvider, LLMProvider, VideoProvider


class MockLLMProvider(LLMProvider):
    def __init__(self, provider_name: str = "mock-llm") -> None:
        self.provider_name = provider_name

    def generate_json(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if task_name == "step1_rewrite":
            return {
                "storyline": "主角先用亲身踩坑的开场钩子吸引注意，中段展示错误选择带来的连锁后果，后段给出新的解决方式并形成结果反转，最后用一句简短结论完成收束。",
                "storyline_rationale": "这版仿写保留了原爆款视频常见的前三秒强钩子、快速抛出问题、后果升级、解决方案反转和结尾价值收束结构；内容层只替换具体冲突和大结局，不改变原视频偏写实短剧口播的构图、节奏和镜头比例。人物只保留贯穿全片的主角和同事，固定空间锚点归入场景，跨分幕重复交互的文件夹与签字笔拆为独立道具，避免把单次出现的临时元素单独建模，保证角色设计与分幕中真实可见的人物严格一致。",
                "overall_style": {
                    "description": "短剧写实冷色质感"
                },
                "character_design": [
                    {
                        "name": "主角",
                        "description": "二十七八岁的都市女性，职场新人气质，鹅蛋脸，眉眼利落，深棕色中长直发，身形偏瘦，穿灰蓝色衬衫和黑色西装长裤，衬衫为细腻棉质面料，外套挺括，整体配色克制偏冷。",
                        "voice_tone": "清亮偏年轻的女声，语速偏快但咬字清楚，遇到反转时会短暂停顿后再加强重音，整体是克制但带一点自嘲的表达。",
                        "art_style": "短剧写实摄影风格，真实皮肤纹理，发丝清晰，服装布料褶皱自然，柔和室内侧光，轻微胶片颗粒，与全片低饱和冷色质感一致。"
                    },
                    {
                        "name": "同事",
                        "description": "三十岁出头的都市男性，同事身份感明显，方脸，鼻梁偏直，短黑发，体型中等，穿深灰针织上衣和黑色休闲长裤，针织面料有细密纹理，整体配色偏暗。",
                        "voice_tone": "中低音男声，语速平稳，咬字清晰，提醒别人时语气直接，情绪提高时音量略升但不过分夸张。",
                        "art_style": "短剧写实摄影风格，真实肤质，针织面料纹理可见，侧逆光下轮廓清楚，轻微胶片颗粒，与全片低饱和冷色短剧风格一致。"
                    },
                ],
                "prop_design": [
                    {
                        "name": "项目文件夹",
                        "description": "A4 尺寸的深蓝色硬壳文件夹，厚度中等，磨砂封面，边角有轻微磨损，封口处带黑色弹力带，内部夹层较多，用于承载关键项目资料并强化职场冲突识别。",
                        "art_style": "写实摄影质感，硬壳表面反光克制，边缘磨损细节清楚，低饱和蓝灰色调，特写时保留浅景深和轻微胶片颗粒，与全片写实短剧质感一致。"
                    },
                    {
                        "name": "签字笔",
                        "description": "细长黑色商务签字笔，金属笔夹，表面半哑光，尺寸接近常规中性笔，用于在关键节点强化决策和反转动作识别。",
                        "art_style": "写实摄影质感，金属笔夹有细窄高光，笔杆反射柔和，低饱和冷色表现，近景下边缘锐利但不过曝，与全片镜头质感一致。"
                    }
                ],
                "scene_design": [
                    {
                        "name": "开放式办公室",
                        "description": "现代开放式办公室空间，前景有固定长桌和办公椅，后景为浅灰隔断与玻璃会议室，顶部是均匀冷白灯带，空间纵深清楚，桌面和玻璃门框是最稳定的视觉锚点，主色调为灰蓝和黑白。",
                        "art_style": "室内短剧写实布光，低饱和冷色调，背景轻微虚化，玻璃和金属边缘保留柔和轮廓光，整体延续纪实摄影质感。"
                    }
                ],
                "script_breakdown": [
                    {
                        "segment_id": 1,
                        "time_range": "00:00-00:09",
                        "duration": "9秒",
                        "design_intent": "作为开场钩子，用单人中近景快速抛出主角踩坑结果，延续原视频常见的正面口播起手和短停顿抓人节奏；这一段合并了开场看文件和抬头口播两个连续动作，减少碎片切分。",
                        "scenes": ["开放式办公室"],
                        "characters": ["主角"],
                        "props": ["项目文件夹"],
                        "visual_dialogue": "00:00-00:03：剧情上，主角先展示自己刚犯下的错误，引出悬念。画面中，主角位于画面中央偏左前景，腰部以上中近景，占画面高度约62%，身体微微朝向右侧；开放式办公室长桌位于画面下三分之一中景，横向占画面宽度约72%，项目文件夹放在桌面中央偏左前景，占画面宽度约18%。主角低头看向文件夹，停顿0.4秒。00:03-00:06：剧情上，她抬头承认自己以为这样更省事。画面保持固定机位，主角视线转回镜头方向，肩部微微前倾，说：‘我以为这一步省掉，项目会更快。’环境音是轻微空调声和远处键盘声。00:06-00:09：剧情上，她补出错误后果，把观众拉进痛点。主角手掌压住文件夹边缘，语速略快地说：‘结果第二天，整个流程全卡住了。’句尾停顿0.3秒，只保留办公室底噪。",
                        "style_and_texture": "全局统一风格：短剧写实摄影风格，低饱和冷色，轻微胶片颗粒，柔和室内顶光与侧光结合，人物清晰、背景轻微虚化、浅景深适中。当前分幕微调：主角面部受光更集中，桌面反光压低，文件夹封面保留轻微磨砂高光。",
                        "cinematography_and_editing": "固定机位中近景开场，机位略低于平视，主体居中偏左留出右侧少量留白；分幕内部通过轻微表情切和微幅推近形成节奏，采用干净硬切进入下一段，保持原视频快节奏口播习惯。"
                    },
                    {
                        "segment_id": 2,
                        "time_range": "00:09-00:19",
                        "duration": "10秒",
                        "design_intent": "作为中段矛盾升级，引入第二角色形成左右对话和压力对比，继承原视频通过同场景快切强化冲突的节奏；同一办公室同一事件链条内的对视、递笔和提醒被合并在一个分幕里。",
                        "scenes": ["开放式办公室"],
                        "characters": ["主角", "同事"],
                        "props": ["项目文件夹", "签字笔"],
                        "visual_dialogue": "00:09-00:12：剧情上，同事进入并指出问题核心，矛盾升级。画面中，主角仍在画面左侧前景，半身入镜，占画面高度约55%；同事从画面右侧中景进入，半身入镜，占画面高度约38%，与主角保持约半个身位距离。项目文件夹仍在桌面中央前景，签字笔放在文件夹右侧，占画面高度约6%。同事看向主角说：‘你少签了确认页，后面没人敢接。’。00:12-00:16：剧情上，主角意识到问题不是小失误。画面内部快切到主角更近的反应镜头，主角占画面高度约68%，看向画面右侧的同事，停顿0.4秒后低声说：‘我真以为不会影响这么大。’00:16-00:19：剧情上，同事把解决压力推到主角面前。镜头切回双人构图，同事位于右侧中景，用手掌把签字笔推到主角面前，说：‘现在只能你自己补回来。’桌面有轻微摩擦声，句末留白0.3秒。",
                        "style_and_texture": "全局统一风格：短剧写实摄影风格，低饱和冷色，轻微胶片颗粒，柔和室内顶光与侧光结合，人物清晰、背景轻微虚化、浅景深适中。当前分幕微调：双人对话时右侧轮廓光略强，签字笔金属笔夹出现窄高光，主角反应镜头背景虚化略强。",
                        "cinematography_and_editing": "从单人中近景切入双人左右构图，轴线稳定保持主角在左、同事在右；中间插入一次主角近景反应快切，再切回双人画面，整体仍以固定机位和短时硬切维持高密度信息节奏。"
                    },
                    {
                        "segment_id": 3,
                        "time_range": "00:19-00:30",
                        "duration": "11秒",
                        "design_intent": "作为反转和结尾收束，让主角在同一视觉体系下完成补救并改写结局，保留原视频常见的结果翻转后快速总结的收口方式；这一段把补签、回传和结论口播合并为一个完整高潮段。",
                        "scenes": ["开放式办公室"],
                        "characters": ["主角"],
                        "props": ["项目文件夹", "签字笔"],
                        "visual_dialogue": "00:19-00:23：剧情上，主角决定立刻补救，进入反转动作。画面中，主角位于画面中央偏左前景，胸口以上近景，占画面高度约66%，桌面仍位于下方前景。项目文件夹被翻开铺在桌面中央，横向占画面宽度约28%；签字笔位于主角右手侧前景，占画面高度约7%。主角拿起签字笔，快速补签，环境音只保留笔尖划过纸面的声音。00:23-00:27：剧情上，她把错误转为补救成功的结果。画面轻微推近，主角看向镜头偏右侧，说：‘我连夜补完，今天反而第一个过审。’语速先快后稳。00:27-00:30：剧情上，她给出最终收束，形成可复用价值点。主角把文件夹合上放回桌面中央，手掌压住封面，停顿0.3秒后说：‘省掉的那一步，最后都会加倍还回来。’句末只留办公室底噪收尾。",
                        "style_and_texture": "全局统一风格：短剧写实摄影风格，低饱和冷色，轻微胶片颗粒，柔和室内顶光与侧光结合，人物清晰、背景轻微虚化、浅景深适中。当前分幕微调：最终反转段的面部亮度略提，纸面高光更清楚，结尾收口时背景虚化略收，保持人物与道具都清晰可辨。",
                        "cinematography_and_editing": "近景起手突出补救动作，随后做轻微推近强化反转表达，结尾保持正面口播收束；内部以动作连续性连接，无额外复杂运镜，用一次细小推近替代多余切镜，延续原视频干脆直接的结尾节奏。"
                    }
                ]
            }

        if task_name == "step2_visual_plan":
            script = payload.get("script", {})
            segments = script.get("script_breakdown", [])
            video_aspect_ratio = payload.get("video_aspect_ratio")
            character_images = [
                {
                    "name": item["name"],
                    "generation_prompt": item["description"] + " 正面角色图，白底，9:16竖图。",
                }
                for item in script.get("character_design", [])
            ]
            prop_images = [
                {
                    "name": item["name"],
                    "generation_prompt": item["description"] + " 白底单一道具图。",
                }
                for item in script.get("prop_design", [])
            ]
            scene_images = [
                {
                    "name": item["name"],
                    "generation_prompt": item["description"]
                    + (
                        f" {video_aspect_ratio}比例图，仅生成场景空间。"
                        if video_aspect_ratio
                        else " 仅生成场景空间。"
                    ),
                }
                for item in script.get("scene_design", [])
            ]
            reference_image_plan = []
            for segment in segments:
                segment_id = int(segment["segment_id"])
                reference_image_plan.append(
                    {
                        "segment_id": segment_id,
                        "reference_image_count": 1,
                        "reference_images": [
                            {
                                "reference_image_id": f"{segment_id}-1",
                                "source_assets": {
                                    "characters": segment.get("characters", []),
                                    "scenes": segment.get("scenes", []),
                                    "props": segment.get("props", []),
                                },
                                "generation_prompt": (
                                    segment.get("visual_dialogue", "")[:500]
                                    + (
                                        f"\n目标视频画面比例：{video_aspect_ratio}。"
                                        if video_aspect_ratio
                                        else ""
                                    )
                                ),
                            }
                        ],
                    }
                )
            return {
                "asset_image_prompts": {
                    "character_images": character_images,
                    "prop_images": prop_images,
                    "scene_images": scene_images,
                },
                "reference_image_plan": reference_image_plan,
            }

        return {
            "provider": self.provider_name,
            "task_name": task_name,
            "input": payload,
            "prompt_preview": prompt[:120],
        }


class MockImageProvider(ImageProvider):
    def __init__(self, provider_name: str = "mock-image") -> None:
        self.provider_name = provider_name

    def generate_image(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        output_path = payload.get("output_path", "data/output/mock.png")
        return {
            "provider": self.provider_name,
            "task_name": task_name,
            "status": "planned",
            "output_path": output_path,
            "file_name": Path(output_path).name,
            "asset_id": payload.get("asset_id"),
            "frame_id": payload.get("frame_id"),
            "name": payload.get("name"),
            "category": payload.get("category"),
            "scene_id": payload.get("scene_id"),
            "duration_sec": payload.get("duration_sec"),
            "reference_image_id": payload.get("reference_image_id"),
            "reused_reference_image_id": payload.get("reused_reference_image_id"),
            "prompt": payload.get("prompt") or prompt,
            "source_materials": payload.get("source_materials", []),
            "source_assets": payload.get("source_assets"),
            "aspect_ratio": payload.get("aspect_ratio"),
        }


class MockVideoProvider(VideoProvider):
    def __init__(self, provider_name: str = "mock-video") -> None:
        self.provider_name = provider_name

    def generate_video(
        self,
        *,
        task_name: str,
        prompt: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        output_path = payload.get("output_path", "data/output/mock.mp4")
        return {
            "provider": self.provider_name,
            "task_name": task_name,
            "status": "planned",
            "segment_id": payload.get("segment_id"),
            "output_path": output_path,
            "duration": payload.get("duration"),
            "duration_sec": payload.get("duration_sec"),
            "reference_frame_path": payload.get("reference_frame_path"),
            "reference_image_paths": payload.get("reference_image_paths", []),
            "reference_image_ids": payload.get("reference_image_ids", []),
            "aspect_ratio": payload.get("aspect_ratio"),
            "prompt": payload.get("prompt") or prompt,
        }


def parse_duration_to_seconds(duration: str) -> int | None:
    text = duration.strip().replace("秒", "")
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None
