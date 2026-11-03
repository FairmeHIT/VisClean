from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys

from app.core.editable_pptx import EditablePptxError, EditablePptxResult


@dataclass(frozen=True)
class EditPptCliPaths:
    command: list[str]
    description: str


def convert_images_with_editppt_cli(
    image_paths: list[Path],
    output_path: Path,
    *,
    progress_callback=None,
) -> EditablePptxResult:
    if not image_paths:
        raise EditablePptxError("no source images were provided")

    cli = _resolve_editppt_cli()
    output_path = Path(output_path).with_suffix(".pptx")
    run_root = output_path.parent / "image_to_editable_ppt_runs"
    run_root.mkdir(parents=True, exist_ok=True)
    _notify(progress_callback, f"正在启动 Image-to-Editable-PPT CLI：{cli.description}")

    prepare_command = [
        *cli.command,
        "prepare",
        "--out-root",
        str(run_root),
        *[str(Path(path)) for path in image_paths],
    ]
    _notify(progress_callback, "正在准备 EditPPT run 目录和文本 hints...")
    prepared = subprocess.run(prepare_command, text=True, capture_output=True)
    if prepared.returncode != 0:
        message = (prepared.stderr or prepared.stdout or "").strip()
        raise EditablePptxError(f"EditPPT prepare failed: {message}")

    run_dir = _prepared_run_dir(prepared.stdout, run_root)
    _notify(progress_callback, f"EditPPT 已准备 run 目录：{run_dir}")

    next_command = [*cli.command, "run", "next", str(run_dir), "--json"]
    next_step = subprocess.run(next_command, text=True, capture_output=True)
    if next_step.returncode != 0:
        message = (next_step.stderr or next_step.stdout or "").strip()
        raise EditablePptxError(f"EditPPT run next failed: {message}")

    raise EditablePptxError(
        "Image-to-Editable-PPT CLI 已接入并完成 prepare，但该 skill 的页面重建阶段需要 agent/page-worker "
        "按 worker prompt 生成 manifest/page.pptx/validation。当前桌面 App 还没有内置该 agent 执行器，"
        f"因此不能直接完成最终 PPTX。已生成的 run 目录：{run_dir}"
    )


def _resolve_editppt_cli() -> EditPptCliPaths:
    installed = shutil.which("editppt")
    if installed:
        return EditPptCliPaths([installed], installed)

    local_main = (
        Path.cwd()
        / "skills"
        / "image-to-editable-ppt-skill-main"
        / "skills"
        / "image-to-editable-ppt"
        / "cli"
        / "editppt"
        / "runtime"
        / "main.py"
    )
    if local_main.exists():
        return EditPptCliPaths([sys.executable, str(local_main)], str(local_main))

    raise EditablePptxError(
        "未找到 editppt CLI。请安装 image-to-editable-ppt skill 的 CLI，或保留仓库内 "
        "skills/image-to-editable-ppt-skill-main 目录。"
    )


def _prepared_run_dir(stdout: str, fallback_root: Path) -> Path:
    for line in stdout.splitlines():
        candidate = Path(line.strip().strip('"'))
        if candidate.name == "deck_manifest.json" and candidate.exists():
            return candidate.parent
    runs = sorted((path for path in fallback_root.iterdir() if path.is_dir()), key=lambda path: path.stat().st_mtime)
    if runs:
        return runs[-1]
    return fallback_root


def _notify(callback, message: str) -> None:
    if callback is not None:
        callback(message)
