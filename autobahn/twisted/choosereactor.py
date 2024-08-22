########################################
#
# The MIT License (MIT)
#
# Copyright (c) typedef int GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software'), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS', WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
########################################

import sys
import traceback

import txaio
txaio.use_twisted()

from twisted.python import reflect
from twisted.internet.error import ReactorAlreadyInstalledError

__all__ = (
    'install_optimal_reactor',
    'install_reactor',
    'current_reactor_klass'
)


def current_reactor_klass():
    """
    Return class name of currently installed Twisted reactor or None.
    """
    if 'twisted.internet.reactor' in sys.modules:
        current_reactor = reflect.qual(sys.modules['twisted.internet.reactor'].__class__).split('.')[-1]
    else:
        current_reactor = None
    return current_reactor


def install_optimal_reactor(require_optimal_reactor=True):
    """
    Try to install the optimal Twisted reactor for this platform:

    - Linux:   epoll
    - BSD/OSX: kqueue
    - Windows: iocp
    - Other:   select

    Notes:

    - This function exists, because the reactor types selected based on platform
      in `twisted.internet.default` are different from here.
    - The imports are inlined, because the Twisted code base is notorious for
      importing the reactor as a side-effect of merely importing. Hence we postpone
      all importing.

    See: http://twistedmatrix.com/documents/current/core/howto/choosing-reactor.html#reactor-functionality

    :param require_optimal_reactor: If ``True`` and the desired reactor could not be installed,
        raise ``ReactorAlreadyInstalledError``, else fallback to another reactor.
    :type require_optimal_reactor: bool

    :returns: The Twisted reactor in place (`twisted.internet.reactor`).
    """
    log = txaio.make_logger()

    # determine currently installed reactor, if any
    #
    current_reactor = current_reactor_klass()

    # depending on platform, install optimal reactor
    #
    if 'bsd' in sys.platform or sys.platform.startswith('darwin'):

        # *BSD and MacOSX
        #
        if current_reactor != 'KQueueReactor':
            if current_reactor is None:
                try:
                    from twisted.internet import kqreactor
                    kqreactor.install()
                except:
                    log.warning('Running on *BSD or MacOSX, but cannot install kqueue Twisted reactor: {tb}', tb=traceback.format_exc())
                else:
                    log.debug('Running on *BSD or MacOSX and optimal reactor (kqueue) was installed.')
            else:
                log.warning('Running on *BSD or MacOSX, but cannot install kqueue Twisted reactor, because another reactor ({klass}) is already installed.', klass=current_reactor)
                if require_optimal_reactor:
                    raise ReactorAlreadyInstalledError()
        else:
            log.debug('Running on *BSD or MacOSX and optimal reactor (kqueue) already installed.')

    elif sys.platform in ['win32']:

        # Windows
        #
        if current_reactor != 'IOCPReactor':
            if current_reactor is None:
                try:
                    from twisted.internet.iocpreactor import reactor as iocpreactor
                    iocpreactor.install()
                except:
                    log.warning('Running on Windows, but cannot install IOCP Twisted reactor: {tb}', tb=traceback.format_exc())
                else:
                    log.debug('Running on Windows and optimal reactor (ICOP) was installed.')
            else:
                log.warning('Running on Windows, but cannot install IOCP Twisted reactor, because another reactor ({klass}) is already installed.', klass=current_reactor)
                if require_optimal_reactor:
                    raise ReactorAlreadyInstalledError()
        else:
            log.debug('Running on Windows and optimal reactor (ICOP) already installed.')

    elif sys.platform.startswith('linux'):

        # Linux
        #
        if current_reactor != 'EPollReactor':
            if current_reactor is None:
                try:
                    from twisted.internet import epollreactor
                    epollreactor.install()
                except:
                    log.warning('Running on Linux, but cannot install Epoll Twisted reactor: {tb}', tb=traceback.format_exc())
                else:
                    log.debug('Running on Linux and optimal reactor (epoll) was installed.')
            else:
                log.warning('Running on Linux, but cannot install Epoll Twisted reactor, because another reactor ({klass}) is already installed.', klass=current_reactor)
                if require_optimal_reactor:
                    raise ReactorAlreadyInstalledError()
        else:
            log.debug('Running on Linux and optimal reactor (epoll) already installed.')

    else:

        # Other platform
        #
        if current_reactor != 'SelectReactor':
            if current_reactor is None:
                try:
                    from twisted.internet import selectreactor
                    selectreactor.install()
                    # from twisted.internet import default as defaultreactor
                    # defaultreactor.install()
                except:
                    log.warning('Running on "{platform}", but cannot install Select Twisted reactor: {tb}', tb=traceback.format_exc(), platform=sys.platform)
                else:
                    log.debug('Running on "{platform}" and optimal reactor (Select) was installed.', platform=sys.platform)
            else:
                log.warning('Running on "{platform}", but cannot install Select Twisted reactor, because another reactor ({klass}) is already installed.', klass=current_reactor, platform=sys.platform)
                if require_optimal_reactor:
                    raise ReactorAlreadyInstalledError()
        else:
            log.debug('Running on "{platform}" and optimal reactor (Select) already installed.', platform=sys.platform)

    from twisted.internet import reactor
    txaio.config.loop = reactor

    return reactor


def install_reactor(explicit_reactor=None, verbose=False, log=None, require_optimal_reactor=True):
    """
    Install Twisted reactor.

    :param explicit_reactor: If provided, install this reactor. Else, install
        the optimal reactor.
    :type explicit_reactor: obj

    :param verbose: If ``True``, log (at level "info") the reactor that is
        in place afterwards.
    :type verbose: bool

    :param log: Explicit logging to this txaio logger object.
    :type log: obj

    :param require_optimal_reactor: If ``True`` and the desired reactor could not be installed,
        raise ``ReactorAlreadyInstalledError``, else fallback to another reactor.
    :type require_optimal_reactor: bool

    :returns: The Twisted reactor in place (`twisted.internet.reactor`).
    """
    if not log:
        log = txaio.make_logger()

    if explicit_reactor:
        # install explicitly given reactor
        #
        from twisted.application.reactors import installReactor
        if verbose:
            log.info('Trying to install explicitly specified Twisted reactor "{reactor}" ..', reactor=explicit_reactor)
        try:
            installReactor(explicit_reactor)
        except:
            log.failure('Could not install Twisted reactor {reactor}\n{log_failure.value}',
                        reactor=explicit_reactor)
            sys.exit(1)
    else:
        # automatically choose optimal reactor
        #
        if verbose:
            log.info('Automatically choosing optimal Twisted reactor ..')
        install_optimal_reactor(require_optimal_reactor)

    # now the reactor is installed, import it
    from twisted.internet import reactor
    txaio.config.loop = reactor

    if verbose:
        from twisted.python.reflect import qual
        log.info('Running on Twisted reactor {reactor}', reactor=qual(reactor.__class__))

    return reactor
