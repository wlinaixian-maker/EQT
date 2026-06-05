import zipfile
import xml.etree.ElementTree as ET
import os
import json

def extract_single_excel(file_path):
    """从单个Excel文件中提取工站数据"""
    all_data = {}
    
    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            # 共享字符串
            shared_strings = []
            if 'xl/sharedStrings.xml' in zf.namelist():
                ss_xml = zf.read('xl/sharedStrings.xml')
                ss_root = ET.fromstring(ss_xml)
                for si in ss_root.iter():
                    if 'si' in si.tag:
                        text = ''
                        for t in si.iter():
                            if 't' in t.tag and t.text:
                                text += t.text
                        shared_strings.append(text)
            
            # 读取第一个sheet
            sheet_file = 'xl/worksheets/sheet1.xml'
            if sheet_file in zf.namelist():
                ws_xml = zf.read(sheet_file)
                ws_root = ET.fromstring(ws_xml)
                
                rows_data = []
                for row in ws_root.iter():
                    if 'row' in row.tag:
                        row_cells = []
                        for c in row.iter():
                            if 'c' in c.tag:
                                cell_value = ''
                                t = c.attrib.get('t', '')
                                for v in c.iter():
                                    if 'v' in v.tag and v.text:
                                        if t == 's':
                                            try:
                                                idx = int(v.text)
                                                if idx < len(shared_strings):
                                                    cell_value = shared_strings[idx]
                                            except:
                                                cell_value = v.text
                                        else:
                                            cell_value = v.text
                                row_cells.append(cell_value)
                        if row_cells:
                            rows_data.append(row_cells)
                
                # 找列索引
                headers = rows_data[1] if len(rows_data) > 1 else []
                station_col_idx = None
                result_col_idx = None
                
                for col_idx, cell in enumerate(headers):
                    if '工站' in str(cell):
                        station_col_idx = col_idx
                    if '测试结果' in str(cell) or 'Result' in str(cell):
                        result_col_idx = col_idx
                
                # 统计
                station_stats = {}
                for row in rows_data[2:]:
                    if station_col_idx is not None and result_col_idx is not None:
                        station_name = str(row[station_col_idx]).strip() if station_col_idx < len(row) else ''
                        result = str(row[result_col_idx]).strip().upper() if result_col_idx < len(row) else ''
                        
                        if station_name and 'M03-' in station_name:
                            if station_name not in station_stats:
                                station_stats[station_name] = {'total': 0, 'pass': 0, 'fail': 0}
                            station_stats[station_name]['total'] += 1
                            
                            if 'PASS' in result:
                                station_stats[station_name]['pass'] += 1
                            elif 'FAIL' in result:
                                station_stats[station_name]['fail'] += 1
                
                all_data = station_stats
                
    except Exception as e:
        print(f"   ❌ 读取失败: {e}")
    
    return all_data

def batch_extract_all():
    """批量提取目录中所有Excel文件"""
    print(f"\n{'='*80}")
    print(f"📊 批量提取Excel数据")
    print('='*80)
    
    excel_dir = '/Users/forest.wangl/Desktop/EQT'
    all_station_data = {}
    
    # 读取所有Excel文件
    for filename in os.listdir(excel_dir):
        if filename.endswith('.xlsx') and not filename.startswith('.~'):
            print(f"\n📄 处理: {filename}")
            file_path = os.path.join(excel_dir, filename)
            
            station_data = extract_single_excel(file_path)
            
            if station_data:
                for station, stats in station_data.items():
                    if station not in all_station_data:
                        all_station_data[station] = stats
                        pass_rate = round(stats['pass'] / stats['total'] * 100, 2)
                        print(f"   ✅ {station}: 总数={stats['total']}, PASS={stats['pass']}, FAIL={stats['fail']}, 通过率={pass_rate}%")
    
    print(f"\n{'='*80}")
    print(f"📋 汇总结果:")
    for station, stats in all_station_data.items():
        pass_rate = round(stats['pass'] / stats['total'] * 100, 2)
        print(f"   - {station}: 总数={stats['total']}, PASS={stats['pass']}, FAIL={stats['fail']}, 通过率={pass_rate}%")
    
    # 保存结果
    output_file = '/Users/forest.wangl/Desktop/EQT/all_stations_excel_data.json'
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_station_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 已保存到 {output_file}")
    print(f"   共 {len(all_station_data)} 个工站的数据")

if __name__ == '__main__':
    batch_extract_all()
