#!/usr/bin/env python3
"""根据内嵌的 HAR 导出请求，从报表服务器拉取各工站 Excel。"""

import os
import urllib.error
import urllib.parse
import urllib.request

from app_paths import EQT_DIR
from batch_extract_excel import extract_single_excel
from build_report_data import STATION_FILES
from har_export_requests import EXPORT_REQUESTS

EXPORT_DIR = os.path.join(EQT_DIR, 'exports')


def patch_export_dates(post_text, date_start, date_end):
    pairs = urllib.parse.parse_qsl(post_text, keep_blank_values=True)
    patched = []
    for key, value in pairs:
        if key == 'txtDayStart':
            value = date_start
        elif key == 'txtDayEnd':
            value = date_end
        patched.append((key, value))
    return urllib.parse.urlencode(patched)


def fetch_excel_from_request(req, out_path, date_start, date_end):
    post_data = patch_export_dates(req['postData'], date_start, date_end).encode('utf-8')
    http_req = urllib.request.Request(
        req['url'], data=post_data, headers=req['headers'], method='POST'
    )
    with urllib.request.urlopen(http_req, timeout=60) as resp:
        body = resp.read()
        if len(body) < 500:
            raise RuntimeError(f'导出文件过小 ({len(body)} bytes)')
        with open(out_path, 'wb') as out:
            out.write(body)
        return len(body)


def fetch_all_exports(date_start, date_end, *, station_ids=None):
    os.makedirs(EXPORT_DIR, exist_ok=True)
    ok_count = 0
    errors = []

    for display_name, station_id, filename in STATION_FILES:
        if station_ids is not None and station_id not in station_ids:
            continue
        req = EXPORT_REQUESTS.get(station_id)
        out_path = os.path.join(EXPORT_DIR, filename)

        print(f'\n📥 {display_name} ({station_id})')
        if not req:
            errors.append(f'{station_id}: 无内嵌导出请求')
            print('   ❌ 无内嵌导出请求，请运行 python3 embed_har_exports.py')
            continue

        try:
            size = fetch_excel_from_request(req, out_path, date_start, date_end)
            stats = extract_single_excel(out_path)
            if stats:
                for sid, s in stats.items():
                    print(
                        f"   ✅ {size:,} bytes → 总={s['total']} "
                        f"PASS={s['pass']} FAIL={s['fail']}"
                    )
            else:
                print(f'   ✅ {size:,} bytes')
            ok_count += 1
        except (urllib.error.URLError, RuntimeError, OSError) as err:
            errors.append(f'{station_id}: {err}')
            print(f'   ❌ {err}')

    if ok_count == 0:
        return {'success': False, 'error': '；'.join(errors) or '未成功导出任何工站', 'count': 0}

    return {'success': True, 'count': ok_count, 'errors': errors}


def main():
    from dashboard_config import fetch_date_range

    date_start, date_end = fetch_date_range()
    print(f'导出日期: {date_start} ~ {date_end}')
    result = fetch_all_exports(date_start, date_end)
    if not result['success']:
        raise SystemExit(result.get('error', '导出失败'))


if __name__ == '__main__':
    main()
