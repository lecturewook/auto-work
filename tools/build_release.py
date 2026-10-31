"""해시 검증된 Windows 패키지로 ZIP 구성. 도구 준비 후 네트워크 호출 없음."""
import hashlib
import json
import shutil
import struct
import zipfile
from pathlib import Path

VERSION='0.1.2'
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'dist'
FOLDERS=['budget_offline','rules','samples','docs','tools','tests','third_party','launcher']
FILES=['README.md','requirements.txt','requirements-dev.txt','pyproject.toml','run_app.py','LICENSE','DEPENDENCY_HASHES.json','BUILD_TOOLCHAIN.json']


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def archive(folder,path):
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(folder.rglob('*')):
            if p.is_file():
                entry=zipfile.ZipInfo(p.relative_to(folder).as_posix(),date_time=(2026,10,31,0,0,0))
                entry.compress_type=zipfile.ZIP_DEFLATED;entry.external_attr=0o644<<16
                z.writestr(entry,p.read_bytes())


def copy_app(stage):
    for folder in FOLDERS:
        shutil.copytree(ROOT/folder,stage/folder,ignore=shutil.ignore_patterns('__pycache__','*.pyc','payload.zip','.cache'))
    for name in FILES:shutil.copy2(ROOT/name,stage/name)


def write_cmd(stage,name,body):
    (stage/name).write_bytes(('@echo off\r\nchcp 65001 >nul\r\ncd /d "%~dp0"\r\n'+body.replace('\n','\r\n')).encode('utf-8'))


def build():
    DEST.mkdir(exist_ok=True)
    stage=DEST/'Windows-x64'
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir();copy_app(stage)
    records=json.loads((ROOT/'DEPENDENCY_HASHES.json').read_text(encoding='utf-8'))
    for name,record in records.items():
        p=ROOT/'vendor'/('wheels' if name.endswith('.whl') else '')/name
        if not p.is_file() or sha(p)!=record['sha256']:raise RuntimeError('Missing or changed build input: '+name)
    runtime=stage/'runtime';runtime.mkdir()
    with zipfile.ZipFile(ROOT/'vendor/python.3.12.10.nupkg') as z:
        for name in z.namelist():
            if name.startswith('tools/') and not name.endswith('/'):
                p=runtime/name[6:];p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
    site=runtime/'Lib/site-packages';site.mkdir(parents=True,exist_ok=True)
    for wheel in sorted((ROOT/'vendor/wheels').glob('*.whl')):
        with zipfile.ZipFile(wheel) as z:
            for name in z.namelist():
                if name.endswith('/'):continue
                if '.data/' in name:raise RuntimeError('Wheel layout needs explicit mapping: '+name)
                p=site/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(name))
                if any(s in name.lower() for s in ('license','licence','copying','authors')) or name.endswith('.dist-info/METADATA'):
                    notice=stage/'third_party'/wheel.name/name
                    notice.parent.mkdir(parents=True,exist_ok=True);notice.write_bytes(z.read(name))
    shutil.copy2(runtime/'LICENSE.txt',stage/'third_party/CPython-LICENSE.txt')
    for name in ('python.exe','pythonw.exe','python312.dll'):
        data=(runtime/name).read_bytes();offset=struct.unpack_from('<I',data,60)[0]
        assert data[offset:offset+4]==b'PE\0\0' and struct.unpack_from('<H',data,offset+4)[0]==0x8664
    write_cmd(stage,'방화벽설정_기관관리자전용.cmd','powershell.exe -NoProfile -NonInteractive -ExecutionPolicy RemoteSigned -File "tools\\windows_policy.ps1" -Mode Install\nif errorlevel 1 goto fail\necho Firewall setup completed. Close this administrator window.\necho Run the application separately by double-clicking its normal launcher.\npause\nexit /b 0\n:fail\necho Firewall setup failed. Ask the institutional administrator.\npause\nexit /b 1\n')
    write_cmd(stage,'실행.cmd','if not exist "%~dp0runtime\\python.exe" goto missing\nif not exist "%~dp0run_app.py" goto missing\n"%~dp0runtime\\python.exe" -E -s -B "%~dp0run_app.py"\nif errorlevel 1 goto fail\nexit /b 0\n:missing\necho Bundled program files are missing. Python installation is NOT needed.\necho Use BudgetOffline-0.1.2-Windows-x64.exe or fully extract the Windows ZIP.\necho If files were quarantined, ask your institutional security administrator.\npause\nexit /b 2\n:fail\necho Launch failed. Read the specific error above and docs\\TROUBLESHOOTING.md.\necho Do not run as administrator.\npause\nexit /b 1\n')
    write_cmd(stage,'가상시험.cmd','"runtime\\python.exe" -E -s -B "tools\\launch_selftest.py"\nif errorlevel 1 goto fail\npause\nexit /b 0\n:fail\necho Test stopped. Use a normal user account. Do not use real work data.\npause\nexit /b 1\n')
    manifest={'app':VERSION,'architecture':'Windows x86-64','windows_execution_validated':False,'execution_mode':'standard-user-only','files':{p.relative_to(stage).as_posix():sha(p) for p in sorted(stage.rglob('*')) if p.is_file()}}
    (stage/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    archive(stage,DEST/f'BudgetOffline-{VERSION}-Windows-x64.zip')
    source=DEST/'source'
    if source.exists():shutil.rmtree(source)
    source.mkdir();copy_app(source)
    # wheel 내부 원본 고지문을 소스 묶음에도 보존한다.
    shutil.copytree(stage/'third_party',source/'third_party',dirs_exist_ok=True)
    archive(source,DEST/f'BudgetOffline-{VERSION}-source.zip')
    guides=DEST/'guides'
    if guides.exists():shutil.rmtree(guides)
    guides.mkdir();shutil.copytree(ROOT/'docs',guides/'docs');shutil.copy2(ROOT/'README.md',guides/'README.md')
    archive(guides,DEST/f'BudgetOffline-{VERSION}-guides.zip')
    sums=''.join(sha(p)+'  '+p.name+'\n' for p in sorted(DEST.glob(f'BudgetOffline-{VERSION}-*.zip')))
    (DEST/'SHA256SUMS.txt').write_text(sums,encoding='utf-8')
    print(sums)
    print('Windows payload files:',len(manifest['files']))


if __name__=='__main__':build()
