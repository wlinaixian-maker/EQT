#!/usr/bin/env python3
"""从各工站 HAR 文件提取真实查询数据（lblInfo 总记录数 + 表格明细）。"""

import json
import os
import re
import base64
from urllib.parse import unquote_plus

from app_paths import EQT_DIR

HAR_DIR = os.path.join(EQT_DIR, 'har')

# (har 文件名, 显示名, stationId, 报表接口 s= 参数)
HAR_STATIONS = [
    ('M03-EQT-CHECK-IN.har', 'CHECK-IN', 'M03-EQT-CHECK-IN', 'M03-EQT-CHECK-IN'),
    ('M03-EQT-Charge-Discharge.har', 'Charge-Discharge', 'M03-EQT-Charge-Discharge', 'M03-EQT-BATTERY'),
    ('M03-EQT-Basketball-Football.har', 'Basketball-Football', 'M03-EQT-Basketball-Football', 'M03-EQT-BALL'),
    ('M03-EQT-Coffee-Convenience Store.har', 'Coffee-Store', 'M03-EQT-Coffee-Convenience Store', 'M03-EQT-COFFEE'),
    ('M03-EQT-Commute.har', 'Commute', 'M03-EQT-Commute', 'M03-EQT-COMMUTE'),
    ('M03-EQT-Gym.har', 'Gym', 'M03-EQT-Gym', 'M03-EQT-GYM'),
    ('M03-EQT-Home.har', 'Home', 'M03-EQT-Home', 'M03-EQT-HOME'),
    ('M03-EQT-Office.har', 'Office', 'M03-EQT-Office', 'M03-EQT-OFFICE'),
    ('M03-EQT-Quiet Room.har', 'Quiet Room', 'M03-EQT-Quiet Room', 'M03-EQT-QUIET'),
    ('M03-EQT-Running Track.har', 'Running Track', 'M03-EQT-Running Track', 'M03-EQT-RUNNING'),
    ('M03-EQT-Stairs.har', 'Stairs', 'M03-EQT-Stairs', 'M03-EQT-STAIRS'),
    ('M03-EQT-Noise Room.har', 'Noise Room', 'M03-EQT-Noise Room', 'M03-EQT-NOISE'),
    ('M03-EQT-Test.har', 'Test', 'M03-EQT-Test', 'M03-STATION229'),
    ('M03-EQT-CHECK-OUT.har', 'CHECK-OUT', 'M03-EQT-CHECK-OUT', 'M03-EQT-CHECK-OUT'),
    ('M03-CQA-Humdity test.har', 'Humdity Test', 'M03-CQA-Humdity test', 'M03-STATION18'),
    ('M03-EQT-Constant Temp Room.har', 'Constant Temp Room', 'M03-EQT-Constant Temp Room', 'M03-EQT-TEMP'),
    ('M03-EQT-Beach.har', 'Beach', 'M03-EQT-Beach', 'M03-EQT-BEACH'),
    ('M03-EQT-Other.har', 'Other', 'M03-EQT-Other', 'M03-EQT-OTHER'),
]


def resolve_har_path(har_file):
    """返回 har/ 目录下的 HAR 路径。"""
    return os.path.join(HAR_DIR, har_file)

RESULT_COL = '测试结果'


def get_prd_details_html(har_path):
    with open(har_path, encoding='utf-8') as f:
        data = json.load(f)
    for entry in data['log']['entries']:
        url = entry.get('request', {}).get('url', '')
        mime = entry.get('response', {}).get('content', {}).get('mimeType', '')
        if mime != 'text/html' or 'PrdDetails' not in url:
            continue
        content = entry['response']['content']
        text = content.get('text', '') or ''
        if content.get('encoding') == 'base64' and text:
            return base64.b64decode(text).decode('utf-8', 'replace'), url
        return text, url
    return None, None


def parse_query_range(html):
    start = re.search(r'id="txtDayStart"[^>]*value="([^"]+)"', html)
    end = re.search(r'id="txtDayEnd"[^>]*value="([^"]+)"', html)
    return (
        start.group(1) if start else '',
        end.group(1) if end else '',
    )


def parse_grid(html):
    match = re.search(r'id="GridView1"([\s\S]*?)</table>', html)
    if not match:
        return [], []

    grid = match.group(1)
    rows_html = re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', grid, re.I)
    if not rows_html:
        return [], []

    headers = [
        re.sub(r'<[^>]+>', '', h).strip()
        for h in re.findall(r'<th[^>]*>([\s\S]*?)</th>', rows_html[0], re.I)
    ]

    result_idx = headers.index(RESULT_COL) if RESULT_COL in headers else None
    records = []

    for row_html in rows_html[1:]:
        cells = [
            re.sub(r'<[^>]+>', '', c).strip().replace('&nbsp;', '')
            for c in re.findall(r'<td[^>]*>([\s\S]*?)</td>', row_html, re.I)
        ]
        if not cells:
            continue
        row = {headers[i]: cells[i] for i in range(min(len(headers), len(cells)))}
        records.append(row)

    return headers, records


def count_results(records):
    pass_count = fail_count = other = 0
    for row in records:
        result = row.get(RESULT_COL, '').upper()
        if result == 'PASS':
            pass_count += 1
        elif result == 'FAIL':
            fail_count += 1
        elif result:
            other += 1
    return pass_count, fail_count, other


def extract_station(har_file, display_name, station_id, api_param):
    path = resolve_har_path(har_file)
    if not os.path.isfile(path):
        return None

    html, url = get_prd_details_html(path)
    if not html:
        return None

    total_match = re.search(r'id="lblInfo"[^>]*>(\d+)笔记录', html)
    total = int(total_match.group(1)) if total_match else 0
    date_start, date_end = parse_query_range(html)
    headers, records = parse_grid(html)
    page_pass, page_fail, page_other = count_results(records)
    page_rows = len(records)
    complete = total <= 50 and page_rows >= total

    if complete:
        pass_count, fail_count = page_pass, page_fail
        data_source = 'har_page_full'
    else:
        pass_count, fail_count = page_pass, page_fail
        data_source = 'har_page_partial'

    fail_count = fail_count
    pass_rate = round(pass_count / total * 100, 2) if total and complete else (
        round(pass_count / page_rows * 100, 2) if page_rows and not complete else 0
    )

    return {
        'name': display_name,
        'stationId': station_id,
        'apiParam': api_param,
        'harFile': har_file,
        'queryUrl': url,
        'dateStart': date_start,
        'dateEnd': date_end,
        'total': total,
        'pass': pass_count if complete else None,
        'fail': fail_count if complete else None,
        'passRate': pass_rate if complete else None,
        'pagePass': page_pass,
        'pageFail': page_fail,
        'pageOther': page_other,
        'pageRows': page_rows,
        'dataComplete': complete,
        'dataSource': data_source,
        'note': '完整PASS/FAIL（页面含全部记录）' if complete else (
            f'网页仅显示前{page_rows}条；总{total}条需导出Excel才有完整PASS/FAIL'
        ),
        'records': records if complete else records[:5],
    }


def extract_all():
    results = []
    for har_file, display, station_id, api_param in HAR_STATIONS:
        row = extract_station(har_file, display, station_id, api_param)
        if row:
            results.append(row)
    return results


def dashboard_payload(stations):
    """看板用的汇总结构。"""
    payload = []
    for s in stations:
        total = s['total']
        if s['dataComplete']:
            pass_n = s['pass']
            fail_n = s['fail']
            pass_rate = s['passRate']
        else:
            pass_n = s['pagePass']
            fail_n = s['pageFail']
            pass_rate = round(pass_n / total * 100, 2) if total else 0

        payload.append({
            'name': s['name'],
            'stationId': s['stationId'],
            'total': total,
            'pass': pass_n,
            'fail': fail_n,
            'passRate': pass_rate,
            'dataComplete': s['dataComplete'],
            'note': s['note'],
        })
    return payload


def main():
    stations = extract_all()
    out_full = os.path.join(EQT_DIR, 'station_data_from_har.json')
    out_dash = os.path.join(EQT_DIR, 'station_dashboard_data.json')

    with open(out_full, 'w', encoding='utf-8') as f:
        json.dump(stations, f, ensure_ascii=False, indent=2)

    dash = dashboard_payload(stations)
    with open(out_dash, 'w', encoding='utf-8') as f:
        json.dump(dash, f, ensure_ascii=False, indent=2)

    print(f'已提取 {len(stations)} 个工站')
    print(f'完整数据: {sum(1 for s in stations if s["dataComplete"])} 个')
    print(f'仅总数完整: {sum(1 for s in stations if not s["dataComplete"])} 个')
    print()
    for s in dash:
        flag = '✓' if s['dataComplete'] else '△'
        print(f'{flag} {s["name"]:22} 总={s["total"]:4}  PASS={s["pass"]} FAIL={s["fail"]}  {s["note"][:40]}...')
    print(f'\n→ {out_full}')
    print(f'→ {out_dash}')


if __name__ == '__main__':
    main()
