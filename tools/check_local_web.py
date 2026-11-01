"""Real HTTP smoke/security flow. Client never imports business socket policy."""
import hashlib
import http.client
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def run():
    with tempfile.TemporaryDirectory(prefix='budget-web-test-') as temp:
        work = Path(temp)
        server = subprocess.Popen([sys.executable, '-B', str(ROOT/'run_web.py'), '--no-browser'], cwd=ROOT,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        lines = []
        ready = threading.Event()
        def read_ready():
            line = server.stdout.readline()
            lines.append(line)
            ready.set()
        threading.Thread(target=read_ready, daemon=True).start()
        try:
            if not ready.wait(15): raise AssertionError('Server startup timeout')
            line = lines[0]
            if not line.startswith('LOCAL_WEB_READY '):
                raise AssertionError('Startup failure: '+line+server.stderr.read())
            url = urlsplit(line.split(' ', 1)[1].strip())
            token, port = url.fragment, url.port
            passed = []
            def request(path='/api/state', body=None, *, auth=True, host=None, origin=None, raw=False):
                connection = http.client.HTTPConnection('127.0.0.1', port, timeout=90)
                headers = {'Host': host or f'127.0.0.1:{port}'}
                if auth: headers['X-Local-Token'] = token
                if origin: headers['Origin'] = origin
                if body is None: method = 'GET'
                else:
                    method = 'POST'
                    if not raw: body = json.dumps(body).encode();headers['Content-Type'] = 'application/json'
                connection.request(method, path, body=body, headers=headers)
                response = connection.getresponse(); data = response.read(); status = response.status
                headers_out = dict(response.getheaders());connection.close()
                return status, data, headers_out
            def action(data):
                status, body, _ = request('/api/action', data)
                assert status == 200, (status, body)
                return json.loads(body)
            assert request(auth=False)[0] == 403
            assert request(host='attacker.invalid')[0] == 403
            assert request(origin='https://attacker.invalid')[0] == 403
            assert request('/api/action', {'action':'shutdown'}, origin='null')[0] == 403
            passed.append('Unauthenticated / bad Host / cross-origin / opaque-origin denied')
            status, html, headers = request('/', auth=False)
            assert status == 200 and b'app.js' in html
            assert "frame-ancestors 'none'" in headers['Content-Security-Policy']
            assert request('/../../project.db')[0] == 404
            passed.append('HTML/CSP available; traversal denied')
            response = action({'action':'demo', 'path':str(work/'demo')})
            state = response['state']
            assert len(state['files']) == 6 and len(state['observations']) == 24
            assert all(i['approval'] != '승인' for i in state['comparisons'])
            passed.append('3 departments / 6 files / 24 observations / approval not automatic')
            for o in state['observations']:
                state = action({'action':'map','id':o['id'],'key':o['key'],'unit':o['unit'],
                                'reviewer':'가상시험','reason':'가상 정답과 의미·단위 확인'})['state']
            assert len(state['comparisons']) == 12
            for i in state['comparisons']:
                assert i['status'] in ('정확 일치','변환 후 정확 일치'), i
                state = action({'action':'review','id':i['id'],'state':'승인','reviewer':'시험자','reason':'가상 정답 대조'})['state']
            assert all(i['approval'] == '승인' for i in state['comparisons'])
            result = action({'action':'export','mode':'approved'})['result']
            status, content, _ = request('/download/'+result['download'])
            assert status == 200 and content[:2] == b'PK'
            assert hashlib.sha256(content).digest() == hashlib.sha256(Path(result['saved']).read_bytes()).digest()
            assert request('/api/action', {'action':'export','mode':'final'})[0] == 400
            passed.append('Manual mapping / single item approval / approved XLSX download / final blocked')
            source = ROOT/'samples/정상자료'/state['files'][0]['name']
            status, body, _ = request('/api/import?name=renamed'+source.suffix,source.read_bytes(),raw=True)
            assert status == 200 and json.loads(body)['result']['status'] == '재가져오기'
            assert len(json.loads(body)['state']['files']) == 6
            assert request('/api/import?name=../bad.xlsx',b'bad',raw=True)[0] == 400
            passed.append('Renamed identical source not counted twice; unsafe name denied')
            result = action({'action':'backup'})['result']
            archive = result['saved']
            action({'action':'close'})
            response = action({'action':'restore','archive':archive,'path':str(work/'restored')})
            assert len(response['state']['files']) == 6
            assert all(i['approval']=='승인' for i in response['state']['comparisons'])
            assert not action({'action':'integrity'})['result']['broken']
            action({'action':'close'})
            response = action({'action':'open','path':str(work/'restored')})
            assert len(response['state']['observations']) == 24
            passed.append('Backup restore / reopen preserves sources, approvals, integrity')
            action({'action':'shutdown'})
            assert server.wait(timeout=10) == 0
            result = {'tests':passed,'passed':len(passed),'platform':sys.platform,'windows_execution_validated':False}
            print(json.dumps(result, ensure_ascii=False, indent=2))
        finally:
            if server.poll() is None: server.terminate();server.wait(timeout=10)


if __name__ == '__main__': run()
