#!/usr/bin/env python3
"""看板配置读写，并同步 station_targets.json。"""

import json
import os
from copy import deepcopy
from datetime import date, timedelta

from app_paths import EQT_DIR
from station_registry import (
    STATION_FILES,
    STATION_MODES,
    DEFAULT_VARIANT_TARGETS,
    STATIONS_PHASE_ONLY,
    STATIONS_REL_ONLY,
)

CONFIG_PATH = os.path.join(EQT_DIR, 'dashboard_config.json')
TARGETS_FILE = os.path.join(EQT_DIR, 'station_targets.json')

def _today():
    return date.today().isoformat()

def _yesterday():
    return (date.today() - timedelta(days=1)).isoformat()


DEFAULT_CONFIG = {
    'dateRange': {'start': _today(), 'end': _today()},
    'rel': {
        'dailyTarget': 20,
        'dateStart': _today(),
        'dateEnd': _today(),
    },
    'other': {
        'label': 'PRB',
        'selectedPhase': 'PRB',
        'dateStart': _today(),
        'dateEnd': _today(),
        'targets': {'M': 400, 'E': 400},
    },
    'phaseTargets': {},
    'refresh': {
        'intervalMinutes': 60,
        'slideDwellSeconds': 30,
    },
    'counting': {
        'dedupeBySn': True,
    },
    'incremental': {
        'enabled': False,
        'frozenThrough': None,
        'fetchDays': 7,
    },
    'phaseOnly': {sid: dict(DEFAULT_VARIANT_TARGETS) for sid in STATIONS_PHASE_ONLY},
    'relOnly': {
        sid: {'M': 10, 'E': 10, 'enabled': False, 'weekly': True}
        for sid in STATIONS_REL_ONLY
    },
}


def normalize_rel_only_entry(targets, *, default_enabled=False):
    side = normalize_side_targets(targets)
    if not targets:
        return {'M': 10, 'E': 10, 'enabled': default_enabled, 'weekly': True, 'enabledSince': None}
    enabled = bool(targets.get('enabled', default_enabled))
    enabled_since = targets.get('enabledSince') if enabled else None
    if enabled_since is not None and not isinstance(enabled_since, str):
        enabled_since = None
    return {
        'M': side['M'] if side['M'] else 10,
        'E': side['E'] if side['E'] else 10,
        'enabled': enabled,
        'weekly': targets.get('weekly', True),
        'enabledSince': enabled_since,
    }


ARCHIVE_HOUR = 23
ARCHIVE_MINUTE = 59
ARCHIVE_SECOND = 59
ARCHIVE_TIME_LABEL = '23:59:59'


def normalize_refresh(refresh=None):
    """定时预览刷新间隔与轮播停留时间（归档时刻固定 23:59:59）。"""
    r = dict(refresh or {})
    try:
        dwell = int(r.get('slideDwellSeconds', 30))
    except (TypeError, ValueError):
        dwell = 30
    try:
        interval = int(r.get('intervalMinutes', 60))
    except (TypeError, ValueError):
        interval = 60
    return {
        'intervalMinutes': max(1, interval),
        'slideDwellSeconds': max(5, dwell),
    }


def archive_deadline_today(now=None):
    """当天归档截止时刻（固定 23:59:59）。"""
    from datetime import datetime as dt
    now = now or dt.now()
    return now.replace(
        hour=ARCHIVE_HOUR,
        minute=ARCHIVE_MINUTE,
        second=ARCHIVE_SECOND,
        microsecond=0,
    )


def is_before_archive_deadline(now=None):
    from datetime import datetime as dt
    now = now or dt.now()
    return now < archive_deadline_today(now)


def format_archive_time():
    return ARCHIVE_TIME_LABEL


def normalize_side_targets(targets):
    """M/E 合计目标；兼容旧版 BM/BL/BP/BN。"""
    if not targets:
        return {'M': 0, 'E': 0}
    if 'M' in targets or 'E' in targets:
        return {'M': int(targets.get('M') or 0), 'E': int(targets.get('E') or 0)}
    return {
        'M': int(targets.get('BM') or 0) + int(targets.get('BL') or 0),
        'E': int(targets.get('BP') or 0) + int(targets.get('BN') or 0),
    }


def side_targets_to_variants(side):
    """写入 station_targets.json 时拆成四型号（合计不变）。"""
    m = int(side.get('M') or 0)
    e = int(side.get('E') or 0)
    if 'BM' in side or 'BL' in side:
        return {v: int(side.get(v) or 0) for v in ('BM', 'BL', 'BP', 'BN')}
    return {
        'BM': m // 2,
        'BL': m - m // 2,
        'BP': e // 2,
        'BN': e - e // 2,
    }


def resolve_date_range(cfg):
    """统一数据日期；兼容旧版 rel/other 分设日期。"""
    dr = cfg.get('dateRange') or {}
    start = dr.get('start') or cfg.get('rel', {}).get('dateStart') or _today()
    end = dr.get('end') or cfg.get('rel', {}).get('dateEnd') or _today()
    if not dr.get('start') and cfg.get('other', {}).get('dateStart'):
        start = min(start, cfg['other']['dateStart'])
    if not dr.get('end') and cfg.get('other', {}).get('dateEnd'):
        end = max(end, cfg['other']['dateEnd'])
    return start, end


def advance_end_to_yesterday(cfg):
    """自动将结束日期推进到昨天（只前进不后退），用于每天归档到前一天。"""
    start, end = resolve_date_range(cfg)
    desired_end = _yesterday()
    if end >= desired_end:
        return cfg, False
    cfg = deepcopy(cfg)
    cfg['dateRange'] = {'start': start, 'end': desired_end}
    cfg.setdefault('rel', {})['dateEnd'] = desired_end
    cfg.setdefault('other', {})['dateEnd'] = desired_end
    return cfg, True


def sync_dates_to_sections(cfg):
    start, end = resolve_date_range(cfg)
    cfg['dateRange'] = {'start': start, 'end': end}
    cfg['rel']['dateStart'] = start
    cfg['rel']['dateEnd'] = end
    cfg['other']['dateStart'] = start
    cfg['other']['dateEnd'] = end
    return cfg


def merge_config(raw):
    cfg = deepcopy(DEFAULT_CONFIG)
    if not raw:
        return sync_dates_to_sections(cfg)
    if raw.get('dateRange'):
        cfg['dateRange'].update(raw['dateRange'])
    if raw.get('rel'):
        cfg['rel'].update(raw['rel'])
    if raw.get('other'):
        cfg['other'].update(raw['other'])
        if raw['other'].get('targets'):
            cfg['other']['targets'] = normalize_side_targets({
                **DEFAULT_CONFIG['other']['targets'],
                **raw['other']['targets'],
            })
    if raw.get('refresh'):
        cfg['refresh'].update(raw['refresh'])
    cfg['refresh'] = normalize_refresh(cfg.get('refresh'))
    if raw.get('counting'):
        cfg['counting'].update(raw['counting'])
    if raw.get('incremental'):
        cfg['incremental'].update(raw['incremental'])
    if raw.get('selectedPhase'):
        cfg['other']['selectedPhase'] = raw['selectedPhase']
    if raw.get('phaseTargets'):
        cfg['phaseTargets'].update(raw['phaseTargets'])
    if raw.get('phaseOnly'):
        for sid, targets in raw['phaseOnly'].items():
            cfg['phaseOnly'].setdefault(sid, normalize_side_targets(DEFAULT_VARIANT_TARGETS))
            cfg['phaseOnly'][sid] = normalize_side_targets({**cfg['phaseOnly'][sid], **targets})
    if raw.get('relOnly'):
        for sid, targets in raw['relOnly'].items():
            cfg['relOnly'].setdefault(
                sid,
                normalize_rel_only_entry({}, default_enabled=False),
            )
            cfg['relOnly'][sid] = normalize_rel_only_entry(
                {**cfg['relOnly'][sid], **targets},
                default_enabled=cfg['relOnly'][sid].get('enabled', False),
            )
    return sync_dates_to_sections(cfg)


def load_config():
    if not os.path.isfile(CONFIG_PATH):
        return deepcopy(DEFAULT_CONFIG)
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return merge_config(json.load(f))


def save_config(config):
    cfg = merge_config(config)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    sync_station_targets(cfg)
    return cfg


def get_refresh_interval_sec(config=None):
    cfg = config or load_config()
    return normalize_refresh(cfg.get('refresh'))['intervalMinutes'] * 60


def fetch_date_range(config=None):
    """报表展示的完整日期范围。"""
    cfg = config or load_config()
    return resolve_date_range(cfg)


def export_fetch_range(config=None):
    """实际拉取 Excel 的日期范围（增量模式下可能短于展示范围）。"""
    from data_archive import resolve_fetch_range

    cfg = config or load_config()
    return resolve_fetch_range(cfg)


def sync_station_targets(config=None):
    """将看板配置写入 station_targets.json（供 build_report_data 使用）。"""
    cfg = config or load_config()
    targets = {'BM': 200, 'BL': 200, 'BP': 200, 'BN': 200}
    if os.path.isfile(TARGETS_FILE):
        with open(TARGETS_FILE, encoding='utf-8') as f:
            existing = json.load(f)
    else:
        existing = {'stations': {}}

    other_side = normalize_side_targets(cfg['other']['targets'])
    other_targets = side_targets_to_variants(other_side)
    stations = existing.setdefault('stations', {})

    for _display, station_id, _filename in STATION_FILES:
        entry = stations.setdefault(station_id, {})
        mode = STATION_MODES[station_id]
        if mode == 'both':
            entry['nonRel'] = dict(other_targets)
        elif mode == 'phase_only':
            po = side_targets_to_variants(
                normalize_side_targets(cfg['phaseOnly'].get(station_id, other_side))
            )
            entry['nonRel'] = po
        elif mode == 'rel_only':
            ro = side_targets_to_variants(
                normalize_side_targets(cfg['relOnly'].get(station_id, other_side))
            )
            entry['rel'] = ro

    existing['relDailyTarget'] = cfg['rel']['dailyTarget']
    start, end = resolve_date_range(cfg)
    existing['dateRange'] = {'start': start, 'end': end}
    existing['_dashboardOther'] = {
        'label': cfg['other']['label'],
        'dateStart': start,
        'dateEnd': end,
    }

    with open(TARGETS_FILE, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    return existing
