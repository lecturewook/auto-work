import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from pathlib import PurePosixPath
from .project import Project, now
from .safety import SafeError, digest, canonical, safe_zip


def backup(project, destination):
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_relative_to(project.root.resolve()):
        raise SafeError('프로젝트 밖에 새 백업 파일 이름을 지정하세요.')
    if project.integrity():
        raise SafeError('원본 무결성 확인에 실패하여 백업을 중단합니다.')
    with tempfile.TemporaryDirectory(prefix='backup-', dir=destination.parent) as td:
        td = Path(td)
        dbfile = td / 'project.db'
        db = sqlite3.connect(dbfile)
        try:
            project.db.backup(db)
        finally:
            db.close()
        members = {'project.db': dbfile}
        for f in project.files():
            members[f['original']] = project.root / f['original']
        for r in project.db.execute("SELECT path,hash FROM outputs WHERE state='반영 완료'"):
            p = project.root / r['path']
            if p.parent.resolve() != (project.root / 'exports').resolve() or p.is_symlink():
                raise SafeError('출력 경로가 프로젝트 범위를 벗어났습니다.')
            if not p.exists() or digest(p) != r['hash']:
                raise SafeError('출력 파일이 없거나 바뀌었습니다. 백업 전 복구·확인하세요.')
            members[r['path']] = p
        manifest = {'format':1,'time':now(),'files':{n:digest(p) for n,p in members.items()}}
        pending = td / 'backup.zip'
        with zipfile.ZipFile(pending,'w',zipfile.ZIP_DEFLATED) as z:
            for n,p in members.items():
                z.write(p,n)
            z.writestr('manifest.json',canonical(manifest))
        with open(pending,'rb') as f:
            os.fsync(f.fileno())
        os.replace(pending,destination)
    with project.db:
        project.audit('백업 생성', {'name':destination.name,'hash':digest(destination)})
    return destination


def restore(archive, destination):
    destination = Path(destination).absolute()
    if destination.exists():
        raise SafeError('복구 위치는 존재하지 않는 새 폴더여야 합니다. 기존 프로젝트를 덮어쓰지 않습니다.')
    with tempfile.TemporaryDirectory(prefix='restore-',dir=destination.parent) as td:
        td = Path(td)
        with safe_zip(archive,max_size=5*1024**3,max_members=20000) as z:
            if 'manifest.json' not in z.namelist():
                raise SafeError('프로그램 백업 형식이 아닙니다.')
            manifest = json.loads(z.read('manifest.json'))
            if manifest.get('format')!=1 or set(manifest['files']) != set(z.namelist())-{'manifest.json'}:
                raise SafeError('백업 파일 목록이 맞지 않습니다.')
            for name, expected in manifest['files'].items():
                if name != 'project.db' and not name.startswith(('originals/','exports/')):
                    raise SafeError('백업에 허용되지 않은 파일이 있습니다.')
                target = td / name
                target.parent.mkdir(parents=True,exist_ok=True)
                with z.open(name) as source, open(target,'wb') as out:
                    shutil.copyfileobj(source,out,1024*1024)
                if digest(target)!=expected:
                    raise SafeError('백업 SHA-256 검증에 실패했습니다.')
        with Project(td) as project:
            if project.db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
                raise SafeError('백업 DB 무결성 확인 실패')
            for f in project.files():
                for field, folder in [('original','originals'),('work','work')]:
                    parts=PurePosixPath(f[field]).parts
                    if len(parts)!=2 or parts[0]!=folder or '\\' in f[field] or ':' in f[field]:
                        raise SafeError('백업 DB 경로가 프로젝트 범위를 벗어났습니다.')
                if f['original'] != f'originals/{f["id"]}{f["kind"]}' or f['work'] != f'work/{f["id"]}{f["kind"]}':
                    raise SafeError('백업 DB 경로가 올바르지 않습니다.')
                shutil.copyfile(td/f['original'],td/f['work'])
                (td/f['original']).chmod(0o400)
            if project.integrity():
                raise SafeError('복구 원본 검증 실패')
            project.comparisons()
            with project.db:
                project.audit('백업 복구', {'archive':Path(archive).name,'hash':digest(archive)})
        # temp directory 자체 대신 하위 폴더 내용을 옮겨 완성된 프로젝트만 공개한다.
        staging = td / '.complete'
        staging.mkdir()
        for p in list(td.iterdir()):
            if p != staging:
                shutil.move(str(p),staging/p.name)
        os.replace(staging,destination)
    return destination
