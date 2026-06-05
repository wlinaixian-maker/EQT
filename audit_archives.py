#!/usr/bin/env python3
"""对比各工站归档与服务器全量拉取，可选自动补拉。"""

import argparse
import glob
import os
import sys

from app_paths import EQT_DIR
from build_report_data import dedupe_records_by_sn, parse_station_records
from dashboard_config import fetch_date_range, load_config
from data_archive import (
    _read_json_records,
    load_state,
    merge_exports_for_stations,
    save_state,
)
from fetch_exports_from_har import EXPORT_DIR, fetch_all_exports
from station_registry import STATION_FILES


def resolve_audit_end(config):
    start, end = fetch_date_range(config)
    inc = config.get('incremental') or {}
    frozen = inc.get('frozenThrough')
    if frozen:
        from datetime import datetime, timedelta
        preview_end = (
            datetime.strptime(frozen, '%Y-%m-%d') + timedelta(days=1)
        ).strftime('%Y-%m-%d')
        if preview_end > end:
            end = preview_end
    return start, end


def audit_station(sid, filename, start, end):
    archive = _read_json_records(sid)
    archive = dedupe_records_by_sn(archive, per_phase=True)
    path = os.path.join(EXPORT_DIR, filename)
    if os.path.isfile(path):
        os.remove(path)
    result = fetch_all_exports(start, end, station_ids={sid})
    if not result.get('success'):
        return {
            'stationId': sid,
            'ok': False,
            'error': result.get('error', '拉取失败'),
        }
    fetched = dedupe_records_by_sn(parse_station_records(path, start, end), per_phase=True)
    if os.path.isfile(path):
        os.remove(path)
    return {
        'stationId': sid,
        'ok': True,
        'archive': len(archive),
        'fetched': len(fetched),
        'diff': len(archive) - len(fetched),
    }


def delete_exports():
    removed = []
    for path in glob.glob(os.path.join(EXPORT_DIR, '*.xlsx')):
        os.remove(path)
        removed.append(os.path.basename(path))
    return removed


def fix_stations(station_ids, start, end):
    targets = set(station_ids)
    print(f'\n🔧 补拉 {len(targets)} 个工站 ({start} ~ {end})')
    result = fetch_all_exports(start, end, station_ids=targets)
    if not result.get('success'):
        return result

    counts = merge_exports_for_stations(targets)
    state = load_state()
    stations = dict(state.get('stations') or {})
    stations.update(counts)
    state['stations'] = stations
    state['lastAuditFixAt'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    state['lastAuditFixCounts'] = counts
    save_state(state)

    try:
        from generate_index import run as run_generate_index
        run_generate_index(only_patch=True)
    except Exception as err:
        return {'success': False, 'error': str(err) or 'generate_index 失败'}

    removed = delete_exports()
    total = sum(counts.values())
    print(f'✓ 已修复 {len(counts)} 个工站，共 {total:,} 条（SN 去重后）')
    if removed:
        print(f'✓ 已删除 {len(removed)} 个临时 Excel')
    return {'success': True, 'counts': counts, 'removed': removed}


def main():
    os.chdir(EQT_DIR)
    parser = argparse.ArgumentParser(description='审计归档完整性')
    parser.add_argument('--fix', action='store_true', help='自动补拉归档偏少的工站')
    parser.add_argument('--threshold', type=int, default=5, help='差异阈值（默认 5）')
    parser.add_argument('stations', nargs='*', help='仅审计指定工站 ID')
    args = parser.parse_args()

    config = load_config()
    start, end = resolve_audit_end(config)
    print(f'审计范围: {start} ~ {end}\n')
    print(f'{"Station":<28} {"archive":>8} {"server":>8} {"diff":>8}')
    print('-' * 56)

    to_fix = []
    for display, sid, filename in STATION_FILES:
        if args.stations and sid not in args.stations:
            continue
        row = audit_station(sid, filename, start, end)
        if not row.get('ok'):
            print(f'{display[:27]:<28} ERROR {row.get("error", "")[:24]}')
            continue
        diff = row['diff']
        flag = ' ←' if abs(diff) > args.threshold else ''
        print(f'{display[:27]:<28} {row["archive"]:>8} {row["fetched"]:>8} {diff:>+8}{flag}')
        if diff < -args.threshold:
            to_fix.append(sid)

    print(f'\n归档偏少（需补拉）: {len(to_fix)} 个')
    if not to_fix:
        return 0

    if not args.fix:
        print('运行 python3 audit_archives.py --fix 可自动补拉')
        return 0

    result = fix_stations(to_fix, start, end)
    if not result.get('success'):
        print(f'❌ {result.get("error", "补拉失败")}')
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
