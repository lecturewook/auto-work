"""동봉 기준 해시 대조. 배포자 신원을 인증하는 기능은 아니다."""
import hashlib
import json
import sys
from pathlib import Path


def main():
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'PACKAGE_MANIFEST.json').read_text(encoding='utf-8'))
    bad=[]
    for name,expected in manifest['files'].items():
        p=root/name
        if not p.resolve().is_relative_to(root) or not p.is_file() or p.is_symlink():
            bad.append(name);continue
        h=hashlib.sha256()
        with p.open('rb') as f:
            for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
        if h.hexdigest()!=expected:bad.append(name)
    if bad:
        print('FAILED: bundle integrity mismatch: '+', '.join(bad[:10]));return 1
    print(f'PASS: {len(manifest["files"])} packaged files match bundled hashes. Identity is NOT authenticated by this check.')
    return 0


if __name__=='__main__':sys.exit(main())
