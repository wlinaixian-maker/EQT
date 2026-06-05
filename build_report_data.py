#!/usr/bin/env python3
"""从各工站 Excel 导出分析 REL / 非 REL，按型号统计过站完成率。"""

import json
import os
import re
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta

from app_paths import EQT_DIR

EXPORT_DIR = os.path.join(EQT_DIR, 'exports')
TARGETS_FILE = os.path.join(EQT_DIR, 'station_targets.json')
OUTPUT_FILE = os.path.join(EQT_DIR, 'report_data.json')

VARIANTS = ['BM', 'BL', 'BP', 'BN']
REL_M = ['BM', 'BL']
REL_E = ['BP', 'BN']
VARIANT_LABEL = {
    'BM': 'M·BM',
    'BL': 'M·BL',
    'BP': 'E·BP',
    'BN': 'E·BN',
}

from station_registry import (
    STATION_FILES,
    STATION_MODES,
    STATION_ORDER,
    CHECKIN_STATION_ID,
    CHECKIN_FILE,
    STATIONS_PHASE_ONLY,
    STATIONS_REL_ONLY,
    DEFAULT_VARIANT_TARGETS,
    PHASE_TYPES,
)
from data_archive import station_records


def resolve_record_phase(rec):
    """统一解析记录阶段（REL / PRB / …）。"""
    phase = rec.get('phase') or classify_work_order_phase(rec.get('wo', ''))
    if rec.get('isRel') and phase != 'REL':
        return 'REL'
    return phase


def dedupe_records_by_sn(records, *, per_phase=True):
    """按 SN 去重：默认同一阶段内只保留最新测试日期的一条。"""
    kept = {}
    order = []
    for rec in records:
        if not rec.get('sn'):
            continue
        phase = resolve_record_phase(rec)
        key = (phase, rec['sn']) if per_phase else (rec['sn'],)
        prev = kept.get(key)
        if prev is None:
            kept[key] = rec
            order.append(key)
            continue
        if (rec.get('date') or '') >= (prev.get('date') or ''):
            kept[key] = rec
    return [kept[k] for k in order]


def should_dedupe_by_sn(config=None):
    cfg = config or load_dashboard_config() or {}
    counting = cfg.get('counting') or {}
    if 'dedupeBySn' in counting:
        return bool(counting.get('dedupeBySn'))
    return True


def classify_work_order_phase(wo):
    """工单阶段：含 REL 为 REL；否则按 DVT/EVT/PVT/PPVT/PRB/P1/OVB 识别。"""
    wu = (wo or '').upper()
    if 'REL' in wu:
        return 'REL'
    for phase in ('PPVT', 'PVT', 'DVT', 'EVT', 'PRB', 'OVB'):
        if phase in wu:
            return phase
    # P1 / P1B（如 MES-TEST-P1-FATP、-P1-MAIN-、-P1B-LBU-）
    if re.search(r'(?:^|[-_/])P1B?(?:[-_/]|$)', wu):
        return 'P1'
    return None


def variant_from_work_order(wo):
    """从工单 MAIN/MINI-M-E-FATP-L/R 或简化 FATP 段解析型号。"""
    match = re.search(r'(?:MAIN|MINI)-([ME])-FATP-([LR])', wo, re.I)
    if not match:
        match = re.search(r'-([ME])-FATP-([LR])', wo, re.I)
    if match:
        key = match.group(1).upper() + match.group(2).upper()
        return {'ML': 'BM', 'MR': 'BL', 'EL': 'BP', 'ER': 'BN'}.get(key)
    match = re.search(r'FATP-([LR])', wo, re.I)
    if match:
        lr = match.group(1).upper()
        return 'BL' if lr == 'R' else 'BM'
    # 工程测试工单（如 MES-TEST-P1-FATP-20250918）无 L/R，归入 M·BM
    if re.search(r'FATP', wo, re.I):
        return 'BM'
    return None


def excel_date(value):
    if not value:
        return ''
    raw = str(value).strip()
    if ' ' in raw:
        raw = raw.split()[0]
    try:
        num = float(raw.replace(',', ''))
        if num > 40000:
            return (datetime(1899, 12, 30) + timedelta(days=num)).strftime('%Y-%m-%d')
    except ValueError:
        pass
    for fmt in ('%Y-%m-%d', '%Y/%m/%d'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            continue
    return raw


def read_xlsx_rows(path):
    with zipfile.ZipFile(path, 'r') as zf:
        shared_strings = []
        if 'xl/sharedStrings.xml' in zf.namelist():
            root = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in root.iter():
                if 'si' in si.tag:
                    shared_strings.append(
                        ''.join(t.text or '' for t in si.iter() if 't' in t.tag)
                    )

        ws_root = ET.fromstring(zf.read('xl/worksheets/sheet1.xml'))
        rows = []
        for row in ws_root.iter():
            if 'row' not in row.tag:
                continue
            cells = []
            for cell in row.iter():
                if 'c' not in cell.tag:
                    continue
                text = ''
                cell_type = cell.attrib.get('t', '')
                for value_node in cell.iter():
                    if 'v' in value_node.tag and value_node.text:
                        if cell_type == 's':
                            idx = int(value_node.text)
                            text = shared_strings[idx] if idx < len(shared_strings) else value_node.text
                        else:
                            text = value_node.text
                cells.append(text)
            if cells:
                rows.append(cells)
    return rows


def classify_variant(sn, wo):
    suffix = sn[-2:].upper()
    wu = (wo or '').upper()

    if 'REL' in wu:
        if suffix in VARIANTS:
            return suffix, True
        return None

    variant = variant_from_work_order(wo)
    if variant:
        return variant, False

    if suffix in VARIANTS:
        return suffix, False

    return None


def in_date_range(date_str, start, end):
    if not date_str:
        return False
    if not start or not end:
        return True
    return start <= date_str <= end


def load_dashboard_config():
    path = os.path.join(EQT_DIR, 'dashboard_config.json')
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def parse_station_records(path, date_start=None, date_end=None):
    rows = read_xlsx_rows(path)
    header_idx = next((i for i, row in enumerate(rows) if '条码' in row), None)
    if header_idx is None:
        return []

    header = rows[header_idx]
    columns = {name: header.index(name) for name in ['条码', '工单', '测试时间', '测试结果'] if name in header}
    records = []

    for row in rows[header_idx + 1:]:
        if max(columns.values()) >= len(row):
            continue
        sn = row[columns['条码']].strip()
        wo = row[columns['工单']].strip()
        if not re.match(r'J5MH', sn):
            continue

        phase = classify_work_order_phase(wo)
        if not phase:
            continue
        classified = classify_variant(sn, wo)
        if not classified:
            continue
        variant, is_rel = classified
        if is_rel and phase != 'REL':
            phase = 'REL'
        if not is_rel and phase == 'REL':
            continue
        result = row[columns['测试结果']].upper() if '测试结果' in columns else 'PASS'
        is_pass = 'PASS' in result
        is_fail = 'FAIL' in result
        if not is_pass and not is_fail:
            continue

        if date_start and date_end:
            rec_date = excel_date(row[columns['测试时间']])
            if not in_date_range(rec_date, date_start, date_end):
                continue

        records.append({
            'sn': sn,
            'wo': wo,
            'date': excel_date(row[columns['测试时间']]),
            'variant': variant,
            'phase': phase,
            'isRel': is_rel,
            'isPass': is_pass,
            'isFail': is_fail,
        })
    return dedupe_records_by_sn(records, per_phase=True)


def yield_pct(pass_count, fail_count):
    total = pass_count + fail_count
    if total <= 0:
        return 100.0
    return round(pass_count / total * 100, 2)


def pct(actual, target):
    if target <= 0:
        return 100.0 if actual <= 0 else 100.0
    return round(min(100.0, actual / target * 100), 2)


def build_variant_block(pass_counts, targets, fail_counts=None):
    fail_counts = fail_counts or {}
    block = {}
    total_pass = total_fail = 0
    for variant in VARIANTS:
        actual = pass_counts.get(variant, 0)
        fail = fail_counts.get(variant, 0)
        target = targets.get(variant, 0)
        total_pass += actual
        total_fail += fail
        block[variant] = {
            'label': VARIANT_LABEL[variant],
            'actual': actual,
            'fail': fail,
            'target': target,
            'completionPct': pct(actual, target),
        }
    total_target = sum(targets.get(v, 0) for v in VARIANTS)
    block['_summary'] = {
        'actual': total_pass,
        'fail': total_fail,
        'target': total_target,
        'completionPct': pct(total_pass, total_target),
        'yieldPct': yield_pct(total_pass, total_fail),
    }
    return block


def build_rel_block(pass_counts, fail_counts, variant_targets, *, m_target=None, e_target=None):
    """REL 目标来自 CHECK-IN；进度条按 M(BM+BL) / E(BP+BN) 合计。"""
    fail_counts = fail_counts or {}
    variant_targets = variant_targets or {}
    if m_target is None:
        m_target = sum(variant_targets.get(v, 0) for v in REL_M)
    if e_target is None:
        e_target = sum(variant_targets.get(v, 0) for v in REL_E)
    m_pass = sum(pass_counts.get(v, 0) for v in REL_M)
    m_fail = sum(fail_counts.get(v, 0) for v in REL_M)
    e_pass = sum(pass_counts.get(v, 0) for v in REL_E)
    e_fail = sum(fail_counts.get(v, 0) for v in REL_E)
    m_pct = pct(m_pass, m_target)
    e_pct = pct(e_pass, e_target)

    block = {}
    for v in REL_M:
        vt = variant_targets.get(v, 0)
        block[v] = {
            'label': VARIANT_LABEL[v],
            'actual': pass_counts.get(v, 0),
            'fail': fail_counts.get(v, 0),
            'target': vt,
            'side': 'M',
            'sideActual': m_pass,
            'sideTarget': m_target,
            'completionPct': pct(pass_counts.get(v, 0), vt) if vt > 0 else (100.0 if pass_counts.get(v, 0) <= 0 else 100.0),
            'sideCompletionPct': m_pct,
        }
    for v in REL_E:
        vt = variant_targets.get(v, 0)
        block[v] = {
            'label': VARIANT_LABEL[v],
            'actual': pass_counts.get(v, 0),
            'fail': fail_counts.get(v, 0),
            'target': vt,
            'side': 'E',
            'sideActual': e_pass,
            'sideTarget': e_target,
            'completionPct': pct(pass_counts.get(v, 0), vt) if vt > 0 else (100.0 if pass_counts.get(v, 0) <= 0 else 100.0),
            'sideCompletionPct': e_pct,
        }
    total_pass = m_pass + e_pass
    total_fail = m_fail + e_fail
    total_target = m_target + e_target
    block['_summary'] = {
        'actual': total_pass,
        'fail': total_fail,
        'target': total_target,
        'mActual': m_pass,
        'mTarget': m_target,
        'eActual': e_pass,
        'eTarget': e_target,
        'completionPct': pct(total_pass, total_target),
        'yieldPct': yield_pct(total_pass, total_fail),
    }
    return block


def collect_checkin_rel_dates(filename=CHECKIN_FILE):
    """CHECK-IN 工站所有有 REL 记录的自然日（不限筛选范围）。"""
    dates = set()
    for rec in station_records(filename):
        if rec['isRel'] and rec['date']:
            dates.add(rec['date'])
    return dates


def analyze_checkin_rel_daily(filename, rel_start, rel_end, daily_target=20):
    """按 CHECK-IN REL 逐日汇总：有数据的天 M/E 各计 daily_target。"""
    m_by_date = defaultdict(int)
    e_by_date = defaultdict(int)
    variant_by_date = defaultdict(lambda: defaultdict(int))

    for rec in station_records(filename):
        if not rec['isRel']:
            continue
        d = rec['date']
        if not d or not in_date_range(d, rel_start, rel_end):
            continue
        if not (rec['isPass'] or rec['isFail']):
            continue
        variant_by_date[d][rec['variant']] += 1
        if rec['variant'] in REL_M:
            m_by_date[d] += 1
        elif rec['variant'] in REL_E:
            e_by_date[d] += 1

    dates = sorted(set(m_by_date) | set(e_by_date))
    daily = []
    for d in dates:
        m_cnt = m_by_date[d]
        e_cnt = e_by_date[d]
        daily.append({
            'date': d,
            'm': m_cnt,
            'e': e_cnt,
            'mTarget': daily_target if m_cnt > 0 else 0,
            'eTarget': daily_target if e_cnt > 0 else 0,
            'variants': {v: variant_by_date[d].get(v, 0) for v in VARIANTS},
        })

    m_active = sum(1 for row in daily if row['m'] > 0)
    e_active = sum(1 for row in daily if row['e'] > 0)
    return {
        'daily': daily,
        'relActiveDates': dates,
        'mActiveDays': m_active,
        'eActiveDays': e_active,
        'mTarget': daily_target * m_active,
        'eTarget': daily_target * e_active,
        'periodTotal': daily_target * m_active + daily_target * e_active,
    }


def checkin_rel_cumulative(filename, rel_start, rel_end):
    """CHECK-IN 筛选期内 REL 各型号累计（作为全工站 REL 目标）。"""
    rel_pass = defaultdict(int)
    rel_fail = defaultdict(int)
    for rec in station_records(filename):
        if not rec['isRel']:
            continue
        if not in_date_range(rec['date'], rel_start, rel_end):
            continue
        if rec['isPass']:
            rel_pass[rec['variant']] += 1
        elif rec['isFail']:
            rel_fail[rec['variant']] += 1
    variant_targets = {v: rel_pass[v] for v in VARIANTS}
    return {
        'variantTargets': variant_targets,
        'variantFail': {v: rel_fail[v] for v in VARIANTS},
        'mTarget': sum(variant_targets[v] for v in REL_M),
        'eTarget': sum(variant_targets[v] for v in REL_E),
    }


def count_rel_active_days(active_dates, rel_start, rel_end, calendar_days):
    """筛选范围内 CHECK-IN 有 REL 数据的天数；无数据时回退日历天数。"""
    if not active_dates:
        return max(1, calendar_days)
    filtered = [d for d in active_dates if in_date_range(d, rel_start, rel_end)]
    if filtered:
        return len(filtered)
    return max(1, calendar_days)


def rel_period_total(daily_target, day_count):
    """M+E 合计：各 daily_target/天 × 天数（两侧各计）。"""
    return daily_target * 2 * day_count


def sync_nonrel_targets_from_exports(config):
    """将各工站非 REL 目标同步为当前 Excel 实绩（PRB 计划完成率 100%）。"""
    stations_cfg = config.setdefault('stations', {})
    for _display, station_id, filename in STATION_FILES:
        counts = defaultdict(int)
        for rec in station_records(filename):
            if not rec['isRel'] and rec['isPass']:
                counts[rec['variant']] += 1
        entry = stations_cfg.setdefault(station_id, {})
        entry['nonRel'] = {v: counts[v] for v in VARIANTS}
    return config


def main():
    with open(TARGETS_FILE, encoding='utf-8') as f:
        config = json.load(f)

    if os.environ.get('SYNC_NONREL') == '1':
        config = sync_nonrel_targets_from_exports(config)
        with open(TARGETS_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    rel_daily_target = config.get('relDailyTarget', 20)
    cfg_start = config['dateRange']['start']
    cfg_end = config['dateRange']['end']
    dash = load_dashboard_config()
    if dash:
        from dashboard_config import resolve_date_range
        rel_start, rel_end = resolve_date_range(dash)
    else:
        rel_start, rel_end = cfg_start, cfg_end
    other_start, other_end = rel_start, rel_end
    phase_only_cfg = (dash or {}).get('phaseOnly', {})
    rel_only_cfg = (dash or {}).get('relOnly', {})
    other_targets_default = (dash or {}).get('other', {}).get('targets', DEFAULT_VARIANT_TARGETS)
    cfg_days = (
        datetime.strptime(cfg_end, '%Y-%m-%d') - datetime.strptime(cfg_start, '%Y-%m-%d')
    ).days + 1
    calendar_rel_days = (
        datetime.strptime(rel_end, '%Y-%m-%d') - datetime.strptime(rel_start, '%Y-%m-%d')
    ).days + 1
    if calendar_rel_days <= 0:
        calendar_rel_days = cfg_days if cfg_days > 0 else 1

    checkin_rel_dates = collect_checkin_rel_dates(CHECKIN_FILE)
    checkin_stats = analyze_checkin_rel_daily(
        CHECKIN_FILE, rel_start, rel_end, rel_daily_target
    )
    checkin_targets = checkin_rel_cumulative(CHECKIN_FILE, rel_start, rel_end)
    rel_day_count = count_rel_active_days(
        checkin_rel_dates, rel_start, rel_end, calendar_rel_days
    )

    station_targets = config.get('stations', {})

    stations_out = []
    global_rel = defaultdict(int)
    global_rel_fail = defaultdict(int)
    global_nonrel = defaultdict(int)
    global_nonrel_fail = defaultdict(int)

    for display_name, station_id, filename in STATION_FILES:
        mode = STATION_MODES[station_id]
        records = station_records(filename)
        if not records:
            print(f'跳过缺失: {filename} ({mode})')
            continue
        rel_pass = defaultdict(int)
        rel_fail = defaultdict(int)
        nonrel_pass = defaultdict(int)
        nonrel_fail = defaultdict(int)

        for rec in records:
            phase = rec.get('phase') or classify_work_order_phase(rec.get('wo', ''))
            if phase == 'REL' or rec['isRel']:
                if mode == 'phase_only':
                    continue
                if not in_date_range(rec['date'], rel_start, rel_end):
                    continue
                if rec['isPass']:
                    rel_pass[rec['variant']] += 1
                elif rec['isFail']:
                    rel_fail[rec['variant']] += 1
            elif phase in PHASE_TYPES:
                if mode == 'rel_only':
                    continue
                if not in_date_range(rec['date'], other_start, other_end):
                    continue
                if rec['isPass']:
                    nonrel_pass[rec['variant']] += 1
                elif rec['isFail']:
                    nonrel_fail[rec['variant']] += 1

        st_cfg = station_targets.get(station_id, {})
        if mode == 'both':
            nonrel_targets = {
                v: st_cfg.get('nonRel', {}).get(v, other_targets_default.get(v, 200))
                for v in VARIANTS
            }
            rel_block = build_rel_block(
                rel_pass,
                rel_fail,
                checkin_targets['variantTargets'],
                m_target=checkin_targets['mTarget'],
                e_target=checkin_targets['eTarget'],
            )
        elif mode == 'phase_only':
            po = phase_only_cfg.get(station_id, st_cfg.get('nonRel', other_targets_default))
            nonrel_targets = {v: po.get(v, other_targets_default.get(v, 200)) for v in VARIANTS}
            rel_block = build_variant_block(
                defaultdict(int), {v: 0 for v in VARIANTS}, defaultdict(int)
            )
        else:  # rel_only
            ro = rel_only_cfg.get(station_id, st_cfg.get('rel', other_targets_default))
            rel_targets = {v: ro.get(v, other_targets_default.get(v, 200)) for v in VARIANTS}
            nonrel_targets = {v: 0 for v in VARIANTS}
            rel_block = build_variant_block(rel_pass, rel_targets, rel_fail)

        nonrel_block = build_variant_block(nonrel_pass, nonrel_targets, nonrel_fail)

        total_pass = sum(1 for r in records if r['isPass'])
        total_fail = sum(1 for r in records if r['isFail'])
        total_target = rel_block['_summary']['target'] + nonrel_block['_summary']['target']
        station_completion = pct(total_pass, total_target)

        for v in VARIANTS:
            if mode != 'phase_only':
                global_rel[v] += rel_pass[v]
                global_rel_fail[v] += rel_fail[v]
            if mode != 'rel_only':
                global_nonrel[v] += nonrel_pass[v]
                global_nonrel_fail[v] += nonrel_fail[v]

        stations_out.append({
            'name': display_name,
            'stationId': station_id,
            'mode': mode,
            'file': filename,
            'totalPass': total_pass,
            'totalFail': total_fail,
            'yieldPct': yield_pct(total_pass, total_fail),
            'completionPct': station_completion,
            'dateRange': {'start': cfg_start, 'end': cfg_end, 'days': rel_day_count},
            'rel': {
                'dailyTarget': rel_daily_target,
                'cumulativeDays': rel_day_count,
                'activeDaysSource': 'CHECK-IN',
                'variants': {v: rel_block[v] for v in VARIANTS},
                'summary': rel_block['_summary'],
                'yieldPct': rel_block['_summary']['yieldPct'],
            },
            'nonRel': {
                'variants': {v: nonrel_block[v] for v in VARIANTS},
                'summary': nonrel_block['_summary'],
                'yieldPct': nonrel_block['_summary']['yieldPct'],
            },
        })
        print(f'✓ {display_name}: 过站 {total_pass} 良率 {yield_pct(total_pass, total_fail)}%')

    period_total = checkin_targets['mTarget'] + checkin_targets['eTarget']
    m_target = checkin_targets['mTarget']
    e_target = checkin_targets['eTarget']
    vt = checkin_targets['variantTargets']
    report = {
        'generatedAt': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'variantLabels': VARIANT_LABEL,
        'rules': {
            'rel': '工单含 REL：型号 = SN 末两位 (BM/BL→M，BP/BN→E)',
            'nonRel': '工单不含 REL：按 DVT/EVT/PVT/PPVT/PRB/P1/OVB 分阶段；型号 = MAIN/MINI-(M|E)-FATP-(L|R)',
            'relTarget': (
                f'全工站 REL 目标 = CHECK-IN 累计：'
                f'BM{vt["BM"]} BL{vt["BL"]} BP{vt["BP"]} BN{vt["BN"]}，'
                f'M{m_target}+E{e_target}={period_total}'
            ),
            'nonRelTarget': '各工站一次性固定目标，见 station_targets.json',
        },
        'dateRange': config['dateRange'],
        'relDailyTarget': rel_daily_target,
        'relDailyTargetNote': 'per_side_me',
        'relPeriodTotal': period_total,
        'relActiveDays': rel_day_count,
        'relActiveDates': sorted(checkin_rel_dates),
        'relMActiveDays': checkin_stats['mActiveDays'],
        'relEActiveDays': checkin_stats['eActiveDays'],
        'relMTarget': m_target,
        'relETarget': e_target,
        'checkinRelDaily': checkin_stats['daily'],
        'stations': stations_out,
    }

    # global aggregates
    g_nonrel = defaultdict(int)
    g_nonrel_t = defaultdict(int)
    for st in stations_out:
        for v in VARIANTS:
            g_nonrel[v] += st['nonRel']['variants'][v]['actual']
            g_nonrel_t[v] += st['nonRel']['variants'][v]['target']
    global_rel_block = build_rel_block(
        global_rel,
        global_rel_fail,
        checkin_targets['variantTargets'],
        m_target=m_target,
        e_target=e_target,
    )
    report['global'] = {
        'rel': global_rel_block,
        'nonRel': build_variant_block(g_nonrel, g_nonrel_t, global_nonrel_fail),
        'totalCompletionPct': pct(
            sum(global_rel.values()) + sum(g_nonrel.values()),
            global_rel_block['_summary']['target'] + sum(g_nonrel_t.values()),
        ),
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f'\n→ {OUTPUT_FILE}')


if __name__ == '__main__':
    main()
