#!/usr/bin/env python3
"""项目根目录（开发模式=源码目录，打包后=可执行文件所在目录）。"""

import os
import sys


def resolve_eqt_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


EQT_DIR = resolve_eqt_dir()
