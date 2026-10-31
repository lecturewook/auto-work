import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, localcontext
from . import VERSION, SCHEMA_VERSION
from .numbers import normalize, key_complete, KEY_FIELDS
from .safety import SafeError, MAX_FILE, digest, canonical, atomic_bytes

PASS = ('정확 일치', '변환 후 정확 일치')


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def identifier():
    return uuid.uuid4().hex


def key_id(key):
    return hashlib.sha256(canonical(key).encode()).hexdigest()


def validate_rules(rules):
    if not isinstance(rules.get('version'), str) or not rules['version'].strip():
        raise SafeError('규칙 버전 이름이 필요합니다.')
    if rules.get('actual_template_validated') is not False or rules.get('final_mapping') is not None:
        raise SafeError('시험판에서는 실제 양식 검증 완료·최종 셀 매핑을 활성화할 수 없습니다.')
    if rules.get('profile') != '가상예산-v1' or not isinstance(rules.get('units'), dict):
        raise SafeError('가상예산-v1 구조만 지원합니다.')
    for unit, spec in rules['units'].items():
        if not isinstance(spec, list) or len(spec) != 2 or spec[0] not in ('KRW', 'person', 'count', 'ratio'):
            raise SafeError('단위 규칙 구조가 올바르지 않습니다.')
        try:
            factor = Decimal(spec[1])
            if not factor.is_finite() or factor <= 0 or factor > Decimal('1e15'):
                raise ValueError()
        except Exception as e:
            raise SafeError('단위 배수는 0보다 큰 유한 십진수여야 합니다.') from e


class Project:
    def __init__(self, root, create=False, name=None):
        self.root = Path(root).absolute()
        if str(self.root).startswith(('\\\\', '//')) or self.root.is_symlink():
            raise SafeError('네트워크 공유·심볼릭 링크 경로는 사용할 수 없습니다.')
        if create:
            if self.root.exists() and any(self.root.iterdir()):
                raise SafeError('새 프로젝트는 비어 있는 폴더에 만드세요.')
            self.root.mkdir(parents=True, exist_ok=True)
        if not self.root.is_dir() or (not create and not (self.root / 'project.db').is_file()):
            raise SafeError('프로젝트 폴더 또는 project.db가 없습니다.')
        for name in ('project.db', '.lock', 'originals', 'work', 'exports'):
            if (self.root / name).is_symlink():
                raise SafeError('프로젝트 내부의 연결 파일·연결 폴더는 허용하지 않습니다.')
        self.lock = open(self.root / '.lock', 'a+b')
        try:
            self.lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                if not self.lock.read(1):
                    self.lock.write(b'0')
                    self.lock.flush()
                self.lock.seek(0)
                msvcrt.locking(self.lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as e:
            self.lock.close()
            raise SafeError('다른 창에서 이 프로젝트를 사용하고 있습니다. 먼저 닫으세요.') from e
        try:
            self.db = sqlite3.connect(self.root / 'project.db')
            self.db.row_factory = sqlite3.Row
            self.db.execute('PRAGMA foreign_keys=ON')
            self.db.execute('PRAGMA synchronous=FULL')
            if create:
                self._create(name or self.root.name)
            if self.meta('schema') != str(SCHEMA_VERSION):
                raise SafeError('DB 버전이 다릅니다. 맞는 프로그램과 백업을 함께 사용하세요.')
            for folder in ('originals', 'work', 'exports'):
                (self.root / folder).mkdir(exist_ok=True)
            with self.db:
                self.db.execute("UPDATE files SET status='처리 실패', reason='이전 실행 중 중단됨: 재처리 필요' WHERE status='처리 중'")
                self.db.execute("UPDATE outputs SET state='반영 실패', reason='이전 출력 중 중단됨: 파일과 이력 확인 필요' WHERE state='반영 준비'")
        except Exception:
            self.close()
            raise

    def _create(self, name):
        self.db.executescript('''
        CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE files (id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT UNIQUE NOT NULL,
          size INTEGER, kind TEXT, role TEXT, imported TEXT, original TEXT, work TEXT,
          status TEXT, reason TEXT, extractor TEXT, excluded INTEGER DEFAULT 0);
        CREATE TABLE imports (id TEXT PRIMARY KEY, file_id TEXT, name TEXT, time TEXT, result TEXT);
        CREATE TABLE obs (id TEXT PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id),
          raw TEXT, unit TEXT, key_json TEXT, location TEXT, context TEXT, flags TEXT, method TEXT,
          confirmed INTEGER DEFAULT 0, active INTEGER DEFAULT 1, parent TEXT, revision INTEGER DEFAULT 1);
        CREATE TABLE decisions (key_id TEXT PRIMARY KEY, fingerprint TEXT, state TEXT, reviewer TEXT, reason TEXT, time TEXT);
        CREATE TABLE expected (key_id TEXT PRIMARY KEY, key_json TEXT);
        CREATE TABLE departments (code TEXT PRIMARY KEY, name TEXT);
        CREATE TABLE history (seq INTEGER PRIMARY KEY AUTOINCREMENT, time TEXT, action TEXT, details TEXT);
        CREATE TABLE outputs (id TEXT PRIMARY KEY, time TEXT, mode TEXT, path TEXT, hash TEXT, snapshot TEXT, state TEXT, reason TEXT);
        ''')
        rules = json.loads((Path(__file__).resolve().parent.parent / 'rules/demo-v1.json').read_text(encoding='utf-8'))
        with self.db:
            for k, v in [('schema', str(SCHEMA_VERSION)), ('name', name), ('rules', canonical(rules)), ('app', VERSION)]:
                self.db.execute('INSERT INTO meta VALUES (?,?)', (k, v))
            self.audit('프로젝트 생성', {'name': name, 'app': VERSION})

    def close(self):
        if getattr(self, 'db', None):
            self.db.close()
            self.db = None
        if getattr(self, 'lock', None):
            self.lock.close()
            self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def meta(self, key):
        row = self.db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else None

    @property
    def rules(self):
        return json.loads(self.meta('rules'))

    def audit(self, action, details):
        self.db.execute('INSERT INTO history(time,action,details) VALUES (?,?,?)', (now(), action, canonical(details)))

    def files(self):
        return [dict(r) for r in self.db.execute('SELECT * FROM files ORDER BY imported,id')]

    def observations(self):
        rows = []
        for r in self.db.execute('SELECT o.*,f.name,f.hash,f.role,f.status AS file_status,f.excluded AS file_excluded FROM obs o JOIN files f ON f.id=o.file_id ORDER BY f.imported,o.rowid'):
            d = dict(r)
            d['key'] = json.loads(d['key_json'])
            d['flags'] = json.loads(d['flags'])
            d['normalized'] = normalize(d['raw'], d['unit'], self.rules)
            rows.append(d)
        return rows

    def import_file(self, path):
        path = Path(path)
        if path.is_symlink() or not path.is_file():
            raise SafeError('일반 파일만 가져올 수 있습니다.')
        if path.stat().st_size > MAX_FILE:
            with self.db:
                self.db.execute('INSERT INTO imports VALUES (?,?,?,?,?)', (identifier(), None, path.name, now(), '제외: 50MB 제한'))
            return {'status': '제외', 'reason': '50MB 파일 크기 제한', 'name': path.name}
        sha = digest(path)
        existing = self.db.execute('SELECT * FROM files WHERE hash=?', (sha,)).fetchone()
        if existing:
            with self.db:
                self.db.execute('INSERT INTO imports VALUES (?,?,?,?,?)', (identifier(), existing['id'], path.name, now(), '동일 파일 재가져오기'))
            return {'status': '재가져오기', 'id': existing['id'], 'name': path.name}
        fid = identifier()
        ext = path.suffix.lower()
        original = f'originals/{fid}{ext}'
        work = f'work/{fid}{ext}'
        try:
            shutil.copyfile(path, self.root / original)
            if digest(self.root / original) != sha:
                raise SafeError('가져오는 동안 파일이 변경되었습니다. 다시 가져오세요.')
            shutil.copyfile(self.root / original, self.root / work)
            os.chmod(self.root / original, 0o400)
            with self.db:
                self.db.execute('INSERT INTO files(id,name,hash,size,kind,role,imported,original,work,status,reason,extractor) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',
                    (fid, path.name, sha, path.stat().st_size, ext, '한글' if ext in ('.hwp','.hwpx') else '엑셀' if ext == '.xlsx' else '미지원', now(), original, work, '처리 중', '', VERSION))
                self.db.execute('INSERT INTO imports VALUES (?,?,?,?,?)', (identifier(), fid, path.name, now(), '신규'))
            self.reprocess(fid)
        except Exception:
            # 기록되지 않은 사본만 제거한다. 정상 기록과 이전 결과는 보존한다.
            if not self.db.execute('SELECT 1 FROM files WHERE id=?', (fid,)).fetchone():
                for p in (self.root / original, self.root / work):
                    if p.exists():
                        p.chmod(0o600)
                        p.unlink()
            raise
        return dict(self.db.execute('SELECT * FROM files WHERE id=?', (fid,)).fetchone())

    def reprocess(self, fid):
        f = self.db.execute('SELECT * FROM files WHERE id=?', (fid,)).fetchone()
        if f is None or digest(self.root / f['original']) != f['hash']:
            raise SafeError('원본 사본의 해시가 다릅니다. 백업을 확인하세요.')
        shutil.copyfile(self.root / f['original'], self.root / f['work'])
        try:
            worker_python = str(Path(sys.executable).with_name('python.exe')) if Path(sys.executable).name.lower() == 'pythonw.exe' else sys.executable
            completed = subprocess.run([worker_python, '-E', '-s', '-m', 'budget_offline.worker'],
                input=canonical({'path': str(self.root / f['work']), 'rules': self.rules}),
                encoding='utf-8', stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=Path(__file__).resolve().parent.parent, timeout=30,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if completed.returncode != 0 or len(completed.stdout) > 20 * 1024 * 1024:
                raise SafeError('읽기 프로세스 실패 또는 결과 크기 제한')
            result = json.loads(completed.stdout)
        except Exception as e:
            result = {'status': '처리 실패', 'reason': '처리 시간 30초 초과' if isinstance(e, subprocess.TimeoutExpired) else f'읽기 프로세스 오류 ({type(e).__name__})', 'observations': []}
        with self.db:
            old = self.db.execute('SELECT COUNT(*) FROM obs WHERE file_id=?', (fid,)).fetchone()[0]
            self.db.execute('UPDATE obs SET active=0, revision=revision+1 WHERE file_id=?', (fid,))
            for o in result['observations']:
                self.db.execute('INSERT INTO obs(id,file_id,raw,unit,key_json,location,context,flags,method) VALUES (?,?,?,?,?,?,?,?,?)',
                    (identifier(), fid, o['raw'], o['unit'], canonical(o['key']), o['location'], o['context'], canonical(o['flags']), o['method']))
            self.db.execute('UPDATE files SET status=?,reason=?,extractor=? WHERE id=?', (result['status'], result['reason'], VERSION, fid))
            self.audit('파일 추출', {'file_id': fid, 'status': result['status'], 'new_count': len(result['observations']), 'previous_count': old, 'rules': self.rules['version']})
        self.comparisons()

    def confirm_mapping(self, oid, key, unit, reviewer, reason):
        if not key_complete(key) or not reviewer.strip() or not reason.strip():
            raise SafeError('업무 키 8개, 검토자, 이유를 모두 입력하세요. 없는 차원은 명시적으로 전체를 사용하세요.')
        with self.db:
            old = self.db.execute('SELECT * FROM obs WHERE id=?', (oid,)).fetchone()
            if not old:
                raise SafeError('근거를 찾을 수 없습니다.')
            self.db.execute('UPDATE obs SET key_json=?, unit=?, confirmed=1, revision=revision+1 WHERE id=?', (canonical(key), unit, oid))
            self.audit('연결 확인', {'id': oid, 'old_key': json.loads(old['key_json']), 'old_unit': old['unit'], 'key': key, 'unit': unit, 'reviewer': reviewer, 'reason': reason})
        self.comparisons()

    def manual_evidence(self, parent_id, raw, unit, key, reviewer, reason):
        parent = self.db.execute('SELECT * FROM obs WHERE id=?', (parent_id,)).fetchone()
        if not parent or not raw.strip() or raw not in parent['raw']:
            raise SafeError('수동 값은 선택한 원문 문자열에 실제로 있는 부분을 입력해야 합니다. 추정·정정값 입력은 지원하지 않습니다.')
        if any(s in parent['flags'] for s in ('수식', '외부 링크', '엑셀 오류')):
            raise SafeError('수식·외부 참조·오류 셀은 수동 확인으로 우회할 수 없습니다. 정정된 값 자료를 새로 받으세요.')
        if any(s in parent['raw'] for s in ('약', '내외', '이상', '이하', '≈', '△', '▲')):
            raise SafeError('근사값·감액 표기는 부분 선택으로 제거할 수 없습니다. 승인된 규칙 또는 정정자료가 필요합니다.')
        if not re.search(r'(?<![\d.,])' + re.escape(raw) + r'(?![\d.,])', parent['raw']):
            raise SafeError('숫자의 일부 자릿수만 잘라서 선택할 수 없습니다.')
        if parent['method']=='XLSX XML 저장값' and raw != parent['raw']:
            raise SafeError('엑셀 셀 저장값 전체를 확인해야 합니다. 부분 숫자는 허용하지 않습니다.')
        if not key_complete(key) or not reviewer.strip() or not reason.strip():
            raise SafeError('업무 키, 검토자, 원문 확인 이유가 필요합니다.')
        oid = identifier()
        with self.db:
            self.db.execute('INSERT INTO obs(id,file_id,raw,unit,key_json,location,context,flags,method,confirmed,parent) VALUES (?,?,?,?,?,?,?,?,?,1,?)',
                (oid, parent['file_id'], raw, unit, canonical(key), parent['location'], parent['context'], '[]', '사람이 원문을 확인하여 부분 선택', parent_id))
            self.db.execute('UPDATE obs SET active=0,revision=revision+1 WHERE id=?', (parent_id,))
            self.audit('수동 근거 확인', {'id': oid, 'parent': parent_id, 'raw': raw, 'key': key, 'unit': unit, 'reviewer': reviewer, 'reason': reason})
        self.comparisons()
        return oid

    def set_active(self, oid, active, reviewer, reason):
        if not reviewer.strip() or not reason.strip():
            raise SafeError('채택·제외 이유와 검토자를 입력하세요.')
        with self.db:
            self.db.execute('UPDATE obs SET active=?,revision=revision+1 WHERE id=?', (int(active), oid))
            self.audit('근거 채택/제외', {'id': oid, 'active': active, 'reviewer': reviewer, 'reason': reason})
        self.comparisons()

    def exclude_file(self, fid, excluded, reviewer, reason):
        if not reviewer.strip() or not reason.strip():
            raise SafeError('파일 제외·복원 이유와 검토자를 입력하세요.')
        with self.db:
            self.db.execute('UPDATE files SET excluded=? WHERE id=?', (int(excluded), fid))
            self.audit('파일 제외/복원', {'id': fid, 'excluded': excluded, 'reviewer': reviewer, 'reason': reason})
        self.comparisons()

    def integrity(self):
        issues = []
        for f in self.files():
            p = self.root / f['original']
            if not p.is_file() or p.is_symlink() or digest(p) != f['hash']:
                issues.append(f['id'])
        return issues

    def comparisons(self):
        observations = self.observations()
        broken = set(self.integrity())
        groups = {}
        for o in observations:
            if key_complete(o['key']):
                groups.setdefault(key_id(o['key']), {'key': o['key'], 'all': []})['all'].append(o)
        for r in self.db.execute('SELECT * FROM expected'):
            groups.setdefault(r['key_id'], {'key': json.loads(r['key_json']), 'all': []})
        decisions = {r['key_id']: dict(r) for r in self.db.execute('SELECT * FROM decisions')}
        result = []
        for kid, g in groups.items():
            obs = [o for o in g['all'] if o['active'] and not o['file_excluded']]
            norm = [o['normalized'] for o in obs]
            roles = {role: [o for o in obs if o['role'] == role] for role in ('한글','엑셀')}
            status, reason = '누락', '한글과 엑셀 근거가 각각 필요합니다.'
            if any(o['file_id'] in broken for o in g['all']):
                status, reason = '추출 실패', '원본 사본 해시 불일치'
            elif any(not o['confirmed'] for o in obs):
                status, reason = '연결 불명', '사람이 업무 키·단위를 확인해야 합니다.'
            elif any(o['flags'] for o in obs):
                status, reason = '추출 실패', ' / '.join(sorted({f for o in obs for f in o['flags']}))
            elif any(len(v) > 1 for v in roles.values()):
                status, reason = '중복·수정본 확인 필요', '같은 출처 종류에 여러 근거가 있습니다. 채택 근거를 직접 선택하세요.'
            elif len(obs) == 2 and all(len(v) == 1 for v in roles.values()):
                if any(n['state'] != '숫자' for n in norm):
                    states = [n['state'] for n in norm if n['state'] != '숫자']
                    status = '단위 불명' if any('단위' in s for s in states) else '표시 정밀도 확인 필요' if '표시 정밀도 확인 필요' in states else '누락'
                    reason = ' / '.join(states)
                elif norm[0]['base_unit'] != norm[1]['base_unit']:
                    status, reason = '단위 불명', '단위의 의미가 서로 다릅니다.'
                elif Decimal(norm[0]['value']) != Decimal(norm[1]['value']):
                    with localcontext() as ctx:
                        ctx.prec = 100
                        difference = Decimal(norm[0]['value']) - Decimal(norm[1]['value'])
                    status, reason = '불일치', '표준값 차이: ' + str(difference)
                else:
                    status = '정확 일치' if norm[0]['unit'] == norm[1]['unit'] else '변환 후 정확 일치'
                    reason = '필수 키 동일, 명시된 단위로 정확한 십진수 비교. 사람 승인 필요.'
            fingerprint = hashlib.sha256(canonical({'rules': self.rules, 'all': [(o['id'], o['revision'], o['active'], o['file_excluded'], o['hash']) for o in g['all']], 'status': status}).encode()).hexdigest()
            decision = decisions.get(kid, {})
            state = decision.get('state', '미검토')
            if decision and decision['fingerprint'] != fingerprint and state != '재검토 필요':
                state = '재검토 필요'
                with self.db:
                    self.db.execute('UPDATE decisions SET state=? WHERE key_id=?', (state, kid))
                    self.audit('승인/검토 무효화', {'key': kid, 'previous_state': decision['state'], 'reason': '근거·연결·규칙·판정 변경'})
            result.append({'id': kid, 'key': g['key'], 'observations': obs, 'status': status, 'reason': reason,
                           'value': norm[0]['value'] if status in PASS else None,
                           'unit': norm[0]['base_unit'] if status in PASS else None,
                           'fingerprint': fingerprint, 'approval': state, 'reviewer': decision.get('reviewer',''),
                           'review_reason': decision.get('reason',''), 'approved_at': decision.get('time','')})
        return sorted(result, key=lambda x: canonical(x['key']))

    def review(self, kid, state, reviewer, reason):
        if state not in ('검토 중', '승인', '보류', '제외') or not reviewer.strip() or not reason.strip():
            raise SafeError('검토 상태, 검토자, 이유를 입력하세요.')
        item = next((c for c in self.comparisons() if c['id'] == kid), None)
        if not item:
            raise SafeError('비교 항목이 없습니다.')
        if state == '승인' and item['status'] not in PASS:
            raise SafeError('필수 검증을 통과한 항목만 승인할 수 있습니다.')
        with self.db:
            self.db.execute('INSERT OR REPLACE INTO decisions VALUES (?,?,?,?,?,?)',
                (kid, item['fingerprint'], state, reviewer, reason, now()))
            self.audit('사용자 검토', {'key': kid, 'state': state, 'reviewer': reviewer, 'reason': reason, 'fingerprint': item['fingerprint'], 'rules': self.rules['version']})

    def set_expectations(self, keys, departments, reviewer):
        if not reviewer.strip() or not all(key_complete(k) for k in keys):
            raise SafeError('기대 업무 키 또는 담당자 형식이 잘못되었습니다.')
        if len({key_id(k) for k in keys}) != len(keys):
            raise SafeError('필수 항목 목록에 중복 업무 키가 있습니다.')
        with self.db:
            self.db.execute('DELETE FROM expected')
            self.db.execute('DELETE FROM departments')
            self.db.executemany('INSERT INTO expected VALUES (?,?)', [(key_id(k),canonical(k)) for k in keys])
            self.db.executemany('INSERT INTO departments VALUES (?,?)', [(d['code'],d['name']) for d in departments])
            self.audit('필수 목록 변경', {'keys': keys, 'departments': departments, 'reviewer': reviewer})

    def update_rules(self, rules, reviewer, reason):
        validate_rules(rules)
        if not reviewer.strip() or not reason.strip() or rules['version'] == self.rules['version']:
            raise SafeError('새 규칙 버전 이름, 검토자, 변경 이유가 필요합니다.')
        with self.db:
            self.audit('규칙 변경', {'old': self.rules, 'new': rules, 'reviewer': reviewer, 'reason': reason})
            self.db.execute("UPDATE meta SET value=? WHERE key='rules'", (canonical(rules),))
        self.comparisons()

    def summary(self):
        comparisons = self.comparisons()
        files = self.files()
        observations = self.observations()
        return {'프로젝트': self.meta('name'), '가져오기 횟수': self.db.execute('SELECT COUNT(*) FROM imports').fetchone()[0],
                '원본 파일': len(files), '처리 성공': sum(f['status']=='처리 성공' for f in files),
                '처리 실패': sum(f['status']=='처리 실패' for f in files), '미지원': sum(f['status']=='미지원' for f in files),
                '파일 제외': sum(bool(f['excluded']) for f in files), '추출 근거': len(observations),
                '연결 미확인': sum(not o['confirmed'] and o['active'] and not o['file_excluded'] for o in observations),
                '업무 키': len(comparisons), '확정 가능': sum(c['status'] in PASS for c in comparisons),
                '승인': sum(c['approval']=='승인' for c in comparisons), '누락': sum(c['status']=='누락' for c in comparisons),
                '불일치': sum(c['status']=='불일치' for c in comparisons), '등록 부서': self.db.execute('SELECT COUNT(*) FROM departments').fetchone()[0],
                '출력 성공': self.db.execute("SELECT COUNT(*) FROM outputs WHERE state='반영 완료'").fetchone()[0], '규칙': self.rules['version']}
