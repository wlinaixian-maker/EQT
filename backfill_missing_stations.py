#!/usr/bin/env python3
"""拉取并归档尚未有历史数据的工站（使用看板完整日期范围）。"""

import glob
import os
import sys

from app_paths import EQT_DIR
from dashboard_config import fetch_date_range, load_config
from data_archive import load_state, merge_exports_for_stations, missing_station_ids, save_state
from fetch_exports_from_har import EXPORT_DIR, fetch_all_exports
from station_registry import STATION_FILES


def delete_exports_for(station_ids):
    filenames = {fn for _d, sid, fn in STATION_FILES if sid in station_ids}
    removed = []
    for path in glob.glob(os.path.join(EXPORT_DIR, '*.xlsx')):
        if os.path.basename(path) in filenames:
            os.remove(path)
            removed.append(os.path.basename(path))
    return removed


def backfill(*, station_ids=None, force=False, include_preview_day=False):
    if station_ids:
        targets = list(station_ids)
    elif force:
        from station_registry import STATION_FILES
        targets = [sid for _d, sid, _fn in STATION_FILES]
    else:
        targets = missing_station_ids()
    if not targets:
        print('✓ 所有工站均已归档，无需补拉')
        return {'success': True, 'count': 0, 'stations': []}

    config = load_config()
    report_start, report_end = fetch_date_range(config)
    if include_preview_day:
        inc = config.get('incremental') or {}
        frozen = inc.get('frozenThrough')
        if frozen:
            from datetime import datetime, timedelta
            preview_end = (
                datetime.strptime(frozen, '%Y-%m-%d') + timedelta(days=1)
            ).strftime('%Y-%m-%d')
            if preview_end > report_end:
                report_end = preview_end
    print(f'📦 待补拉 {len(targets)} 个工站')
    print(f'   日期范围: {report_start} ~ {report_end}')
    for sid in targets:
        print(f'   · {sid}')

    result = fetch_all_exports(report_start, report_end, station_ids=set(targets))
    if not result.get('success'):
        return result

    counts = merge_exports_for_stations(set(targets))
    if not counts:
        return {
            'success': False,
            'error': '拉取成功但未解析到任何记录，请检查 HAR/会话是否有效',
        }

    state = load_state()
    stations = dict(state.get('stations') or {})
    stations.update(counts)
    state['stations'] = stations
    state['lastBackfillAt'] = __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    state['lastBackfillCounts'] = counts
    save_state(state)

    try:
        from generate_index import run as run_generate_index
        run_generate_index(only_patch=True)
    except Exception as err:
        return {'success': False, 'error': str(err) or 'generate_index 失败'}

    removed = delete_exports_for(set(targets))
    total = sum(counts.values())
    print(f'✓ 已归档 {len(counts)} 个工站、共 {total:,} 条记录')
    if removed:
        print(f'✓ 已删除 {len(removed)} 个临时 Excel')
    return {'success': True, 'counts': counts, 'removed': removed}


def main():
    args = sys.argv[1:]
    force = '--force' in args
    include_preview = '--include-preview-day' in args
    ids = [a for a in args if not a.startswith('-')]
    result = backfill(
        station_ids=ids or None,
        force=force and not ids,
        include_preview_day=include_preview,
    )
    if not result.get('success'):
        print(f'❌ {result.get("error", "补拉失败")}')
        sys.exit(1)


if __name__ == '__main__':
    main()
