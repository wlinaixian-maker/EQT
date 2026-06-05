#!/usr/bin/env python3
"""打包 EQT 看板（PyInstaller），生成可分发的文件夹与 zip。"""

import os
import platform
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))
DIST_APP = os.path.join(ROOT, 'dist', 'EQT-Dashboard')
RELEASE_DIR = os.path.join(ROOT, 'release')

DATA_FILES = [
    'index.html',
    'dashboard_config.json',
    'station_targets.json',
    'har_export_requests.py',
    'report_data.json',
    'refresh_status.json',
]

DATA_DIRS = ['data_archive', 'exports', 'har']


def run(cmd, **kwargs):
    print('→', ' '.join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True, **kwargs)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print('未安装 PyInstaller，请先执行：')
        print('  pip3 install pyinstaller')
        raise SystemExit(1)


def copy_runtime_data(target_dir):
    os.makedirs(target_dir, exist_ok=True)
    for name in DATA_FILES:
        src = os.path.join(ROOT, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(target_dir, name))
            print(f'  + {name}')
    for dirname in DATA_DIRS:
        src = os.path.join(ROOT, dirname)
        dst = os.path.join(target_dir, dirname)
        if os.path.isdir(src):
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f'  + {dirname}/')
        else:
            os.makedirs(dst, exist_ok=True)
            print(f'  + {dirname}/ (空)')


def write_readme(target_dir):
    exe = 'EQT-Dashboard.exe' if platform.system() == 'Windows' else 'EQT-Dashboard'
    path = os.path.join(target_dir, '使用说明.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'''EQT 看板 — 打包版（无需安装 Python）

【启动】
  双击 {exe}
  浏览器会自动打开 http://localhost:8765

【要求】
  - 需能访问内网报表服务器（刷新数据时）
  - 关闭看板：在黑色窗口按 Ctrl+C，或直接关掉窗口

【数据目录】（与 {exe} 同目录）
  exports/      临时 Excel
  data_archive/ 历史归档
  dashboard_config.json  看板设置

【Mac 首次打不开】
  右键 {exe} → 打开 → 仍要打开
''')
    print(f'  + 使用说明.txt')


def zip_release(folder, zip_path):
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
        for dirpath, _dirnames, filenames in os.walk(folder):
            for name in filenames:
                full = os.path.join(dirpath, name)
                arc = os.path.relpath(full, os.path.dirname(folder))
                zf.write(full, arc)
    print(f'✓ {zip_path}')


def main():
    ensure_pyinstaller()

    print('\n[1/4] 更新看板数据…')
    from generate_index import run as generate_index_run
    generate_index_run()

    print('\n[2/4] PyInstaller 打包…')
    if os.path.isdir(DIST_APP):
        shutil.rmtree(DIST_APP)
    run([sys.executable, '-m', 'PyInstaller', 'eqt_dashboard.spec', '--noconfirm', '--clean'])

    if not os.path.isdir(DIST_APP):
        raise SystemExit(f'打包失败，未找到 {DIST_APP}')

    print('\n[3/4] 复制数据文件…')
    copy_runtime_data(DIST_APP)
    write_readme(DIST_APP)

    print('\n[4/4] 生成 release zip…')
    os.makedirs(RELEASE_DIR, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M')
    plat = 'win' if platform.system() == 'Windows' else 'mac'
    zip_name = f'EQT-Dashboard_{plat}_{stamp}.zip'
    zip_path = os.path.join(RELEASE_DIR, zip_name)
    zip_release(DIST_APP, zip_path)

    print(f'\n完成。分发文件夹: {DIST_APP}')
    print(f'分发 zip: {zip_path}')


if __name__ == '__main__':
    main()
