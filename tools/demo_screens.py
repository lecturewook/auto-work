"""가상자료를 실제 GUI와 처리 함수로 실행하여 화면을 캡처한다. Windows 실행 증거가 아님."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication,QLabel
from PySide6.QtGui import QFont
from budget_offline.gui import Window
from budget_offline.project import Project
from budget_offline.outputs import export_workbook
from tools.make_fixtures import generate,key,row,xlsx


def run(root,images):
    root=Path(root);images=Path(images)
    if root.exists():raise RuntimeError('새 시연 작업 폴더가 필요합니다.')
    images.mkdir(parents=True,exist_ok=True)
    app=QApplication([])
    app.setStyle('Fusion')
    app.setFont(QFont('Noto Sans CJK KR',10))
    data=root/'input';generate(data,3,False)
    window=Window();window.resize(1460,1000)
    badge=QLabel('실제 프로그램의 Linux 실행 화면 · 가상자료 시연 · Windows 실기기 검증 전')
    badge.setStyleSheet('background:#e5eef8;color:#163751;padding:8px;font-weight:bold;')
    window.centralWidget().layout().insertWidget(1,badge)
    project=Project(root/'가상시연',create=True,name='2026 예산 · 가상자료 시연')
    window.project=project
    req=json.loads((data/'필수항목.json').read_text(encoding='utf-8'))
    project.set_expectations(req['keys'],req['departments'],'가상 시연')
    for path in sorted((data/'정상자료').iterdir()):project.import_file(path)
    def capture(name,tab,table,find=None):
        window.refresh();window.tabs.setCurrentIndex(tab);window.show();app.processEvents()
        t=window.tables[table]
        for r in range(t.rowCount()):
            record=t.item(r,0).data(256)
            if find is None or find(record):
                t.selectRow(r);break
        app.processEvents()
        assert window.grab().save(str(images/name))
    capture('01-import.png',0,'files')
    capture('02-source.png',1,'obs',lambda o:o['key'].get('부서코드')=='D001' and o['key'].get('지표코드')=='시행예산' and o['role']=='한글')
    for o in project.observations():project.confirm_mapping(o['id'],o['key'],o['unit'],'가상 시연','기대결과의 키·단위와 비교한 시연')
    item=next(i for i in project.comparisons() if i['key']==key())
    project.review(item['id'],'승인','가상 시연','1,000천원과 1,000,000원의 의미·단위 확인')
    capture('03-compare.png',2,'compare',lambda i:i['key']==key())
    capture('04-preview.png',3,'preview',lambda i:i['key']==key())
    output=export_workbook(project,'approved')
    assert output.exists()
    revision=root/'수정본.xlsx';xlsx(revision,[row(key(),'1000001','원')]);project.import_file(revision)
    for o in project.observations():
        if not o['confirmed']:project.confirm_mapping(o['id'],o['key'],o['unit'],'가상 시연','추가 수정본의 키 확인')
    capture('05-revision.png',2,'compare',lambda i:i['key']==key())
    check=next(i for i in project.comparisons() if i['key']==key())
    assert check['approval']=='재검토 필요' and check['status']=='중복·수정본 확인 필요'
    (images/'demo-results.json').write_text(json.dumps({'app':'0.1.1','platform':'Linux Qt offscreen','input_files':6,'initial_observations':24,'business_keys':12,'approved_before_revision':1,'after_revision_status':check['status'],'after_revision_approval':check['approval'],'windows_executable_tested':False},ensure_ascii=False,indent=2),encoding='utf-8')
    window.close();app.processEvents()
    print('Captured 5 real application screens; matching, approval, export and revision invalidation verified.')


if __name__=='__main__':run(sys.argv[1],sys.argv[2])
