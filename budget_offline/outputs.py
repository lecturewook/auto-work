import json
import os
import tempfile
from pathlib import Path
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment
from . import VERSION
from .numbers import KEY_FIELDS
from .project import PASS, now, identifier
from .safety import SafeError, canonical, digest, safe_zip


def append_text(ws, values):
    """모든 숫자를 정확한 십진 문자열로 보존. 수식으로 해석되지 않는 문자열 셀."""
    row = ws.max_row + 1 if ws.max_row > 1 or ws.cell(1, 1).value is not None else 1
    for col, value in enumerate(values, 1):
        cell = ws.cell(row, col)
        cell.value = '' if value is None else str(value)
        cell.data_type = 's'
        cell.number_format = '@'


def wide_rows(items):
    keys = tuple(k for k in KEY_FIELDS if k != '지표코드')
    metrics = sorted({i['key']['지표코드'] for i in items})
    result = {}
    occupied = set()
    for i in items:
        row_key = tuple(i['key'][k] for k in keys)
        metric = i['key']['지표코드']
        if (row_key, metric) in occupied:
            raise SafeError('wide의 같은 위치에 여러 값이 있습니다. 합산하거나 첫 값을 고르지 않습니다.')
        occupied.add((row_key, metric))
        result.setdefault(row_key, {})[metric] = (i['value'], i['unit'], i['id'])
    header = list(keys)
    for metric in metrics:
        header += [metric + ' 값', metric + ' 단위', metric + ' 항목ID']
    rows = []
    for key, values in sorted(result.items()):
        row = list(key)
        for metric in metrics:
            row.extend(values.get(metric, ('','','')))
        rows.append(row)
    return header, rows


def inspect_mapping(template, targets):
    """가상 셀 매핑의 충돌 검사만 제공. 실제 최종 양식 쓰기는 아직 없음."""
    with safe_zip(template):
        pass
    wb = load_workbook(template, data_only=False, keep_links=False)
    seen = set()
    try:
        for t in targets:
            slot = (t['sheet'], t['cell'].upper())
            if slot in seen:
                raise SafeError('출력 대상 셀 중복')
            seen.add(slot)
            if slot[0] not in wb.sheetnames:
                raise SafeError('출력 시트 없음')
            cell = wb[slot[0]][slot[1]]
            if cell.value is not None:
                raise SafeError('출력 대상 기존 값·수식 충돌')
    finally:
        wb.close()


def export_workbook(project, mode='draft', destination=None):
    if mode == 'final':
        raise SafeError('공식 최종본 출력은 잠겨 있습니다. 실제 양식·필수 지표·셀 매핑 검증이 필요합니다.')
    if mode not in ('draft', 'approved'):
        raise SafeError('지원하지 않는 출력 종류입니다.')
    if project.integrity():
        raise SafeError('원본 사본 무결성 확인 실패. 출력을 중단합니다.')
    items = project.comparisons()
    chosen = [i for i in items if i['approval'] == '승인' and i['status'] in PASS] if mode == 'approved' else items
    if mode == 'approved' and not chosen:
        raise SafeError('승인된 항목이 없습니다.')
    expected_ids = {r[0] for r in project.db.execute('SELECT key_id FROM expected')}
    approved_ids = {i['id'] for i in items if i['approval'] == '승인' and i['status'] in PASS}
    missing = expected_ids - approved_ids
    oid = identifier()
    label = '검토용초안' if mode == 'draft' else '시험용승인데이터'
    path = Path(destination) if destination else project.root / 'exports' / f'{label}_{oid[:8]}.xlsx'
    if path.parent.resolve() != (project.root / 'exports').resolve() or path.suffix.lower() != '.xlsx':
        raise SafeError('결과는 프로젝트 exports 폴더의 새 XLSX 파일로 저장하세요.')
    if path.exists():
        raise SafeError('같은 이름의 결과가 있습니다. 새 이름을 사용하세요.')
    snapshot = {'app': VERSION, 'rules': project.rules, 'time': now(), 'mode': mode,
                'expected': sorted(expected_ids), 'missing': sorted(missing),
                'items': [{k:v for k,v in i.items() if k != 'observations'} for i in chosen],
                'files': [{k:f[k] for k in ('id','hash','name','extractor','excluded')} for f in project.files()]}
    with project.db:
        project.db.execute('INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?)', (oid, now(), mode, str(path.relative_to(project.root)), '', canonical(snapshot), '반영 준비', ''))
    temp = None
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = '읽어주세요'
        for row in [ ['오프라인 예산 대조 시험판', VERSION], ['출력 종류', label],
                     ['주의', '공식 최종본이 아닙니다. 실제 제출 양식 매핑 미검증.'],
                     ['숫자 저장', '정확성을 위해 모든 값은 텍스트 셀입니다. Excel 자동 합계는 제공하지 않습니다.'],
                     ['필수 목록', '등록됨' if expected_ids else '미등록: 완전성 판단 불가'],
                     ['미승인 필수 항목 수', len(missing)], ['원본 무결성', '출력 직전 SHA-256 확인'],
                     ['출력 ID', oid], ['규칙', project.rules['version']], ['시각 UTC', snapshot['time']]]:
            append_text(ws,row)
        long = wb.create_sheet('long')
        append_text(long, list(KEY_FIELDS) + ['표준값','표준단위','비교판정','업무승인','항목ID','근거ID','승인자','승인시각UTC','규칙버전'])
        for i in chosen:
            append_text(long,[i['key'][k] for k in KEY_FIELDS]+[i['value'],i['unit'],i['status'],i['approval'],i['id'],','.join(o['id'] for o in i['observations']),i['reviewer'],i['approved_at'],project.rules['version']])
        wide = wb.create_sheet('wide')
        header, rows = wide_rows([i for i in chosen if i['status'] in PASS])
        append_text(wide,header)
        for row in rows:
            append_text(wide,row)
        evidence = wb.create_sheet('원문근거')
        append_text(evidence,['근거ID','원본파일ID','파일명','SHA256','위치','원문값','단위','표준값','변환과정','맥락','주의','연결확인','채택','추출방법','이전근거ID'])
        for o in project.observations():
            append_text(evidence,[o['id'],o['file_id'],o['name'],o['hash'],o['location'],o['raw'],o['unit'],o['normalized']['value'],canonical(o['normalized']['steps']),o['context'],canonical(o['flags']),o['confirmed'],o['active'],o['method'],o['parent']])
        unresolved = wb.create_sheet('미해결목록')
        append_text(unresolved,['업무키','판정','승인','사유','항목ID'])
        for i in items:
            if i['approval'] != '승인' or i['status'] not in PASS:
                append_text(unresolved,[canonical(i['key']),i['status'],i['approval'],i['reason'],i['id']])
        for o in project.observations():
            if o['active'] and not o['file_excluded'] and not o['confirmed']:
                append_text(unresolved,[canonical(o['key']),'연결 불명','미검토','근거 연결 미확인',o['id']])
        for name, query in [('파일목록','SELECT * FROM files'), ('가져오기이력','SELECT * FROM imports'), ('검토이력','SELECT * FROM history'), ('출력이력','SELECT * FROM outputs')]:
            sheet = wb.create_sheet(name)
            cursor = project.db.execute(query)
            append_text(sheet,[d[0] for d in cursor.description])
            for r in cursor:
                append_text(sheet,list(r))
        progress = wb.create_sheet('부서현황')
        append_text(progress,['부서코드','부서명','연결확인 근거수','필수항목수','승인된 필수항목수','제출상태','검증상태'])
        allobs = project.observations()
        for d in project.db.execute('SELECT * FROM departments ORDER BY code'):
            expected = [i for i in items if i['id'] in expected_ids and i['key']['부서코드']==d['code']]
            received = sum(o['confirmed'] and o['active'] and not o['file_excluded'] and o['key'].get('부서코드')==d['code'] for o in allobs)
            approved = sum(i['id'] in approved_ids for i in expected)
            append_text(progress,[d['code'],d['name'],received,len(expected),approved,'제출 근거 있음' if received else '미제출/연결 미확인','필수 목록 미등록' if not expected else '필수 항목 승인 완료' if approved==len(expected) else '검증 미완료'])
        for sheet in wb:
            sheet.freeze_panes = 'A2'
            sheet.auto_filter.ref = sheet.dimensions
            for cell in sheet[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='24445C')
            for col in sheet.columns:
                sheet.column_dimensions[col[0].column_letter].width = min(55, max(16, max(len(str(c.value or '')) for c in col[:100]) + 2))
        fd, temp = tempfile.mkstemp(suffix='.xlsx', prefix='.pending-', dir=path.parent)
        os.close(fd)
        wb.save(temp)
        wb.close()
        # 쓰기 후 실제 출력의 수식 없음, 행 수, ZIP 구조를 확인한다.
        with safe_zip(temp):
            pass
        check = load_workbook(temp, read_only=True, data_only=False)
        try:
            if check['long'].max_row != len(chosen) + 1 or any(c.data_type == 'f' for s in check for row in s for c in row):
                raise SafeError('출력 재검증 실패')
        finally:
            check.close()
        with open(temp, 'rb') as stream:
            os.fsync(stream.fileno())
        os.replace(temp,path)
        temp = None
        with project.db:
            project.db.execute("UPDATE outputs SET hash=?,state='반영 완료' WHERE id=?", (digest(path),oid))
            project.audit('출력 성공',{'id':oid,'path':str(path.relative_to(project.root)),'rows':len(chosen),'mode':mode})
        return path
    except Exception as e:
        with project.db:
            project.db.execute("UPDATE outputs SET state='반영 실패',reason=? WHERE id=?",(type(e).__name__,oid))
        raise SafeError('엑셀 저장 실패. 남은 공간·폴더 권한·Excel 파일 잠금을 확인하세요. 이전 출력은 보존됩니다.') from e
    finally:
        if temp and os.path.exists(temp):
            os.unlink(temp)
