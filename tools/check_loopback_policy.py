"""Check actual socket policy in a fresh process; no external packets are sent."""
import socket
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from budget_offline import offline

offline.enable_loopback_listener()
listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
listener.bind(('127.0.0.1', 0))
listener.listen(1)
blocked = 0
for operation in [lambda: listener.connect(('203.0.113.1',443)),
                  lambda: listener.connect(('127.0.0.1',listener.getsockname()[1])),
                  lambda: socket.getaddrinfo('example.invalid',443),
                  lambda: socket.socket(socket.AF_INET,socket.SOCK_STREAM),
                  lambda: listener.bind(('0.0.0.0',0)),
                  lambda: socket.socket(socket.AF_INET6,socket.SOCK_STREAM)]:
    try:
        operation();raise AssertionError('forbidden socket operation allowed')
    except PermissionError:
        blocked += 1
listener.close()
assert blocked == 6
print('PASS: one loopback listener; outbound, DNS, additional socket, wildcard bind and IPv6 denied (6 checks)')
