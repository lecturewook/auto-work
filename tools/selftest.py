"""가상 정답을 읽고 전체 흐름을 검사한다. 업무자료를 읽거나 보내지 않는다."""
import argparse
import json
import platform
import sys
import time
from decimal import Decimal
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from budget_offline.project import Project, PASS, key_id
from budget_offline.outputs import export_workbook
from budget_offline.backup import backup, restore
from budget_offline.safety import SafeError
from tools.make_fixtures import generate, key, row, xlsx


def run(root,departments=3):
    root=Path(root)
    if root.exists():raise SafeError('시험 결과 위치는 존재하지 않는 새 폴더를 지정하세요.')
    root.mkdir(parents=True)
    started=time.perf_counter();data=root/'가상자료';truth=generate(data,departments,False)
    expected={key_id(t['key']):t for t in truth}
    paths=sorted((data/'정상자료').iterdir())
    results=[]
    def check(name,condition,actual):
        results.append({'test':name,'passed':bool(condition),'actual':actual})
        if not condition:raise AssertionError(name)
    with Project(root/'시험프로젝트',create=True) as p:
        requirements=json.loads((data/'필수항목.json').read_text(encoding='utf-8'))
        p.set_expectations(requirements['keys'],requirements['departments'],'가상자료 자동시험')
        import_start=time.perf_counter()
        for f in paths:p.import_file(f)
        import_seconds=time.perf_counter()-import_start
        check('자동 사업 연결 없음',all(c['status']=='연결 불명' for c in p.comparisons()),p.summary())
        for o in p.observations():p.confirm_mapping(o['id'],o['key'],o['unit'],'가상자료 자동시험','기대결과.json의 명시한 업무 키로 확인')
        comparisons=p.comparisons()
        false_pass=sum(i['status'] in PASS and (i['id'] not in expected or Decimal(i['value'])!=Decimal(expected[i['id']]['expected_value']) or i['unit']!=expected[i['id']]['expected_unit']) for i in comparisons)
        passes=sum(i['status'] in PASS for i in comparisons)
        check('가상 정답 일치',false_pass==0 and passes==len(truth),{'exact_or_converted':passes,'expected':len(truth),'false_pass':false_pass})
        try:export_workbook(p,'approved');unauthorized=1
        except SafeError:unauthorized=0
        check('미승인 출력 차단',unauthorized==0,unauthorized)
        for i in comparisons:p.review(i['id'],'승인','가상자료 자동시험','기대결과와 직접 비교한 자동시험')
        export_workbook(p,'approved');export_workbook(p,'draft')
        before=len(p.observations())
        for f in paths:p.import_file(f)
        check('재가져오기 이중 집계 없음',len(p.observations())==before and p.summary()['승인']==len(truth),p.summary())
        archive=backup(p,root/'전체백업.zip')
        restored=restore(archive,root/'복원프로젝트')
        with Project(restored) as q:
            check('백업 복원 근거·승인 유지',q.integrity()==[] and q.summary()['승인']==len(truth),q.summary())
        revised=root/'수정본.xlsx';xlsx(revised,[row(key(),'1000001','원')]);p.import_file(revised)
        affected=next(i for i in p.comparisons() if i['id']==key_id(key()))
        check('추가 자료 즉시 재검토',affected['approval']=='재검토 필요',affected['approval'])
        for o in p.observations():
            if not o['confirmed']:p.confirm_mapping(o['id'],o['key'],o['unit'],'가상자료 자동시험','수정본 확인')
        affected=next(i for i in p.comparisons() if i['id']==key_id(key()))
        check('수정본 자동 채택 금지',affected['status']=='중복·수정본 확인 필요',affected['status'])
        try:export_workbook(p,'final');final=1
        except SafeError:final=0
        check('미검증 공식 최종본 차단',final==0,final)
    with Project(root/'시험프로젝트') as q:
        check('종료·재실행 유지',len(q.files())==len(paths)+1 and q.integrity()==[],len(q.files()))
    try:
        import resource
        memory=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    except ImportError:memory=None
    report={'environment':platform.platform(),'python':platform.python_version(),'departments':departments,
            'initial_files':len(paths),'input_bytes':sum(f.stat().st_size for f in paths),
            'expected_metrics':len(truth),'extracted_observations':len(truth)*2,
            'manual_mapping_required':len(truth)*2,'missing_after_mapping':len(truth)-passes,'held_after_mapping':len(truth)-passes,
            'false_pass':false_pass,'unauthorized_approved_export':unauthorized,'unauthorized_final_export':final,
            'initial_import_seconds':round(import_seconds,3),'total_seconds':round(time.perf_counter()-started,3),
            'parent_peak_rss_mib_linux':memory,'tests':results,
            'limits':'Windows 실기기·한컴 렌더링·사람의 정답 검수는 이 자동시험에 포함되지 않음'}
    (root/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('destination');parser.add_argument('--departments',type=int,default=3)
    args=parser.parse_args()
    try:
        report=run(args.destination,args.departments)
        print(json.dumps(report,ensure_ascii=True,indent=2))
    except Exception as e:
        print(f'FAILED: {type(e).__name__}: {e}',file=sys.stderr)
        sys.exit(1)
