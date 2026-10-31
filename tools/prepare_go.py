"""개발 전용. 공식 고정 Go SDK를 해시 검사 후 별도 폴더에 준비한다."""
import hashlib
import json
import platform
import shutil
import tarfile
import tempfile
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    record = json.loads((root/'BUILD_TOOLCHAIN.json').read_text(encoding='utf-8'))
    if platform.system() != 'Linux' or platform.machine() not in ('x86_64', 'amd64'):
        raise RuntimeError('이 재현 빌드 절차의 제작 PC는 Linux x86-64입니다. 결과물은 Windows x64용입니다.')
    archive = root/'vendor'/record['filename']
    archive.parent.mkdir(exist_ok=True)
    if not archive.exists():
        pending = archive.with_suffix('.part')
        try:
            with urllib.request.urlopen(record['url'], timeout=120) as response, pending.open('wb') as output:
                shutil.copyfileobj(response, output, 1024*1024)
            if hashlib.sha256(pending.read_bytes()).hexdigest() != record['sha256']:
                raise RuntimeError('공식 Go SDK 해시 불일치. 사용하지 않습니다.')
            pending.replace(archive)
        finally:
            pending.unlink(missing_ok=True)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != record['sha256']:
        raise RuntimeError('Go SDK 해시 불일치. 검증을 끄거나 기준 해시를 바꾸지 마세요.')
    tools = root/'.build-tools'
    tools.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=tools, prefix='go-verified-') as temp:
        with tarfile.open(archive) as tar:
            if any(m.name != 'go' and not m.name.startswith('go/') for m in tar.getmembers()):
                raise RuntimeError('Unexpected SDK layout')
            tar.extractall(temp, filter='data')
        destination = tools/'go'
        if destination.is_symlink():
            raise RuntimeError('SDK destination must not be a link')
        if destination.exists():
            shutil.rmtree(destination)
        (Path(temp)/'go').rename(destination)
    print('Verified SDK:', record['version'], destination)


if __name__ == '__main__':
    main()
