"""개발·배포 제작 전용 다운로드. 업무용 실행 경로에서는 호출하지 않는다."""
import hashlib
import json
import urllib.request
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    records=json.loads((root/'DEPENDENCY_HASHES.json').read_text(encoding='utf-8'))
    for name,r in records.items():
        p=root/'vendor'/('wheels' if name.endswith('.whl') else '')/name
        p.parent.mkdir(parents=True,exist_ok=True)
        if not p.exists():
            tmp=p.with_suffix(p.suffix+'.part')
            try:
                with urllib.request.urlopen(r['url'],timeout=120) as response, tmp.open('wb') as f:
                    while chunk:=response.read(1024*1024):f.write(chunk)
                if hashlib.sha256(tmp.read_bytes()).hexdigest()!=r['sha256']:raise RuntimeError('Upstream hash mismatch: '+name)
                tmp.replace(p)
            finally:
                if tmp.exists():tmp.unlink()
        if hashlib.sha256(p.read_bytes()).hexdigest()!=r['sha256']:raise RuntimeError('Hash mismatch: '+name)
        print('verified:',name)


if __name__=='__main__':main()
