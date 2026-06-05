#!/usr/bin/env python3
"""工站分类与顺序（看板唯一来源）。"""

# mode: both = REL + 阶段 | phase_only = 仅阶段 | rel_only = 仅 REL

STATION_REGISTRY = [
    ('CHECK-IN', 'M03-EQT-CHECK-IN', 'M03-EQT-CHECK-IN.xlsx', 'both', 'main'),
    ('Basketball-Football', 'M03-EQT-Basketball-Football', 'M03-EQT-Basketball-Football.xlsx', 'both', 'main'),
    ('Coffee-Store', 'M03-EQT-Coffee-Convenience Store', 'M03-EQT-Coffee-Convenience_Store.xlsx', 'both', 'main'),
    ('Commute', 'M03-EQT-Commute', 'M03-EQT-Commute.xlsx', 'both', 'main'),
    ('Gym', 'M03-EQT-Gym', 'M03-EQT-Gym.xlsx', 'both', 'main'),
    ('Home', 'M03-EQT-Home', 'M03-EQT-Home.xlsx', 'both', 'main'),
    ('Office', 'M03-EQT-Office', 'M03-EQT-Office.xlsx', 'both', 'main'),
    ('Quiet Room', 'M03-EQT-Quiet Room', 'M03-EQT-Quiet_Room.xlsx', 'both', 'main'),
    ('Running Track', 'M03-EQT-Running Track', 'M03-EQT-Running_Track.xlsx', 'both', 'main'),
    ('Stairs', 'M03-EQT-Stairs', 'M03-EQT-Stairs.xlsx', 'both', 'main'),
    ('Noise Room', 'M03-EQT-Noise Room', 'M03-EQT-Noise_Room.xlsx', 'both', 'main'),
    ('Test', 'M03-EQT-Test', 'M03-EQT-Test.xlsx', 'both', 'main'),
    ('CHECK-OUT', 'M03-EQT-CHECK-OUT', 'M03-EQT-CHECK-OUT.xlsx', 'both', 'main'),
    ('Charge-Discharge', 'M03-EQT-Charge-Discharge', 'M03-EQT-Charge-Discharge.xlsx', 'rel_only', 'main'),
    ('Humdity Test', 'M03-CQA-Humdity test', 'M03-CQA-Humdity_test.xlsx', 'phase_only', 'phase'),
    ('Constant Temp Room', 'M03-EQT-Constant Temp Room', 'M03-EQT-Constant_Temp_Room.xlsx', 'phase_only', 'phase'),
    ('Beach', 'M03-EQT-Beach', 'M03-EQT-Beach.xlsx', 'phase_only', 'phase'),
    ('Other', 'M03-EQT-Other', 'M03-EQT-Other.xlsx', 'phase_only', 'phase'),
]

STATION_FILES = [(d, sid, fn) for d, sid, fn, _m, _g in STATION_REGISTRY]
STATION_ORDER = [sid for _d, sid, _fn, _m, _g in STATION_REGISTRY]
STATION_MODES = {sid: mode for _d, sid, _fn, mode, _g in STATION_REGISTRY}
STATION_GROUPS = {sid: group for _d, sid, _fn, _m, group in STATION_REGISTRY}
STATION_DISPLAY = {sid: d for d, sid, _fn, _m, _g in STATION_REGISTRY}

CHECKIN_STATION_ID = 'M03-EQT-CHECK-IN'
CHECKIN_FILE = 'M03-EQT-CHECK-IN.xlsx'

STATIONS_BOTH = [sid for _d, sid, _fn, m, _g in STATION_REGISTRY if m == 'both']
STATIONS_PHASE_ONLY = [sid for _d, sid, _fn, m, _g in STATION_REGISTRY if m == 'phase_only']
STATIONS_REL_ONLY = [sid for _d, sid, _fn, m, _g in STATION_REGISTRY if m == 'rel_only']

DEFAULT_VARIANT_TARGETS = {'BM': 200, 'BL': 200, 'BP': 200, 'BN': 200}

# 非 REL 工单阶段（看板第二页可切换）
PHASE_TYPES = ['DVT', 'EVT', 'PVT', 'PPVT', 'PRB', 'P1', 'OVB']
DEFAULT_PHASE = 'PRB'
