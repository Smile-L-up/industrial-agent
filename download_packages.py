#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Python 依赖包离线下载脚本
用于下载所有 Python 依赖包到本地

使用方法:
    python download_packages.py

下载后的包将保存在 python-packages 目录中
"""

import os
import subprocess
import sys
import shutil
from pathlib import Path


def read_requirements(file_path="requirements.txt"):
    """读取 requirements.txt 文件"""
    packages = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # 跳过注释和空行
            if line and not line.startswith("#"):
                packages.append(line)
    return packages


def download_packages(packages, output_dir="python-packages"):
    """
    下载 Python 包到指定目录
    
    Args:
        packages: 包列表
        output_dir: 输出目录
    """
    # 创建输出目录
    output_path = Path(output_dir)
    if output_path.exists():
        print(f"清理旧目录：{output_dir}")
        shutil.rmtree(output_path)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # 构建 pip 命令 - 使用当前平台的包
    cmd = [
        sys.executable, "-m", "pip", "download",
        "-d", str(output_path),
        "--no-cache-dir",
    ]
    
    # 添加包列表
    cmd.extend(packages)
    
    print(f"\n开始下载 {len(packages)} 个依赖包...")
    print(f"下载目录：{output_dir}")
    print(f"目标平台：当前系统平台")
    print("-" * 50)
    
    try:
        # 执行下载
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        
        # 显示输出
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        # 统计下载的包
        downloaded = list(output_path.glob("*.whl")) + list(output_path.glob("*.tar.gz"))
        print("-" * 50)
        print(f"下载完成！共下载 {len(downloaded)} 个文件")
        
        # 计算总大小
        total_size = sum(f.stat().st_size for f in output_path.iterdir())
        print(f"总大小：{total_size / 1024 / 1024:.2f} MB")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"下载失败：{e}")
        if e.stderr:
            print(e.stderr)
        return False
    except Exception as e:
        print(f"发生错误：{e}")
        return False


def main():
    """主函数"""
    print("=" * 50)
    print("Python 依赖包离线下载工具")
    print("=" * 50)
    print()
    
    # 读取 requirements.txt
    if not os.path.exists("requirements.txt"):
        print("错误：找不到 requirements.txt 文件")
        return 1
    
    packages = read_requirements()
    print(f"找到 {len(packages)} 个依赖包")
    
    # 下载包
    success = download_packages(packages, "python-packages")
    
    if success:
        print()
        print("=" * 50)
        print("下载完成！")
        print("=" * 50)
        print()
        print("下一步操作:")
        print("1. 确保 Dockerfile 中包含了 COPY ./python-packages 指令")
        print("2. 运行 docker build 构建镜像")
        print("3. 运行 docker save 导出镜像")
        print()
        return 0
    else:
        print()
        print("=" * 50)
        print("下载失败，请检查网络连接或 pip 源配置")
        print("=" * 50)
        return 1


if __name__ == "__main__":
    sys.exit(main())