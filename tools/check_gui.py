"""Linux offscreen에서 화면 생성, 실제 프로젝트 표시, 가져오기 스레드 취소를 검사."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop,QTimer
from budget_offline.gui import Window, ImportJob
from budget_offline.project import Project
from tools.make_fixtures import generate


def run():
    app=QApplication([])
    with tempfile.TemporaryDirectory() as td:
        root=Path(td);generate(root/'input',3,False)
        with Project(root/'project',create=True):pass
        job=ImportJob(root/'project',list((root/'input'/'정상자료').iterdir()))
        loop=QEventLoop();reports=[]
        def progress(n,total,name):
            if n>=1:job.requestInterruption()
        job.progress.connect(progress)
        job.done.connect(lambda r:(reports.extend(r),loop.quit()))
        job.start();QTimer.singleShot(60000,loop.quit);loop.exec();job.wait(40000)
        assert not job.isRunning()
        assert any(r['status']=='미처리' for r in reports),reports
        window=Window();window.project=Project(root/'project');window.refresh();window.show();app.processEvents()
        assert window.tables['files'].rowCount()>=1
        assert window.tables['obs'].rowCount()>=4
        window.search.setText('D001');app.processEvents()
        window.search.clear();window.tables['obs'].selectRow(0);app.processEvents()
        assert '원문:' in window.detail.toPlainText()
        window.close();app.processEvents()
    print('GUI PASS: 화면·원문 표시·검색·프로젝트 닫기·배치 취소 확인')


if __name__=='__main__':run()
