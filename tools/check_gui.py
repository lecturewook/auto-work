"""Linux offscreen에서 화면 생성, 실제 프로젝트 표시, 가져오기 스레드 취소를 검사."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtGui import QFont
from PySide6.QtCore import QEventLoop,QTimer
from budget_offline.gui import Window, ImportJob
from budget_offline.project import Project
from tools.make_fixtures import generate


def run():
    app=QApplication([])
    app.setFont(QFont('Noto Sans CJK KR',10))
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
        window=Window();window.show();app.processEvents()
        if len(sys.argv)>1:
            assert window.grab().save(sys.argv[1])
        loop=QEventLoop()
        with patch('budget_offline.gui.QFileDialog.getExistingDirectory',return_value=str(root)), \
             patch('budget_offline.gui.QInputDialog.getText',return_value=('한글 가상시작',True)), \
             patch('budget_offline.gui.QMessageBox.information') as info:
            button=next(b for b in window.findChildren(QPushButton) if b.text()=='가상자료로 시작')
            button.click()
            assert window.job is not None
            window.job.done.connect(loop.quit)
            QTimer.singleShot(60000,loop.quit);loop.exec()
            assert window.job is None, 'Demo import timed out'
            info.assert_called_once()
        assert len(window.project.files())==6
        assert len(window.project.observations())==24
        assert all(not o['confirmed'] for o in window.project.observations())
        assert all(i['approval']!='승인' for i in window.project.comparisons())
        assert window.tables['compare'].rowCount()==12
        with patch('budget_offline.gui.QMessageBox.warning') as warning:
            button.click()
            warning.assert_called_once()
        assert len(window.project.files())==6, 'Existing work must not receive demo files'
        window.close();app.processEvents()
    print('GUI PASS: 화면·원문·검색·닫기·취소 및 실제 가상자료 시작 버튼 → 6파일/24근거/12항목, 자동 확인·승인 0건')


if __name__=='__main__':run()
