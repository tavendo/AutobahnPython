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

import asyncio
import ssl
import signal
from functools import wraps

import txaio
from autobahn.asyncio.websocket import WampWebSocketClientFactory
from autobahn.asyncio.rawsocket import WampRawSocketClientFactory

from autobahn.wamp import component
from autobahn.wamp.exception import TransportLost

from autobahn.asyncio.wamp import Session
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


def _create_transport_factory(loop, transport, session_factory):
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
        """
        return isinstance(e, ssl.SSLError)

    def _check_native_endpoint(self, endpoint):
        if isinstance(endpoint, dict):
            if 'tls' in endpoint:
                tls = endpoint['tls']
                if isinstance(tls, (dict, bool)):
                    pass
                elif isinstance(tls, ssl.SSLContext):
                    pass
                else:
                    raise ValueError(
                        "'tls' configuration must be a dict, bool or "
                        "SSLContext instance"
                    )
        else:
            raise ValueError(
                "'endpoint' configuration must be a dict or IStreamClientEndpoint"
                " provider"
            )

    # async function
    def _connect_transport(self, loop, transport, session_factory, done):
        """
        Create and connect a WAMP-over-XXX transport.
        """
        factory = _create_transport_factory(loop, transport, session_factory)

        # XXX the rest of this should probably be factored into its
        # own method (or three!)...

        if transport.proxy:
            timeout = transport.endpoint.get('timeout', 10)  # in seconds
            if type(timeout) != int:
                raise ValueError('invalid type {} for timeout in client endpoint configuration'.format(type(timeout)))
            # do we support HTTPS proxies?

            f = loop.create_connection(
                protocol_factory=factory,
                host=transport.proxy['host'],
                port=transport.proxy['port'],
            )
            time_f = asyncio.ensure_future(asyncio.wait_for(f, timeout=timeout))
            return self._wrap_connection_future(transport, done, time_f)

        elif transport.endpoint['type'] == 'tcp':

            version = transport.endpoint.get('version', 4)
            if version not in [4, 6]:
                raise ValueError('invalid IP version {} in client endpoint configuration'.format(version))

            host = transport.endpoint['host']
            if type(host) != str:
                raise ValueError('invalid type {} for host in client endpoint configuration'.format(type(host)))

            port = transport.endpoint['port']
            if type(port) != int:
                raise ValueError('invalid type {} for port in client endpoint configuration'.format(type(port)))

            timeout = transport.endpoint.get('timeout', 10)  # in seconds
            if type(timeout) != int:
                raise ValueError('invalid type {} for timeout in client endpoint configuration'.format(type(timeout)))

            tls = transport.endpoint.get('tls', None)
            tls_hostname = None

            # create a TLS enabled connecting TCP socket
            if tls:
                if isinstance(tls, dict):
                    for k in tls.keys():
                        if k not in ["hostname", "trust_root"]:
                            raise ValueError("Invalid key '{}' in 'tls' config".format(k))
                    hostname = tls.get('hostname', host)
                    if type(hostname) != str:
                        raise ValueError('invalid type {} for hostname in TLS client endpoint configuration'.format(hostname))
                    cert_fname = tls.get('trust_root', None)

                    tls_hostname = hostname
                    tls = True
                    if cert_fname is not None:
                        tls = ssl.create_default_context(
                            purpose=ssl.Purpose.SERVER_AUTH,
                            cafile=cert_fname,
                        )

                elif isinstance(tls, ssl.SSLContext):
                    # tls=<an SSLContext> is valid
                    tls_hostname = host

                elif tls in [False, True]:
                    if tls:
                        tls_hostname = host

                else:
                    raise RuntimeError('unknown type {} for "tls" configuration in transport'.format(type(tls)))

            f = loop.create_connection(
                protocol_factory=factory,
                host=host,
                port=port,
                ssl=tls,
                server_hostname=tls_hostname,
            )
            time_f = asyncio.ensure_future(asyncio.wait_for(f, timeout=timeout))
            return self._wrap_connection_future(transport, done, time_f)

        elif transport.endpoint['type'] == 'unix':
            path = transport.endpoint['path']
            timeout = int(transport.endpoint.get('timeout', 10))  # in seconds

            f = loop.create_unix_connection(
                protocol_factory=factory,
                path=path,
            )
            time_f = asyncio.ensure_future(asyncio.wait_for(f, timeout=timeout))
            return self._wrap_connection_future(transport, done, time_f)

        else:
            assert(False), 'should not arrive here'

    def _wrap_connection_future(self, transport, done, conn_f):

        def on_connect_success(result):
            # async connect call returns a 2-tuple
            transport, proto = result

            # in the case where we .abort() the transport / connection
            # during setup, we still get on_connect_success but our
            # transport is already closed (this will happen if
            # e.g. there's an "open handshake timeout") -- I don't
            # know if there's a "better" way to detect this? #python
            # doesn't know of one, anyway
            if transport.is_closing():
                if not txaio.is_called(done):
                    reason = getattr(proto, "_onclose_reason", "Connection already closed")
                    txaio.reject(done, TransportLost(reason))
                return

            # if e.g. an SSL handshake fails, we will have
            # successfully connected (i.e. get here) but need to
            # 'listen' for the "connection_lost" from the underlying
            # protocol in case of handshake failure .. so we wrap
            # it. Also, we don't increment transport.success_count
            # here on purpose (because we might not succeed).

            # XXX double-check that asyncio behavior on TLS handshake
            # failures is in fact as described above
            orig = proto.connection_lost

            @wraps(orig)
            def lost(fail):
                rtn = orig(fail)
                if not txaio.is_called(done):
                    # asyncio will call connection_lost(None) in case of
                    # a transport failure, in which case we create an
                    # appropriate exception
                    if fail is None:
                        fail = TransportLost("failed to complete connection")
                    txaio.reject(done, fail)
                return rtn
            proto.connection_lost = lost

        def on_connect_failure(err):
            transport.connect_failures += 1
            # failed to establish a connection in the first place
            txaio.reject(done, err)

        txaio.add_callbacks(conn_f, on_connect_success, None)
        # the errback is added as a second step so it gets called if
        # there as an error in on_connect_success itself.
        txaio.add_callbacks(conn_f, None, on_connect_failure)
        return conn_f

    # async function
    def start(self, loop=None):
        """
        This starts the Component, which means it will start connecting
        (and re-connecting) to its configured transports. A Component
        runs until it is "done", which means one of:
        - There was a "main" function defined, and it completed successfully;
        - Something called ``.leave()`` on our session, and we left successfully;
        - ``.stop()`` was called, and completed successfully;
        - none of our transports were able to connect successfully (failure);

        :returns: a Future which will resolve (to ``None``) when we are
            "done" or with an error if something went wrong.
        """

        if loop is None:
            self.log.warning("Using default loop")
            loop = asyncio.get_event_loop()

        return self._start(loop=loop)


def run(components, start_loop=True, log_level='info'):
    """
    High-level API to run a series of components.

    This will only return once all the components have stopped
    (including, possibly, after all re-connections have failed if you
    have re-connections enabled). Under the hood, this calls

    XXX fixme for asyncio

    -- if you wish to manage the loop yourself, use the
    :meth:`autobahn.asyncio.component.Component.start` method to start
    each component yourself.

    :param components: the Component(s) you wish to run
    :type components: instance or list of :class:`autobahn.asyncio.component.Component`

    :param start_loop: When ``True`` (the default) this method
        start a new asyncio loop.
    :type start_loop: bool

    :param log_level: a valid log-level (or None to avoid calling start_logging)
    :type log_level: string
    """

    # actually, should we even let people "not start" the logging? I'm
    # not sure that's wise... (double-check: if they already called
    # txaio.start_logging() what happens if we call it again?)
    if log_level is not None:
        txaio.start_logging(level=log_level)
    loop = asyncio.get_event_loop()
    if loop.is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        txaio.config.loop = loop
    log = txaio.make_logger()

    # see https://github.com/python/asyncio/issues/341 asyncio has
    # "odd" handling of KeyboardInterrupt when using Tasks (as
    # run_until_complete does). Another option is to just resture
    # default SIGINT handling, which is to exit:
    #   import signal
    #   signal.signal(signal.SIGINT, signal.SIG_DFL)

    async def nicely_exit(signal):
        log.info("Shutting down due to {signal}", signal=signal)

        try:
            tasks = asyncio.Task.all_tasks()
        except AttributeError:
            # this changed with python >= 3.7
            tasks = asyncio.all_tasks()

        for task in tasks:
            # Do not cancel the current task.

            try:
                current_task = asyncio.Task.current_task()
            except AttributeError:
                current_task = asyncio.current_task()

            if task is not current_task:
                task.cancel()

        def cancel_all_callback(fut):
            try:
                fut.result()
            except asyncio.CancelledError:
                log.debug("All task cancelled")
            except Exception as e:
                log.error("Error while shutting down: {exception}", exception=e)
            finally:
                loop.stop()

        fut = asyncio.gather(*tasks)
        fut.add_done_callback(cancel_all_callback)

    try:
        loop.add_signal_handler(signal.SIGINT, lambda: asyncio.ensure_future(nicely_exit("SIGINT")))
        loop.add_signal_handler(signal.SIGTERM, lambda: asyncio.ensure_future(nicely_exit("SIGTERM")))
    except NotImplementedError:
        # signals are not available on Windows
        pass

    def done_callback(loop, arg):
        loop.stop()

    # returns a future; could run_until_complete() but see below
    component._run(loop, components, done_callback)

    if start_loop:
        try:
            loop.run_forever()
            # this is probably more-correct, but then you always get
            # "Event loop stopped before Future completed":
            # loop.run_until_complete(f)
        except asyncio.CancelledError:
            pass
        # finally:
        #     signal.signal(signal.SIGINT, signal.SIG_DFL)
        #     signal.signal(signal.SIGTERM, signal.SIG_DFL)

        # Close the event loop at the end, otherwise an exception is
        # thrown. https://bugs.python.org/issue23548
        loop.close()
