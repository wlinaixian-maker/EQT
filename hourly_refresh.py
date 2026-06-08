#!/usr/bin/env python3
"""按 dashboard_config.json 拉取工站 Excel、更新看板、删除已处理的 xlsx。"""

import glob
import os
import sys
from datetime import datetime

from dashboard_config import (
    advance_end_to_yesterday,
    export_fetch_range,
    fetch_date_range,
    format_archive_time,
    is_before_archive_deadline,
    load_config,
    save_config,
    sync_station_targets,
)
from app_paths import EQT_DIR
from data_archive import freeze_from_exports, is_incremental_fetch, merge_incremental_exports
EXPORT_DIR = os.path.join(EQT_DIR, 'exports')
STATUS_FILE = os.path.join(EQT_DIR, 'refresh_status.json')


def write_status(ok, message='', extra=None):
    payload = {
        'ok': ok,
        'running': False,
        'message': message,
        'lastRun': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if extra:
        payload.update(extra)
    with open(STATUS_FILE, 'w', encoding='utf-8') as f:
        import json
        json.dump(payload, f, ensure_ascii=False, indent=2)


def delete_processed_exports():
    removed = []
    for path in glob.glob(os.path.join(EXPORT_DIR, '*.xlsx')):
        try:
            os.remove(path)
            removed.append(os.path.basename(path))
        except OSError as err:
            print(f'⚠️ 无法删除 {path}: {err}')
    return removed


def refresh_once(*, freeze=False, force=False):
    config = load_config()
    inc = config.get('incremental') or {}
    inc_enabled = bool(inc.get('enabled'))

    # 仅在未启用“增量日更链路”时，才自动把结束日期推进到昨天。
    # 启用后，结束日期应严格跟随“归档最后一天”，由 23:59 日更任务推进。
    if not (inc.get('enabled') and inc.get('frozenThrough')):
        config, changed = advance_end_to_yesterday(config)
        if changed:
            save_config(config)

    sync_station_targets(config)
    report_start, report_end = fetch_date_range(config)
    fetch_start, fetch_end = export_fetch_range(config)
    incremental = is_incremental_fetch(config, fetch_start, fetch_end)

    from fetch_exports_from_har import fetch_all_exports

    print(f'\n🔄 数据刷新 {datetime.now():%Y-%m-%d %H:%M:%S}')
    print(f'   看板日期范围: {report_start} ~ {report_end}')
    if incremental:
        print(f'   本次拉取范围: {fetch_start} ~ {fetch_end}（增量，历史已归档）')
    else:
        print(f'   本次拉取范围: {fetch_start} ~ {fetch_end}')

    # “满一天”要求：当增量要归档“今天”的那一天时，仅在 23:59:59 之后才执行。
    if (not force) and incremental and fetch_start == fetch_end:
        next_day = datetime.strptime(fetch_start, '%Y-%m-%d')
        now = datetime.now()
        archive_time = format_archive_time()
        if now.date() == next_day.date():
            if is_before_archive_deadline(now):
                msg = f'增量日更：{fetch_start} 需满一天，{archive_time} 后才会拉取并归档'
                write_status(False, f'转入增量预览 {fetch_start}…', {
                    'running': True,
                    'incremental': True,
                    'skipped': True,
                    'nextFetch': fetch_start,
                })
                return {'success': True, 'skipped': True, 'message': msg, 'nextFetch': fetch_start}

    write_status(False, f'正在拉取 Excel（{fetch_start} ~ {fetch_end}）…', {
        'running': True,
        'dateStart': fetch_start,
        'dateEnd': fetch_end,
        'reportStart': report_start,
        'reportEnd': report_end,
        'incremental': incremental,
    })

    fetch_result = fetch_all_exports(fetch_start, fetch_end)
    if not fetch_result.get('success'):
        write_status(False, fetch_result.get('error', '导出失败'), {'running': False})
        return fetch_result

    # 先归档/合并，再生成看板（确保 index.html 内置数据包含刚归档的那天）。
    write_status(False, '正在归档/合并…', {'running': True})

    if freeze or not inc_enabled:
        archive_info = freeze_from_exports(
            frozen_through=report_end,
            incremental_enabled=inc_enabled,
        )
        print(f'📦 已全量归档，冻结至 {archive_info["frozenThrough"]}')
        archive_msg = f'全量归档 {sum(archive_info["stations"].values()):,} 条至 {archive_info["frozenThrough"]}'
    elif incremental:
        merge_incremental_exports(frozen_through=fetch_end)
        print(f'📦 已合并增量数据，更新冻结至 {fetch_end}')
        archive_msg = '增量已合并'

        # 结束日期也跟随归档最后一天推进
        cfg2 = load_config()
        cfg2.setdefault('dateRange', {})['end'] = fetch_end
        cfg2.setdefault('rel', {})['dateEnd'] = fetch_end
        cfg2.setdefault('other', {})['dateEnd'] = fetch_end
        save_config(cfg2)
        sync_station_targets(cfg2)
        report_end = fetch_end
    else:
        archive_msg = '未变更归档'

    removed = delete_processed_exports()

    write_status(False, '正在更新看板…', {'running': True})
    try:
        from generate_index import run as run_generate_index
        run_generate_index(only_patch=True)
    except Exception as err:
        msg = str(err) or 'generate_index 失败'
        print(msg)
        write_status(False, msg, {'running': False})
        return {'success': False, 'error': msg}

    msg = f'已更新看板（{archive_msg}），删除 {len(removed)} 个临时 Excel'
    print(f'✓ {msg}')
    write_status(True, msg, {
        'running': False,
        'dateStart': fetch_start,
        'dateEnd': fetch_end,
        'reportStart': report_start,
        'reportEnd': report_end,
        'incremental': incremental,
        'filesRemoved': removed,
        'stationsFetched': fetch_result.get('count', 0),
    })
    return {'success': True, 'message': msg, 'removed': removed}


def refresh_preview():
    """增量预览：拉取 frozenThrough+1 当天数据更新看板，不归档、不推进结束日期。"""
    config = load_config()
    inc = config.get('incremental') or {}
    if not (inc.get('enabled') and inc.get('frozenThrough')):
        msg = '仅启用增量归档后可预览下一天数据'
        write_status(False, msg, {'running': False})
        return {'success': False, 'error': msg}

    sync_station_targets(config)
    report_start, report_end = fetch_date_range(config)
    fetch_start, fetch_end = export_fetch_range(config)
    incremental = is_incremental_fetch(config, fetch_start, fetch_end)
    if not incremental:
        msg = '当前无待预览的增量日期'
        write_status(False, msg, {'running': False})
        return {'success': False, 'error': msg}

    from fetch_exports_from_har import fetch_all_exports

    print(f'\n👁 增量预览 {datetime.now():%Y-%m-%d %H:%M:%S}')
    print(f'   正式截止: {report_end} · 预览拉取: {fetch_start} ~ {fetch_end}（不归档）')

    write_status(False, f'预览拉取 Excel（{fetch_start} ~ {fetch_end}）…', {
        'running': True,
        'preview': True,
        'dateStart': fetch_start,
        'dateEnd': fetch_end,
        'reportStart': report_start,
        'reportEnd': report_end,
        'incremental': True,
    })

    fetch_result = fetch_all_exports(fetch_start, fetch_end)
    if not fetch_result.get('success'):
        write_status(False, fetch_result.get('error', '导出失败'), {'running': False})
        return fetch_result

    write_status(False, '正在更新预览看板…', {'running': True, 'preview': True})
    os.environ['EQT_PREVIEW'] = '1'
    os.environ['EQT_PREVIEW_END'] = fetch_end
    try:
        from generate_index import run as run_generate_index
        run_generate_index(only_patch=True)
    except Exception as err:
        msg = str(err) or 'generate_index 失败'
        print(msg)
        write_status(False, msg, {'running': False})
        return {'success': False, 'error': msg}
    finally:
        os.environ.pop('EQT_PREVIEW', None)
        os.environ.pop('EQT_PREVIEW_END', None)

    removed = delete_processed_exports()
    frozen = inc.get('frozenThrough')
    msg = f'增量预览 {fetch_end} 已更新（未归档，正式截止仍为 {report_end}）'
    print(f'✓ {msg}')
    write_status(True, msg, {
        'running': False,
        'preview': True,
        'previewDay': fetch_end,
        'frozenThrough': frozen,
        'reportEnd': report_end,
        'dateStart': fetch_start,
        'dateEnd': fetch_end,
        'incremental': True,
        'filesRemoved': removed,
        'stationsFetched': fetch_result.get('count', 0),
    })
    return {'success': True, 'preview': True, 'previewDay': fetch_end, 'message': msg, 'removed': removed}


def run_daemon(interval_sec=3600):
    import time

    print(f'⏱ 每小时自动刷新（间隔 {interval_sec}s），Ctrl+C 停止')
    while True:
        try:
            refresh_once()
        except Exception as err:
            print(f'❌ 刷新异常: {err}')
            write_status(False, str(err))
        time.sleep(interval_sec)


def main():
    freeze = '--freeze' in sys.argv
    if '--daemon' in sys.argv:
        run_daemon()
    elif '--preview' in sys.argv:
        result = refresh_preview()
        sys.exit(0 if result.get('success') else 1)
    else:
        result = refresh_once(freeze=freeze)
        sys.exit(0 if result.get('success') else 1)


if __name__ == '__main__':
    main()
