#!/usr/bin/env python3
"""本地看板服务：提供页面、保存配置、定时预览刷新与每日归档。"""

import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timedelta

from app_paths import EQT_DIR
from dashboard_config import (
    archive_deadline_today,
    format_archive_time,
    get_refresh_interval_sec,
    load_config,
    save_config,
)
PORT = int(os.environ.get('EQT_PORT', '8765'))
STATUS_FILE = os.path.join(EQT_DIR, 'refresh_status.json')
_refresh_lock = threading.Lock()
_refresh_thread = None


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f'[{self.log_date_time_string()}] {fmt % args}')

    def _send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode('utf-8')
        return json.loads(raw) if raw else {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == '/api/config':
            return self._send_json(200, load_config())
        if path == '/api/status':
            if os.path.isfile(STATUS_FILE):
                with open(STATUS_FILE, encoding='utf-8') as f:
                    return self._send_json(200, json.load(f))
            return self._send_json(200, {'ok': True, 'message': '尚未刷新', 'lastRun': None})
        if path == '/api/archive':
            from data_archive import archive_summary
            return self._send_json(200, archive_summary())
        if path in ('/', '/index.html'):
            return self._serve_file('index.html', 'text/html; charset=utf-8')
        rel_path = path.lstrip('/')
        file_path = os.path.join(EQT_DIR, rel_path)
        if os.path.isfile(file_path):
            ctype = 'application/octet-stream'
            if rel_path.endswith('.html'):
                ctype = 'text/html; charset=utf-8'
            elif rel_path.endswith('.json'):
                ctype = 'application/json; charset=utf-8'
            return self._serve_file(rel_path, ctype)
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        if path == '/api/config':
            try:
                body = self._read_json_body()
                cfg = save_config(body)
                return self._send_json(200, {'ok': True, 'config': cfg})
            except Exception as err:
                return self._send_json(400, {'ok': False, 'error': str(err)})
        if path == '/api/refresh':
            try:
                qs = parse_qs(urlparse(self.path).query)
                mode = (qs.get('mode') or ['preview'])[0]
                return self._send_json(200, start_refresh_async(mode=mode))
            except Exception as err:
                return self._send_json(500, {'ok': False, 'error': str(err)})
        self.send_error(404)

    def _serve_file(self, rel_path, content_type):
        file_path = os.path.join(EQT_DIR, rel_path)
        if not os.path.isfile(file_path):
            self.send_error(404)
            return
        with open(file_path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _run_refresh_job(*, mode='preview'):
    global _refresh_thread
    try:
        from hourly_refresh import refresh_once, refresh_preview
        if mode == 'archive':
            refresh_once(force=False)
            return
        result = refresh_preview()
        if not result.get('success'):
            err = result.get('error', '')
            if '仅启用增量' in err or '无待预览' in err:
                refresh_once(force=False)
    except Exception as err:
        from hourly_refresh import write_status
        write_status(False, str(err), {'running': False})
        print(f'❌ 刷新异常: {err}')
    finally:
        with _refresh_lock:
            _refresh_thread = None


def start_refresh_async(*, mode='preview'):
    """后台刷新，避免 HTTP 请求长时间阻塞导致前端无响应。"""
    global _refresh_thread
    with _refresh_lock:
        if _refresh_thread and _refresh_thread.is_alive():
            return {'success': True, 'running': True, 'message': '刷新进行中，请稍候…'}
        _refresh_thread = threading.Thread(
            target=_run_refresh_job, kwargs={'mode': mode}, daemon=True
        )
        _refresh_thread.start()
    if mode == 'archive':
        msg = '归档刷新已开始，请稍候…'
    else:
        msg = '增量预览刷新已开始，请稍候…'
    return {'success': True, 'started': True, 'running': True, 'message': msg, 'mode': mode}


def next_archive_target(now=None):
    """下次每日归档时刻（固定 23:59:59）。"""
    now = now or datetime.now()
    target = archive_deadline_today(now)
    if now >= target:
        target = target + timedelta(days=1)
    return target


def archive_worker():
    """每天 23:59:59 触发正式归档。"""
    time.sleep(5)
    last_announced = None
    while True:
        try:
            while True:
                now = datetime.now()
                target = next_archive_target(now)
                if last_announced != target:
                    print(f'⏱ 下次归档：{target:%Y-%m-%d %H:%M:%S}')
                    last_announced = target
                sleep_sec = (target - now).total_seconds()
                if sleep_sec <= 0:
                    break
                time.sleep(min(sleep_sec, 30))

            with _refresh_lock:
                busy = _refresh_thread and _refresh_thread.is_alive()
            if busy:
                print('⏭ 归档推迟：刷新任务进行中')
                time.sleep(30)
                continue

            from hourly_refresh import refresh_once
            refresh_once(force=False)
            last_announced = None
        except Exception as err:
            print(f'❌ 归档失败: {err}')


def interval_refresh_worker():
    """按配置间隔触发增量预览刷新（不归档）。"""
    time.sleep(15)
    last_announced = None
    while True:
        try:
            interval_sec = get_refresh_interval_sec()
            minutes = interval_sec // 60
            if last_announced != minutes:
                print(f'🔁 定时预览刷新：每 {minutes} 分钟')
                last_announced = minutes
            slept = 0
            while slept < interval_sec:
                chunk = min(30, interval_sec - slept)
                time.sleep(chunk)
                slept += chunk
                interval_sec = get_refresh_interval_sec()

            start_refresh_async(mode='preview')
        except Exception as err:
            print(f'❌ 定时预览刷新失败: {err}')


def main():
    os.chdir(EQT_DIR)
    threading.Thread(target=archive_worker, daemon=True).start()
    threading.Thread(target=interval_refresh_worker, daemon=True).start()

    cfg = load_config()
    minutes = cfg.get('refresh', {}).get('intervalMinutes', 60)
    try:
        server = ThreadingHTTPServer(('0.0.0.0', PORT), DashboardHandler)
    except OSError as err:
        if getattr(err, 'errno', None) == 48:
            print(f'⚠ 端口 {PORT} 已被占用，看板服务可能已在运行。')
            print(f'  直接打开：http://localhost:{PORT}')
            print(f'  若要重启：lsof -ti :{PORT} | xargs kill')
            return
        raise
    url = f'http://localhost:{PORT}'
    print(f'✓ 看板服务 {url}')
    print(f'  归档：每天 {format_archive_time()} 自动归档')
    print(f'  定时刷新：每 {minutes} 分钟增量预览（不归档）')
    print('  设置保存后会同步到 dashboard_config.json')
    if getattr(sys, 'frozen', False):
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\n已停止')
        server.shutdown()


if __name__ == '__main__':
    main()
