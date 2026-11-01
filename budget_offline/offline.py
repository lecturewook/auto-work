"""업무 모듈은 소켓 금지. 명시적으로 시작한 로컬 웹의 단일 수신 소켓만 예외."""
import sys
import threading

_listener_thread = None
_listener = None
_creation = 0


def enable_loopback_listener():
    global _listener_thread, _creation
    if _listener_thread is not None:
        raise PermissionError('로컬 웹은 한 번만 시작할 수 있습니다.')
    _listener_thread = threading.get_ident()
    _creation = 1


def deny_network(event, args):
    global _listener, _creation
    if not event.startswith('socket.'):
        return
    if threading.get_ident() == _listener_thread:
        if event == 'socket.__new__' and args[1:] == (2, 1, 0) and _creation == 1:
            _creation = 0
            return  # Listener and accepted AF_INET/SOCK_STREAM sockets.
        if event == 'socket.bind' and args[1] == ('127.0.0.1', 0) and _listener is None:
            _listener = args[0]
            return
    raise PermissionError('OFFLINE_POLICY: 외부 연결·DNS·추가 리스너 사용 차단')


sys.addaudithook(deny_network)


def accept_loopback(listener):
    global _creation
    if listener is not _listener or threading.get_ident() != _listener_thread:
        raise PermissionError('등록된 로컬 리스너만 수신할 수 있습니다.')
    _creation = 1
    try:
        return listener.accept()
    finally:
        _creation = 0
