"""검증된 ZIP을 포함하는 Windows 단일 EXE. 제작 중에도 온라인 모듈 조회 없음."""
import hashlib
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    from build_release import VERSION
    record = json.loads((ROOT/'BUILD_TOOLCHAIN.json').read_text(encoding='utf-8'))
    go = ROOT/'.build-tools/go/bin/go'
    if not go.is_file():
        raise RuntimeError('제작 PC에서 tools/prepare_go.py를 먼저 실행하세요.')
    env = dict(os.environ, GOTOOLCHAIN='local', GOPROXY='off',
               GOTELEMETRY='off', GOCACHE=str(ROOT/'.cache/gobuild'),
               GOMODCACHE=str(ROOT/'.cache/gomod'), CGO_ENABLED='0')
    version = subprocess.check_output([go, 'version'], env=env, text=True)
    if version.split()[2] != record['version']:
        raise RuntimeError('SDK 버전이 다릅니다: '+version)
    payload = ROOT/'dist'/f'BudgetOffline-{VERSION}-Windows-x64.zip'
    embedded = ROOT/'launcher/payload.zip'
    shutil.copyfile(payload, embedded)
    try:
        # 실제 배포 ZIP을 읽고 추출·검증한다. 단위 시험용 가짜 실행 파일과 구분한다.
        subprocess.run([go, 'test', '-count=1', '-v', './...'], cwd=ROOT/'launcher',
                       env=dict(env, BUDGET_TEST_PAYLOAD=str(embedded)), check=True)
        binary = ROOT/'dist'/f'BudgetOffline-{VERSION}-Windows-x64.exe'
        subprocess.run([go, 'build', '-trimpath', '-buildvcs=false',
                        '-ldflags=-H=windowsgui -s -w -buildid=', '-o', str(binary), '.'],
                       cwd=ROOT/'launcher', env=dict(env, GOOS='windows', GOARCH='amd64'), check=True)
        data = binary.read_bytes()
        offset = struct.unpack_from('<I', data, 60)[0]
        if data[:2] != b'MZ' or data[offset:offset+4] != b'PE\0\0':
            raise RuntimeError('Windows PE file required')
        if struct.unpack_from('<H', data, offset+4)[0] != 0x8664:
            raise RuntimeError('x64 machine required')
        if struct.unpack_from('<H', data, offset+24+68)[0] != 2:
            raise RuntimeError('Windows GUI subsystem required')
        if len(data) >= 100*1024**2:
            raise RuntimeError('Download artifact exceeds repository limit')
        payload_data = payload.read_bytes()
        if data.count(payload_data) != 1:
            raise RuntimeError('Exact release ZIP not found once in executable')
        result = {'app':VERSION, 'go':record['version'], 'target':'windows/amd64',
                  'subsystem':'Windows GUI', 'bytes':len(data), 'sha256':digest(binary),
                  'embedded_payload_sha256':digest(payload), 'embedded_payload_bytes':len(payload_data),
                  'real_payload_extraction_test':'passed on Linux', 'windows_execution_validated':False}
        (ROOT/'dist/STANDALONE_BUILD.json').write_text(json.dumps(result, indent=2)+'\n',encoding='utf-8')
        paths = sorted((ROOT/'dist').glob(f'BudgetOffline-{VERSION}-*'))
        (ROOT/'dist/SHA256SUMS.txt').write_text(''.join(digest(p)+'  '+p.name+'\n' for p in paths if p.is_file()),encoding='utf-8')
        print(json.dumps(result, indent=2))
    finally:
        embedded.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
