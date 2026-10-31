import json
import shutil
import zipfile
from decimal import Decimal
from pathlib import Path
import pytest
from openpyxl import load_workbook
from budget_offline.project import Project, PASS
from budget_offline.numbers import normalize, HEADERS
from budget_offline.readers import read_file
from budget_offline.outputs import export_workbook, wide_rows, inspect_mapping
from budget_offline.backup import backup, restore
from budget_offline.safety import SafeError, safe_zip, xml, digest
from tools.make_fixtures import key,row,xlsx,hwpx,generate,hwp_structure_fixture


@pytest.fixture
def p(tmp_path):
    with Project(tmp_path/'project',create=True) as project:
        yield project


def pair(p,tmp_path,hvalue='1000',hunit='천원',xvalue='1000000',xunit='원',hkey=None,xkey=None,tag='a'):
    h=tmp_path/(tag+'.hwpx');x=tmp_path/(tag+'.xlsx')
    hwpx(h,[row(hkey or key(),hvalue,hunit)])
    xlsx(x,[row(xkey or hkey or key(),xvalue,xunit)])
    p.import_file(h);p.import_file(x)
    return h,x


def confirm(p):
    for o in p.observations():
        if o['active'] and o['key']:
            p.confirm_mapping(o['id'],o['key'],o['unit'],'가상자료 시험자','명시한 가상 정답과 확인')


def approve(p):
    for c in p.comparisons():p.review(c['id'],'승인','가상자료 시험자','가상 정답 일치 확인')


def test_end_to_end_provenance_and_restart(p,tmp_path):
    pair(p,tmp_path)
    assert p.comparisons()[0]['status']=='연결 불명'
    with pytest.raises(SafeError):approve(p)
    confirm(p)
    item=p.comparisons()[0]
    assert item['status']=='변환 후 정확 일치'
    assert item['value']=='1000000'
    assert len(item['observations'])==2
    assert all(o['location'] for o in item['observations'])
    approve(p)
    out=export_workbook(p,'approved')
    wb=load_workbook(out,data_only=False)
    assert wb['long'].max_row==2
    assert wb['long']['I2'].value=='1000000'
    assert wb['long']['I2'].data_type=='s'
    assert wb['원문근거'].max_row==3
    wb.close()
    root=p.root;p.close()
    with Project(root) as again:
        assert again.comparisons()[0]['approval']=='승인'
        assert again.integrity()==[]


@pytest.mark.parametrize('changed',[{'사업코드':'OTHER'},{'기간':'2025'},{'지표코드':'OTHER'},{'부서코드':'OTHER'},{'재원':'국비'},{'집계수준':'소계'}])
def test_same_numbers_different_meaning_never_pass(p,tmp_path,changed):
    k=key();k.update(changed)
    pair(p,tmp_path,xkey=k);confirm(p)
    assert len(p.comparisons())==2
    assert all(c['status']=='누락' for c in p.comparisons())
    with pytest.raises(SafeError):approve(p)


@pytest.mark.parametrize('raw,unit,state',[
    ('','원','빈칸'),('0','원','숫자'),('-','원','대시 의미 미확인'),('해당 없음','원','해당 없음'),
    ('약 1.2','억원','표시 정밀도 확인 필요'),('1000','','단위 불명'),('1,00','원','숫자 해석 불가'),
    ('△100','원','감액 표기 확인 필요'),('100원','천원','단위 충돌')])
def test_numeric_states(p,raw,unit,state):
    n=normalize(raw,unit,p.rules)
    assert n['state']==state
    assert n['original']==raw
    if raw=='0':assert n['value']=='0'


def test_decimal_precision_and_percent(p,tmp_path):
    pair(p,tmp_path,'12.5','%','0.125','비율');confirm(p)
    assert p.comparisons()[0]['status']=='변환 후 정확 일치'
    assert normalize('12345678901234567890.123456789','원',p.rules)['value']=='12345678901234567890.123456789'
    assert normalize('0.1','원',p.rules)['value']=='0.1'


def test_missing_unit_and_approximate_hold(p,tmp_path):
    pair(p,tmp_path,'1000','','1000','원');confirm(p)
    assert p.comparisons()[0]['status']=='단위 불명'
    with pytest.raises(SafeError):approve(p)


def test_renamed_identical_dedup(p,tmp_path):
    h,x=pair(p,tmp_path);confirm(p);approve(p)
    copy=tmp_path/'renamed.xlsx';shutil.copyfile(x,copy)
    assert p.import_file(copy)['status']=='재가져오기'
    assert len(p.files())==2 and len(p.observations())==2
    assert p.comparisons()[0]['approval']=='승인'
    assert p.summary()['가져오기 횟수']==3


def test_revision_invalidates_approval_and_preserves_originals(p,tmp_path):
    pair(p,tmp_path);confirm(p);approve(p)
    revised=tmp_path/'revision.xlsx';xlsx(revised,[row(key(),'1000001','원')]);p.import_file(revised)
    assert p.comparisons()[0]['approval']=='재검토 필요'
    confirm(p)
    assert p.comparisons()[0]['status']=='중복·수정본 확인 필요'
    with pytest.raises(SafeError):approve(p)
    new=next(o for o in p.observations() if o['raw']=='1000001')
    p.set_active(new['id'],False,'검토자','수정본 반려: 가상 시험')
    assert p.comparisons()[0]['status'] in PASS
    assert p.comparisons()[0]['approval']=='재검토 필요'
    assert len(p.files())==3


def test_duplicate_repeat_and_level_no_summing(p,tmp_path):
    k=key();h=tmp_path/'repeat.hwpx';x=tmp_path/'a.xlsx'
    hwpx(h,[row(k,'1000','원'),row(k,'1000','원')]);xlsx(x,[row(k,'1000','원')])
    p.import_file(h);p.import_file(x);confirm(p)
    assert p.comparisons()[0]['status']=='중복·수정본 확인 필요'
    obs=[o for o in p.observations() if o['role']=='한글']
    p.set_active(obs[-1]['id'],False,'검토자','본문 반복 인용으로 확인')
    assert p.comparisons()[0]['value']=='1000'


@pytest.mark.parametrize('formula',['=500+500',"='[external.xlsx]Sheet1'!A1",'=1+1'])
def test_formulas_never_accepted_even_manual(p,tmp_path,formula):
    h=tmp_path/'f.hwpx';x=tmp_path/'f.xlsx'
    hwpx(h,[row(key(),'1000','원')]);xlsx(x,[row(key(),'1000','원')],formula=formula)
    p.import_file(h);p.import_file(x);confirm(p)
    assert p.comparisons()[0]['status']=='추출 실패'
    with pytest.raises(SafeError):approve(p)
    obs=next(o for o in p.observations() if o['role']=='엑셀')
    with pytest.raises(SafeError):p.manual_evidence(obs['id'],'500','원',key(),'검토자','우회 시도')


def test_unknown_and_real_binary_hwp_restricted(p,tmp_path):
    h=tmp_path/'unknown.hwpx';hwpx(h,[row(key(),'1000','원')],unknown=True)
    assert p.import_file(h)['status']=='미지원'
    binary=tmp_path/'struct.hwp';hwp_structure_fixture(binary)
    result=p.import_file(binary)
    assert result['status']=='미지원'
    obs=[o for o in p.observations() if o['method']=='HWP 5 텍스트 레코드']
    assert len(obs)==1 and '1,000천원' in obs[0]['raw']
    assert not obs[0]['confirmed']
    p.manual_evidence(obs[0]['id'],'1,000','천원',key(),'검토자','가상 원문 직접 확인')
    assert p.comparisons()[0]['status']=='누락'


def test_layout_change_and_multiple_projects(p,tmp_path):
    rows=[row(key(project='P1'),'1','원'),row(key(project='P2'),'2','원')]
    h=tmp_path/'shift.hwpx';x=tmp_path/'shift.xlsx';hwpx(h,rows,shift=True);xlsx(x,rows,header_row=8)
    p.import_file(h);p.import_file(x);confirm(p)
    assert len(p.comparisons())==2 and all(c['status']=='정확 일치' for c in p.comparisons())


def test_rules_mapping_exclusion_tamper_revoke(p,tmp_path):
    pair(p,tmp_path);confirm(p);approve(p)
    rules=p.rules;rules['version']='가상규칙-2';p.update_rules(rules,'검토자','버전 시험')
    assert p.comparisons()[0]['approval']=='재검토 필요'
    approve(p)
    o=p.observations()[0];p.confirm_mapping(o['id'],key(period='2027'),o['unit'],'검토자','기간 정정')
    assert all(i['approval']!='승인' for i in p.comparisons())
    p.confirm_mapping(o['id'],key(),o['unit'],'검토자','다시 확인');approve(p)
    p.exclude_file(o['file_id'],True,'검토자','파일 제외')
    assert p.comparisons()[0]['approval']=='재검토 필요'
    p.exclude_file(o['file_id'],False,'검토자','복원');approve(p)
    f=p.files()[0];original=p.root/f['original'];original.chmod(0o600);original.write_bytes(b'tampered')
    assert p.comparisons()[0]['approval']=='재검토 필요'
    with pytest.raises(SafeError):export_workbook(p,'approved')


def test_wide_and_mapping_collisions(p,tmp_path):
    pair(p,tmp_path);confirm(p)
    i=p.comparisons()[0]
    with pytest.raises(SafeError):wide_rows([i,i])
    template=tmp_path/'target.xlsx';xlsx(template,[row(key(),'1000','원')])
    with pytest.raises(SafeError):inspect_mapping(template,[{'sheet':'가상제출','cell':'I4'}])
    with pytest.raises(SafeError):inspect_mapping(template,[{'sheet':'가상제출','cell':'L4'},{'sheet':'가상제출','cell':'L4'}])


def test_output_atomic_failure_and_formula_injection(p,tmp_path,monkeypatch):
    k=key(project='=HYPERLINK("https://example.invalid","X")')
    pair(p,tmp_path,hkey=k);confirm(p);approve(p)
    old=export_workbook(p,'approved');oldhash=digest(old)
    wb=load_workbook(old,data_only=False)
    assert wb['long']['B2'].data_type=='s'
    assert wb['long']['B2'].value.startswith('=')
    wb.close()
    import budget_offline.outputs as output
    def fail(*args):raise OSError('disk full/locked')
    monkeypatch.setattr(output.os,'replace',fail)
    with pytest.raises(SafeError):export_workbook(p,'approved')
    assert digest(old)==oldhash
    assert p.db.execute("SELECT COUNT(*) FROM outputs WHERE state='반영 실패'").fetchone()[0]==1


def test_backup_restore_all_links_and_lock(p,tmp_path):
    pair(p,tmp_path);confirm(p);approve(p);export_workbook(p,'approved')
    with pytest.raises(SafeError):Project(p.root)
    archive=backup(p,tmp_path/'copy.zip');restored=restore(archive,tmp_path/'restored')
    with Project(restored) as q:
        assert q.integrity()==[]
        assert q.comparisons()[0]['approval']=='승인'
        assert len(q.observations())==2
        assert q.db.execute("SELECT COUNT(*) FROM outputs WHERE state='반영 완료'").fetchone()[0]==1
        assert q.rules==p.rules


def test_missing_expected_and_final_gate(p,tmp_path):
    pair(p,tmp_path);confirm(p);approve(p)
    p.set_expectations([key(),key(project='MISSING')],[{'code':'D001','name':'가상부서'}],'검토자')
    assert p.summary()['누락']==1
    with pytest.raises(SafeError):export_workbook(p,'final')
    draft=export_workbook(p,'draft')
    wb=load_workbook(draft);assert wb['long'].max_row==3;wb.close()


def test_corruption_path_traversal_bomb_xml_and_continue(p,tmp_path):
    corrupt=tmp_path/'broken.xlsx';corrupt.write_bytes(b'broken')
    assert p.import_file(corrupt)['status']=='처리 실패'
    bad=tmp_path/'bad.hwpx'
    with zipfile.ZipFile(bad,'w') as z:z.writestr('../escape','x')
    assert p.import_file(bad)['status']=='처리 실패'
    bomb=tmp_path/'bomb.hwpx'
    with zipfile.ZipFile(bomb,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('bomb',b'0'*(2*1024*1024))
    with pytest.raises(SafeError):safe_zip(bomb)
    with pytest.raises(SafeError):xml(b'<!DOCTYPE x [<!ENTITY a SYSTEM "file:///etc/passwd">]><x>&a;</x>')
    pair(p,tmp_path);confirm(p)
    assert p.comparisons()[0]['status'] in PASS


def test_hidden_and_merged_block(p,tmp_path):
    h=tmp_path/'a.hwpx';x=tmp_path/'a.xlsx';hwpx(h,[row(key(),'1000','원')]);xlsx(x,[row(key(),'1000','원')],hidden=True)
    p.import_file(h);p.import_file(x);confirm(p)
    assert p.comparisons()[0]['status']=='추출 실패'


def test_synthetic_truth_3_departments(tmp_path):
    data=tmp_path/'data';truth=generate(data,3,False)
    with Project(tmp_path/'project',create=True) as p:
        for path in sorted((data/'정상자료').iterdir()):p.import_file(path)
        assert p.summary()['확정 가능']==0
        confirm(p)
        items=p.comparisons()
        lookup={json.dumps(t['key'],sort_keys=True):t for t in truth}
        assert len(items)==12
        for i in items:
            t=lookup[json.dumps(i['key'],sort_keys=True)]
            assert Decimal(i['value'])==Decimal(t['expected_value'])
            assert i['unit']==t['expected_unit'] and i['status']==t['after_manual_mapping']
            assert i['approval']=='미검토'


def test_failed_original_copy_is_detected(p,tmp_path,monkeypatch):
    path=tmp_path/'source.xlsx';xlsx(path,[row(key(),'1','원')])
    realcopy=shutil.copyfile
    def corruptcopy(src,dst,*a,**kw):
        realcopy(src,dst,*a,**kw)
        Path(dst).write_bytes(b'changed-during-import')
    monkeypatch.setattr(shutil,'copyfile',corruptcopy)
    with pytest.raises(SafeError):p.import_file(path)
    assert p.files()==[]
    assert list((p.root/'originals').iterdir())==[]


def test_python_network_guard():
    import socket
    with pytest.raises(PermissionError,match='OFFLINE_POLICY'):
        socket.socket()


def test_manual_partial_and_approximate_cannot_bypass(p,tmp_path):
    h=tmp_path/'manual.hwp';hwp_structure_fixture(h,'가상부서 약 1,000천원')
    p.import_file(h)
    o=p.observations()[0]
    with pytest.raises(SafeError):p.manual_evidence(o['id'],'1,000','천원',key(),'검토자','근사 제거 시도')
    pair(p,tmp_path)
    o=next(o for o in p.observations() if o['role']=='엑셀')
    with pytest.raises(SafeError):p.manual_evidence(o['id'],'100','원',key(),'검토자','자릿수 잘라내기 시도')


def test_hwp_encryption_and_oversize(p,tmp_path):
    import struct
    h=tmp_path/'encrypted.hwp';hwp_structure_fixture(h)
    data=bytearray(h.read_bytes());struct.pack_into('<I',data,2048+36,3);h.write_bytes(data)
    r=p.import_file(h)
    assert r['status']=='처리 실패' and '암호화' in r['reason']
    large=tmp_path/'large.xlsx'
    with large.open('wb') as f:f.truncate(50*1024*1024+1)
    assert p.import_file(large)['status']=='제외'


def test_backup_tamper_rejected(p,tmp_path):
    pair(p,tmp_path);archive=backup(p,tmp_path/'backup.zip')
    bad=tmp_path/'bad.zip'
    with zipfile.ZipFile(archive) as source,zipfile.ZipFile(bad,'w') as dest:
        for n in source.namelist():dest.writestr(n,b'changed' if n.startswith('originals/') else source.read(n))
    with pytest.raises(SafeError):restore(bad,tmp_path/'restored')
    assert not (tmp_path/'restored').exists()


def test_reprocessing_preserves_history_and_revokes(p,tmp_path):
    pair(p,tmp_path);confirm(p);approve(p)
    fid=p.files()[0]['id'];old_ids={o['id'] for o in p.observations()}
    p.reprocess(fid)
    assert old_ids.issubset({o['id'] for o in p.observations()})
    assert p.comparisons()[0]['approval']=='재검토 필요'


def test_forced_exit_during_output_preserves_previous(tmp_path):
    import subprocess,sys
    root=tmp_path/'project'
    with Project(root,create=True) as p:
        pair(p,tmp_path);confirm(p);approve(p);old=export_workbook(p,'approved');before=digest(old)
    script='''
import os,sys
from budget_offline.project import Project
from budget_offline.outputs import export_workbook
import budget_offline.outputs as m
def terminate(*args): os._exit(23)
with Project(sys.argv[1]) as p:
    m.os.replace=terminate
    export_workbook(p,'approved')
'''
    completed=subprocess.run([sys.executable,'-c',script,str(root)])
    assert completed.returncode==23 and digest(old)==before
    with Project(root) as p:
        assert p.db.execute("SELECT COUNT(*) FROM outputs WHERE state='반영 실패'").fetchone()[0]==1
        assert p.comparisons()[0]['approval']=='승인'


def test_oversized_xml_and_evidence_are_rejected():
    from budget_offline.readers import EvidenceList
    with pytest.raises(SafeError):xml(b'<r>'+b'a'*10001+b'</r>')
    rows=EvidenceList()
    with pytest.raises(SafeError):rows.append({'raw':'x'*3000001})


def test_hwp_non_bmp_text_preserved(p,tmp_path):
    path=tmp_path/'unicode.hwp';hwp_structure_fixture(path,'가상자료 😀 예산 1,000천원')
    result=p.import_file(path)
    assert result['status']=='미지원'
    assert '😀' in p.observations()[0]['raw']
