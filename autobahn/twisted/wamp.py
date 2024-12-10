###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) typedef int GmbH
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
###############################################################################

import inspect
import binascii
import random
from typing import Optional, Dict, Any, List, Union

import txaio
from autobahn.websocket.protocol import WebSocketProtocol

txaio.use_twisted()  # noqa

from twisted.internet.defer import inlineCallbacks, succeed, Deferred
from twisted.application import service
from twisted.internet.interfaces import IReactorCore, IStreamClientEndpoint

try:
    from twisted.internet.ssl import CertificateOptions
except ImportError:
    # PyOpenSSL / TLS not available
    CertificateOptions = Any

from autobahn.util import public

from autobahn.websocket.util import parse_url as parse_ws_url
from autobahn.rawsocket.util import parse_url as parse_rs_url

from autobahn.twisted.websocket import WampWebSocketClientFactory
from autobahn.twisted.rawsocket import WampRawSocketClientFactory

from autobahn.websocket.compress import PerMessageDeflateOffer, \
    PerMessageDeflateResponse, PerMessageDeflateResponseAccept

from autobahn.wamp import protocol, auth
from autobahn.wamp.interfaces import ITransportHandler, ISession, IAuthenticator, ISerializer
from autobahn.wamp.types import ComponentConfig

__all__ = [
    'ApplicationSession',
    'ApplicationSessionFactory',
    'ApplicationRunner',
    'Application',
    'Service',

    # new API
    'Session',
    # 'run',  # should probably move this method to here? instead of component
]


@public
class ApplicationSession(protocol.ApplicationSession):
    """
    WAMP application session for Twisted-based applications.

    Implements:

        * :class:`autobahn.wamp.interfaces.ITransportHandler`
        * :class:`autobahn.wamp.interfaces.ISession`
    """

    log = txaio.make_logger()


ITransportHandler.register(ApplicationSession)

# ISession.register collides with the abc.ABCMeta.register method
ISession.abc_register(ApplicationSession)


class ApplicationSessionFactory(protocol.ApplicationSessionFactory):
    """
    WAMP application session factory for Twisted-based applications.
    """

    session: ApplicationSession = ApplicationSession
    """
    The application session class this application session factory will use. Defaults to :class:`autobahn.twisted.wamp.ApplicationSession`.
    """

    log = txaio.make_logger()


@public
class ApplicationRunner(object):
    """
    This class is a convenience tool mainly for development and quick hosting
    of WAMP application components.

    It can host a WAMP application component in a WAMP-over-WebSocket client
    connecting to a WAMP router.
    """

    log = txaio.make_logger()

    def __init__(self,
                 url: str,
                 realm: Optional[str] = None,
                 extra: Optional[Dict[str, Any]] = None,
                 serializers: Optional[List[ISerializer]] = None,
                 ssl: Optional[CertificateOptions] = None,
                 proxy: Optional[Dict[str, Any]] = None,
                 headers: Optional[Dict[str, Any]] = None,
                 websocket_options: Optional[Dict[str, Any]] = None,
                 max_retries: Optional[int] = None,
                 initial_retry_delay: Optional[float] = None,
                 max_retry_delay: Optional[float] = None,
                 retry_delay_growth: Optional[float] = None,
                 retry_delay_jitter: Optional[float] = None):
        """

        :param url: The WebSocket URL of the WAMP router to connect to (e.g. `ws://example.com:8080/mypath`)
        :param realm: The WAMP realm to join the application session to.
        :param extra: Optional extra configuration to forward to the application component.
        :param serializers: A list of WAMP serializers to use (or None for default serializers).
           Serializers must implement :class:`autobahn.wamp.interfaces.ISerializer`.
        :type serializers: list
        :param ssl: (Optional). If specified this should be an
            instance suitable to pass as ``sslContextFactory`` to
            :class:`twisted.internet.endpoints.SSL4ClientEndpoint`` such
            as :class:`twisted.internet.ssl.CertificateOptions`. Leaving
            it as ``None`` will use the result of calling Twisted
            :meth:`twisted.internet.ssl.platformTrust` which tries to use
            your distribution's CA certificates.
        :param proxy: Explicit proxy server to use; a dict with ``host`` and ``port`` keys.
        :param headers: Additional headers to send (only applies to WAMP-over-WebSocket).
        :param websocket_options: Specific WebSocket options to set (only applies to WAMP-over-WebSocket).
            If not provided, conservative and practical default are chosen.
        :param max_retries: Maximum number of reconnection attempts. Unlimited if set to -1.
        :param initial_retry_delay: Initial delay for reconnection attempt in seconds (Default: 1.0s).
        :param max_retry_delay: Maximum delay for reconnection attempts in seconds (Default: 60s).
        :param retry_delay_growth: The growth factor applied to the retry delay between reconnection
            attempts (Default 1.5).
        :param retry_delay_jitter: A 0-argument callable that introduces noise into the
            delay (Default ``random.random``).
        """
        # IMPORTANT: keep this, as it is tested in
        # autobahn.twisted.test.test_tx_application_runner.TestApplicationRunner.test_runner_bad_proxy
        assert (proxy is None or type(proxy) == dict)

        self.url = url
        self.realm = realm
        self.extra = extra or dict()
        self.serializers = serializers
        self.ssl = ssl
        self.proxy = proxy
        self.headers = headers
        self.websocket_options = websocket_options
        self.max_retries = max_retries
        self.initial_retry_delay = initial_retry_delay
        self.max_retry_delay = max_retry_delay
        self.retry_delay_growth = retry_delay_growth
        self.retry_delay_jitter = retry_delay_jitter

        # this if for auto-reconnection when Twisted ClientService is avail
        self._client_service = None
        # total number of successful connections
        self._connect_successes = 0

    @public
    def stop(self):
        """
        Stop reconnecting, if auto-reconnecting was enabled.
        """
        self.log.debug('{klass}.stop()', klass=self.__class__.__name__)

        if self._client_service:
            return self._client_service.stopService()
        else:
            return succeed(None)

    @public
    def run(self, make, start_reactor: bool = True, auto_reconnect: bool = False,
            log_level: str = 'info', endpoint: Optional[IStreamClientEndpoint] = None,
            reactor: Optional[IReactorCore] = None) -> Union[type(None), Deferred]:
        """
        Run the application component.

        :param make: A factory that produces instances of :class:`autobahn.twisted.wamp.ApplicationSession`
           when called with an instance of :class:`autobahn.wamp.types.ComponentConfig`.
        :param start_reactor: When ``True`` (the default) this method starts
           the Twisted reactor and doesn't return until the reactor
           stops. If there are any problems starting the reactor or
           connect()-ing, we stop the reactor and raise the exception
           back to the caller.
        :param auto_reconnect:
        :param log_level:
        :param endpoint:
        :param reactor:
        :return: None is returned, unless you specify
            ``start_reactor=False`` in which case the Deferred that
            connect() returns is returned; this will callback() with
            an IProtocol instance, which will actually be an instance
            of :class:`WampWebSocketClientProtocol`
        """
        self.log.debug('{klass}.run()', klass=self.__class__.__name__)

        if start_reactor:
            # only select framework, set loop and start logging when we are asked
            # start the reactor - otherwise we are running in a program that likely
            # already tool care of all this.
            from twisted.internet import reactor
            txaio.use_twisted()
            txaio.config.loop = reactor
            txaio.start_logging(level=log_level)

        if callable(make):
            # factory for use ApplicationSession
            def create():
                cfg = ComponentConfig(self.realm, self.extra, runner=self)
                try:
                    session = make(cfg)
                except Exception:
                    self.log.failure('ApplicationSession could not be instantiated: {log_failure.value}')
                    if start_reactor and reactor.running:
                        reactor.stop()
                    raise
                else:
                    return session
        else:
            create = make

        if self.url.startswith('rs'):
            # try to parse RawSocket URL
            isSecure, host, port = parse_rs_url(self.url)

            # use the first configured serializer if any (which means, auto-choose "best")
            serializer = self.serializers[0] if self.serializers else None

            # create a WAMP-over-RawSocket transport client factory
            transport_factory = WampRawSocketClientFactory(create, serializer=serializer)

        else:
            # try to parse WebSocket URL
            isSecure, host, port, resource, path, params = parse_ws_url(self.url)

            # create a WAMP-over-WebSocket transport client factory
            transport_factory = WampWebSocketClientFactory(create, url=self.url, serializers=self.serializers, proxy=self.proxy, headers=self.headers)

            # client WebSocket settings - similar to:
            # - http://crossbar.io/docs/WebSocket-Compression/#production-settings
            # - http://crossbar.io/docs/WebSocket-Options/#production-settings

            # The permessage-deflate extensions offered to the server
            offers = [PerMessageDeflateOffer()]

            # Function to accept permessage-deflate responses from the server
            def accept(response):
                if isinstance(response, PerMessageDeflateResponse):
                    return PerMessageDeflateResponseAccept(response)

            # default WebSocket options for all client connections
            protocol_options = {
                'version': WebSocketProtocol.DEFAULT_SPEC_VERSION,
                'utf8validateIncoming': True,
                'acceptMaskedServerFrames': False,
                'maskClientFrames': True,
                'applyMask': True,
                'maxFramePayloadSize': 1048576,
                'maxMessagePayloadSize': 1048576,
                'autoFragmentSize': 65536,
                'failByDrop': True,
                'echoCloseCodeReason': False,
                'serverConnectionDropTimeout': 1.,
                'openHandshakeTimeout': 2.5,
                'closeHandshakeTimeout': 1.,
                'tcpNoDelay': True,
                'perMessageCompressionOffers': offers,
                'perMessageCompressionAccept': accept,
                'autoPingInterval': 10.,
                'autoPingTimeout': 5.,
                'autoPingSize': 12,

                # see: https://github.com/crossbario/autobahn-python/issues/1327 and
                # _cancelAutoPingTimeoutCall
                'autoPingRestartOnAnyTraffic': True,
            }

            # let user override above default options
            if self.websocket_options:
                protocol_options.update(self.websocket_options)

            # set websocket protocol options on Autobahn/Twisted protocol factory, from where it will
            # be applied for every Autobahn/Twisted protocol instance from the factory
            transport_factory.setProtocolOptions(**protocol_options)

        # supress pointless log noise
        transport_factory.noisy = False

        if endpoint:
            client = endpoint
        else:
            # if user passed ssl= but isn't using isSecure, we'll never
            # use the ssl argument which makes no sense.
            context_factory = None
            if self.ssl is not None:
                if not isSecure:
                    raise RuntimeError(
                        'ssl= argument value passed to %s conflicts with the "ws:" '
                        'prefix of the url argument. Did you mean to use "wss:"?' %
                        self.__class__.__name__)
                context_factory = self.ssl
            elif isSecure:
                from twisted.internet.ssl import optionsForClientTLS
                context_factory = optionsForClientTLS(host)

            from twisted.internet import reactor
            if self.proxy is not None:
                from twisted.internet.endpoints import TCP4ClientEndpoint
                client = TCP4ClientEndpoint(reactor, self.proxy['host'], self.proxy['port'])
                transport_factory.contextFactory = context_factory
            elif isSecure:
                from twisted.internet.endpoints import SSL4ClientEndpoint
                assert context_factory is not None
                client = SSL4ClientEndpoint(reactor, host, port, context_factory)
            else:
                from twisted.internet.endpoints import TCP4ClientEndpoint
                client = TCP4ClientEndpoint(reactor, host, port)

        # as the reactor shuts down, we wish to wait until we've sent
        # out our "Goodbye" message; leave() returns a Deferred that
        # fires when the transport gets to STATE_CLOSED
        def cleanup(proto):
            if hasattr(proto, '_session') and proto._session is not None:
                if proto._session.is_attached():
                    return proto._session.leave()
                elif proto._session.is_connected():
                    return proto._session.disconnect()

        # when our proto was created and connected, make sure it's cleaned
        # up properly later on when the reactor shuts down for whatever reason
        def init_proto(proto):
            self._connect_successes += 1
            reactor.addSystemEventTrigger('before', 'shutdown', cleanup, proto)
            return proto

        use_service = False
        if auto_reconnect:
            try:
                # since Twisted 16.1.0
                from twisted.application.internet import ClientService
                from twisted.application.internet import backoffPolicy
                use_service = True
            except ImportError:
                use_service = False

        if use_service:
            # this code path is automatically reconnecting ..
            self.log.debug('using t.a.i.ClientService')

            if (self.max_retries is not None or self.initial_retry_delay is not None or self.max_retry_delay is not None or self.retry_delay_growth is not None or self.retry_delay_jitter is not None):

                if self.max_retry_delay > 0:
                    kwargs = {}

                    def _jitter():
                        j = 1 if self.retry_delay_jitter is None else self.retry_delay_jitter
                        return random.random() * j

                    for key, val in [('initialDelay', self.initial_retry_delay),
                                     ('maxDelay', self.max_retry_delay),
                                     ('factor', self.retry_delay_growth),
                                     ('jitter', _jitter)]:
                        if val is not None:
                            kwargs[key] = val

                    # retry policy that will only try to reconnect if we connected
                    # successfully at least once before (so it fails on host unreachable etc ..)
                    def retry(failed_attempts):
                        if self._connect_successes > 0 and (self.max_retries == -1 or failed_attempts < self.max_retries):
                            return backoffPolicy(**kwargs)(failed_attempts)
                        else:
                            print('hit stop')
                            self.stop()
                            return 100000000000000
                else:
                    # immediately reconnect (zero delay)
                    def retry(_):
                        return 0
            else:
                retry = backoffPolicy()

            # https://twistedmatrix.com/documents/current/api/twisted.application.internet.ClientService.html
            self._client_service = ClientService(client, transport_factory, retryPolicy=retry)
            self._client_service.startService()

            d = self._client_service.whenConnected()

        else:
            # this code path is only connecting once!
            self.log.debug('using t.i.e.connect()')

            d = client.connect(transport_factory)

        # if we connect successfully, the arg is a WampWebSocketClientProtocol
        d.addCallback(init_proto)

        # if the user didn't ask us to start the reactor, then they
        # get to deal with any connect errors themselves.
        if start_reactor:
            # if an error happens in the connect(), we save the underlying
            # exception so that after the event-loop exits we can re-raise
            # it to the caller.

            class ErrorCollector(object):
                exception = None

                def __call__(self, failure):
                    self.exception = failure.value
                    reactor.stop()
            connect_error = ErrorCollector()
            d.addErrback(connect_error)

            # now enter the Twisted reactor loop
            reactor.run()

            # if the ApplicationSession sets an "error" key on the self.config.extra dictionary, which
            # has been set to the self.extra dictionary, extract the Exception from that and re-raise
            # it as the very last one (see below) exciting back to the caller of self.run()
            app_error = self.extra.get('error', None)

            # if we exited due to a connection error, raise that to the caller
            if connect_error.exception:
                raise connect_error.exception
            elif app_error:
                raise app_error

        else:
            # let the caller handle any errors
            return d


class _ApplicationSession(ApplicationSession):
    """
    WAMP application session class used internally with :class:`autobahn.twisted.app.Application`.
    """

    def __init__(self, config, app):
        """

        :param config: The component configuration.
        :type config: Instance of :class:`autobahn.wamp.types.ComponentConfig`
        :param app: The application this session is for.
        :type app: Instance of :class:`autobahn.twisted.wamp.Application`.
        """
        # noinspection PyArgumentList
        ApplicationSession.__init__(self, config)
        self.app = app

    @inlineCallbacks
    def onConnect(self):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onConnect`
        """
        yield self.app._fire_signal('onconnect')
        self.join(self.config.realm)

    @inlineCallbacks
    def onJoin(self, details):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onJoin`
        """
        for uri, proc in self.app._procs:
            yield self.register(proc, uri)

        for uri, handler in self.app._handlers:
            yield self.subscribe(handler, uri)

        yield self.app._fire_signal('onjoined')

    @inlineCallbacks
    def onLeave(self, details):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onLeave`
        """
        yield self.app._fire_signal('onleave')
        self.disconnect()

    @inlineCallbacks
    def onDisconnect(self):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onDisconnect`
        """
        yield self.app._fire_signal('ondisconnect')


class Application(object):
    """
    A WAMP application. The application object provides a simple way of
    creating, debugging and running WAMP application components.
    """

    log = txaio.make_logger()

    def __init__(self, prefix=None):
        """

        :param prefix: The application URI prefix to use for procedures and topics,
           e.g. ``"com.example.myapp"``.
        :type prefix: unicode
        """
        self._prefix = prefix

        # procedures to be registered once the app session has joined the router/realm
        self._procs = []

        # event handler to be subscribed once the app session has joined the router/realm
        self._handlers = []

        # app lifecycle signal handlers
        self._signals = {}

        # once an app session is connected, this will be here
        self.session = None

    def __call__(self, config):
        """
        Factory creating a WAMP application session for the application.

        :param config: Component configuration.
        :type config: Instance of :class:`autobahn.wamp.types.ComponentConfig`

        :returns: obj -- An object that derives of
           :class:`autobahn.twisted.wamp.ApplicationSession`
        """
        assert(self.session is None)
        self.session = _ApplicationSession(config, self)
        return self.session

    def run(self, url="ws://localhost:8080/ws", realm="realm1", start_reactor=True):
        """
        Run the application.

        :param url: The URL of the WAMP router to connect to.
        :type url: unicode
        :param realm: The realm on the WAMP router to join.
        :type realm: unicode
        """
        runner = ApplicationRunner(url, realm)
        return runner.run(self.__call__, start_reactor)

    def register(self, uri=None):
        """
        Decorator exposing a function as a remote callable procedure.

        The first argument of the decorator should be the URI of the procedure
        to register under.

        :Example:

        .. code-block:: python

           @app.register('com.myapp.add2')
           def add2(a, b):
              return a + b

        Above function can then be called remotely over WAMP using the URI `com.myapp.add2`
        the function was registered under.

        If no URI is given, the URI is constructed from the application URI prefix
        and the Python function name.

        :Example:

        .. code-block:: python

           app = Application('com.myapp')

           # implicit URI will be 'com.myapp.add2'
           @app.register()
           def add2(a, b):
              return a + b

        If the function `yields` (is a co-routine), the `@inlineCallbacks` decorator
        will be applied automatically to it.

        :param uri: The URI of the procedure to register under.
        :type uri: unicode
        """
        def decorator(func):
            if uri:
                _uri = uri
            else:
                assert(self._prefix is not None)
                _uri = "{0}.{1}".format(self._prefix, func.__name__)

            if inspect.isgeneratorfunction(func):
                func = inlineCallbacks(func)

            self._procs.append((_uri, func))
            return func
        return decorator

    def subscribe(self, uri=None):
        """
        Decorator attaching a function as an event handler.

        The first argument of the decorator should be the URI of the topic
        to subscribe to. If no URI is given, the URI is constructed from
        the application URI prefix and the Python function name.

        If the function yield, it will be assumed that it's an asynchronous
        process and inlineCallbacks will be applied to it.

        :Example:

        .. code-block:: python

           @app.subscribe('com.myapp.topic1')
           def onevent1(x, y):
              print("got event on topic1", x, y)

        :param uri: The URI of the topic to subscribe to.
        :type uri: unicode
        """
        def decorator(func):
            if uri:
                _uri = uri
            else:
                assert(self._prefix is not None)
                _uri = "{0}.{1}".format(self._prefix, func.__name__)

            if inspect.isgeneratorfunction(func):
                func = inlineCallbacks(func)

            self._handlers.append((_uri, func))
            return func
        return decorator

    def signal(self, name):
        """
        Decorator attaching a function as handler for application signals.

        Signals are local events triggered internally and exposed to the
        developer to be able to react to the application lifecycle.

        If the function yield, it will be assumed that it's an asynchronous
        coroutine and inlineCallbacks will be applied to it.

        Current signals :

           - `onjoined`: Triggered after the application session has joined the
              realm on the router and registered/subscribed all procedures
              and event handlers that were setup via decorators.
           - `onleave`: Triggered when the application session leaves the realm.

        .. code-block:: python

           @app.signal('onjoined')
           def _():
              # do after the app has join a realm

        :param name: The name of the signal to watch.
        :type name: unicode
        """
        def decorator(func):
            if inspect.isgeneratorfunction(func):
                func = inlineCallbacks(func)
            self._signals.setdefault(name, []).append(func)
            return func
        return decorator

    @inlineCallbacks
    def _fire_signal(self, name, *args, **kwargs):
        """
        Utility method to call all signal handlers for a given signal.

        :param name: The signal name.
        :type name: str
        """
        for handler in self._signals.get(name, []):
            try:
                # FIXME: what if the signal handler is not a coroutine?
                # Why run signal handlers synchronously?
                yield handler(*args, **kwargs)
            except Exception as e:
                # FIXME
                self.log.info("Warning: exception in signal handler swallowed: {err}", err=e)


class Service(service.MultiService):
    """
    A WAMP application as a twisted service.
    The application object provides a simple way of creating, debugging and running WAMP application
    components inside a traditional twisted application

    This manages application lifecycle of the wamp connection using startService and stopService
    Using services also allows to create integration tests that properly terminates their connections

    It can host a WAMP application component in a WAMP-over-WebSocket client
    connecting to a WAMP router.
    """
    factory = WampWebSocketClientFactory

    def __init__(self, url, realm, make, extra=None, context_factory=None):
        """

        :param url: The WebSocket URL of the WAMP router to connect to (e.g. `ws://somehost.com:8090/somepath`)
        :type url: unicode

        :param realm: The WAMP realm to join the application session to.
        :type realm: unicode

        :param make: A factory that produces instances of :class:`autobahn.asyncio.wamp.ApplicationSession`
           when called with an instance of :class:`autobahn.wamp.types.ComponentConfig`.
        :type make: callable

        :param extra: Optional extra configuration to forward to the application component.
        :type extra: dict

        :param context_factory: optional, only for secure connections. Passed as contextFactory to
            the ``listenSSL()`` call; see https://twistedmatrix.com/documents/current/api/twisted.internet.interfaces.IReactorSSL.connectSSL.html
        :type context_factory: twisted.internet.ssl.ClientContextFactory or None

        You can replace the attribute factory in order to change connectionLost or connectionFailed behaviour.
        The factory attribute must return a WampWebSocketClientFactory object
        """
        self.url = url
        self.realm = realm
        self.extra = extra or dict()
        self.make = make
        self.context_factory = context_factory
        service.MultiService.__init__(self)
        self.setupService()

    def setupService(self):
        """
        Setup the application component.
        """
        is_secure, host, port, resource, path, params = parse_ws_url(self.url)

        # factory for use ApplicationSession
        def create():
            cfg = ComponentConfig(self.realm, self.extra)
            session = self.make(cfg)
            return session

        # create a WAMP-over-WebSocket transport client factory
        transport_factory = self.factory(create, url=self.url)

        # setup the client from a Twisted endpoint

        if is_secure:
            from twisted.application.internet import SSLClient
            ctx = self.context_factory
            if ctx is None:
                from twisted.internet.ssl import optionsForClientTLS
                ctx = optionsForClientTLS(host)
            client = SSLClient(host, port, transport_factory, contextFactory=ctx)
        else:
            if self.context_factory is not None:
                raise Exception("context_factory specified on non-secure URI")
            from twisted.application.internet import TCPClient
            client = TCPClient(host, port, transport_factory)

        client.setServiceParent(self)


# new API
class Session(protocol._SessionShim):
    # XXX these methods are redundant, but put here for possibly
    # better clarity; maybe a bad idea.

    def on_welcome(self, welcome_msg):
        pass

    def on_join(self, details):
        pass

    def on_leave(self, details):
        self.disconnect()

    def on_connect(self):
        self.join(self.config.realm)

    def on_disconnect(self):
        pass


# experimental authentication API
class AuthCryptoSign(object):

    def __init__(self, **kw):
        # should put in checkconfig or similar
        for key in kw.keys():
            if key not in ['authextra', 'authid', 'authrole', 'privkey']:
                raise ValueError(
                    "Unexpected key '{}' for {}".format(key, self.__class__.__name__)
                )
        for key in ['privkey']:
            if key not in kw:
                raise ValueError(
                    "Must provide '{}' for cryptosign".format(key)
                )
        for key in kw.get('authextra', dict()):
            if key not in ['pubkey', 'channel_binding', 'trustroot', 'challenge']:
                raise ValueError(
                    "Unexpected key '{}' in 'authextra'".format(key)
                )

        from autobahn.wamp.cryptosign import CryptosignKey
        self._privkey = CryptosignKey.from_bytes(
            binascii.a2b_hex(kw['privkey'])
        )

        if 'pubkey' in kw.get('authextra', dict()):
            pubkey = kw['authextra']['pubkey']
            if pubkey != self._privkey.public_key():
                raise ValueError(
                    "Public key doesn't correspond to private key"
                )
        else:
            kw['authextra'] = kw.get('authextra', dict())
            kw['authextra']['pubkey'] = self._privkey.public_key()
        self._args = kw

    def on_challenge(self, session, challenge):
        # sign the challenge with our private key.
        channel_id_type = self._args['authextra'].get('channel_binding', None)
        channel_id = self.transport.transport_details.channel_id.get(channel_id_type, None)
        signed_challenge = self._privkey.sign_challenge(challenge, channel_id=channel_id,
                                                        channel_id_type=channel_id_type)
        return signed_challenge


IAuthenticator.register(AuthCryptoSign)


class AuthWampCra(object):

    def __init__(self, **kw):
        # should put in checkconfig or similar
        for key in kw.keys():
            if key not in ['authextra', 'authid', 'authrole', 'secret']:
                raise ValueError(
                    "Unexpected key '{}' for {}".format(key, self.__class__.__name__)
                )
        for key in ['secret', 'authid']:
            if key not in kw:
                raise ValueError(
                    "Must provide '{}' for wampcra".format(key)
                )

        self._args = kw
        self._secret = kw.pop('secret')
        if not isinstance(self._secret, str):
            self._secret = self._secret.decode('utf8')

    def on_challenge(self, session, challenge):
        key = self._secret.encode('utf8')
        if 'salt' in challenge.extra:
            key = auth.derive_key(
                key,
                challenge.extra['salt'],
                challenge.extra['iterations'],
                challenge.extra['keylen']
            )

        signature = auth.compute_wcs(
            key,
            challenge.extra['challenge'].encode('utf8')
        )
        return signature.decode('ascii')


IAuthenticator.register(AuthWampCra)
