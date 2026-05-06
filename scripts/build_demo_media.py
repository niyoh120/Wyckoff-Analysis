#!/usr/bin/env python3
"""Build demo videos with Chinese subtitles from screenshots.

Usage:
  uv run python scripts/build_demo_media.py
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS_W = 1920
CANVAS_H = 1080
CONTENT_TOP = 80
CONTENT_BOTTOM = 220
CAPTION_H = 140


@dataclass(frozen=True)
class FrameDef:
    image: str
    caption: str
    duration_sec: int


@dataclass(frozen=True)
class VideoDef:
    name: str
    frames: list[FrameDef]
    masks: list[tuple[int, int, int, int]]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ]
    for f in candidates:
        if Path(f).exists():
            try:
                return ImageFont.truetype(f, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def _prepare_frame(
    src_path: Path,
    dst_path: Path,
    caption: str,
    masks: list[tuple[int, int, int, int]],
) -> None:
    src = Image.open(src_path).convert("RGB")
    canvas = Image.new("RGB", (CANVAS_W, CANVAS_H), (6, 10, 18))

    avail_h = CANVAS_H - CONTENT_TOP - CONTENT_BOTTOM
    scale = min(CANVAS_W / src.width, avail_h / src.height)
    nw = int(src.width * scale)
    nh = int(src.height * scale)
    ox = (CANVAS_W - nw) // 2
    oy = CONTENT_TOP + (avail_h - nh) // 2
    resized = src.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas.paste(resized, (ox, oy))

    draw = ImageDraw.Draw(canvas, "RGBA")
    for x0, y0, x1, y1 in masks:
        draw.rectangle((x0, y0, x1, y1), fill=(0, 0, 0, 220))

    font = _font(46)
    text_bbox = draw.textbbox((0, 0), caption, font=font)
    tw = text_bbox[2] - text_bbox[0]
    th = text_bbox[3] - text_bbox[1]
    pad_x = 26
    pad_y = 14
    box_w = tw + pad_x * 2
    box_h = th + pad_y * 2
    bx0 = (CANVAS_W - box_w) // 2
    by0 = CANVAS_H - CAPTION_H + (CAPTION_H - box_h) // 2
    bx1 = bx0 + box_w
    by1 = by0 + box_h
    draw.rounded_rectangle((bx0, by0, bx1, by1), radius=16, fill=(0, 0, 0, 150))
    draw.text((bx0 + pad_x, by0 + pad_y - 2), caption, font=font, fill=(255, 255, 255, 255))

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dst_path)


def _concat_file(frames_dir: Path, frames: list[FrameDef], video_key: str) -> Path:
    concat_path = frames_dir / f"{video_key}.ffconcat"
    lines = ["ffconcat version 1.0"]
    for idx, frame in enumerate(frames, start=1):
        p = (frames_dir / f"{idx:02d}.png").resolve()
        lines.append(f"file '{p.as_posix()}'")
        lines.append(f"duration {frame.duration_sec}")
    last = (frames_dir / f"{len(frames):02d}.png").resolve()
    lines.append(f"file '{last.as_posix()}'")
    concat_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return concat_path


def _render_video(concat_path: Path, out_path: Path) -> None:
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        "-fps_mode",
        "vfr",
        "-pix_fmt",
        "yuv420p",
        "-c:v",
        "libx264",
        "-crf",
        "21",
        "-movflags",
        "+faststart",
        str(out_path),
    ]
    subprocess.run(cmd, check=True)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    demo = root / "attach" / "demo"
    build_root = demo / "_frames"
    build_root.mkdir(parents=True, exist_ok=True)

    videos = [
        VideoDef(
            name="web-demo",
            masks=[(0, 800, 350, 1080)],
            frames=[
                FrameDef("web-chat.png", "Step 1/8 读盘室：查看聊天与大盘水温", 4),
                FrameDef("web-analysis.png", "Step 2/8 单股分析：输入代码发起分析", 4),
                FrameDef("web-screener.png", "Step 3/8 漏斗选股：查看每日候选池", 4),
                FrameDef("web-portfolio.png", "Step 4/8 持仓管理：同步并审视组合", 4),
                FrameDef("web-tracking.png", "Step 5/8 推荐跟踪：复盘历史推荐表现", 4),
                FrameDef("web-tail-buy.png", "Step 6/8 尾盘记录：回看尾盘策略结果", 4),
                FrameDef("web-export.png", "Step 7/8 数据导出：拉取行情并导出 CSV", 4),
                FrameDef("web-settings.png", "Step 8/8 参数设置：配置模型与数据源", 4),
            ],
        ),
        VideoDef(
            name="streamlit-demo",
            masks=[(0, 160, 360, 300)],
            frames=[
                FrameDef("streamlit-chat.png", "Step 1/8 读盘室：多模型对话入口", 4),
                FrameDef("streamlit-export.png", "Step 2/8 数据导出：历史行情导出工具", 4),
                FrameDef("streamlit-screener.png", "Step 3/8 沙里淘金：漏斗参数与任务入口", 4),
                FrameDef("streamlit-ai-analysis.png", "Step 4/8 大师模式：单股深度分析", 4),
                FrameDef("streamlit-portfolio.png", "Step 5/8 持仓管理：编辑持仓与建议", 4),
                FrameDef("streamlit-tracking.png", "Step 6/8 推荐跟踪：观察推荐后续表现", 4),
                FrameDef("streamlit-settings.png", "Step 7/8 设置：通知与数据源配置", 4),
                FrameDef("streamlit-changelog.png", "Step 8/8 更新日志：查看版本演进", 4),
            ],
        ),
        VideoDef(
            name="cli-demo",
            masks=[],
            frames=[
                FrameDef("../cli-home.png", "Step 1/4 CLI 首页：能力总览", 4),
                FrameDef("../cli-running.png", "Step 2/4 执行中：工具调用与推理过程", 4),
                FrameDef("../cli-analysis.png", "Step 3/4 分析结果：结构化结论输出", 4),
                FrameDef("../cli-result.png", "Step 4/4 结果落地：可追踪可复盘", 4),
            ],
        ),
        VideoDef(
            name="dashboard-demo",
            masks=[(1270, 370, 1920, 560)],
            frames=[
                FrameDef("dashboard-overview-new.png", "Step 1/10 总览：核心指标与入口", 3),
                FrameDef("dashboard-recommendations.png", "Step 2/10 AI 推荐：推荐池明细", 3),
                FrameDef("dashboard-signals.png", "Step 3/10 信号池：待确认信号", 3),
                FrameDef("dashboard-tail-buy.png", "Step 4/10 尾盘记录：尾盘策略结果", 3),
                FrameDef("dashboard-portfolio.png", "Step 5/10 持仓：组合与仓位快照", 3),
                FrameDef("dashboard-memory.png", "Step 6/10 Agent 记忆：偏好与上下文", 3),
                FrameDef("dashboard-bgtasks.png", "Step 7/10 后台任务：任务执行追踪", 3),
                FrameDef("dashboard-chatlog-new.png", "Step 8/10 对话日志：会话列表", 3),
                FrameDef("dashboard-chatlog-detail-content.png", "Step 9/10 对话日志：单会话详情", 3),
                FrameDef("dashboard-sync.png", "Step 10/10 同步状态：Supabase 与本地一致性", 3),
            ],
        ),
    ]

    for video in videos:
        frames_dir = build_root / video.name
        frames_dir.mkdir(parents=True, exist_ok=True)
        for idx, frame in enumerate(video.frames, start=1):
            src = (demo / frame.image).resolve()
            dst = (frames_dir / f"{idx:02d}.png").resolve()
            _prepare_frame(src, dst, frame.caption, video.masks)
        concat_path = _concat_file(frames_dir, video.frames, video.name)
        out_path = (demo / f"{video.name}.mp4").resolve()
        _render_video(concat_path, out_path)
        print(f"[ok] {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
