#!/usr/bin/env python3
"""将 Excel 分析结果写入单页 index.html（可双击直接打开）。"""

import json
import os
import re
from datetime import datetime

from station_registry import (
    STATION_FILES,
    STATION_REGISTRY,
    STATION_MODES,
    CHECKIN_FILE,
    DEFAULT_VARIANT_TARGETS,
    PHASE_TYPES,
    DEFAULT_PHASE,
)
from dashboard_config import fetch_date_range
from build_report_data import (
    VARIANTS,
    TARGETS_FILE,
    in_date_range,
    load_dashboard_config,
    collect_checkin_rel_dates,
    count_rel_active_days,
    analyze_checkin_rel_daily,
    checkin_rel_cumulative,
    classify_work_order_phase,
    main as build_report,
)
from app_paths import EQT_DIR
from data_archive import archive_summary, station_records
INDEX_PATH = os.path.join(EQT_DIR, 'index.html')
EMBED_MARKER = '/*__EMBED_JSON__*/'
EMBED_SCRIPT_ID = 'raw-data-package'


def collect_embed_payload():
    with open(TARGETS_FILE, encoding='utf-8') as f:
        config = json.load(f)

    dash = load_dashboard_config()
    if dash:
        rel_start, rel_end = fetch_date_range(dash)
    else:
        rel_start = config['dateRange']['start']
        rel_end = config['dateRange']['end']
    preview_end = os.environ.get('EQT_PREVIEW_END')
    display_end = rel_end
    if preview_end and preview_end > rel_end:
        display_end = preview_end
    other_start, other_end = rel_start, display_end
    other_targets = dash['other']['targets'] if dash else DEFAULT_VARIANT_TARGETS
    phase_only_cfg = (dash or {}).get('phaseOnly', {})
    rel_only_cfg = (dash or {}).get('relOnly', {})

    def empty_buckets():
        return {v: {'pass': 0, 'fail': 0} for v in VARIANTS}

    by_id = {}
    for display_name, station_id, filename in STATION_FILES:
        mode = STATION_MODES[station_id]
        rel = empty_buckets()
        phases = {p: empty_buckets() for p in PHASE_TYPES}
        for rec in station_records(filename):
            phase = rec.get('phase') or classify_work_order_phase(rec.get('wo', ''))
            if phase == 'REL' or rec['isRel']:
                if mode == 'phase_only':
                    continue
                if not in_date_range(rec['date'], rel_start, display_end):
                    continue
                bucket = rel
            else:
                if mode == 'rel_only':
                    continue
                if phase not in phases:
                    continue
                if not in_date_range(rec['date'], other_start, other_end):
                    continue
                bucket = phases[phase]
            if rec['isPass']:
                bucket[rec['variant']]['pass'] += 1
            elif rec['isFail']:
                bucket[rec['variant']]['fail'] += 1
        by_id[station_id] = {
            'name': display_name,
            'stationId': station_id,
            'mode': mode,
            'rel': rel,
            'phases': phases,
            'nonRel': phases.get(DEFAULT_PHASE, empty_buckets()),
        }

    stations = [by_id[sid] for _d, sid, _f, _m, _g in STATION_REGISTRY if sid in by_id]

    non_rel_targets = {}
    rel_only_targets = {}
    for _d, sid, _f, mode, _g in STATION_REGISTRY:
        if mode == 'both':
            non_rel_targets[sid] = {**other_targets}
        elif mode == 'phase_only':
            non_rel_targets[sid] = {**phase_only_cfg.get(sid, other_targets)}
        elif mode == 'rel_only':
            rel_only_targets[sid] = {**rel_only_cfg.get(sid, other_targets)}

    default_settings = {
        'relDailyTarget': config.get('relDailyTarget', 20),
        'dateStart': rel_start,
        'dateEnd': rel_end,
        'nonRelTargets': non_rel_targets,
        'relOnlyTargets': rel_only_targets,
        'phaseOnlyTargets': {sid: non_rel_targets[sid] for sid in non_rel_targets if STATION_MODES[sid] == 'phase_only'},
    }
    if dash:
        default_settings['dateRange'] = dash.get('dateRange', {'start': rel_start, 'end': rel_end})
        default_settings['rel'] = dash['rel']
        default_settings['other'] = dash['other']
        from dashboard_config import normalize_refresh
        default_settings['refresh'] = normalize_refresh(dash.get('refresh'))
        default_settings['incremental'] = dash.get('incremental', {
            'enabled': False,
            'frozenThrough': None,
            'fetchDays': 7,
        })
        default_settings['selectedPhase'] = dash.get('other', {}).get('selectedPhase', DEFAULT_PHASE)
        default_settings['phaseTargets'] = dash.get('phaseTargets', {})
        default_settings['phaseOnly'] = dash.get('phaseOnly', {})
        default_settings['relOnly'] = dash.get('relOnly', {})
        default_settings['counting'] = dash.get('counting', {'dedupeBySn': True})

    checkin_rel_dates = collect_checkin_rel_dates(CHECKIN_FILE)
    calendar_rel_days = max(1, (
        datetime.strptime(display_end, '%Y-%m-%d') - datetime.strptime(rel_start, '%Y-%m-%d')
    ).days + 1)
    rel_active_days = count_rel_active_days(
        checkin_rel_dates, rel_start, display_end, calendar_rel_days
    )
    checkin_stats = analyze_checkin_rel_daily(
        CHECKIN_FILE, rel_start, display_end, config.get('relDailyTarget', 20)
    )
    checkin_targets = checkin_rel_cumulative(CHECKIN_FILE, rel_start, display_end)

    station_registry = [
        {'id': sid, 'name': d, 'mode': m, 'group': g}
        for d, sid, _f, m, g in STATION_REGISTRY
    ]

    preview_day = preview_end if preview_end and preview_end > rel_end else None
    return {
        'generatedAt': '',
        'previewDay': preview_day,
        'archiveSummary': archive_summary(),
        'phaseTypes': PHASE_TYPES,
        'stations': stations,
        'stationRegistry': station_registry,
        'relActiveDates': sorted(checkin_rel_dates),
        'relActiveDays': rel_active_days,
        'relMTarget': checkin_targets['mTarget'],
        'relETarget': checkin_targets['eTarget'],
        'relVariantTargets': checkin_targets['variantTargets'],
        'checkinRelDaily': checkin_stats['daily'],
        'defaultSettings': default_settings,
    }


def patch_index(embed):
    with open(INDEX_PATH, encoding='utf-8') as f:
        html = f.read()

    payload = json.dumps(embed, ensure_ascii=False)

    if EMBED_MARKER in html:
        html = html.replace(EMBED_MARKER, payload)
    else:
        html = re.sub(
            rf'(<script type="application/json" id="{EMBED_SCRIPT_ID}">)(.*?)(</script>)',
            lambda m: m.group(1) + payload + m.group(3),
            html,
            count=1,
            flags=re.DOTALL,
        )

    with open(INDEX_PATH, 'w', encoding='utf-8') as f:
        f.write(html)

    if not embed.get('stations'):
        print('⚠️ 未找到 exports/*.xlsx，网页将显示“无数据”提示')
    print(f'✓ 已写入 {len(embed.get("stations", []))} 个工站 → {INDEX_PATH}')


def run(only_patch=False):
    if not only_patch:
        build_report()
    with open(os.path.join(EQT_DIR, 'report_data.json'), encoding='utf-8') as f:
        report = json.load(f)
    embed = collect_embed_payload()
    embed['generatedAt'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    patch_index(embed)


if __name__ == '__main__':
    import sys
    run(only_patch='--only-patch' in sys.argv)
