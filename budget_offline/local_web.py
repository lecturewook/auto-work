"""Single-user HTTP UI, no outbound connections, dependencies or external assets."""
import hmac
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from . import VERSION, offline
from .project import Project
from .outputs import export_workbook
from .backup import backup, restore
from .privileges import require_standard_user
from .safety import SafeError

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 50*1024*1024


class LocalServer(HTTPServer):
    allow_reuse_address = False
    request_queue_size = 8

    def server_bind(self):
        self.socket.bind(self.server_address)  # HTTPServer's getfqdn would use DNS.
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = self.server_address

    def get_request(self):
        conn, address = offline.accept_loopback(self.socket)
        conn.settimeout(10)
        if address[0] != '127.0.0.1':
            conn.close()
            raise OSError('Local access only')
        return conn, address


class Session:
    def __init__(self):
        self.token = secrets.token_urlsafe(32)
        self.project = None
        self.downloads = {}
        self.stop = False
        self.base = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BudgetOfflineWork'

    def need(self):
        if self.project is None:
            raise SafeError('먼저 프로젝트를 만들거나 여세요.')
        return self.project

    def state(self):
        p = self.project
        return {'version': VERSION, 'base': str(self.base), 'project': str(p.root) if p else '',
                'summary': p.summary() if p else {}, 'files': p.files() if p else [],
                'observations': p.observations() if p else [], 'comparisons': p.comparisons() if p else []}

    def downloadable(self, path):
        path = Path(path).absolute()
        if not path.is_file() or path.is_symlink():
            raise SafeError('저장 파일을 확인할 수 없습니다.')
        key = secrets.token_urlsafe(20)
        self.downloads[key] = path
        return {'download': key, 'filename': path.name, 'saved': str(path)}

    def action(self, data):
        action = data.get('action')
        if action in ('create', 'demo', 'open', 'restore'):
            if self.project:
                raise SafeError('현재 프로젝트를 먼저 닫으세요.')
            path = Path(data.get('path', '')).expanduser()
            if not path.is_absolute() or str(path).startswith(('\\\\', '//')):
                raise SafeError('기관이 승인한 PC 내부의 전체 폴더 경로를 입력하세요.')
            if action == 'restore':
                archive = Path(data['archive'])
                if not archive.is_absolute() or str(archive).startswith(('\\\\', '//')):
                    raise SafeError('PC 내부 백업 파일 경로가 필요합니다.')
                restore(archive, path)
            self.project = Project(path, create=action in ('create', 'demo'), name=path.name)
            if action == 'demo':
                required = json.loads((ROOT/'samples/필수항목.json').read_text(encoding='utf-8'))
                self.project.set_expectations(required['keys'], required['departments'], '가상자료 시작')
                results = [self.project.import_file(f) for f in sorted((ROOT/'samples/정상자료').glob('*'))]
                return {'message': '가상 파일 6개를 가져왔습니다. 연결 확인과 승인은 자동으로 하지 않습니다.', 'results': results}
            return {'message': '프로젝트를 열었습니다.'}
        if action == 'close':
            self.need().close(); self.project = None; self.downloads.clear()
            return {'message': '완료된 작업을 저장하고 프로젝트를 닫았습니다.'}
        if action == 'shutdown':
            if self.project: self.project.close(); self.project = None
            self.downloads.clear(); self.stop = True
            return {'message': '프로그램을 종료했습니다. 이 브라우저 탭을 닫으세요.'}
        p = self.need()
        reviewer, reason = data.get('reviewer', ''), data.get('reason', '')
        if action == 'map': p.confirm_mapping(data['id'], data['key'], data['unit'], reviewer, reason)
        elif action == 'manual': p.manual_evidence(data['id'], data['raw'], data['unit'], data['key'], reviewer, reason)
        elif action == 'evidence': p.set_active(data['id'], bool(data['active']), reviewer, reason)
        elif action == 'file': p.exclude_file(data['id'], bool(data['excluded']), reviewer, reason)
        elif action == 'reprocess': p.reprocess(data['id'])
        elif action == 'review': p.review(data['id'], data['state'], reviewer, reason)
        elif action == 'expectations': p.set_expectations(data['keys'], data['departments'], reviewer)
        elif action == 'rules': p.update_rules(data['rules'], reviewer, reason)
        elif action == 'integrity': return {'message': '무결성 확인 결과', 'broken': p.integrity()}
        elif action == 'export': return self.downloadable(export_workbook(p, data['mode']))
        elif action == 'backup':
            # New path outside the project, never overwrite an existing backup.
            directory = p.root.parent/'BudgetOfflineBackups'
            directory.mkdir(exist_ok=True)
            return self.downloadable(backup(p, directory/('backup-'+secrets.token_hex(8)+'.zip')))
        elif action == 'source':
            matches = [f for f in p.files() if f['id'] == data['id']]
            if len(matches) != 1 or p.integrity(): raise SafeError('원본 무결성을 먼저 확인하세요.')
            result = self.downloadable(p.root/matches[0]['original'])
            result['filename'] = matches[0]['name']
            return result
        else: raise SafeError('지원하지 않는 작업입니다.')
        return {'message': '변경을 저장했습니다.'}


class Handler(BaseHTTPRequestHandler):
    server_version = 'BudgetOfflineLocal'
    sys_version = ''
    protocol_version = 'HTTP/1.0'

    def log_message(self, *args):
        pass  # Do not retain filenames, request URLs or session secrets.

    @property
    def session(self): return self.server.session

    def valid_host(self):
        return self.headers.get_all('Host') == [f'127.0.0.1:{self.server.server_port}']

    def authenticated(self):
        token = self.headers.get('X-Local-Token', '')
        origin = self.headers.get('Origin')
        site = self.headers.get('Sec-Fetch-Site', '')
        return (self.valid_host() and hmac.compare_digest(token.encode(), self.session.token.encode())
                and origin in (None, f'http://127.0.0.1:{self.server.server_port}')
                and site in ('', 'none', 'same-origin'))

    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.valid_host(): return self.send(403, {'error': '접속 주소 확인 실패'})
        route = urlsplit(self.path).path
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8')}
        if route in assets:
            name, kind = assets[route]
            return self.send(200, (Path(__file__).parent/'web'/name).read_bytes(), kind)
        if not self.authenticated(): return self.send(403, {'error': '실행 창의 접속 주소로 다시 여세요.'})
        if route == '/api/state': return self.send(200, self.session.state())
        if route.startswith('/download/'):
            path = self.session.downloads.get(route.removeprefix('/download/'))
            if path and path.is_file() and not path.is_symlink():
                return self.send(200, path.read_bytes(), 'application/octet-stream')
        return self.send(404, {'error': '없는 주소입니다.'})

    def do_POST(self):
        if not self.authenticated(): return self.send(403, {'error': '접속 확인 실패'})
        try:
            if self.headers.get('Transfer-Encoding'): raise SafeError('분할 전송은 지원하지 않습니다.')
            size = int(self.headers.get('Content-Length', '-1'))
            limit = MAX_BODY if urlsplit(self.path).path == '/api/import' else 1024*1024
            if not 0 <= size <= limit: return self.send(413, {'error': '파일은 50MiB, 설정은 1MiB까지 가능합니다.'})
            body = self.rfile.read(size)
            if len(body) != size: raise SafeError('파일 전송이 끝나지 않았습니다. 다시 가져오세요.')
            if urlsplit(self.path).path == '/api/import':
                name = parse_qs(urlsplit(self.path).query).get('name', [''])[0]
                if not name or len(name)>240 or any(c in name for c in '\\/:*?"<>|') or name in ('.', '..'):
                    raise SafeError('파일 이름을 확인하세요.')
                if Path(name).suffix.lower() not in ('.hwp', '.hwpx', '.xlsx', '.xls', '.xlsm'):
                    raise SafeError('한글·엑셀 파일만 선택하세요.')
                p = self.session.need()
                with tempfile.TemporaryDirectory(prefix='budget-import-') as td:
                    path = Path(td)/name
                    path.write_bytes(body)
                    result = p.import_file(path)
            elif self.path == '/api/action':
                data = json.loads(body)
                if not isinstance(data, dict): raise SafeError('요청 형식이 잘못됐습니다.')
                result = self.session.action(data)
            else: return self.send(404, {'error': '없는 주소입니다.'})
            return self.send(200, {'result': result, 'state': self.session.state()})
        except (SafeError, ValueError, KeyError, TypeError) as error:
            self.send(400, {'error': str(error)})
        except Exception as error:
            self.send(500, {'error': f'작업 실패 ({type(error).__name__}). 경로 권한·파일 잠금·남은 공간을 확인하세요.'})


def main(open_browser=True):
    require_standard_user()
    offline.enable_loopback_listener()
    server = LocalServer(('127.0.0.1', 0), Handler)
    server.session = Session()
    server.timeout = 1
    url = f'http://127.0.0.1:{server.server_port}/#{server.session.token}'
    print('LOCAL_WEB_READY '+url, flush=True)
    if os.name == 'nt':
        import ctypes
        # Local native window keeps the URL available; no shell commands or downloads.
        if open_browser:
            candidates = [Path(os.environ.get(key, ''))/'Microsoft/Edge/Application/msedge.exe'
                          for key in ('ProgramFiles(x86)', 'ProgramFiles', 'LOCALAPPDATA')]
            edge = next((p for p in candidates if p.is_absolute() and p.is_file()), None)
            if edge: subprocess.Popen([str(edge), '--new-window', url], close_fds=True)
            else: ctypes.windll.user32.MessageBoxW(None, 'Edge 주소창에 아래 주소를 입력하세요.\n'+url, '내 PC 전용 예산 웹', 0x40)
    try:
        while not server.session.stop:
            server.handle_request()
    finally:
        if server.session.project: server.session.project.close()
        server.server_close()
    return 0
