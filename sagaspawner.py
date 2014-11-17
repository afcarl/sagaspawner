"""
A Spawner for JupyterHub that runs each user's server in a separate docker container
"""
import itertools
import os
from textwrap import dedent
from concurrent.futures import ThreadPoolExecutor

import docker
from tornado import gen

from jupyterhub.spawner import Spawner
from IPython.config import LoggingConfigurable
from IPython.utils.traitlets import (
    Any, Bool, Dict, Enum, Instance, Integer, List, Unicode,
)

import pwd

import saga
from jupyterhub.utils import random_port

class SagaSpawner(Spawner):
    """A Spawner that uses Saga to spawn notebooks on PBS or similar queue systems."""
    
    INTERRUPT_TIMEOUT = Integer(10, config=True,
        help="Seconds to wait for process to halt after SIGINT before proceeding to SIGTERM"
    )
    TERM_TIMEOUT = Integer(5, config=True,
        help="Seconds to wait for process to halt after SIGTERM before proceeding to SIGKILL"
    )
    KILL_TIMEOUT = Integer(5, config=True,
        help="Seconds to wait for process to halt after SIGKILL before giving up"
    )
    
    pid = Integer()
    sudo_args = List(['-n'], config=True,
        help="""arguments to be passed to sudo (in addition to -u [username])

        only used if set_user = sudo
        """
    )

    set_user = Enum(['sudo', 'setuid'], default_value='setuid', config=True,
        help="""scheme for setting the user of the spawned process

        'sudo' can be more prudently restricted,
        but 'setuid' is simpler for a server run as root
        """
    )
    def _set_user_changed(self, name, old, new):
        if new == 'sudo':
            self.make_preexec_fn = set_user_sudo
        elif new == 'setuid':
            self.make_preexec_fn = set_user_setuid
        else:
            raise ValueError("This should be impossible")
    
    def load_state(self, state):
        super(LocalProcessSpawner, self).load_state(state)
        self.pid = state['pid']
    
    def get_state(self):
        state = super(LocalProcessSpawner, self).get_state()
        state['pid'] = self.pid
        return state
    
    def sudo_cmd(self, user):
        return ['sudo', '-u', user.name] + self.sudo_args
    
    @gen.coroutine
    def start(self):
        """Start the process"""
        #self.user.server.port = random_port()
        cmd = []
        #env = self.user_env(self.env)
        
        cmd.extend(self.cmd)
        cmd.extend(self.get_args())
        
        self.log.info("Spawning %r", cmd)

        ctx = saga.Context("ssh")

        session = saga.Session()
        session.add_context(ctx)

        js = saga.job.Service("pbs+ssh://gordon.sdsc.edu", session=session)
        jd = saga.job.Description()

        jd.environment     = {'MYOUTPUT': '"Hello from SAGA"'}
        jd.executable      = cmd[0]
        jd.arguments       = cmd[1:]
        jd.output          = "mysagajob.stdout"
        jd.error           = "mysagajob.stderr"
        jd.wall_time_limit   = 5 

        self.job = js.create_job(jd)
        self.job.run()

        #self.start_polling()
    @gen.coroutine
    def poll(self):
        """Poll the process"""
        # if we started the process, poll with Popen
        if self.proc is not None:
            raise gen.Return(self.proc.poll())
        
        # if we resumed from stored state,
        # we don't have the Popen handle anymore
        
        # this doesn't work on Windows, but that's okay because we don't support Windows.
        try:
            os.kill(self.pid, 0)
        except OSError as e:
            if e.errno == errno.ESRCH:
                # no such process, return exitcode == 0, since we don't know the exit status
                raise gen.Return(0)
        else:
            # None indicates the process is running
            raise gen.Return(None)
    
    @gen.coroutine
    def _wait_for_death(self, timeout=10):
        """wait for the process to die, up to timeout seconds"""
        for i in range(int(timeout * 10)):
            status = yield self.poll()
            if status is not None:
                break
            else:
                loop = IOLoop.current()
                yield gen.Task(loop.add_timeout, loop.time() + 0.1)
    
    @gen.coroutine
    def stop(self, now=False):
        """stop the subprocess
        
        if `now`, skip waiting for clean shutdown
        """
        self.stop_polling()
        if not now:
            # SIGINT to request clean shutdown
            self.log.debug("Interrupting %i", self.pid)
            try:
                os.kill(self.pid, signal.SIGINT)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    return
            
            yield self._wait_for_death(self.INTERRUPT_TIMEOUT)
        
        # clean shutdown failed, use TERM
        status = yield self.poll()
        if status is None:
            self.log.debug("Terminating %i", self.pid)
            try:
                os.kill(self.pid, signal.SIGTERM)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    return
            yield self._wait_for_death(self.TERM_TIMEOUT)
        
        # TERM failed, use KILL
        status = yield self.poll()
        if status is None:
            self.log.debug("Killing %i", self.pid)
            try:
                os.kill(self.pid, signal.SIGKILL)
            except OSError as e:
                if e.errno == errno.ESRCH:
                    return
            yield self._wait_for_death(self.KILL_TIMEOUT)

        status = yield self.poll()
        if status is None:
            # it all failed, zombie process
            self.log.warn("Process %i never died", self.pid)
