#!/usr/bin/env python

# this is mostly for testing that the examples run without errors
#
# To use this script:
#
#  0. change to this directory
#  1. be in an activated Python2 virtual-env with crossbar installed
#  2. pip install colorama
#  3. have a virtualenv called ./venv-py3 using a Python3
#     interpreter with crossbar (or just Autobahn) installed.
#
# ...then just run this script; it colors the output and runs each
# frontend/backend pair for a few seconds.

import sys
import platform
from os import environ
from os.path import join, exists

import colorama
from colorama import Fore

from twisted.internet.protocol import ProcessProtocol
from twisted.internet.defer import inlineCallbacks, Deferred
from twisted.internet.error import ProcessExitedAlready
from twisted.internet import reactor
from twisted.internet.task import react

from autobahn.twisted.util import sleep


class CrossbarProcessProtocol(ProcessProtocol):
    """
    A helper to talk to a crossbar instance we've launched.
    """

    def __init__(self, all_done, launched, color=None, prefix=''):
        """
        :param all_done: Deferred that gets callback() when our process exits (.errback if it exits non-zero)
        :param launched: Deferred that gets callback() when our process starts.
        """
        self.all_done = all_done
        self.launched = launched
        self.color = color or ''
        self.prefix = prefix
        self._out = ''
        self._err = ''

    def connectionMade(self):
        """ProcessProtocol override"""
        if not self.launched.called:
            self.launched.callback(self)

    def outReceived(self, data):
        """ProcessProtocol override"""
        self._out += data.decode('utf8')
        while '\n' in self._out:
            idx = self._out.find('\n')
            line = self._out[:idx]
            self._out = self._out[idx + 1:]
            sys.stdout.write(self.prefix + self.color + line + Fore.RESET + '\n')

    def errReceived(self, data):
        """ProcessProtocol override"""
        self._err += data.decode('utf8')
        while '\n' in self._err:
            idx = self._err.find('\n')
            line = self._err[:idx]
            self._err = self._err[idx + 1:]
            sys.stderr.write(self.prefix + self.color + line + Fore.RESET + '\n')

    def processEnded(self, reason):
        """IProcessProtocol API"""
        # reason.value should always be a ProcessTerminated instance
        fail = reason.value
        # print('processEnded', fail)

        if fail.exitCode != 0 and fail.exitCode is not None:
            msg = 'Process exited with code "{}".'.format(fail.exitCode)
            err = RuntimeError(msg)
            self.all_done.errback(err)
            if not self.launched.called:
                self.launched.errback(err)
        else:
            self.all_done.callback(fail)
            if not self.launched.called:
                print("FIXME: _launched should have been callbacked by now.")
                self.launched.callback(self)


@inlineCallbacks
def start_crossbar():
    finished = Deferred()
    launched = Deferred()
    protocol = CrossbarProcessProtocol(finished, launched, Fore.YELLOW)
    exe = 'crossbar'
    args = [exe, 'start', '--cbdir', './router/.crossbar']

    env = environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    reactor.spawnProcess(protocol, exe, args, path='.', env=env)

    yield launched
    if platform.python_implementation() == 'PyPy':
        DELAY = 10.
    else:
        DELAY = 2.
    yield sleep(DELAY)
    return protocol


@inlineCallbacks
def start_example(py_fname, color, prefix='', exe=sys.executable):
    finished = Deferred()
    launched = Deferred()
    protocol = CrossbarProcessProtocol(finished, launched, color, prefix)
    args = [exe, py_fname]

    env = environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    reactor.spawnProcess(protocol, exe, args, path='.', env=env)

    yield launched
    return protocol


def print_banner(title):
    print('-' * 80)
    print(title)
    print('-' * 80)
    print()


@inlineCallbacks
def main(reactor):
    colorama.init()
    examples = [
        './twisted/wamp/overview',

        './twisted/wamp/pubsub/basic/',
        './twisted/wamp/pubsub/complex/',
        './twisted/wamp/pubsub/decorators/',
        './twisted/wamp/pubsub/options/',
        './twisted/wamp/pubsub/tls/',
        './twisted/wamp/pubsub/unsubscribe/',

        './twisted/wamp/rpc/timeservice/',
        './twisted/wamp/rpc/slowsquare/',
        './twisted/wamp/rpc/progress/',
        './twisted/wamp/rpc/options/',
        './twisted/wamp/rpc/errors/',
        './twisted/wamp/rpc/decorators/',
        './twisted/wamp/rpc/complex/',
        './twisted/wamp/rpc/arguments/',

        'py3 ./asyncio/wamp/overview',

        'py3 ./asyncio/wamp/pubsub/unsubscribe/',
        'py3 ./asyncio/wamp/pubsub/tls/',
        'py3 ./asyncio/wamp/pubsub/options/',
        'py3 ./asyncio/wamp/pubsub/decorators/',
        'py3 ./asyncio/wamp/pubsub/complex/',
        'py3 ./asyncio/wamp/pubsub/basic/',

        'py3 ./asyncio/wamp/rpc/timeservice/',
        'py3 ./asyncio/wamp/rpc/slowsquare/',
        'py3 ./asyncio/wamp/rpc/progress/',
        'py3 ./asyncio/wamp/rpc/options/',
        'py3 ./asyncio/wamp/rpc/errors/',
        'py3 ./asyncio/wamp/rpc/decorators/',
        'py3 ./asyncio/wamp/rpc/complex/',
        'py3 ./asyncio/wamp/rpc/arguments/',

    ]

    print_banner("Running crossbar.io instance")
    cb_proto = yield start_crossbar()
    yield sleep(2)  # wait for sockets to be listening
    if cb_proto.all_done.called:
        raise RuntimeError("crossbar exited already")

    success = True
    for exdir in examples:
        py = sys.executable
        if exdir.startswith('py3 '):
            exdir = exdir[4:]
            if sys.version_info.major < 3:
                print("don't have python3, skipping:", exdir)
                continue
        frontend = join(exdir, 'frontend.py')
        backend = join(exdir, 'backend.py')
        if not exists(frontend) or not exists(backend):
            print("skipping:", exdir, exists(frontend), exists(backend))
            continue

        print_banner("Running example: " + exdir)
        print("  starting backend")
        back_proto = yield start_example(backend, Fore.GREEN, ' backend: ', exe=py)
        yield sleep(1)
        print("  starting frontend")
        front_proto = yield start_example(frontend, Fore.BLUE, 'frontend: ', exe=py)
        yield sleep(3)

        for p in [back_proto, front_proto]:
            try:
                if p.all_done.called:
                    yield p.all_done
            except Exception as e:
                print("FAILED:", e)
                success = False

        for p in [front_proto, back_proto]:
            try:
                p.transport.signalProcess('KILL')
            except ProcessExitedAlready:
                pass

        if not success:
            break
        yield sleep(1)

    print("Killing crossbar")
    try:
        cb_proto.transport.signalProcess('KILL')
        yield cb_proto.all_done
    except:
        pass
    if success:
        print()
        print("Success!")
        print("  ...all the examples neither crashed nor burned...")
        return 0
    return 5


if __name__ == '__main__':
    sys.exit(react(main))
