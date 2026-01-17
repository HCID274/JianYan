# 语音转文字工具（Windows）

一款 Windows 端语音转文字工具。支持 NVIDIA 显卡本地部署，提供秒级响应。快捷键录音、本地 AI 转写、自动去口水词，一键粘贴到任意位置。

---

## 目录

- [功能亮点](#功能亮点)
- [快速上手](#快速上手)
- [开发者部署指南](#开发者部署指南)
- [使用教程](#使用教程)
- [配置说明](#配置说明)
- [技术规格](#技术规格)
- [常见问题](#常见问题)

---

## 功能亮点

- **NVIDIA 本地部署**：支持 RTX 显卡 CUDA 加速，转写速度秒级响应
- **快捷键录音**：`Ctrl+Shift+Space` 开始/停止录音
- **本地 AI 转写**：使用 SenseVoice Small 模型，无需联网
- **智能去口水**：AI 自动去除重复、口水词，让表达更精炼（需配置 API）
- **自动粘贴**：转写完成后自动粘贴到当前光标位置

---

## 快速上手

### 1. 下载安装包

下载 `JianyanSetup_0.1.0.exe`（约 3.3GB），内含模型权重、Python 虚拟环境与可执行程序。

下载地址：https://jianyan.hcid274.xyz/downloads/JianyanSetup_0.1.0.exe

### 2. 运行安装

直接安装即用。程序会自动检测 RTX 显卡并启用加速，无显卡则回退 CPU 模式。

**注意**：请选择普通目录安装（如 `D:\Apps`），不要选择 `C:\Program Files` 等系统保护目录。

### 3. 配置 API（可选）

如需「润色去重」功能，在托盘设置中填写 OpenAI 兼容格式 API：
- Base URL
- API Key
- Model（推荐 Qwen 系列）

---

## 开发者部署指南

本章节面向需要从源码构建或二次开发的技术人员。

### 环境要求

| 依赖 | 要求 |
|------|------|
| Python | 3.10.13 |
| 显卡驱动 | NVIDIA 驱动（支持 CUDA 加速） |
| 操作系统 | Windows 10/11 |

### 从源码安装

**方式一：一键安装（推荐）**

```cmd
install.cmd
```

**方式二：手动安装**

```cmd
# 1. 创建虚拟环境
py -3.10 -m venv .venv

# 2. 激活虚拟环境
.\.venv\Scripts\activate

# 3. 安装 PyTorch（CUDA 版）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 4. 安装其他依赖
pip install -r requirements.txt

# 5. 下载模型
python scripts\predownload_models.py
```

### 构建安装包

1. 确保已安装 Python 3.10.13
2. 安装 [Inno Setup](https://jrsoftware.org/isinfo.php)
3. 用 Inno Setup 打开并编译：`installer\setup.iss`
4. 生成的安装包位于：`installer\output\AudioToTextSetup.exe`

---

## 使用教程

### 启动应用

- 桌面快捷方式
- 开始菜单
- 命令行运行 `run_app.cmd`

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| `Ctrl+Shift+Space` | 开始/停止录音 |

### 托盘菜单

应用运行后会在系统托盘显示图标，右键点击可进行设置。

---

## 配置说明

在托盘图标右键菜单中打开「设置」，可配置以下选项：

| 配置项 | 说明 |
|--------|------|
| OpenAI Base URL | API 服务地址 |
| OpenAI API Key | API 密钥 |
| 模型名 | 推荐 Qwen 系列 |

如果不配置 API，语音转写功能仍可正常使用，但「智能去口水」功能将不可用。

---

## 技术规格

### 模型信息

| 项目 | 说明 |
|------|------|
| 转写模型 | SenseVoice Small（本地运行） |
| 模型目录 | 安装目录下 `models/` |
| 录音格式 | WAV PCM 16kHz 单声道 |

### 资源占用

| 项目 | 大小 |
|------|------|
| 安装空间 | 约 6-10 GB（含依赖和模型） |
| GPU 显存 | 约 2-4 GB（含 VAD/标点模型） |

---

## 常见问题

### 快捷键无效怎么办？

`keyboard` 库需要高权限才能全局监听键盘。请以管理员身份运行应用。

### 安装失败怎么办？

请检查网络是否正常，模型下载需要联网。

### AMD 显卡能用吗？

**不建议使用**。本项目针对 NVIDIA 显卡优化，AMD 显卡存在兼容性问题。如无 NVIDIA 显卡，程序会回退到 CPU 模式，转写速度较慢（约 10-30 秒）。

---

如有其他问题，欢迎提交 Issue 反馈。
