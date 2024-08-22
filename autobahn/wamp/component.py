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


import itertools
import random
from functools import partial

import txaio

from autobahn.util import ObservableMixin
from autobahn.websocket.util import parse_url as parse_ws_url
from autobahn.rawsocket.util import parse_url as parse_rs_url

from autobahn.wamp.types import ComponentConfig, SubscribeOptions, RegisterOptions
from autobahn.wamp.exception import SessionNotReady, ApplicationError
from autobahn.wamp.auth import create_authenticator, IAuthenticator
from autobahn.wamp.serializer import SERID_TO_SER


__all__ = (
    'Component'
)


def _validate_endpoint(endpoint, check_native_endpoint=None):
    """
    Check a WAMP connecting endpoint configuration.
    """
    if check_native_endpoint:
        check_native_endpoint(endpoint)
    elif not isinstance(endpoint, dict):
        raise ValueError(
            "'endpoint' must be a dict"
        )

    # note, we're falling through here -- check_native_endpoint can
    # disallow or allow dict-based config as it likes, but if it
    # *does* allow a dict through, we want to check "base options"
    # here so that both Twisted and asyncio don't have to check these
    # things as well.
    if isinstance(endpoint, dict):
        # XXX what about filling in anything missing from the URL? Or
        # is that only for when *nothing* is provided for endpoint?
        if 'type' not in endpoint:
            # could maybe just make tcp the default?
            raise ValueError("'type' required in endpoint configuration")
        if endpoint['type'] not in ['tcp', 'unix']:
            raise ValueError('invalid type "{}" in endpoint'.format(endpoint['type']))

        for k in endpoint.keys():
            if k not in ['type', 'host', 'port', 'path', 'tls', 'timeout', 'version']:
                raise ValueError(
                    "Invalid key '{}' in endpoint configuration".format(k)
                )

        if endpoint['type'] == 'tcp':
            for k in ['host', 'port']:
                if k not in endpoint:
                    raise ValueError(
                        "'{}' required in 'tcp' endpoint config".format(k)
                    )
            for k in ['path']:
                if k in endpoint:
                    raise ValueError(
                        "'{}' not valid in 'tcp' endpoint config".format(k)
                    )
        elif endpoint['type'] == 'unix':
            for k in ['path']:
                if k not in endpoint:
                    raise ValueError(
                        "'{}' required for 'unix' endpoint config".format(k)
                    )
            for k in ['host', 'port', 'tls']:
                if k in endpoint:
                    raise ValueError(
                        "'{}' not valid in 'unix' endpoint config".format(k)
                    )
        else:
            assert False, 'should not arrive here'


def _create_transport(index, transport, check_native_endpoint=None):
    """
    Internal helper to insert defaults and create _Transport instances.

    :param transport: a (possibly valid) transport configuration
    :type transport: dict

    :returns: a _Transport instance

    :raises: ValueError on invalid configuration
    """
    if type(transport) != dict:
        raise ValueError('invalid type {} for transport configuration - must be a dict'.format(type(transport)))

    valid_transport_keys = [
        'type', 'url', 'endpoint', 'serializer', 'serializers', 'options',
        'max_retries', 'max_retry_delay', 'initial_retry_delay',
        'retry_delay_growth', 'retry_delay_jitter', 'proxy', 'headers'
    ]
    for k in transport.keys():
        if k not in valid_transport_keys:
            raise ValueError(
                "'{}' is not a valid configuration item".format(k)
            )

    kind = 'websocket'
    if 'type' in transport:
        if transport['type'] not in ['websocket', 'rawsocket']:
            raise ValueError('Invalid transport type {}'.format(transport['type']))
        kind = transport['type']
    else:
        transport['type'] = 'websocket'

    if 'proxy' in transport and kind != 'websocket':
        raise ValueError(
            "proxy= only supported for type=websocket transports"
        )
    proxy = transport.get("proxy", None)
    if proxy is not None:
        for k in proxy.keys():
            if k not in ['host', 'port']:
                raise ValueError(
                    "Unknown key '{}' in proxy config".format(k)
                )
        for k in ['host', 'port']:
            if k not in proxy:
                raise ValueError(
                    "Proxy config requires '{}'".formaT(k)
                )

    options = dict()
    if 'options' in transport:
        options = transport['options']
        if not isinstance(options, dict):
            raise ValueError(
                'options must be a dict, not {}'.format(type(options))
            )

    headers = transport.get("headers")

    if kind == 'websocket':
        for key in ['url']:
            if key not in transport:
                raise ValueError("Transport requires '{}' key".format(key))
        # endpoint not required; we will deduce from URL if it's not provided
        # XXX not in the branch I rebased; can this go away? (is it redundant??)
        if 'endpoint' not in transport:
            is_secure, host, port, resource, path, params = parse_ws_url(transport['url'])
            endpoint_config = {
                'type': 'tcp',
                'host': host,
                'port': port,
                'tls': is_secure,
            }
        else:
            # note: we're avoiding mutating the incoming "configuration"
            # dict, so this should avoid that too...
            endpoint_config = transport['endpoint']
            _validate_endpoint(endpoint_config, check_native_endpoint)

        if 'serializer' in transport:
            raise ValueError("'serializer' is only for rawsocket; use 'serializers'")
        if 'serializers' in transport:
            if not isinstance(transport['serializers'], (list, tuple)):
                raise ValueError("'serializers' must be a list of strings")
            if not all([
                    isinstance(s, (str, str))
                    for s in transport['serializers']]):
                raise ValueError("'serializers' must be a list of strings")
            valid_serializers = SERID_TO_SER.keys()
            for serial in transport['serializers']:
                if serial not in valid_serializers:
                    raise ValueError(
                        "Invalid serializer '{}' (expected one of: {})".format(
                            serial,
                            ', '.join([repr(s) for s in valid_serializers]),
                        )
                    )
        serializer_config = transport.get('serializers', ['cbor', 'json'])

    elif kind == 'rawsocket':
        if 'endpoint' not in transport:
            if transport['url'].startswith('rs'):
                # # try to parse RawSocket URL ..
                isSecure, host, port = parse_rs_url(transport['url'])
            elif transport['url'].startswith('ws'):
                # try to parse WebSocket URL ..
                isSecure, host, port, resource, path, params = parse_ws_url(transport['url'])
            else:
                raise RuntimeError()
            if host == 'unix':
                # here, "port" is actually holding the path on the host, eg "/tmp/file.sock"
                endpoint_config = {
                    'type': 'unix',
                    'path': port,
                }
            else:
                endpoint_config = {
                    'type': 'tcp',
                    'host': host,
                    'port': port,
                }
        else:
            endpoint_config = transport['endpoint']
        if 'serializers' in transport:
            raise ValueError("'serializers' is only for websocket; use 'serializer'")
        if headers is not None:
            raise ValueError("'headers' not supported for rawsocket transport")
        # always a list; len == 1 for rawsocket
        if 'serializer' in transport:
            if not isinstance(transport['serializer'], (str, str)):
                raise ValueError("'serializer' must be a string")
            serializer_config = [transport['serializer']]
        else:
            serializer_config = ['cbor']

    else:
        assert False, 'should not arrive here'

    kw = {}
    for key in ['max_retries', 'max_retry_delay', 'initial_retry_delay',
                'retry_delay_growth', 'retry_delay_jitter']:
        if key in transport:
            kw[key] = transport[key]

    return _Transport(
        index,
        kind=kind,
        url=transport.get('url', None),
        endpoint=endpoint_config,
        serializers=serializer_config,
        proxy=proxy,
        options=options,
        headers=headers,
        **kw
    )


class _Transport(object):
    """
    Thin-wrapper for WAMP transports used by a Connection.
    """

    def __init__(self, idx, kind, url, endpoint, serializers,
                 max_retries=-1,
                 max_retry_delay=300,
                 initial_retry_delay=1.5,
                 retry_delay_growth=1.5,
                 retry_delay_jitter=0.1,
                 proxy=None,
                 options=None,
                 headers=None):
        """
        """
        if options is None:
            options = dict()
        self.idx = idx

        self.type = kind
        self.url = url
        self.endpoint = endpoint
        self.options = options
        self.headers = headers

        self.serializers = serializers
        if self.type == 'rawsocket' and len(serializers) != 1:
            raise ValueError(
                "'rawsocket' transport requires exactly one serializer"
            )

        self.max_retries = max_retries
        self.max_retry_delay = max_retry_delay
        self.initial_retry_delay = initial_retry_delay
        self.retry_delay_growth = retry_delay_growth
        self.retry_delay_jitter = retry_delay_jitter
        self.proxy = proxy  # this is a dict of proxy config

        # used via can_reconnect() and failed() to record this
        # transport is never going to work
        self._permanent_failure = False

        self.reset()

    def reset(self):
        """
        set connection failure rates and retry-delay to initial values
        """
        self.connect_attempts = 0
        self.connect_sucesses = 0
        self.connect_failures = 0
        self.retry_delay = self.initial_retry_delay

    def failed(self):
        """
        Mark this transport as failed, meaning we won't try to connect to
        it any longer (that is: can_reconnect() will always return
        False afer calling this).
        """
        self._permanent_failure = True

    def can_reconnect(self):
        if self._permanent_failure:
            return False
        if self.max_retries == -1:
            return True
        return self.connect_attempts < self.max_retries + 1

    def next_delay(self):
        if self.connect_attempts == 0:
            # if we never tried before, try immediately
            return 0
        elif self.max_retries != -1 and self.connect_attempts >= self.max_retries + 1:
            raise RuntimeError('max reconnects reached')
        else:
            self.retry_delay = self.retry_delay * self.retry_delay_growth
            self.retry_delay = random.normalvariate(self.retry_delay, self.retry_delay * self.retry_delay_jitter)
            if self.retry_delay > self.max_retry_delay:
                self.retry_delay = self.max_retry_delay
            return self.retry_delay

    def describe_endpoint(self):
        """
        returns a human-readable description of the endpoint
        """
        if isinstance(self.endpoint, dict):
            return self.endpoint['type']
        return repr(self.endpoint)


# this could probably implement twisted.application.service.IService
# if we wanted; or via an adapter...which just adds a startService()
# and stopService() [latter can be async]

class Component(ObservableMixin):
    """
    A WAMP application component. A component holds configuration for
    (and knows how to create) transports and sessions.
    """

    session_factory = None
    """
    The factory of the session we will instantiate.
    """

    def subscribe(self, topic, options=None, check_types=False):
        """
        A decorator as a shortcut for subscribing during on-join

        For example::

            @component.subscribe(
                "some.topic",
                options=SubscribeOptions(match='prefix'),
            )
            def topic(*args, **kw):
                print("some.topic({}, {}): event received".format(args, kw))
        """
        assert options is None or isinstance(options, SubscribeOptions)

        def decorator(fn):

            def do_subscription(session, details):
                return session.subscribe(fn, topic=topic, options=options, check_types=check_types)
            self.on('join', do_subscription)
            return fn
        return decorator

    def register(self, uri, options=None, check_types=False):
        """
        A decorator as a shortcut for registering during on-join

        For example::

            @component.register(
                "com.example.add",
                options=RegisterOptions(invoke='roundrobin'),
            )
            def add(*args, **kw):
                print("add({}, {}): event received".format(args, kw))
        """
        assert options is None or isinstance(options, RegisterOptions)

        def decorator(fn):

            def do_registration(session, details):
                return session.register(fn, procedure=uri, options=options, check_types=check_types)
            self.on('join', do_registration)
            return fn
        return decorator

    def __init__(self, main=None, transports=None, config=None, realm='realm1', extra=None,
                 authentication=None, session_factory=None, is_fatal=None):
        """
        :param main: After a transport has been connected and a session
            has been established and joined to a realm, this (async)
            procedure will be run until it finishes -- which signals that
            the component has run to completion. In this case, it usually
            doesn't make sense to use the ``on_*`` kwargs. If you do not
            pass a main() procedure, the session will not be closed
            (unless you arrange for .leave() to be called).

        :type main: callable taking two args ``reactor`` and ``ISession``

        :param transports: Transport configurations for creating
            transports. Each transport can be a WAMP URL, or a dict
            containing the following configuration keys:

                - ``type`` (optional): ``websocket`` (default) or ``rawsocket``
                - ``url``: the router URL
                - ``endpoint`` (optional, derived from URL if not provided):
                    - ``type``: "tcp" or "unix"
                    - ``host``, ``port``: only for TCP
                    - ``path``: only for unix
                    - ``timeout``: in seconds
                    - ``tls``: ``True`` or (under Twisted) an
                      ``twisted.internet.ssl.IOpenSSLClientComponentCreator``
                      instance (such as returned from
                      ``twisted.internet.ssl.optionsForClientTLS``) or
                      ``CertificateOptions`` instance.
                - ``max_retries``: Maximum number of reconnection attempts. Unlimited if set to -1.
                - ``initial_retry_delay``: Initial delay for reconnection attempt in seconds (Default: 1.0s).
                - ``max_retry_delay``: Maximum delay for reconnection attempts in seconds (Default: 60s).
                - ``retry_delay_growth``: The growth factor applied to the retry delay between reconnection attempts (Default 1.5).
                - ``retry_delay_jitter``: A 0-argument callable that introduces nose into the delay. (Default random.random)
                - ``serializer`` (only for raw socket): Specify an accepted serializer (e.g. 'json', 'msgpack', 'cbor', 'ubjson', 'flatbuffers')
                - ``serializers``: Specify list of accepted serializers
                - ``options``: tbd
                - ``proxy``: tbd

        :type transports: None or str or list

        :param realm: the realm to join
        :type realm: str

        :param authentication: configuration of authenticators
        :type authentication: dict

        :param session_factory: if None, ``ApplicationSession`` is
            used, otherwise a callable taking a single ``config`` argument
            that is used to create a new `ApplicationSession` instance.

        :param is_fatal: a callable taking a single argument, an
            ``Exception`` instance. The callable should return ``True`` if
            this error is "fatal", meaning we should not try connecting to
            the current transport again. The default behavior (on None) is
            to always return ``False``
        """
        self.set_valid_events(
            [
                'start',        # fired by base class
                'connect',      # fired by ApplicationSession
                'join',         # fired by ApplicationSession
                'ready',        # fired by ApplicationSession
                'leave',        # fired by ApplicationSession
                'disconnect',   # fired by ApplicationSession
                'connectfailure',   # fired by base class
            ]
        )

        if is_fatal is not None and not callable(is_fatal):
            raise ValueError('"is_fatal" must be a callable or None')
        self._is_fatal = is_fatal

        if main is not None and not callable(main):
            raise ValueError('"main" must be a callable if given')
        self._entry = main

        # use WAMP-over-WebSocket to localhost when no transport is specified at all
        if transports is None:
            transports = 'ws://127.0.0.1:8080/ws'

        # allows to provide a URL instead of a list of transports
        if isinstance(transports, (str, str)):
            url = transports
            # 'endpoint' will get filled in by parsing the 'url'
            transport = {
                'type': 'websocket',
                'url': url,
            }
            transports = [transport]

        # allows single transport instead of a list (convenience)
        elif isinstance(transports, dict):
            transports = [transports]

        # XXX do we want to be able to provide an infinite iterable of
        # transports here? e.g. a generator that makes new transport
        # to try?

        # now check and save list of transports
        self._transports = []
        for idx, transport in enumerate(transports):
            # allows to provide a URL instead of transport dict
            if type(transport) == str:
                _transport = {
                    'type': 'websocket',
                    'url': transport,
                }
            else:
                _transport = transport
            self._transports.append(
                _create_transport(idx, _transport, self._check_native_endpoint)
            )

        # XXX should have some checkconfig support
        self._authentication = authentication or {}

        if session_factory:
            self.session_factory = session_factory
        self._realm = realm
        self._extra = extra

        self._delay_f = None
        self._done_f = None
        self._session = None
        self._stopping = False

    def _can_reconnect(self):
        # check if any of our transport has any reconnect attempt left
        for transport in self._transports:
            if transport.can_reconnect():
                return True
        return False

    def _start(self, loop=None):
        """
        This starts the Component, which means it will start connecting
        (and re-connecting) to its configured transports. A Component
        runs until it is "done", which means one of:

        - There was a "main" function defined, and it completed successfully;
        - Something called ``.leave()`` on our session, and we left successfully;
        - ``.stop()`` was called, and completed successfully;
        - none of our transports were able to connect successfully (failure);

        :returns: a Future/Deferred which will resolve (to ``None``) when we are
            "done" or with an error if something went wrong.
        """

        # we can only be "start()ed" once before we stop .. but that
        # doesn't have to be an error we can give back another future
        # that fires when our "real" _done_f is completed.
        if self._done_f is not None:
            d = txaio.create_future()

            def _cb(arg):
                txaio.resolve(d, arg)

            txaio.add_callbacks(self._done_f, _cb, _cb)
            return d

        # this future will be returned, and thus has the semantics
        # specified in the docstring.
        self._done_f = txaio.create_future()

        def _reset(arg):
            """
            if the _done_f future is resolved (good or bad), we want to set it
            to None in our class
            """
            self._done_f = None
            return arg
        txaio.add_callbacks(self._done_f, _reset, _reset)

        # Create a generator of transports that .can_reconnect()
        transport_gen = itertools.cycle(self._transports)

        # this is a 1-element list so we can set it from closures in
        # this function
        transport_candidate = [0]

        def error(fail):
            self._delay_f = None
            if self._stopping:
                # might be better to add framework-specific checks in
                # subclasses to see if this is CancelledError (for
                # Twisted) and whatever asyncio does .. but tracking
                # if we're in the shutdown path is fine too
                txaio.resolve(self._done_f, None)
            else:
                self.log.info("Internal error {msg}", msg=txaio.failure_message(fail))
                self.log.debug("{tb}", tb=txaio.failure_format_traceback(fail))
                txaio.reject(self._done_f, fail)

        def attempt_connect(_):
            self._delay_f = None

            def handle_connect_error(fail):
                # FIXME - make txaio friendly
                # Can connect_f ever be in a cancelled state?
                # if txaio.using_asyncio and isinstance(fail.value, asyncio.CancelledError):
                #     unrecoverable_error = True

                self.log.debug('component failed: {error}', error=txaio.failure_message(fail))
                self.log.debug('{tb}', tb=txaio.failure_format_traceback(fail))
                # If this is a "fatal error" that will never work,
                # we bail out now
                if isinstance(fail.value, ApplicationError):
                    self.log.error("{msg}", msg=fail.value.error_message())

                elif isinstance(fail.value, OSError):
                    # failed to connect entirely, like nobody
                    # listening etc.
                    self.log.info("Connection failed with OS error: {msg}", msg=txaio.failure_message(fail))

                elif self._is_ssl_error(fail.value):
                    # Quoting pyOpenSSL docs: "Whenever
                    # [SSL.Error] is raised directly, it has a
                    # list of error messages from the OpenSSL
                    # error queue, where each item is a tuple
                    # (lib, function, reason). Here lib, function
                    # and reason are all strings, describing where
                    # and what the problem is. See err(3) for more
                    # information."
                    # (and 'args' is a 1-tuple containing the above
                    # 3-tuple...)
                    ssl_lib, ssl_func, ssl_reason = fail.value.args[0][0]
                    self.log.error("TLS failure: {reason}", reason=ssl_reason)
                else:
                    self.log.error(
                        'Connection failed: {error}',
                        error=txaio.failure_message(fail),
                    )

                if self._is_fatal is None:
                    is_fatal = False
                else:
                    is_fatal = self._is_fatal(fail.value)
                if is_fatal:
                    self.log.info("Error was fatal; failing transport")
                    transport_candidate[0].failed()

                txaio.call_later(0, transport_check, None)
                return

            def notify_connect_error(fail):
                chain_f = txaio.create_future()
                # hmm, if connectfailure took a _Transport instead of
                # (or in addition to?) self it could .failed() the
                # transport and we could do away with the is_fatal
                # listener?
                handler_f = self.fire('connectfailure', self, fail.value)
                txaio.add_callbacks(
                    handler_f,
                    lambda _: txaio.reject(chain_f, fail),
                    lambda _: txaio.reject(chain_f, fail)
                )
                return chain_f

            def connect_error(fail):
                notify_f = notify_connect_error(fail)
                txaio.add_callbacks(notify_f, None, handle_connect_error)

            def session_done(x):
                txaio.resolve(self._done_f, None)

            connect_f = txaio.as_future(
                self._connect_once,
                loop, transport_candidate[0],
            )
            txaio.add_callbacks(connect_f, session_done, connect_error)

        def transport_check(_):
            self.log.debug('Entering re-connect loop')

            if not self._can_reconnect():
                err_msg = "Component failed: Exhausted all transport connect attempts"
                self.log.info(err_msg)
                try:
                    raise RuntimeError(err_msg)
                except RuntimeError as e:
                    txaio.reject(self._done_f, e)
                    return

            while True:

                transport = next(transport_gen)

                if transport.can_reconnect():
                    transport_candidate[0] = transport
                    break

            delay = transport.next_delay()
            self.log.warning(
                'trying transport {transport_idx} ("{transport_url}") using connect delay {transport_delay}',
                transport_idx=transport.idx,
                transport_url=transport.url,
                transport_delay=delay,
            )

            self._delay_f = txaio.sleep(delay)
            txaio.add_callbacks(self._delay_f, attempt_connect, error)

        # issue our first event, then start reconnect loop
        start_f = self.fire('start', loop, self)
        txaio.add_callbacks(start_f, transport_check, error)
        return self._done_f

    def stop(self):
        self._stopping = True
        if self._session and self._session.is_attached():
            return self._session.leave()
        elif self._delay_f:
            # This cancel request will actually call the "error" callback of
            # the _delay_f future. Nothing to worry about.
            return txaio.as_future(txaio.cancel, self._delay_f)
        # if (for some reason -- should we log warning here to figure
        # out if this can evern happen?) we've not fired _done_f, we
        # do that now (causing our "main" to exit, and thus react() to
        # quit)
        if not txaio.is_called(self._done_f):
            txaio.resolve(self._done_f, None)
        return txaio.create_future_success(None)

    def _connect_once(self, reactor, transport):

        self.log.info(
            'connecting once using transport type "{transport_type}" '
            'over endpoint "{endpoint_desc}"',
            transport_type=transport.type,
            endpoint_desc=transport.describe_endpoint(),
        )

        done = txaio.create_future()

        # factory for ISession objects
        def create_session():
            cfg = ComponentConfig(self._realm, self._extra)
            try:
                self._session = session = self.session_factory(cfg)
                for auth_name, auth_config in self._authentication.items():
                    if isinstance(auth_config, IAuthenticator):
                        session.add_authenticator(auth_config)
                    else:
                        authenticator = create_authenticator(auth_name, **auth_config)
                        session.add_authenticator(authenticator)

            except Exception as e:
                # couldn't instantiate session calls, which is fatal.
                # let the reconnection logic deal with that
                f = txaio.create_failure(e)
                txaio.reject(done, f)
                raise
            else:
                # hook up the listener to the parent so we can bubble
                # up events happning on the session onto the
                # connection. This lets you do component.on('join',
                # cb) which will work just as if you called
                # session.on('join', cb) for every session created.
                session._parent = self

                # listen on leave events; if we get errors
                # (e.g. no_such_realm), an on_leave can happen without
                # an on_join before
                def on_leave(session, details):
                    self.log.info(
                        "session leaving '{details.reason}'",
                        details=details,
                    )
                    if not txaio.is_called(done):
                        if details.reason in ["wamp.close.normal", "wamp.close.goodbye_and_out"]:
                            txaio.resolve(done, None)
                        else:
                            f = txaio.create_failure(
                                ApplicationError(details.reason, details.message)
                            )
                            txaio.reject(done, f)
                session.on('leave', on_leave)

                # if we were given a "main" procedure, we run through
                # it completely (i.e. until its Deferred fires) and
                # then disconnect this session
                def on_join(session, details):
                    transport.reset()
                    transport.connect_sucesses += 1
                    self.log.debug("session on_join: {details}", details=details)
                    d = txaio.as_future(self._entry, reactor, session)

                    def main_success(_):
                        self.log.debug("main_success")

                        def leave():
                            try:
                                session.leave()
                            except SessionNotReady:
                                # someone may have already called
                                # leave()
                                pass
                        txaio.call_later(0, leave)

                    def main_error(err):
                        self.log.debug("main_error: {err}", err=err)
                        txaio.reject(done, err)
                        session.disconnect()
                    txaio.add_callbacks(d, main_success, main_error)
                if self._entry is not None:
                    session.on('join', on_join)

                # listen on disconnect events. Note that in case we
                # had a "main" procedure, we could have already
                # resolve()'d our "done" future
                def on_disconnect(session, was_clean):
                    self.log.debug(
                        "session on_disconnect: was_clean={was_clean}",
                        was_clean=was_clean,
                    )
                    if not txaio.is_called(done):
                        if not was_clean:
                            self.log.warning(
                                "Session disconnected uncleanly"
                            )
                        else:
                            # eg the session has left the realm, and the transport was properly
                            # shut down. successfully finish the connection
                            txaio.resolve(done, None)
                session.on('disconnect', on_disconnect)

                # return the fresh session object
                return session

        transport.connect_attempts += 1

        d = txaio.as_future(
            self._connect_transport,
            reactor, transport, create_session, done,
        )

        def on_error(err):
            """
            this may seem redundant after looking at _connect_transport, but
            it will handle a case where something goes wrong in
            _connect_transport itself -- as the only connect our
            caller has is the 'done' future
            """
            transport.connect_failures += 1
            # something bad has happened, and maybe didn't get caught
            # upstream yet
            if not txaio.is_called(done):
                txaio.reject(done, err)
        txaio.add_callbacks(d, None, on_error)

        return done

    def on_join(self, fn):
        """
        A decorator as a shortcut for listening for 'join' events.

        For example::

           @component.on_join
           def joined(session, details):
               print("Session {} joined: {}".format(session, details))
        """
        self.on('join', fn)

    def on_leave(self, fn):
        """
        A decorator as a shortcut for listening for 'leave' events.
        """
        self.on('leave', fn)

    def on_connect(self, fn):
        """
        A decorator as a shortcut for listening for 'connect' events.
        """
        self.on('connect', fn)

    def on_disconnect(self, fn):
        """
        A decorator as a shortcut for listening for 'disconnect' events.
        """
        self.on('disconnect', fn)

    def on_ready(self, fn):
        """
        A decorator as a shortcut for listening for 'ready' events.
        """
        self.on('ready', fn)

    def on_connectfailure(self, fn):
        """
        A decorator as a shortcut for listening for 'connectfailure' events.
        """
        self.on('connectfailure', fn)


def _run(reactor, components, done_callback=None):
    """
    Internal helper. Use "run" method from autobahn.twisted.wamp or
    autobahn.asyncio.wamp

    This is the generic parts of the run() method so that there's very
    little code in the twisted/asyncio specific run() methods.

    This is called by react() (or run_until_complete() so any errors
    coming out of this should be handled properly. Logging will
    already be started.
    """
    # let user pass a single component to run, too
    # XXX probably want IComponent? only demand it, here and below?
    if isinstance(components, Component):
        components = [components]

    if type(components) != list:
        raise ValueError(
            '"components" must be a list of Component objects - encountered'
            ' {0}'.format(type(components))
        )

    for c in components:
        if not isinstance(c, Component):
            raise ValueError(
                '"components" must be a list of Component objects - encountered'
                'item of type {0}'.format(type(c))
            )

    # validation complete; proceed with startup
    log = txaio.make_logger()

    def component_success(comp, arg):
        log.debug("Component '{c}' successfully completed: {arg}", c=comp, arg=arg)
        return arg

    def component_failure(comp, f):
        log.error("Component '{c}' error: {msg}", c=comp, msg=txaio.failure_message(f))
        log.debug("Component error: {tb}", tb=txaio.failure_format_traceback(f))
        # double-check: is a component-failure still fatal to the
        # startup process (because we passed consume_exception=False
        # to gather() below?)
        return None

    def component_start(comp):
        # the future from start() errbacks if we fail, or callbacks
        # when the component is considered "done" (so maybe never)
        d = txaio.as_future(comp.start, reactor)
        txaio.add_callbacks(
            d,
            partial(component_success, comp),
            partial(component_failure, comp),
        )
        return d

    # note that these are started in parallel -- maybe we want to add
    # a "connected" signal to components so we could start them in the
    # order they're given to run() as "a" solution to dependencies.
    dl = []
    for comp in components:
        d = component_start(comp)
        dl.append(d)
    done_d = txaio.gather(dl, consume_exceptions=False)

    if done_callback:
        def all_done(arg):
            log.debug("All components ended; stopping reactor")
            done_callback(reactor, arg)
        txaio.add_callbacks(done_d, all_done, all_done)

    return done_d
