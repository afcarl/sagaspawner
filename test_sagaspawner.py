import sagaspawner
import sys
import time
from jupyterhub.tests.conftest import *
from jupyterhub import orm

_echo_sleep = """
import sys, time
print(sys.argv)
time.sleep(30)
"""

def new_spawner(db, **kwargs):
    kwargs.setdefault('cmd', [sys.executable, '-c', _echo_sleep])
    kwargs.setdefault('user', db.query(orm.User).first())
    kwargs.setdefault('hub', db.query(orm.Hub).first())
    kwargs.setdefault('INTERRUPT_TIMEOUT', 2)
    kwargs.setdefault('TERM_TIMEOUT', 1)
    kwargs.setdefault('KILL_TIMEOUT', 1)
    return sagaspawner.SagaSpawner(**kwargs)

s = new_spawner(db())

fut = s.start()

time.sleep(1)

print fut.result()
