"""모든 읽기는 작업 사본에 한정. 매크로, 계산, 링크 열기 기능 없음."""
import json
import re
import struct
import zlib
from pathlib import Path
from .numbers import KEY_FIELDS, HEADERS
from .safety import safe_zip, xml, SafeError, MAX_CELLS, MAX_EXPANDED


class EvidenceList(list):
    def __init__(self):
        super().__init__()
        self.characters = 0

    def append(self, item):
        self.characters += len(json.dumps(item, ensure_ascii=False))
        if len(self)>=20000 or self.characters>3000000:
            raise SafeError('추출 결과 20,000개 또는 총 3,000,000자 제한을 넘었습니다.')
        super().append(item)


def local(tag):
    return tag.rsplit('}', 1)[-1]


def observation(raw, unit, key, location, context, flags=None, method='구조 읽기'):
    return dict(raw='' if raw is None else str(raw), unit=str(unit or ''), key=key,
                location=location, context=context, flags=flags or [], method=method)


def read_xlsx(path, rules):
    from openpyxl import load_workbook
    with safe_zip(path) as z:
        # openpyxl 호출 전 모든 XML의 개체·구조·수량을 제한한다.
        roots = {}
        for name in z.namelist():
            if name.endswith(('.xml', '.rels')):
                roots[name] = xml(z.read(name))
        external = any(n.get('TargetMode') == 'External' for r in roots.values() for n in r.iter())
        if any('vbaProject' in n for n in z.namelist()):
            raise SafeError('매크로가 포함된 파일은 지원하지 않습니다.')
        book_root = roots.get('xl/workbook.xml')
        rel_root = roots.get('xl/_rels/workbook.xml.rels')
        if book_root is None or rel_root is None:
            raise SafeError('XLSX 필수 구조가 없습니다.')
        links = {r.get('Id'): r.get('Target') for r in rel_root}
        raw_cells = {}
        for sheet in book_root.iter():
            if local(sheet.tag) != 'sheet':
                continue
            rid = next((v for k, v in sheet.attrib.items() if local(k) == 'id'), '')
            target = links.get(rid, '')
            if '..' in target.split('/'):
                raise SafeError('시트 참조 경로를 지원하지 않습니다.')
            target = target.lstrip('/') if target.startswith('/') else 'xl/' + target
            root = roots.get(target)
            if root is None:
                raise SafeError('시트 XML을 찾을 수 없습니다.')
            cells = {}
            for c in root.iter():
                if local(c.tag) == 'c':
                    values = [v.text or '' for v in c if local(v.tag) == 'v']
                    if c.get('t', 'n') == 'n' and values:
                        cells[c.get('r')] = values[0]
            raw_cells[sheet.get('name')] = cells
    wb = load_workbook(path, read_only=False, data_only=False, keep_links=False)
    rows = EvidenceList()
    supported = False
    try:
        if sum(ws.max_row * ws.max_column for ws in wb) > MAX_CELLS:
            raise SafeError('시트의 셀 범위가 100,000개를 넘습니다.')
        for ws in wb:
            common = []
            if external:
                common.append('외부 링크 포함: 계산·접속하지 않음')
            if ws.sheet_state != 'visible':
                common.append('숨김 시트')
            if ws.auto_filter.ref:
                common.append('필터 설정 있음')
            known = ws['A1'].value == rules['profile']
            header = None
            if known:
                for cells in ws.iter_rows(min_row=2, max_row=min(ws.max_row, 100), max_col=len(HEADERS)):
                    if [c.value for c in cells] == HEADERS:
                        header = cells[0].row
                        supported = True
                        break
            for cell_row in ws.iter_rows(min_row=(header + 1 if header else 1)):
                if all(c.value is None for c in cell_row):
                    continue
                if header:
                    cells = list(cell_row[:len(HEADERS)])
                    key = {k: str(cells[i].value if cells[i].value is not None else '') for i, k in enumerate(KEY_FIELDS)}
                    targets = [(cells[8], cells[9].value, key)]
                    context = ' / '.join(f'{k}={v}' for k, v in key.items())
                    row_flags = common.copy()
                    if any(c.value is not None for c in cell_row[len(HEADERS):]):
                        row_flags.append('정의 밖의 추가 열: 새 양식 확인 필요')
                    if any(c.data_type == 'f' for c in cells):
                        row_flags.append('수식 포함: 저장 결과 최신성 미확인')
                    if any(c.number_format != 'General' and c.data_type == 'n' for c in cells[:8]):
                        row_flags.append('코드 표시형식: 앞자리 0 등 확인 필요')
                    if any(c.coordinate in mr for mr in ws.merged_cells.ranges for c in cells):
                        row_flags.append('병합셀: 표 구조 확인 필요')
                else:
                    targets = [(c, '', {}) for c in cell_row if c.value is not None]
                    context = ' | '.join(str(c.value or '') for c in cell_row)[:2000]
                    row_flags = common + ['새 양식/미지원 양식: 수동 연결 필요']
                for c, unit, key in targets:
                    flags = row_flags.copy()
                    if ws.row_dimensions[c.row].hidden or ws.column_dimensions[c.column_letter].hidden:
                        flags.append('숨김 행/열')
                    if c.data_type == 'f':
                        flags.append('수식: 계산하지 않음')
                    if c.data_type == 'e':
                        flags.append('엑셀 오류 값')
                    if '%' in c.number_format:
                        flags.append('백분율 표시형식: 저장값 의미 수동 확인 필요')
                    raw = raw_cells.get(ws.title, {}).get(c.coordinate, c.value)
                    rows.append(observation(raw, unit, key, f'{ws.title}!{c.coordinate}',
                                context + f' / 표시형식={c.number_format}', flags, 'XLSX XML 저장값'))
    finally:
        wb.close()
    return {'status': '처리 성공' if supported else '미지원', 'reason': '' if supported else '일반 셀 근거만 읽음. 실제 양식 규칙 미검증.', 'observations': rows}


def read_hwpx(path, rules):
    rows = EvidenceList()
    supported = False
    incomplete = False
    with safe_zip(path) as z:
        if 'mimetype' not in z.namelist() or z.read('mimetype').strip() != b'application/hwp+zip':
            raise SafeError('HWPX 형식 표식이 없습니다.')
        sections = sorted(n for n in z.namelist() if re.fullmatch(r'Contents/section\d+\.xml', n))
        if not sections:
            raise SafeError('HWPX 본문이 없습니다. 암호화·배포용 파일은 지원하지 않습니다.')
        roots = {n: xml(z.read(n)) for n in z.namelist() if n.endswith(('.xml', '.hpf', '.rdf'))}
        unsafe = any(local(e.tag).lower() in ('script', 'ole', 'equation') for r in roots.values() for e in r.iter())
        for name in sections:
            root = roots[name]
            all_text = '\n'.join(e.text or '' for e in root.iter() if local(e.tag) == 't')
            known = rules['profile'] in all_text.splitlines()
            tables = [e for e in root.iter() if local(e.tag) == 'tbl']
            recognized = False
            for ti, table in enumerate(tables, 1):
                records = []
                flags = []
                if unsafe:
                    flags.append('내장 객체 포함: 실행하지 않음')
                for e in table.iter():
                    if local(e.tag) == 'cellSpan' and (e.get('rowSpan', '1') != '1' or e.get('colSpan', '1') != '1'):
                        flags.append('병합셀: 구조 수동 확인 필요')
                if sum(local(e.tag) == 'tbl' for e in table.iter()) > 1:
                    flags.append('중첩 표')
                trs = [e for e in table if local(e.tag) == 'tr']
                for tr in trs:
                    records.append([''.join(t.text or '' for t in tc.iter() if local(t.tag) == 't')
                                    for tc in tr if local(tc.tag) == 'tc'])
                if known and records and records[0] == HEADERS:
                    supported = recognized = True
                    for ri, row in enumerate(records[1:], 2):
                        if len(row) != len(HEADERS):
                            raise SafeError('가상 양식의 열 수가 달라 안전하게 중단했습니다.')
                        key = dict(zip(KEY_FIELDS, row[:8]))
                        rows.append(observation(row[8], row[9], key, f'{name} 표{ti} 행{ri} 열9',
                                                ' / '.join(row), flags.copy(), 'HWPX XML 표'))
                else:
                    incomplete = True
                    text = ' | '.join(e.text or '' for e in table.iter() if local(e.tag) == 't')
                    if text.strip():
                        rows.append(observation(text, '', {}, f'{name} 미검증 표{ti}', text,
                                    ['새 양식/미지원 표: 수동 원문 확인 필요'], 'HWPX 미검증 표 문자열'))
            if not recognized:
                incomplete = True
                for pi, p in enumerate((e for e in root.iter() if local(e.tag) == 'p'), 1):
                    text = ''.join(e.text or '' for e in p.iter() if local(e.tag) == 't')
                    if text.strip():
                        rows.append(observation(text, '', {}, f'{name} 문단{pi}', text,
                                    ['새 양식/미지원 양식: 수동 원문 확인 필요'], 'HWPX 문단'))
            if len(rows) > 20000:
                raise SafeError('추출 항목 제한을 넘었습니다.')
    return {'status': '처리 성공' if supported and not incomplete else '미지원', 'reason': '' if supported and not incomplete else '미검증 표·문단 근거 포함. 표 의미와 실제 양식 미검증.', 'observations': rows}


def read_hwp(path, rules):
    import olefile
    rows = EvidenceList()
    if not olefile.isOleFile(path):
        raise SafeError('HWP 5 OLE 구조가 아닙니다. HWP 3/손상 파일은 지원하지 않습니다.')
    with olefile.OleFileIO(path, raise_defects=olefile.DEFECT_INCORRECT) as ole:
        if not ole.exists('FileHeader'):
            raise SafeError('HWP FileHeader가 없습니다.')
        header = ole.openstream('FileHeader').read()
        if len(header) < 40 or not header.startswith(b'HWP Document File'):
            raise SafeError('HWP 5 서명이 올바르지 않습니다.')
        flags = struct.unpack_from('<I', header, 36)[0]
        if flags & 6:
            raise SafeError('암호화 또는 배포용 HWP는 지원하지 않습니다.')
        streams = sorted(p for p in ole.listdir() if len(p) == 2 and p[0] == 'BodyText' and p[1].startswith('Section'))
        total = 0
        for path_parts in streams:
            if ole.get_size(path_parts) > 20 * 1024 * 1024:
                raise SafeError('HWP 스트림 크기 제한을 넘었습니다.')
            data = ole.openstream(path_parts).read()
            if flags & 1:
                decoder = zlib.decompressobj(-15)
                data = decoder.decompress(data, 20 * 1024 * 1024 + 1)
                if len(data) > 20 * 1024 * 1024 or not decoder.eof:
                    raise SafeError('HWP 압축 크기 제한 또는 손상입니다.')
            total += len(data)
            if total > MAX_EXPANDED:
                raise SafeError('HWP 전체 해제 크기 제한을 넘었습니다.')
            offset = para = 0
            while offset < len(data):
                if offset + 4 > len(data):
                    raise SafeError('HWP 레코드가 잘렸습니다.')
                word, = struct.unpack_from('<I', data, offset)
                offset += 4
                tag, size = word & 1023, word >> 20
                if size == 4095:
                    if offset + 4 > len(data):
                        raise SafeError('HWP 레코드 길이가 없습니다.')
                    size, = struct.unpack_from('<I', data, offset)
                    offset += 4
                if offset + size > len(data):
                    raise SafeError('HWP 레코드 길이가 올바르지 않습니다.')
                block = data[offset:offset + size]
                offset += size
                if tag != 67:
                    continue
                para += 1
                # HWP 확장 제어 문자는 8 UTF-16 코드 단위. 내부 바이트를 숫자로 오독하지 않는다.
                chars, pos = [], 0
                extended = {1, 2, 3, 4, 5, 6, 7, 8, 9, 11, 12, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23}
                while pos + 2 <= len(block):
                    c, = struct.unpack_from('<H', block, pos)
                    if c in extended:
                        chars.append(' ')
                        pos += 16
                    else:
                        if c >= 32 or c in (10, 13):
                            chars.append(chr(c))
                        pos += 2
                text = ''.join(chars).encode('utf-16le', 'surrogatepass').decode('utf-16le').strip()
                if text:
                    rows.append(observation(text, '', {}, f'{"/".join(path_parts)} 텍스트레코드{para}', text,
                                ['HWP 표 관계 미검증: 수동 원문 확인 필요'], 'HWP 5 텍스트 레코드'))
                if len(rows) > 20000:
                    raise SafeError('HWP 항목 제한을 넘었습니다.')
    return {'status': '미지원', 'reason': 'HWP 5 텍스트 근거 제한 지원. 자동 표 추출·한컴 호환성 검증 미완료.', 'observations': rows}


def read_file(path, rules):
    suffix = Path(path).suffix.lower()
    reader = {'.xlsx': read_xlsx, '.hwpx': read_hwpx, '.hwp': read_hwp}.get(suffix)
    if reader is None:
        return dict(status='미지원', reason='지원 확장자: HWPX, XLSX. HWP 5는 텍스트 근거만 제한 지원.', observations=[])
    return reader(path, rules)
