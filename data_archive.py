#!/usr/bin/env python3
"""历史数据归档：全量拉取后保留，后续仅增量拉取并合并。"""

import json
import os
from datetime import datetime, timedelta

from app_paths import EQT_DIR
from station_registry import STATION_FILES, CHECKIN_STATION_ID, CHECKIN_FILE
EXPORT_DIR = os.path.join(EQT_DIR, 'exports')
ARCHIVE_DIR = os.path.join(EQT_DIR, 'data_archive')
RECORDS_DIR = os.path.join(ARCHIVE_DIR, 'records')
STATE_FILE = os.path.join(ARCHIVE_DIR, 'state.json')

STATION_ID_BY_FILE = {filename: station_id for _d, station_id, filename in STATION_FILES}


def _ensure_dirs():
    os.makedirs(RECORDS_DIR, exist_ok=True)


def load_state():
    if not os.path.isfile(STATE_FILE):
        return {}
    with open(STATE_FILE, encoding='utf-8') as f:
        return json.load(f)


def save_state(state):
    _ensure_dirs()
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _records_path(station_id):
    return os.path.join(RECORDS_DIR, f'{station_id}.json')


def _read_json_records(station_id):
    path = _records_path(station_id)
    if not os.path.isfile(path):
        return []
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def _write_json_records(station_id, records):
    _ensure_dirs()
    with open(_records_path(station_id), 'w', encoding='utf-8') as f:
        json.dump(records, f, ensure_ascii=False)


def _parse_xlsx(filename):
    from build_report_data import parse_station_records

    path = os.path.join(EXPORT_DIR, filename)
    if not os.path.isfile(path):
        return []
    return parse_station_records(path)


def merge_records(existing, incoming, *, replace=False):
    from build_report_data import dedupe_records_by_sn

    base = [] if replace or not existing else existing
    return dedupe_records_by_sn(base + list(incoming), per_phase=True)


def freeze_from_exports(frozen_through=None):
    """将当前 exports/*.xlsx 全量写入归档（首次长区间拉取后执行）。"""
    from dashboard_config import load_config, save_config, resolve_date_range

    _ensure_dirs()
    config = load_config()
    _, full_end = resolve_date_range(config)
    frozen = frozen_through or full_end
    counts = {}

    from build_report_data import dedupe_records_by_sn

    for _display, station_id, filename in STATION_FILES:
        incoming = _parse_xlsx(filename)
        if incoming:
            merged = dedupe_records_by_sn(incoming, per_phase=True)
            _write_json_records(station_id, merged)
            counts[station_id] = len(merged)

    inc = config.setdefault('incremental', {})
    inc['enabled'] = True
    inc['frozenThrough'] = frozen
    inc.setdefault('fetchDays', 7)
    save_config(config)

    save_state({
        'frozenThrough': frozen,
        'archivedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'mode': 'freeze',
        'stations': counts,
    })
    return {'frozenThrough': frozen, 'stations': counts}


def missing_station_ids():
    """归档中尚无记录的工站 ID。"""
    missing = []
    for _display, station_id, _filename in STATION_FILES:
        if not _read_json_records(station_id):
            missing.append(station_id)
    return missing


def merge_exports_for_stations(station_ids):
    """将 exports 中指定工站的 Excel 合并进归档，返回 {station_id: 合并后总条数}。"""
    counts = {}
    wanted = set(station_ids)
    for _display, station_id, filename in STATION_FILES:
        if station_id not in wanted:
            continue
        incoming = _parse_xlsx(filename)
        if not incoming:
            continue
        merged = merge_records(_read_json_records(station_id), incoming)
        _write_json_records(station_id, merged)
        counts[station_id] = len(merged)
    return counts


def merge_incremental_exports(frozen_through=None):
    """将本次增量 exports 合并进归档（按 SN 覆盖更新）。"""
    from dashboard_config import load_config, save_config

    counts = {}
    for _display, station_id, filename in STATION_FILES:
        incoming = _parse_xlsx(filename)
        if not incoming:
            continue
        merged = merge_records(_read_json_records(station_id), incoming)
        _write_json_records(station_id, merged)
        counts[station_id] = len(incoming)

    if frozen_through:
        config = load_config()
        inc = config.setdefault('incremental', {})
        inc['enabled'] = True
        inc['frozenThrough'] = frozen_through
        save_config(config)

    state = load_state()
    state.update({
        'lastMergeAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'lastMergeCounts': counts,
    })
    if frozen_through:
        state['frozenThrough'] = frozen_through
    save_state(state)
    return counts


def resolve_fetch_range(config):
    """返回本次应请求的日期区间；启用增量时仅拉最近窗口。"""
    from dashboard_config import resolve_date_range

    full_start, full_end = resolve_date_range(config)
    inc = config.get('incremental') or {}
    if not inc.get('enabled'):
        return full_start, full_end

    frozen = inc.get('frozenThrough')
    if not frozen:
        return full_start, full_end

    # 每次只拉“归档最后一天的下一天”，由定时任务在 23:59 触发归档。
    next_day = datetime.strptime(frozen, '%Y-%m-%d') + timedelta(days=1)
    next_s = next_day.strftime('%Y-%m-%d')
    return next_s, next_s


def is_incremental_fetch(config, fetch_start, fetch_end):
    from dashboard_config import resolve_date_range

    full_start, full_end = resolve_date_range(config)
    inc = config.get('incremental') or {}
    return bool(inc.get('enabled') and inc.get('frozenThrough') and (fetch_start, fetch_end) != (full_start, full_end))


def load_station_records(station_id, filename, date_start=None, date_end=None):
    """优先读归档 JSON，无归档时回退 exports xlsx。EQT_PREVIEW=1 时合并归档与 exports（仅预览）。"""
    from build_report_data import in_date_range

    records = _read_json_records(station_id)
    if os.environ.get('EQT_PREVIEW') == '1' and filename:
        incoming = _parse_xlsx(filename)
        if incoming:
            records = merge_records(records, incoming) if records else incoming
    elif not records and filename:
        records = _parse_xlsx(filename)

    if date_start and date_end:
        records = [r for r in records if in_date_range(r['date'], date_start, date_end)]

    from build_report_data import dedupe_records_by_sn, should_dedupe_by_sn
    from dashboard_config import load_config

    if should_dedupe_by_sn(load_config()):
        records = dedupe_records_by_sn(records, per_phase=True)
    return records


def station_records(filename, date_start=None, date_end=None):
    station_id = STATION_ID_BY_FILE.get(filename)
    if not station_id:
        return []
    return load_station_records(station_id, filename, date_start, date_end)


def archive_summary():
    state = load_state()
    total = 0
    stations = 0
    for _display, station_id, _filename in STATION_FILES:
        recs = _read_json_records(station_id)
        if recs:
            stations += 1
            total += len(recs)
    return {
        'stations': stations,
        'records': total,
        'frozenThrough': state.get('frozenThrough'),
        'archivedAt': state.get('archivedAt'),
    }
