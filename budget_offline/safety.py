import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from defusedxml import ElementTree as ET

MAX_FILE = 50 * 1024 * 1024
MAX_EXPANDED = 200 * 1024 * 1024
MAX_MEMBERS = 5000
MAX_CELLS = 100000


class SafeError(Exception):
    """사용자에게 보여줄 수 있는 오류. 문서 전체나 환경 비밀을 포함하지 않는다."""


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def safe_zip(path, max_size=MAX_EXPANDED, max_members=MAX_MEMBERS):
    try:
        z = zipfile.ZipFile(path)
        total = 0
        names = set()
        for info in z.infolist():
            p = PurePosixPath(info.filename)
            if ('\\' in info.filename or ':' in info.filename or p.is_absolute()
                    or '..' in p.parts or info.filename in names
                    or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise SafeError('압축 경로 또는 중복 항목이 안전하지 않습니다.')
            names.add(info.filename)
            if info.flag_bits & 1:
                raise SafeError('암호화 압축 파일은 지원하지 않습니다.')
            total += info.file_size
            if (info.file_size > max_size or total > max_size or len(names) > max_members
                    or info.file_size > max(1024 * 1024, info.compress_size * 200)):
                raise SafeError('압축 해제 크기·항목 수·압축률 제한을 넘었습니다.')
        return z
    except Exception as e:
        if 'z' in locals():
            z.close()
        if isinstance(e, SafeError):
            raise
        raise SafeError('손상되었거나 지원하지 않는 압축 구조입니다.') from e


def xml(data):
    if len(data) > 20 * 1024 * 1024:
        raise SafeError('XML 크기 제한을 넘었습니다.')
    try:
        root = ET.fromstring(data)
        count = 0
        stack = [(root, 0)]
        while stack:
            node, depth = stack.pop()
            count += 1
            if depth > 80 or count > 300000:
                raise SafeError('XML 깊이·항목 수 제한을 넘었습니다.')
            if (node.text and len(node.text)>10000) or (node.tail and len(node.tail)>10000):
                raise SafeError('XML 단일 문자열 10,000자 제한을 넘었습니다.')
            stack.extend((child, depth + 1) for child in node)
        return root
    except SafeError:
        raise
    except Exception as e:
        raise SafeError('XML이 손상되었거나 외부 개체 선언을 포함합니다.') from e


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.pending-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
