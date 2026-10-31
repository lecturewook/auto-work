"""Python 수준의 추가 방어. OS 방화벽·물리 망분리를 대신하지 않는다."""
import sys


def deny_network(event, args):
    if event.startswith('socket.'):
        raise PermissionError('OFFLINE_POLICY: Python 네트워크 기능 사용 차단')


sys.addaudithook(deny_network)
