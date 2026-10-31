import json
import os
from pathlib import Path
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QLineEdit, QTextEdit, QFileDialog, QMessageBox, QDialog, QFormLayout,
    QDialogButtonBox, QComboBox, QSplitter, QProgressBar, QInputDialog)
from . import VERSION
from .project import Project, PASS
from .numbers import KEY_FIELDS
from .outputs import export_workbook
from .backup import backup, restore
from .safety import SafeError, canonical
from .privileges import require_standard_user, PrivilegeError


class ImportJob(QThread):
    progress = Signal(int, int, str)
    done = Signal(list)

    def __init__(self, root, paths):
        super().__init__()
        self.root, self.paths = root, paths

    def run(self):
        results = []
        try:
            with Project(self.root) as project:
                for i, path in enumerate(self.paths):
                    if self.isInterruptionRequested():
                        results.append({'status':'미처리','reason':f'사용자 취소: 남은 {len(self.paths)-i}개는 가져오지 않음'})
                        break
                    self.progress.emit(i,len(self.paths),Path(path).name)
                    try:
                        r = project.import_file(path)
                        results.append({'status':r['status'],'name':Path(path).name,'reason':r.get('reason','')})
                    except Exception as e:
                        results.append({'status':'처리 실패','name':Path(path).name,'reason':str(e) if isinstance(e,SafeError) else type(e).__name__})
                    self.progress.emit(i+1,len(self.paths),Path(path).name)
        except Exception as e:
            results.append({'status':'처리 실패','reason':str(e) if isinstance(e,SafeError) else type(e).__name__})
        self.done.emit(results)


class Form(QDialog):
    def __init__(self, title, fields, parent=None, note=''):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(640,600)
        layout = QVBoxLayout(self)
        if note:
            text = QLabel(note)
            text.setWordWrap(True)
            layout.addWidget(text)
        form = QFormLayout()
        self.entries = {}
        for name, value in fields.items():
            entry = QLineEdit(str(value or ''))
            self.entries[name] = entry
            form.addRow(name, entry)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText('확인하여 저장')
        buttons.button(QDialogButtonBox.Cancel).setText('취소')
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self):
        return {k:v.text().strip() for k,v in self.entries.items()}


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.project = None
        self.job = None
        self.setWindowTitle(f'예산 근거 대조 · 오프라인 시험판 {VERSION}')
        self.resize(1400,900)
        outer = QWidget()
        layout = QVBoxLayout(outer)
        heading = QLabel('예산 근거 대조  |  오프라인 시험판')
        heading.setStyleSheet('font-size:24px;font-weight:700;color:#21425b;padding:8px')
        layout.addWidget(heading)
        notice = QLabel('실제 양식 미검증 · 자동 사업 연결 없음 · 정확 일치 후에도 사람 승인 필요 · 공식 최종본 출력 잠김')
        notice.setWordWrap(True)
        notice.setStyleSheet('background:#fff0d5;padding:10px;color:#694b12')
        layout.addWidget(notice)
        top = QHBoxLayout()
        for text, action in [('새 프로젝트',self.create),('프로젝트 열기',self.open_project),('백업 복구',self.restore_project),('사용 안내',self.help)]:
            top.addWidget(self.button(text,action))
        self.top = QWidget()
        self.top.setLayout(top)
        layout.addWidget(self.top)
        self.status_label = QLabel('새 프로젝트를 만들거나 기존 프로젝트 폴더를 여세요. 자료는 PC 안에 저장됩니다.')
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText('부서·사업·기간·지표·파일명 검색')
        self.search.textChanged.connect(self.filter_rows)
        controls.addWidget(self.search)
        self.filter = QComboBox()
        self.filter.addItems(['전체','연결 불명','중복·수정본','정확 일치','불일치','누락','단위 불명','추출 실패','승인','보류','재검토 필요'])
        self.filter.currentTextChanged.connect(self.filter_rows)
        controls.addWidget(self.filter)
        layout.addLayout(controls)
        self.tabs = QTabWidget()
        self.tables = {}
        self.add_tab('파일 가져오기','files',[('파일 선택',self.import_files),('폴더 선택',self.import_folder),('재처리',self.reprocess),('파일 제외/복원',self.toggle_file)])
        self.add_tab('연결·원문 근거','obs',[('연결 확인/수정',self.mapping),('원문에서 수동 값 선택',self.manual),('근거 채택/제외',self.toggle_evidence)])
        self.add_tab('대조·승인·수정본','compare',[('검토 중',lambda:self.review('검토 중')),('선택 항목 승인',lambda:self.review('승인')),('보류',lambda:self.review('보류')),('업무 항목 제외',lambda:self.review('제외'))])
        self.add_tab('취합 미리보기','preview',[('미리보기 새로 고침',self.refresh),('검토용 초안 저장',lambda:self.export('draft')),('승인 데이터 저장',lambda:self.export('approved'))])
        management = QWidget()
        box = QVBoxLayout(management)
        for text,action in [('프로젝트 백업',self.backup_project),('부서·필수 항목 JSON 등록',self.expectations),('규칙 JSON 변경',self.rules),('원본 SHA-256 확인',self.check_integrity),('프로젝트 닫기',self.close_project)]:
            box.addWidget(self.button(text,action))
        self.management = QTextEdit()
        self.management.setReadOnly(True)
        box.addWidget(self.management)
        self.tabs.addTab(management,'작업 관리')
        layout.addWidget(self.tabs,1)
        self.detail = QTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumHeight(230)
        self.detail.setPlaceholderText('행을 선택하면 원문·위치·단위 변환 근거·검토 상태가 여기에 표시됩니다.')
        layout.addWidget(self.detail)
        self.progress = QProgressBar()
        self.progress.hide()
        self.cancel = self.button('가져오기 취소 (현재 파일 처리가 끝나면 중단)',self.cancel_import)
        self.cancel.hide()
        layout.addWidget(self.progress)
        layout.addWidget(self.cancel)
        self.setCentralWidget(outer)
        self.setStyleSheet('QPushButton {padding:8px;} QTableWidget {gridline-color:#dce2e8;} QTabBar::tab {padding:10px;}')

    def button(self,text,action):
        b = QPushButton(text)
        b.clicked.connect(lambda checked=False:self.safe(action))
        return b

    def safe(self,action):
        try:
            action()
        except Exception as e:
            message = str(e) if isinstance(e,(SafeError,PrivilegeError,ValueError,json.JSONDecodeError)) else f'작업 실패 ({type(e).__name__}). 폴더 권한·파일 잠금·남은 공간을 확인하세요.'
            QMessageBox.warning(self,'작업을 완료하지 못했습니다',message)

    def need(self):
        if self.project is None:
            raise SafeError('프로젝트를 먼저 여세요.')
        return self.project

    def add_tab(self,title,key,buttons):
        page = QWidget()
        layout = QVBoxLayout(page)
        bar = QHBoxLayout()
        for text,action in buttons:
            bar.addWidget(self.button(text,action))
        layout.addLayout(bar)
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        table.setSelectionMode(QTableWidget.SingleSelection)
        table.verticalHeader().hide()
        table.horizontalHeader().setStretchLastSection(True)
        table.itemSelectionChanged.connect(lambda:self.show_detail(key))
        layout.addWidget(table)
        self.tables[key] = table
        self.tabs.addTab(page,title)

    def selected(self,key):
        t = self.tables[key]
        if t.currentRow()<0:
            raise SafeError('먼저 표에서 한 행을 선택하세요.')
        return t.item(t.currentRow(),0).data(Qt.UserRole)

    def fill(self,key,headers,rows):
        table = self.tables[key]
        table.blockSignals(True)
        table.clear()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for r,(record,values) in enumerate(rows):
            for c,v in enumerate(values):
                item = QTableWidgetItem(str(v if v is not None else ''))
                if c==0:
                    item.setData(Qt.UserRole,record)
                table.setItem(r,c,item)
        table.resizeColumnsToContents()
        for c in range(len(headers)):
            table.setColumnWidth(c,min(260,max(90,table.columnWidth(c))))
        table.blockSignals(False)

    def refresh(self):
        p = self.need()
        self.status_label.setText('  |  '.join(f'{k}: {v}' for k,v in p.summary().items()))
        self.fill('files',['파일명','역할','처리 상태','제외','이유','파일 ID'],[(f,[f['name'],f['role'],f['status'],'제외' if f['excluded'] else '사용',f['reason'],f['id']]) for f in p.files()])
        self.fill('obs',['파일·위치','원문값','단위','업무 키','연결','채택','주의'],[(o,[o['name']+' / '+o['location'],o['raw'],o['unit'],' / '.join(o['key'].values()),'확인' if o['confirmed'] else '연결 불명','채택' if o['active'] and not o['file_excluded'] else '제외',', '.join(o['flags'])]) for o in p.observations()])
        items = p.comparisons()
        rows=[]
        for i in items:
            values=[]
            for role in ('한글','엑셀'):
                values.append(' | '.join(f'{o["raw"]} {o["unit"]} ({o["location"]})' for o in i['observations'] if o['role']==role))
            rows.append((i,[' / '.join(i['key'][k] for k in KEY_FIELDS),*values,i['status'],i['approval'],i['reason']]))
        self.fill('compare',['업무 키','한글 근거','엑셀 근거','비교 판정','업무 승인','이유'],rows)
        self.fill('preview',list(KEY_FIELDS)+['표준값','단위','판정','승인'],[(i,[i['key'][k] for k in KEY_FIELDS]+[i['value'],i['unit'],i['status'],i['approval']]) for i in items])
        self.management.setPlainText(f'프로젝트: {p.root}\nDB 구조: {p.meta("schema")}\n프로그램: {VERSION}\n규칙: {p.rules["version"]}\n\n원본: originals\n작업 사본: work\n결과: exports\n검토·가져오기·출력 이력: project.db\n\n작업은 각 단계에서 자동 저장됩니다. 한 프로젝트는 한 사용자만 열 수 있습니다.\n공식 최종본 출력, 자동 계산식, 자동 수정본 선택, 일괄 승인은 이 시험판에서 제공하지 않습니다.')
        self.filter_rows()

    def filter_rows(self):
        query = self.search.text().casefold().split()
        status = self.filter.currentText()
        for t in self.tables.values():
            for r in range(t.rowCount()):
                text = ' '.join(t.item(r,c).text() for c in range(t.columnCount())).casefold()
                t.setRowHidden(r,not all(q in text for q in query) or (status!='전체' and status.casefold() not in text))

    def show_detail(self,key):
        try:
            r = self.selected(key)
        except SafeError:
            return
        if key=='obs':
            self.detail.setPlainText(f'원문: {r["raw"]}\n출처: {r["name"]} / {r["location"]}\n맥락: {r["context"]}\n추출: {r["method"]}\n주의: {", ".join(r["flags"])}\n변환: {canonical(r["normalized"])}\n근거 ID: {r["id"]}\n원본 SHA-256: {r["hash"]}')
        elif key in ('compare','preview'):
            k=r['key']
            lines=[f'업무 항목: {k["부서코드"]} / {k["사업코드"]} / {k["기간"]} / {k["예산구분"]} / {k["지표코드"]}',
                   f'세부차원: {k["세부차원"]} | 집계수준: {k["집계수준"]} | 재원: {k["재원"]}',
                   f'비교 판정: {r["status"]} | 업무 승인: {r["approval"]} | 검토자: {r["reviewer"] or "미입력"}',
                   f'표준값: {r["value"] if r["value"] is not None else "확정하지 않음"} {r["unit"] or ""}',
                   '판정 이유: '+r['reason']]
            for o in r['observations']:
                lines.append(f'{o["role"]}: {o["raw"]} {o["unit"]} → {o["normalized"]["value"] or "미확정"} {o["normalized"]["base_unit"] or ""} / 출처: {o["name"]}, {o["location"]}')
            lines.extend(['검토 이유: '+(r['review_reason'] or '미입력'),'항목 ID: '+r['id']])
            self.detail.setPlainText('\n'.join(lines))
        else:
            self.detail.setPlainText(json.dumps(r,ensure_ascii=False,indent=2))

    def create(self):
        if self.project:
            raise SafeError('현재 프로젝트를 작업 관리에서 먼저 닫으세요.')
        folder=QFileDialog.getExistingDirectory(self,'새 프로젝트를 넣을 상위 로컬 폴더 선택')
        if not folder:return
        name,ok=QInputDialog.getText(self,'프로젝트 이름','새 폴더 이름 (예: 2026_가상시험)')
        if ok and name:
            if Path(name).name!=name or any(c in name for c in '\\/:*?"<>|') or name in ('.','..'):
                raise SafeError('폴더 이름에 경로·특수문자를 넣지 마세요.')
            self.project=Project(Path(folder)/name,create=True,name=name)
            self.refresh()

    def open_project(self):
        if self.project:
            raise SafeError('현재 프로젝트를 먼저 닫으세요.')
        path=QFileDialog.getExistingDirectory(self,'project.db가 있는 프로젝트 폴더 선택')
        if path:
            self.project=Project(path)
            self.refresh()

    def close_project(self):
        if self.project:
            self.project.close()
            self.project=None
        for t in self.tables.values():t.setRowCount(0)
        self.status_label.setText('프로젝트를 닫았습니다. 모든 완료된 작업은 저장되어 있습니다.')
        self.detail.clear()
        self.management.clear()

    def import_files(self):
        self.need()
        paths,_=QFileDialog.getOpenFileNames(self,'파일 가져오기 (PC 내부 복사)','', '문서 (*.hwp *.hwpx *.xlsx *.xls *.xlsm);;모든 파일 (*)')
        if paths:self.start_import(paths)

    def import_folder(self):
        p=self.need()
        folder=QFileDialog.getExistingDirectory(self,'가져올 로컬 폴더 선택 (하위 폴더 포함)')
        if not folder:return
        root=Path(folder).resolve()
        if root==p.root.resolve() or root.is_relative_to(p.root.resolve()) or p.root.resolve().is_relative_to(root):
            raise SafeError('프로젝트와 분리된 제출자료 폴더를 선택하세요.')
        paths=[]
        for current,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if not (Path(current)/d).is_symlink()]
            for f in sorted(files):
                path=Path(current)/f
                if path.suffix.lower() in ('.hwp','.hwpx','.xlsx','.xls','.xlsm') and not path.is_symlink():paths.append(str(path))
        if len(paths)>2000:raise SafeError('한 번에 2,000개 파일까지 가져올 수 있습니다.')
        if paths:self.start_import(paths)

    def start_import(self,paths):
        p=self.need()
        root=p.root
        self.close_project()
        self.tabs.setEnabled(False)
        self.top.setEnabled(False)
        self.progress.show()
        self.cancel.show()
        self.job=ImportJob(root,paths)
        self.job.progress.connect(self.import_progress)
        self.job.done.connect(lambda results:self.import_done(root,results))
        self.job.start()

    def import_progress(self,n,total,name):
        self.progress.setMaximum(total)
        self.progress.setValue(n)
        self.status_label.setText(f'처리 중 {n}/{total}: {name} · 파일당 최대 30초, 취소는 현재 파일 뒤 적용')

    def cancel_import(self):
        if self.job:self.job.requestInterruption()

    def import_done(self,root,results):
        self.job.wait()
        self.job=None
        self.tabs.setEnabled(True)
        self.top.setEnabled(True)
        self.progress.hide()
        self.cancel.hide()
        self.project=Project(root)
        self.refresh()
        counts={}
        for r in results:counts[r['status']]=counts.get(r['status'],0)+1
        self.detail.setPlainText('\n'.join(f'{r.get("name", "")}: {r["status"]} {r.get("reason", "")}' for r in results))
        QMessageBox.information(self,'가져오기 결과','\n'.join(f'{k}: {v}' for k,v in counts.items())+'\n미지원·실패·미처리는 정상 완료가 아닙니다. 아래 목록을 확인하세요.')

    def mapping(self):
        p=self.need();o=self.selected('obs')
        fields={k:o['key'].get(k,'') for k in KEY_FIELDS}
        fields.update({'단위':o['unit'],'검토자':'','이유':''})
        form=Form('연결과 단위 확인',fields,self,'원문을 직접 확인하세요. 코드·기간·예산구분·집계수준·재원까지 같은 항목인지 확인합니다. 빈 차원은 의미를 확인한 뒤 전체로 표시합니다.')
        if form.exec():
            v=form.values();p.confirm_mapping(o['id'],{k:v[k] for k in KEY_FIELDS},v['단위'],v['검토자'],v['이유']);self.refresh()

    def manual(self):
        p=self.need();o=self.selected('obs')
        fields={'원문에서 선택한 값':o['raw'],**{k:o['key'].get(k,'') for k in KEY_FIELDS},'단위':o['unit'],'검토자':'','이유':''}
        form=Form('사람이 원문을 확인하여 값 선택',fields,self,'원문 문자열 안에 있는 숫자 표기만 선택할 수 있습니다. 정정값을 만들어 넣을 수 없습니다. 한컴·Excel에서 로컬 작업 사본을 직접 확인한 이유를 남기세요. 원래 근거는 제외 상태로 보존합니다.')
        if form.exec():
            v=form.values();p.manual_evidence(o['id'],v['원문에서 선택한 값'],v['단위'],{k:v[k] for k in KEY_FIELDS},v['검토자'],v['이유']);self.refresh()

    def reason(self,title,note=''):
        form=Form(title,{'검토자':'','이유':''},self,note)
        return form.values() if form.exec() else None

    def toggle_evidence(self):
        p=self.need();o=self.selected('obs');v=self.reason('근거 제외' if o['active'] else '근거 다시 채택','같은 종류의 근거가 여러 개면 자동 선택하지 않습니다. 수정본 채택 시 기존 근거를 제외하고 새 근거를 확인하세요.')
        if v:p.set_active(o['id'],not o['active'],v['검토자'],v['이유']);self.refresh()

    def toggle_file(self):
        p=self.need();f=self.selected('files');v=self.reason('파일 제외/복원')
        if v:p.exclude_file(f['id'],not f['excluded'],v['검토자'],v['이유']);self.refresh()

    def reprocess(self):
        p=self.need();f=self.selected('files')
        if QMessageBox.question(self,'재처리','이 파일의 기존 근거를 이력으로 보존하고 새로 추출합니다. 연결 확인과 승인이 다시 필요합니다. 진행할까요?')==QMessageBox.Yes:
            p.reprocess(f['id']);self.refresh()

    def review(self,state):
        p=self.need();i=self.selected('compare')
        v=self.reason(state, f'선택한 1개 항목\n{canonical(i["key"])}\n표준값: {i["value"]} {i["unit"]}\n판정: {i["status"]}\n원문과 의미를 직접 확인한 검토자를 기록하세요.')
        if v:p.review(i['id'],state,v['검토자'],v['이유']);self.refresh()

    def export(self,mode):
        path=export_workbook(self.need(),mode)
        self.refresh()
        QMessageBox.information(self,'결과 저장',f'{path}\n\n공식 최종본이 아닙니다. 원문근거·미해결목록·부서현황 시트를 함께 확인하세요.')

    def backup_project(self):
        p=self.need();path,_=QFileDialog.getSaveFileName(self,'프로젝트 밖에 새 백업 저장','예산작업_백업.zip','백업 (*.zip)')
        if path:backup(p,path);QMessageBox.information(self,'백업 완료','백업을 만들었습니다. 작업 복사본에서 실제 복구 시험도 하세요.')

    def restore_project(self):
        archive,_=QFileDialog.getOpenFileName(self,'백업 ZIP 선택','','백업 (*.zip)')
        if not archive:return
        parent=QFileDialog.getExistingDirectory(self,'복구할 새 폴더를 둘 상위 폴더')
        if not parent:return
        name,ok=QInputDialog.getText(self,'복구 폴더 이름','존재하지 않는 새 폴더 이름')
        if ok and name and Path(name).name==name and not any(c in name for c in '\\/:*?"<>|') and name not in ('.','..'):
            result=restore(archive,Path(parent)/name)
            QMessageBox.information(self,'복구 완료',f'{result}\n프로젝트 열기로 확인하세요.')

    def expectations(self):
        p=self.need();path,_=QFileDialog.getOpenFileName(self,'부서·필수 항목 JSON 선택','','JSON (*.json)')
        if path:
            data=json.loads(Path(path).read_text(encoding='utf-8'))
            v=self.reason('부서·필수 목록 교체',f'부서 {len(data["departments"])}개, 필수 항목 {len(data["keys"])}개로 교체합니다.')
            if v:p.set_expectations(data['keys'],data['departments'],v['검토자']);self.refresh()

    def rules(self):
        p=self.need();path,_=QFileDialog.getOpenFileName(self,'새 규칙 JSON 선택','','JSON (*.json)')
        if path:
            data=json.loads(Path(path).read_text(encoding='utf-8'));v=self.reason('규칙 변경','먼저 백업하세요. 영향받는 승인은 재검토로 바뀝니다. 추출 구조 변경은 파일 재처리도 필요합니다.')
            if v:p.update_rules(data,v['검토자'],v['이유']);self.refresh()

    def check_integrity(self):
        bad=self.need().integrity()
        self.refresh()
        QMessageBox.information(self,'원본 무결성','원본 사본 SHA-256이 모두 일치합니다.' if not bad else f'{len(bad)}개 불일치. 승인과 출력을 중단하고 백업을 확인하세요.')

    def help(self):
        path=Path(__file__).resolve().parent.parent/'docs'/'USER_GUIDE.md'
        dialog=QDialog(self);dialog.setWindowTitle('사용 안내');dialog.resize(950,750)
        layout=QVBoxLayout(dialog);text=QTextEdit();text.setReadOnly(True)
        text.setPlainText(path.read_text(encoding='utf-8') if path.exists() else '패키지의 docs/USER_GUIDE.md를 확인하세요.')
        layout.addWidget(text);dialog.exec()

    def closeEvent(self,event):
        if self.job:
            QMessageBox.information(self,'가져오기 진행 중','가져오기 취소를 누른 뒤 현재 파일 처리가 끝날 때까지 기다리세요.')
            event.ignore();return
        self.close_project();event.accept()


def main():
    require_standard_user()
    app=QApplication([])
    app.setApplicationName('예산 근거 대조 시험판')
    app.setStyle('Fusion')
    window=Window();window.show()
    return app.exec()
