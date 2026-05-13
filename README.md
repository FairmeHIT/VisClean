# pptx-fig-erase - 幻灯片清痕

幻灯片清痕是一个 Windows 桌面工具，用于打开 PowerPoint 文件，将幻灯片转换为图片，在页面上框选需要擦除的区域，使用 OpenCV 修复背景，并导出处理后的结果。适用于精细化图片水印去除，比如从NotebookLM、豆包、Qwen等AI大模型生成的pptx/图片中去除多余的内容。

## 功能

- 基于 PySide6 的 Windows 桌面界面
- 支持打开 `.pptx` 文件
- 通过 Microsoft PowerPoint COM 自动化将幻灯片导出为 PNG
- 支持在幻灯片图片上进行矩形框选
- 使用 OpenCV inpainting 擦除选区内容
- 支持基础撤销和重做
- 支持导出 PNG、图片版 PDF、图片版 PPTX

## 环境要求

- Windows 10 或 Windows 11
- Python 3.10 或更高版本
- 本机已安装 Microsoft PowerPoint
- PowerPoint COM 自动化可正常使用

注意：WPS 或其他演示软件不能替代 Microsoft PowerPoint。本工具的 PPTX 转图片功能依赖 PowerPoint COM。

## 首次安装

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动窗口

推荐使用 `pythonw.exe` 启动桌面窗口，不会额外打开控制台：

```powershell
.\.venv\Scripts\pythonw.exe -m app.main
```

开发时可以使用调试启动方式：

```powershell
.\.venv\Scripts\python.exe -m app.main
```


## 使用流程

1. 启动程序。
2. 在顶部 `图片分辨率` 中选择导出为图片时的宽度。分辨率越高，擦除细节越好，但转换和处理会更慢。
3. 点击顶部 `打开`，选择需要处理的 PPTX 文件。
4. 等待 PowerPoint 将幻灯片转换为图片。
5. 在左侧缩略图中选择页面。
6. 点击底部 `选框`，在页面上拖拽框选需要擦除的区域。
7. 点击底部 `擦除` 执行擦除。
8. 需要回退时使用底部 `撤销`。
9. 点击顶部 `导出`，选择导出目录。

在图片展示区域按住鼠标右键拖动，可以移动图片查看不同区域。

导出目录中会生成：

- `png/`：逐页 PNG 图片
- `export.pdf`：图片版 PDF
- `export.pptx`：图片版 PPTX


## 项目结构

```text
app/
  core/       转换、擦除、导出、会话和历史逻辑
  ui/         PySide6 桌面界面
  utils/      PowerPoint、路径、图片工具
  workers/    后台转换与擦除任务
tests/        单元测试
tools/        辅助验证脚本
```

## 运行测试

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```
