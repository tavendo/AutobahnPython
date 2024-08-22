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


from functools import wraps
from typing import List

from twisted.internet.interfaces import IStreamClientEndpoint
from twisted.internet.endpoints import UNIXClientEndpoint
from twisted.internet.endpoints import TCP4ClientEndpoint
from twisted.python.failure import Failure
from twisted.internet.error import ReactorNotRunning

try:
    _TLS = True
    from twisted.internet.endpoints import SSL4ClientEndpoint
    from twisted.internet.ssl import optionsForClientTLS, CertificateOptions, Certificate
    from twisted.internet.interfaces import IOpenSSLClientConnectionCreator
    from OpenSSL import SSL
except ImportError:
    _TLS = False
    # there's no optionsForClientTLS in older Twisteds or we might be
    # missing OpenSSL entirely.

import txaio

from autobahn.twisted.websocket import WampWebSocketClientFactory
from autobahn.twisted.rawsocket import WampRawSocketClientFactory

from autobahn.wamp import component

from autobahn.twisted.wamp import Session
from autobahn.wamp.serializer import create_transport_serializers, create_transport_serializer

__all__ = ('Component', 'run')


def _unique_list(seq):
    """
    Return a list with unique elements from sequence, preserving order.
    """
    seen = set()
    return [x for x in seq if x not in seen and not seen.add(x)]


def _camel_case_from_snake_case(snake):
    parts = snake.split('_')
    return parts[0] + ''.join(s.capitalize() for s in parts[1:])


def _create_transport_factory(reactor, transport, session_factory):
    """
    Create a WAMP-over-XXX transport factory.
    """
    if transport.type == 'websocket':
        serializers = create_transport_serializers(transport)
        factory = WampWebSocketClientFactory(
            session_factory,
            url=transport.url,
            serializers=serializers,
            proxy=transport.proxy,  # either None or a dict with host, port
        )

    elif transport.type == 'rawsocket':
        serializer = create_transport_serializer(transport.serializers[0])
        factory = WampRawSocketClientFactory(session_factory, serializer=serializer)

    else:
        assert(False), 'should not arrive here'

    # set the options one at a time so we can give user better feedback
    for k, v in transport.options.items():
        try:
            factory.setProtocolOptions(**{k: v})
        except (TypeError, KeyError):
            # this allows us to document options as snake_case
            # until everything internally is upgraded from
            # camelCase
            try:
                factory.setProtocolOptions(
                    **{_camel_case_from_snake_case(k): v}
                )
            except (TypeError, KeyError):
                raise ValueError(
                    "Unknown {} transport option: {}={}".format(transport.type, k, v)
                )
    return factory


def _create_transport_endpoint(reactor, endpoint_config):
    """
    Create a Twisted client endpoint for a WAMP-over-XXX transport.
    """
    if IStreamClientEndpoint.providedBy(endpoint_config):
        endpoint = IStreamClientEndpoint(endpoint_config)
    else:
        # create a connecting TCP socket
        if endpoint_config['type'] == 'tcp':

            version = endpoint_config.get('version', 4)
            if version not in [4, 6]:
                raise ValueError('invalid IP version {} in client endpoint configuration'.format(version))

            host = endpoint_config['host']
            if type(host) != str:
                raise ValueError('invalid type {} for host in client endpoint configuration'.format(type(host)))

            port = endpoint_config['port']
            if type(port) != int:
                raise ValueError('invalid type {} for port in client endpoint configuration'.format(type(port)))

            timeout = endpoint_config.get('timeout', 10)  # in seconds
            if type(timeout) != int:
                raise ValueError('invalid type {} for timeout in client endpoint configuration'.format(type(timeout)))

            tls = endpoint_config.get('tls', None)

            # create a TLS enabled connecting TCP socket
            if tls:
                if not _TLS:
                    raise RuntimeError('TLS configured in transport, but TLS support is not installed (eg OpenSSL?)')

                # FIXME: create TLS context from configuration
                if IOpenSSLClientConnectionCreator.providedBy(tls):
                    # eg created from twisted.internet.ssl.optionsForClientTLS()
                    context = IOpenSSLClientConnectionCreator(tls)

                elif isinstance(tls, dict):
                    for k in tls.keys():
                        if k not in ["hostname", "trust_root"]:
                            raise ValueError("Invalid key '{}' in 'tls' config".format(k))
                    hostname = tls.get('hostname', host)
                    if type(hostname) != str:
                        raise ValueError('invalid type {} for hostname in TLS client endpoint configuration'.format(hostname))
                    trust_root = None
                    cert_fname = tls.get("trust_root", None)
                    if cert_fname is not None:
                        trust_root = Certificate.loadPEM(open(cert_fname, 'r').read())
                    context = optionsForClientTLS(hostname, trustRoot=trust_root)

                elif isinstance(tls, CertificateOptions):
                    context = tls

                elif tls is True:
                    context = optionsForClientTLS(host)

                else:
                    raise RuntimeError('unknown type {} for "tls" configuration in transport'.format(type(tls)))

                if version == 4:
                    endpoint = SSL4ClientEndpoint(reactor, host, port, context, timeout=timeout)
                elif version == 6:
                    # there is no SSL6ClientEndpoint!
                    raise RuntimeError('TLS on IPv6 not implemented')
                else:
                    assert(False), 'should not arrive here'

            # create a non-TLS connecting TCP socket
            else:
                if host.endswith(".onion"):
                    # hmm, can't log here?
                    # self.log.info("{host} appears to be a Tor endpoint", host=host)
                    try:
                        import txtorcon
                        endpoint = txtorcon.TorClientEndpoint(host, port)
                    except ImportError:
                        raise RuntimeError(
                            "{} appears to be a Tor Onion service, but txtorcon is not installed".format(
                                host,
                            )
                        )
                elif version == 4:
                    endpoint = TCP4ClientEndpoint(reactor, host, port, timeout=timeout)
                elif version == 6:
                    try:
                        from twisted.internet.endpoints import TCP6ClientEndpoint
                    except ImportError:
                        raise RuntimeError('IPv6 is not supported (please upgrade Twisted)')
                    endpoint = TCP6ClientEndpoint(reactor, host, port, timeout=timeout)
                else:
                    assert(False), 'should not arrive here'

        # create a connecting Unix domain socket
        elif endpoint_config['type'] == 'unix':
            path = endpoint_config['path']
            timeout = int(endpoint_config.get('timeout', 10))  # in seconds
            endpoint = UNIXClientEndpoint(reactor, path, timeout=timeout)

        else:
            assert(False), 'should not arrive here'

    return endpoint


class Component(component.Component):
    """
    A component establishes a transport and attached a session
    to a realm using the transport for communication.

    The transports a component tries to use can be configured,
    as well as the auto-reconnect strategy.
    """

    log = txaio.make_logger()

    session_factory = Session
    """
    The factory of the session we will instantiate.
    """

    def _is_ssl_error(self, e):
        """
        Internal helper.

        This is so we can just return False if we didn't import any
        TLS/SSL libraries. Otherwise, returns True if this is an
        OpenSSL.SSL.Error
        """
        if _TLS:
            return isinstance(e, SSL.Error)
        return False

    def _check_native_endpoint(self, endpoint):
        if IStreamClientEndpoint.providedBy(endpoint):
            pass
        elif isinstance(endpoint, dict):
            if 'tls' in endpoint:
                tls = endpoint['tls']
                if isinstance(tls, (dict, bool)):
                    pass
                elif IOpenSSLClientConnectionCreator.providedBy(tls):
                    pass
                elif isinstance(tls, CertificateOptions):
                    pass
                else:
                    raise ValueError(
                        "'tls' configuration must be a dict, CertificateOptions or"
                        " IOpenSSLClientConnectionCreator provider"
                    )
        else:
            raise ValueError(
                "'endpoint' configuration must be a dict or IStreamClientEndpoint"
                " provider"
            )

    def _connect_transport(self, reactor, transport, session_factory, done):
        """
        Create and connect a WAMP-over-XXX transport.

        :param done: is a Deferred/Future from the parent which we
            should signal upon error if it is not done yet (XXX maybe an
            "on_error" callable instead?)
        """
        transport_factory = _create_transport_factory(reactor, transport, session_factory)
        if transport.proxy:
            transport_endpoint = _create_transport_endpoint(
                reactor,
                {
                    "type": "tcp",
                    "host": transport.proxy["host"],
                    "port": transport.proxy["port"],
                }
            )
        else:
            transport_endpoint = _create_transport_endpoint(reactor, transport.endpoint)
        d = transport_endpoint.connect(transport_factory)

        def on_connect_success(proto):

            # if e.g. an SSL handshake fails, we will have
            # successfully connected (i.e. get here) but need to
            # 'listen' for the "connectionLost" from the underlying
            # protocol in case of handshake failure .. so we wrap
            # it. Also, we don't increment transport.success_count
            # here on purpose (because we might not succeed).
            orig = proto.connectionLost

            @wraps(orig)
            def lost(fail):
                rtn = orig(fail)
                if not txaio.is_called(done):
                    txaio.reject(done, fail)
                return rtn
            proto.connectionLost = lost

        def on_connect_failure(err):
            transport.connect_failures += 1
            # failed to establish a connection in the first place
            txaio.reject(done, err)

        txaio.add_callbacks(d, on_connect_success, None)
        txaio.add_callbacks(d, None, on_connect_failure)
        return d

    def start(self, reactor=None):
        """
        This starts the Component, which means it will start connecting
        (and re-connecting) to its configured transports. A Component
        runs until it is "done", which means one of:
        - There was a "main" function defined, and it completed successfully;
        - Something called ``.leave()`` on our session, and we left successfully;
        - ``.stop()`` was called, and completed successfully;
        - none of our transports were able to connect successfully (failure);

        :returns: a Deferred that fires (with ``None``) when we are
            "done" or with a Failure if something went wrong.
        """
        if reactor is None:
            self.log.warning("Using default reactor")
            from twisted.internet import reactor

        return self._start(loop=reactor)


def run(components: List[Component], log_level: str = 'info', stop_at_close: bool = True):
    """
    High-level API to run a series of components.

    This will only return once all the components have stopped
    (including, possibly, after all re-connections have failed if you
    have re-connections enabled). Under the hood, this calls
    :meth:`twisted.internet.reactor.run` -- if you wish to manage the
    reactor loop yourself, use the
    :meth:`autobahn.twisted.component.Component.start` method to start
    each component yourself.

    :param components: the Component(s) you wish to run
    :param log_level: a valid log-level (or None to avoid calling start_logging)
    :param stop_at_close: Flag to control whether to stop the reactor when done.
    """
    # only for Twisted > 12
    # ...so this isn't in all Twisted versions we test against -- need
    # to do "something else" if we can't import .. :/ (or drop some
    # support)
    from twisted.internet.task import react

    # actually, should we even let people "not start" the logging? I'm
    # not sure that's wise... (double-check: if they already called
    # txaio.start_logging() what happens if we call it again?)
    if log_level is not None:
        txaio.start_logging(level=log_level)

    log = txaio.make_logger()

    if stop_at_close:
        def done_callback(reactor, arg):
            if isinstance(arg, Failure):
                log.error('Something went wrong: {log_failure}', failure=arg)
                try:
                    log.warning('Stopping reactor ..')
                    reactor.stop()
                except ReactorNotRunning:
                    pass
    else:
        done_callback = None

    react(component._run, (components, done_callback))
