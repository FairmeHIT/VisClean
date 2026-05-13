# SlideClean（幻灯片清痕）

SlideClean（幻灯片清痕）是一个 Windows 桌面工具，用于打开 PowerPoint 文件，将幻灯片转换为图片，在页面上框选需要擦除的区域，使用 OpenCV 修复背景，并导出处理后的结果。

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

如果窗口没有出现，或者需要查看报错信息，使用调试启动方式：

```powershell
.\.venv\Scripts\python.exe -m app.main
```

程序窗口标题是 `SlideClean`。启动后如果看不到窗口，可以检查任务栏，或使用 `Alt+Tab` 切换。

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

## 验证 PowerPoint 导出

如果不确定本机 PowerPoint COM 是否可用，可以先运行验证脚本：

```powershell
$sample = Get-ChildItem -Filter *.pptx | Select-Object -First 1
.\.venv\Scripts\python.exe tools\validate_powerpoint_export.py $sample.FullName --out validation_output
```

验证成功后，`validation_output` 目录中应出现导出的幻灯片图片。

## 常见问题

### 启动后没有看到窗口

先检查任务栏或使用 `Alt+Tab`。如果仍然没有窗口，使用调试启动命令查看终端输出：

```powershell
.\.venv\Scripts\python.exe -m app.main
```

### 窗口显示不全或跑到屏幕边缘

当前版本启动时会根据屏幕可用区域计算窗口大小，并默认最大化显示。如果仍然显示异常，可以先关闭已有进程，再重新启动：

```powershell
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -in @("python.exe", "pythonw.exe") -and
    $_.CommandLine -match "\s-m\s+app\.main(\s|$)"
  } |
  ForEach-Object { Stop-Process -Id $_.ProcessId }
.\.venv\Scripts\pythonw.exe -m app.main
```

### 提示缺少依赖

确认已经在项目根目录安装依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 打开 PPTX 后转换失败

确认本机已安装 Microsoft PowerPoint，并且 PowerPoint 可以正常打开目标文件。该工具依赖 PowerPoint COM 自动化，PowerPoint 未安装、未激活、被弹窗阻塞，或目标文件无法正常打开，都会导致转换失败。

### 中文文件名在终端中显示乱码

这通常是终端编码显示问题。建议使用 PowerShell 或支持 UTF-8 的终端，也可以使用 PowerShell 变量、文件选择窗口或 Tab 补全，避免手动输入完整中文文件名。

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

如果尚未安装 `pytest`：

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
```

运行测试：

```powershell
.\.venv\Scripts\python.exe -m pytest
```
