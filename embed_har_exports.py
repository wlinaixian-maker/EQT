#!/usr/bin/env python3
"""从 har/*.har 提取 Excel 导出请求，写入 har_export_requests.py。"""

import json
import os
import re
from datetime import datetime

from app_paths import EQT_DIR
from extract_har_data import HAR_DIR, HAR_STATIONS, resolve_har_path

OUTPUT_PATH = os.path.join(EQT_DIR, 'har_export_requests.py')


def extract_export_request(har_path):
    with open(har_path, encoding='utf-8') as f:
        data = json.load(f)
    for entry in reversed(data['log']['entries']):
        mime = entry.get('response', {}).get('content', {}).get('mimeType', '')
        if 'excel' not in mime:
            continue
        req = entry['request']
        post_data = req.get('postData', {}).get('text', '')
        if not post_data:
            continue
        headers = {h['name']: h['value'] for h in req.get('headers', [])}
        return {
            'url': req['url'],
            'postData': post_data,
            'headers': {
                'Content-Type': headers.get('Content-Type', 'application/x-www-form-urlencoded'),
                'User-Agent': headers.get('User-Agent', 'Mozilla/5.0'),
                'Accept': headers.get('Accept', '*/*'),
            },
        }
    return None


def build_requests():
    requests = {}
    errors = []
    for har_file, display, station_id, api_param in HAR_STATIONS:
        har_path = resolve_har_path(har_file)
        if not os.path.isfile(har_path):
            errors.append(f'{station_id}: 缺少 {har_file}')
            continue
        req = extract_export_request(har_path)
        if not req:
            errors.append(f'{station_id}: HAR 中无 Excel 导出请求')
            continue
        requests[station_id] = {
            'display': display,
            'apiParam': api_param,
            'harFile': har_file,
            **req,
        }
    return requests, errors


def write_module(requests):
    payload = json.dumps(requests, ensure_ascii=False, indent=4)
    content = f'''#!/usr/bin/env python3
"""各工站 Excel 导出请求（由 embed_har_exports.py 从 HAR 提取生成）。"""

GENERATED_AT = {json.dumps(datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ensure_ascii=False)}
SOURCE_DIR = {json.dumps("har/", ensure_ascii=False)}
STATION_COUNT = {len(requests)}

# station_id -> 导出请求模板（postData 中 txtDayStart/txtDayEnd 会在拉取时替换）
EXPORT_REQUESTS = {payload}
'''
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        f.write(content)


def main():
    requests, errors = build_requests()
    if not requests:
        raise SystemExit('未提取到任何导出请求')
    write_module(requests)
    total = sum(len(v['postData']) for v in requests.values())
    print(f'✓ 已从 {HAR_DIR} 写入 {len(requests)} 个工站 → {OUTPUT_PATH}')
    print(f'  postData 合计 {total:,} bytes')
    if errors:
        print('⚠ 问题:')
        for err in errors:
            print(f'  - {err}')


if __name__ == '__main__':
    main()
