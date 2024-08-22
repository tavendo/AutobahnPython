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
from typing import Union, Optional, Dict, Any, ClassVar, List, Callable

import txaio
import inspect
from functools import reduce

from autobahn import wamp
from autobahn.util import public, IdGenerator, ObservableMixin
from autobahn.wamp import uri
from autobahn.wamp import message
from autobahn.wamp import types
from autobahn.wamp import role
from autobahn.wamp import exception
from autobahn.wamp.exception import ApplicationError, ProtocolError, SerializationError, TypeCheckError
from autobahn.wamp.interfaces import ISession, IPayloadCodec, IAuthenticator, ITransport, IMessage  # noqa
from autobahn.wamp.types import Challenge, SessionDetails, CloseDetails, EncodedPayload, SubscribeOptions, \
    CallResult, RegisterOptions
from autobahn.exception import PayloadExceededError
from autobahn.wamp.request import \
    Publication, \
    Subscription, \
    Handler, \
    Registration, \
    Endpoint, \
    PublishRequest, \
    SubscribeRequest, \
    UnsubscribeRequest, \
    CallRequest, \
    InvocationRequest, \
    RegisterRequest, \
    UnregisterRequest


def is_method_or_function(f):
    return inspect.ismethod(f) or inspect.isfunction(f)


class BaseSession(ObservableMixin):
    """
    WAMP session base class.

    This class implements :class:`autobahn.wamp.interfaces.ISession`.
    """
    log = None

    def __init__(self):
        self.log = txaio.make_logger()

        self.set_valid_events(
            valid_events=[
                'join',         # right before onJoin runs
                'leave',        # after onLeave has run
                'ready',        # after onJoin and all 'join' listeners have completed
                'connect',      # right before onConnect
                'disconnect',   # right after onDisconnect
            ]
        )

        # this is for marshalling traceback from exceptions thrown in user
        # code within WAMP error messages (that is, when invoking remoted
        # procedures)
        self.traceback_app = False

        # mapping of exception classes to list of WAMP error URI patterns
        self._ecls_to_uri_pat: Dict[ClassVar, List[uri.Pattern]] = {}

        # mapping of WAMP error URIs to exception classes
        self._uri_to_ecls: Dict[str, ClassVar] = {
            ApplicationError.INVALID_PAYLOAD: SerializationError,
            ApplicationError.PAYLOAD_SIZE_EXCEEDED: PayloadExceededError,
        }

        # WAMP ITransport (_not_ a Twisted protocol, which is self.transport - when using Twisted)
        self._transport: Optional[ITransport] = None

        # session authentication information
        self._realm: Optional[str] = None
        self._session_id: Optional[int] = None
        self._authid: Optional[str] = None
        self._authrole: Optional[str] = None
        self._authmethod: Optional[str] = None
        self._authprovider: Optional[str] = None
        self._authextra: Optional[Dict[str, Any]] = None

        # set client role features supported and announced
        self._session_roles: Dict[str, role.RoleFeatures] = role.DEFAULT_CLIENT_ROLES

        # complete session details
        self._session_details: Optional[SessionDetails] = None

        # payload transparency codec
        self._payload_codec: Optional[IPayloadCodec] = None

        # generator for WAMP request IDs
        self._request_id_gen = IdGenerator()

    @property
    def transport(self) -> Optional[ITransport]:
        """
        Implements :func:`autobahn.wamp.interfaces.ITransportHandler.transport`
        """
        # Note: self._transport (which is a WAMP ITransport) is different from self.transport (which
        # is a Twisted protocol when using Twisted)!
        return self._transport

    @public
    def is_connected(self) -> bool:
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.is_connected`
        """
        return self._transport is not None and self._transport.isOpen()

    @public
    def is_attached(self) -> bool:
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.is_attached`
        """
        return self._session_id is not None and self.is_connected()

    @property
    def session_details(self) -> Optional[SessionDetails]:
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.session_details`
        """
        return self._session_details

    @property
    def realm(self) -> Optional[str]:
        return self._realm

    @property
    def session_id(self) -> Optional[int]:
        return self._session_id

    @property
    def authid(self) -> Optional[str]:
        return self._authid

    @property
    def authrole(self) -> Optional[str]:
        return self._authrole

    @property
    def authmethod(self) -> Optional[str]:
        return self._authmethod

    @property
    def authprovider(self) -> Optional[str]:
        return self._authprovider

    @property
    def authextra(self) -> Optional[Dict[str, Any]]:
        return self._authextra

    def define(self, exception: Exception, error: Optional[str] = None):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.define`
        """
        if error is None:
            if hasattr(exception, '_wampuris'):
                self._ecls_to_uri_pat[exception] = exception._wampuris
                self._uri_to_ecls[exception._wampuris[0].uri()] = exception
            else:
                raise RuntimeError('cannot define WAMP exception from class with no decoration ("_wampuris" unset)')
        else:
            if not hasattr(exception, '_wampuris'):
                self._ecls_to_uri_pat[exception] = [uri.Pattern(error, uri.Pattern.URI_TARGET_HANDLER)]
                self._uri_to_ecls[error] = exception
            else:
                raise RuntimeError('cannot define WAMP exception: error URI is explicit, but class is decorated ("_wampuris" set')

    def _message_from_exception(self, request_type, request, exc, tb=None, enc_algo=None):
        """
        Create a WAMP error message from an exception.

        :param request_type: The request type this WAMP error message is for.
        :type request_type: int

        :param request: The request ID this WAMP error message is for.
        :type request: int

        :param exc: The exception.
        :type exc: Instance of :class:`Exception` or subclass thereof.

        :param tb: Optional traceback. If present, it'll be included with the WAMP error message.
        :type tb: list or None
        """
        args = None
        if hasattr(exc, 'args'):
            args = list(exc.args)  # make sure tuples are made into lists

        kwargs = None
        if hasattr(exc, 'kwargs'):
            kwargs = exc.kwargs

        if tb:
            if kwargs:
                kwargs['traceback'] = tb
            else:
                kwargs = {'traceback': tb}

        if isinstance(exc, exception.ApplicationError):
            error = exc.error if type(exc.error) == str else exc.error
        else:
            if exc.__class__ in self._ecls_to_uri_pat:
                error = self._ecls_to_uri_pat[exc.__class__][0]._uri
            else:
                error = "wamp.error.runtime_error"

        encoded_payload = None
        if self._payload_codec:
            encoded_payload = self._payload_codec.encode(False, error, args, kwargs)

        if encoded_payload:
            msg = message.Error(request_type,
                                request,
                                error,
                                payload=encoded_payload.payload,
                                enc_algo=encoded_payload.enc_algo,
                                enc_key=encoded_payload.enc_key,
                                enc_serializer=encoded_payload.enc_serializer)
        else:
            msg = message.Error(request_type,
                                request,
                                error,
                                args,
                                kwargs)

        return msg

    def _exception_from_message(self, msg):
        """
        Create a user (or generic) exception from a WAMP error message.

        :param msg: A WAMP error message.
        :type msg: instance of :class:`autobahn.wamp.message.Error`
        """

        # FIXME:
        # 1. map to ecls based on error URI wildcard/prefix
        # 2. extract additional args/kwargs from error URI

        exc = None
        enc_err = None

        if msg.enc_algo:

            if not self._payload_codec:
                log_msg = "received encoded payload, but no payload codec active"
                self.log.warning(log_msg)
                enc_err = ApplicationError(ApplicationError.ENC_NO_PAYLOAD_CODEC, log_msg, enc_algo=msg.enc_algo)
            else:
                try:
                    encoded_payload = EncodedPayload(msg.payload, msg.enc_algo, msg.enc_serializer, msg.enc_key)
                    decrypted_error, msg.args, msg.kwargs = self._payload_codec.decode(True, msg.error, encoded_payload)
                except Exception as e:
                    self.log.warning("failed to decrypt application payload 1: {err}", err=e)
                    enc_err = ApplicationError(
                        ApplicationError.ENC_DECRYPT_ERROR,
                        "failed to decrypt application payload 1: {}".format(e),
                        enc_algo=msg.enc_algo,
                    )
                else:
                    if msg.error != decrypted_error:
                        self.log.warning(
                            "URI within encrypted payload ('{decrypted_error}') does not match the envelope ('{error}')",
                            decrypted_error=decrypted_error,
                            error=msg.error,
                        )
                        enc_err = ApplicationError(
                            ApplicationError.ENC_TRUSTED_URI_MISMATCH,
                            "URI within encrypted payload ('{}') does not match the envelope ('{}')".format(decrypted_error, msg.error),
                            enc_algo=msg.enc_algo,
                        )

        if enc_err:
            return enc_err

        if msg.error in self._uri_to_ecls:
            ecls = self._uri_to_ecls[msg.error]
            try:
                # the following might fail, eg. TypeError when
                # signature of exception constructor is incompatible
                # with args/kwargs or when the exception constructor raises
                if msg.kwargs:
                    if msg.args:
                        exc = ecls(*msg.args, **msg.kwargs)
                    else:
                        exc = ecls(**msg.kwargs)
                else:
                    if msg.args:
                        exc = ecls(*msg.args)
                    else:
                        exc = ecls()
            except Exception:
                try:
                    self.onUserError(
                        txaio.create_failure(),
                        "While re-constructing exception",
                    )
                except:
                    pass

        if not exc:
            # the following ctor never fails ..
            if msg.kwargs:
                if msg.args:
                    exc = exception.ApplicationError(msg.error, *msg.args, **msg.kwargs)
                else:
                    exc = exception.ApplicationError(msg.error, **msg.kwargs)
            else:
                if msg.args:
                    exc = exception.ApplicationError(msg.error, *msg.args)
                else:
                    exc = exception.ApplicationError(msg.error)

        # FIXME: cleanup and integate into ctors above
        if hasattr(exc, 'enc_algo'):
            exc.enc_algo = msg.enc_algo
        if hasattr(exc, 'callee'):
            exc.callee = msg.callee
        if hasattr(exc, 'callee_authid'):
            exc.callee_authid = msg.callee_authid
        if hasattr(exc, 'callee_authrole'):
            exc.callee_authrole = msg.callee_authrole
        if hasattr(exc, 'forward_for'):
            exc.forward_for = msg.forward_for

        return exc


@public
class ApplicationSession(BaseSession):
    """
    WAMP application session for applications (networking framework agnostic parts).

    Implements (partially):

        * :class:`autobahn.wamp.interfaces.ITransportHandler`
        * :class:`autobahn.wamp.interfaces.ISession`
    """

    def __init__(self, config: Optional[types.ComponentConfig] = None):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession`
        """
        BaseSession.__init__(self)
        self._config: types.ComponentConfig = config or types.ComponentConfig(realm="realm1")

        # for keeping transport-closing state
        self._goodbye_sent: bool = False
        self._transport_is_closing: bool = False

        # WAMP application payload codec (e.g. for WAMP-cryptobox E2E)
        self._payload_codec: Optional[IPayloadCodec] = None

        # outstanding requests
        self._publish_reqs = {}
        self._subscribe_reqs = {}
        self._unsubscribe_reqs = {}
        self._call_reqs = {}
        self._register_reqs = {}
        self._unregister_reqs = {}

        # subscriptions in place
        self._subscriptions = {}

        # registrations in place
        self._registrations = {}

        # incoming invocations
        self._invocations = {}

    @property
    def config(self) -> types.ComponentConfig:
        return self._config

    @public
    def set_payload_codec(self, payload_codec: Optional[IPayloadCodec]):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.set_payload_codec`
        """
        self._payload_codec = payload_codec

    @public
    def get_payload_codec(self) -> Optional[IPayloadCodec]:
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.get_payload_codec`
        """
        return self._payload_codec

    @public
    def onOpen(self, transport: ITransport):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransportHandler.onOpen`
        """
        self.log.debug('{func}(transport={transport})', func=self.onOpen, transport=transport)

        # The WAMP transport (e.g. WebSocket connection)
        self._transport = transport

        # FIXME: the observer API gets "transport" as argument, but _not_ the onConnect callback below?
        d = self.fire('connect', self, transport)
        txaio.add_callbacks(
            d, None,
            lambda fail: self._swallow_error(fail, "While notifying 'connect'")
        )
        txaio.add_callbacks(
            d,
            lambda _: txaio.as_future(self.onConnect),
            lambda fail: self._swallow_error(fail, "While calling 'onConnect'")
        )

    @public
    def onConnect(self):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.onConnect`
        """
        self.log.debug('{func}()', func=self.onConnect)
        self.join(self.config.realm)

    @public
    def join(self,
             realm: str,
             authmethods: Optional[List[str]] = None,
             authid: Optional[str] = None,
             authrole: Optional[str] = None,
             authextra: Optional[Dict[str, Any]] = None,
             resumable: Optional[bool] = None,
             resume_session: Optional[int] = None,
             resume_token: Optional[str] = None):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.join`
        """
        if self._session_id:
            raise Exception("session already joined")

        if not self._transport:
            raise Exception("no transport set for session")

        # store the realm requested by client, though this might be overwritten later,
        # when realm redirection kicks in
        self._realm = realm

        # closing handshake state
        self._goodbye_sent = False

        # send HELLO message to router
        msg = message.Hello(realm=realm,
                            roles=self._session_roles,
                            authmethods=authmethods,
                            authid=authid,
                            authrole=authrole,
                            authextra=authextra,
                            resumable=resumable,
                            resume_session=resume_session,
                            resume_token=resume_token)
        self._transport.send(msg)

    @public
    def disconnect(self):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.disconnect`
        """
        if self._transport:
            self._transport.close()

    @public
    def onUserError(self, fail, msg):
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.onUserError`
        """
        if hasattr(fail, 'value') and isinstance(fail.value, exception.ApplicationError):
            self.log.warning('{klass}.onUserError(): "{msg}"',
                             klass=self.__class__.__name__,
                             msg=fail.value.error_message())
        else:
            self.log.error(
                '{klass}.onUserError(): "{msg}"\n{traceback}',
                klass=self.__class__.__name__,
                msg=msg,
                traceback=txaio.failure_format_traceback(fail),
            )

    def _swallow_error(self, fail, msg):
        '''
        This is an internal generic error-handler for errors encountered
        when calling down to on*() handlers that can reasonably be
        expected to be overridden in user code.

        Note that it *cancels* the error, so use with care!

        Specifically, this should *never* be added to the errback
        chain for a Deferred/coroutine that will make it out to user
        code.
        '''
        try:
            self.onUserError(fail, msg)
        except Exception:
            self.log.error(
                "Internal error: {tb}",
                tb=txaio.failure_format_traceback(txaio.create_failure()),
            )
        return None

    def type_check(self, func):
        """
        Does parameter type checking and validation against type hints
        and appropriately tells the user code and the caller (through router).
        """
        async def _type_check(*args, **kwargs):
            # Converge both args and kwargs into a dictionary
            arguments = inspect.getcallargs(func, *args, **kwargs)
            response = []
            for name, kind in func.__annotations__.items():
                if name in arguments:
                    # if a "type" has __origin__ attribute it is a
                    # parameterized generic
                    if getattr(kind, "__origin__", None) == Union:
                        expected_types = [arg.__name__ for arg in kind.__args__]
                        if not isinstance(arguments[name], kind.__args__):
                            response.append(
                                "'{}' expected types={} got={}".format(name, expected_types,
                                                                       type(arguments[name]).__name__))
                    elif not isinstance(arguments[name], kind):
                        response.append(
                            "'{}' expected type={} got={}".format(name, kind.__name__, type(arguments[name]).__name__))
            if response:
                raise TypeCheckError(', '.join(response))
            return await txaio.as_future(func, *args, **kwargs)

        return _type_check

    def onMessage(self, msg: IMessage):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransportHandler.onMessage`
        """

        if self._session_id is None:

            # the first message must be WELCOME, ABORT or CHALLENGE ..
            if isinstance(msg, message.Welcome):

                # before we let user code see the session -- that is,
                # before we fire "join" -- we give authentication
                # instances a chance to abort the session. Usually
                # this would be for "mutual authentication"
                # scenarios. For example, WAMP-SCRAM uses this to
                # confirm the server-signature
                d = txaio.as_future(self.onWelcome, msg)

                def success(res):
                    if res is not None:
                        self.log.debug("Session denied by onWelcome: {res}", res=res)
                        reply = message.Abort(
                            "wamp.error.cannot_authenticate", "{0}".format(res)
                        )
                        self._transport.send(reply)
                        return

                    if msg.realm:
                        self._realm = msg.realm
                    self._session_id = msg.session
                    self._authid = msg.authid
                    self._authrole = msg.authrole
                    self._authmethod = msg.authmethod
                    self._authprovider = msg.authprovider
                    self._authextra = msg.authextra
                    self._router_roles = msg.roles

                    self._session_details = SessionDetails(
                        realm=self._realm,
                        session=self._session_id,
                        authid=self._authid,
                        authrole=self._authrole,
                        authmethod=self._authmethod,
                        authprovider=self._authprovider,
                        authextra=msg.authextra,
                        serializer=self._transport._serializer.SERIALIZER_ID,
                        transport=self._transport.transport_details,
                        # FIXME
                        resumed=False,  # msg.resumed,
                        resumable=False,  # msg.resumable,
                        resume_token=None,  # msg.resume_token,
                    )

                    # firing 'join' *before* running onJoin, so that
                    # the idiom where you "do stuff" in onJoin --
                    # possibly including self.leave() -- works
                    # properly. Besides, there's "ready" that fires
                    # after 'join' and onJoin have all completed...
                    d = self.fire('join', self, self._session_details)
                    # add a logging errback first, which will ignore any
                    # errors from fire()
                    txaio.add_callbacks(
                        d, None,
                        lambda e: self._swallow_error(e, "While notifying 'join'")
                    )
                    # this should run regardless
                    txaio.add_callbacks(
                        d,
                        lambda _: txaio.as_future(self.onJoin, self._session_details),
                        None
                    )
                    # ignore any errors from onJoin (XXX or, should that be fatal?)
                    txaio.add_callbacks(
                        d, None,
                        lambda e: self._swallow_error(e, "While firing onJoin")
                    )
                    # this instance is now "ready"...
                    txaio.add_callbacks(
                        d,
                        lambda _: self.fire('ready', self),
                        None
                    )
                    # ignore any errors from 'ready'
                    txaio.add_callbacks(
                        d, None,
                        lambda e: self._swallow_error(e, "While notifying 'ready'")
                    )

                def error(e):
                    reply = message.Abort(
                        "wamp.error.cannot_authenticate", "Error calling onWelcome handler"
                    )
                    self._transport.send(reply)
                    return self._swallow_error(e, "While firing onWelcome")
                txaio.add_callbacks(d, success, error)

            elif isinstance(msg, message.Abort):
                # fire callback and close the transport
                details = types.CloseDetails(msg.reason, msg.message)
                d = txaio.as_future(self.onLeave, details)

                def success(arg):
                    # XXX also: handle async
                    d = self.fire('leave', self, details)

                    def return_arg(_):
                        return arg

                    def _error(e):
                        return self._swallow_error(e, "While firing 'leave' event")
                    txaio.add_callbacks(d, return_arg, _error)
                    return d

                def _error(e):
                    return self._swallow_error(e, "While firing onLeave")
                txaio.add_callbacks(d, success, _error)

            elif isinstance(msg, message.Challenge):

                challenge = types.Challenge(msg.method, msg.extra)
                d = txaio.as_future(self.onChallenge, challenge)

                def success(signature):
                    if signature is None:
                        raise Exception('onChallenge user callback did not return a signature')
                    if type(signature) == bytes:
                        signature = signature.decode('utf8')
                    if type(signature) != str:
                        raise Exception('signature must be unicode (was {})'.format(type(signature)))
                    reply = message.Authenticate(signature)
                    self._transport.send(reply)

                def error(err):
                    self.onUserError(err, "Authentication failed")
                    reply = message.Abort("wamp.error.cannot_authenticate", "{0}".format(err.value))
                    self._transport.send(reply)
                    # fire callback and close the transport
                    details = types.CloseDetails(reply.reason, reply.message)
                    d = txaio.as_future(self.onLeave, details)

                    def success(arg):
                        # XXX also: handle async
                        self.fire('leave', self, details)
                        return arg

                    def _error(e):
                        return self._swallow_error(e, "While firing onLeave")
                    txaio.add_callbacks(d, success, _error)
                    # switching to the callback chain, effectively
                    # cancelling error (which we've now handled)
                    return d

                txaio.add_callbacks(d, success, error)

            else:
                raise ProtocolError("Received {0} message, and session is not yet established".format(msg.__class__))

        else:
            # self._session_id != None (aka "session established")
            if isinstance(msg, message.Goodbye):
                if not self._goodbye_sent:
                    # the peer wants to close: send GOODBYE reply
                    reply = message.Goodbye()
                    self._transport.send(reply)

                self._session_id = None

                # fire callback and close the transport
                details = types.CloseDetails(msg.reason, msg.message)
                d = txaio.as_future(self.onLeave, details)

                def success(arg):
                    # XXX also: handle async
                    self.fire('leave', self, details)
                    return arg

                def _error(e):
                    errmsg = 'While firing onLeave for reason "{0}" and message "{1}"'.format(msg.reason, msg.message)
                    return self._swallow_error(e, errmsg)
                txaio.add_callbacks(d, success, _error)

            elif isinstance(msg, message.Event):

                if msg.subscription in self._subscriptions:

                    # fire all event handlers on subscription ..
                    for subscription in self._subscriptions[msg.subscription]:

                        handler = subscription.handler
                        topic = msg.topic or subscription.topic

                        if msg.enc_algo:
                            # FIXME: behavior in error cases (no keyring, decrypt issues, URI mismatch, ..)
                            if not self._payload_codec:
                                self.log.warning("received encoded payload with enc_algo={enc_algo}, but no payload codec active - ignoring encoded payload!", enc_algo=msg.enc_algo)
                                return
                            else:
                                try:
                                    encoded_payload = EncodedPayload(msg.payload, msg.enc_algo, msg.enc_serializer, msg.enc_key)
                                    decoded_topic, msg.args, msg.kwargs = self._payload_codec.decode(False, topic, encoded_payload)
                                except Exception as e:
                                    self.log.warning("failed to decode application payload encoded with enc_algo={enc_algo}: {error}", error=e, enc_algo=msg.enc_algo)
                                    return
                                else:
                                    if topic != decoded_topic:
                                        self.log.warning("envelope topic URI does not match encoded one")
                                        return

                        invoke_args = (handler.obj,) if handler.obj else tuple()
                        if msg.args:
                            invoke_args = invoke_args + tuple(msg.args)
                        invoke_kwargs = msg.kwargs if msg.kwargs else dict()

                        if handler.details_arg:
                            invoke_kwargs[handler.details_arg] = types.EventDetails(subscription, msg.publication, publisher=msg.publisher, publisher_authid=msg.publisher_authid, publisher_authrole=msg.publisher_authrole, topic=topic, transaction_hash=msg.transaction_hash, retained=msg.retained, enc_algo=msg.enc_algo, forward_for=msg.forward_for)

                        # FIXME: https://github.com/crossbario/autobahn-python/issues/764
                        def _success(_):
                            # Acknowledged Events -- only if we got the details header and
                            # the broker advertised it
                            if msg.x_acknowledged_delivery and self._router_roles["broker"].x_acknowledged_event_delivery:
                                if self._transport:
                                    response = message.EventReceived(msg.publication)
                                    self._transport.send(response)
                                else:
                                    self.log.warning("successfully processed event with acknowledged delivery, but could not send ACK, since the transport was lost in the meantime")

                        def _error(e):
                            errmsg = 'While firing {0} subscribed under {1}.'.format(
                                handler.fn, msg.subscription)
                            return self._swallow_error(e, errmsg)

                        future = txaio.as_future(handler.fn, *invoke_args, **invoke_kwargs)
                        txaio.add_callbacks(future, _success, _error)

                else:
                    raise ProtocolError("EVENT received for non-subscribed subscription ID {0}".format(msg.subscription))

            elif isinstance(msg, message.Published):

                if msg.request in self._publish_reqs:

                    # get and pop outstanding publish request
                    publish_request = self._publish_reqs.pop(msg.request)

                    if txaio.is_future(publish_request.on_reply) and txaio.is_called(publish_request.on_reply):
                        return

                    # create a new publication object
                    publication = Publication(msg.publication, was_encrypted=publish_request.was_encrypted)

                    # resolve deferred/future for publishing successfully
                    txaio.resolve(publish_request.on_reply, publication)
                else:
                    raise ProtocolError("PUBLISHED received for non-pending request ID {0}".format(msg.request))

            elif isinstance(msg, message.Subscribed):

                if msg.request in self._subscribe_reqs:

                    # get and pop outstanding subscribe request
                    request = self._subscribe_reqs.pop(msg.request)

                    if txaio.is_future(request.on_reply) and txaio.is_called(request.on_reply):
                        return

                    # create new handler subscription list for subscription ID if not yet tracked
                    if msg.subscription not in self._subscriptions:
                        self._subscriptions[msg.subscription] = []

                    subscription = Subscription(msg.subscription, request.topic, self, request.handler)

                    # add handler to existing subscription
                    self._subscriptions[msg.subscription].append(subscription)

                    # resolve deferred/future for subscribing successfully
                    txaio.resolve(request.on_reply, subscription)
                else:
                    raise ProtocolError("SUBSCRIBED received for non-pending request ID {0}".format(msg.request))

            elif isinstance(msg, message.Unsubscribed):

                if msg.request in self._unsubscribe_reqs:

                    # get and pop outstanding subscribe request
                    request = self._unsubscribe_reqs.pop(msg.request)

                    if txaio.is_future(request.on_reply) and txaio.is_called(request.on_reply):
                        return

                    # if the subscription still exists, mark as inactive and remove ..
                    if request.subscription_id in self._subscriptions:
                        for subscription in self._subscriptions[request.subscription_id]:
                            subscription.active = False
                        del self._subscriptions[request.subscription_id]

                    # resolve deferred/future for unsubscribing successfully
                    txaio.resolve(request.on_reply, 0)
                else:
                    raise ProtocolError("UNSUBSCRIBED received for non-pending request ID {0}".format(msg.request))

            elif isinstance(msg, message.Result):

                if msg.request in self._call_reqs:

                    call_request = self._call_reqs[msg.request]
                    proc = call_request.procedure
                    enc_err = None

                    if msg.enc_algo:

                        if not self._payload_codec:
                            log_msg = "received encoded payload, but no payload codec active"
                            self.log.warning(log_msg)
                            enc_err = ApplicationError(ApplicationError.ENC_NO_PAYLOAD_CODEC, log_msg)
                        else:
                            try:
                                encoded_payload = EncodedPayload(msg.payload, msg.enc_algo, msg.enc_serializer, msg.enc_key)
                                decrypted_proc, msg.args, msg.kwargs = self._payload_codec.decode(True, proc, encoded_payload)
                            except Exception as e:
                                self.log.warning(
                                    "failed to decrypt application payload 1: {err}",
                                    err=e,
                                )
                                enc_err = ApplicationError(
                                    ApplicationError.ENC_DECRYPT_ERROR,
                                    "failed to decrypt application payload 1: {}".format(e),
                                )
                            else:
                                if proc != decrypted_proc:
                                    self.log.warning(
                                        "URI within encrypted payload ('{decrypted_proc}') does not match the envelope ('{proc}')",
                                        decrypted_proc=decrypted_proc,
                                        proc=proc,
                                    )
                                    enc_err = ApplicationError(
                                        ApplicationError.ENC_TRUSTED_URI_MISMATCH,
                                        "URI within encrypted payload ('{}') does not match the envelope ('{}')".format(decrypted_proc, proc),
                                    )

                    if msg.progress:
                        # process progressive call result

                        if call_request.options.on_progress:
                            if enc_err:
                                self.onUserError(enc_err, "could not deliver progressive call result, because payload decryption failed")
                            else:
                                kw = msg.kwargs or dict()
                                args = msg.args or tuple()

                                def _error(fail):
                                    self.onUserError(fail, "While firing on_progress")

                                if call_request.options and call_request.options.details:
                                    prog_d = txaio.as_future(call_request.options.on_progress,
                                                             types.CallResult(*msg.args,
                                                                              callee=msg.callee,
                                                                              callee_authid=msg.callee_authid,
                                                                              callee_authrole=msg.callee_authrole,
                                                                              forward_for=msg.forward_for,
                                                                              **msg.kwargs))
                                else:
                                    prog_d = txaio.as_future(call_request.options.on_progress,
                                                             *args,
                                                             **kw)

                                txaio.add_callbacks(prog_d, None, _error)

                    else:
                        # process final call result

                        # drop original request
                        del self._call_reqs[msg.request]

                        # user callback that gets fired
                        on_reply = call_request.on_reply

                        if txaio.is_future(on_reply) and txaio.is_called(on_reply):
                            return

                        # above might already have rejected, so we guard ..
                        if enc_err:
                            txaio.reject(on_reply, enc_err)
                        else:
                            if msg.kwargs or (call_request.options and call_request.options.details):
                                kwargs = msg.kwargs or {}
                                if msg.args:
                                    res = types.CallResult(*msg.args,
                                                           callee=msg.callee,
                                                           callee_authid=msg.callee_authid,
                                                           callee_authrole=msg.callee_authrole,
                                                           forward_for=msg.forward_for,
                                                           **kwargs)
                                else:
                                    res = types.CallResult(callee=msg.callee,
                                                           callee_authid=msg.callee_authid,
                                                           callee_authrole=msg.callee_authrole,
                                                           forward_for=msg.forward_for,
                                                           **kwargs)
                                txaio.resolve(on_reply, res)
                            else:
                                if msg.args:
                                    if len(msg.args) > 1:
                                        res = types.CallResult(*msg.args)
                                        txaio.resolve(on_reply, res)
                                    else:
                                        txaio.resolve(on_reply, msg.args[0])
                                else:
                                    txaio.resolve(on_reply, None)
                else:
                    raise ProtocolError("RESULT received for non-pending request ID {0}".format(msg.request))

            elif isinstance(msg, message.Invocation):

                if msg.request in self._invocations:

                    raise ProtocolError("INVOCATION received for request ID {0} already invoked".format(msg.request))

                else:

                    if msg.registration not in self._registrations:

                        raise ProtocolError("INVOCATION received for non-registered registration ID {0}".format(msg.registration))

                    else:
                        registration = self._registrations[msg.registration]
                        endpoint = registration.endpoint
                        proc = msg.procedure or registration.procedure
                        enc_err = None

                        if msg.enc_algo:
                            if not self._payload_codec:
                                log_msg = "received encrypted INVOCATION payload, but no keyring active"
                                self.log.warning(log_msg)
                                enc_err = ApplicationError(ApplicationError.ENC_NO_PAYLOAD_CODEC, log_msg)
                            else:
                                try:
                                    encoded_payload = EncodedPayload(msg.payload, msg.enc_algo, msg.enc_serializer, msg.enc_key)
                                    decrypted_proc, msg.args, msg.kwargs = self._payload_codec.decode(False, proc, encoded_payload)
                                except Exception as e:
                                    self.log.warning(
                                        "failed to decrypt INVOCATION payload: {err}",
                                        err=e,
                                    )
                                    enc_err = ApplicationError(
                                        ApplicationError.ENC_DECRYPT_ERROR,
                                        "failed to decrypt INVOCATION payload: {}".format(e),
                                    )
                                else:
                                    if proc != decrypted_proc:
                                        self.log.warning(
                                            "URI within encrypted INVOCATION payload ('{decrypted_proc}') "
                                            "does not match the envelope ('{proc}')",
                                            decrypted_proc=decrypted_proc,
                                            proc=proc,
                                        )
                                        enc_err = ApplicationError(
                                            ApplicationError.ENC_TRUSTED_URI_MISMATCH,
                                            "URI within encrypted INVOCATION payload ('{}') does not match the envelope ('{}')".format(decrypted_proc, proc),
                                        )

                        if enc_err:
                            # when there was a problem decrypting the INVOCATION payload, we obviously can't invoke
                            # the endpoint, but return and
                            reply = self._message_from_exception(message.Invocation.MESSAGE_TYPE, msg.request, enc_err)
                            self._transport.send(reply)

                        else:

                            if endpoint.obj is not None:
                                invoke_args = (endpoint.obj,)
                            else:
                                invoke_args = tuple()

                            if msg.args:
                                invoke_args = invoke_args + tuple(msg.args)

                            invoke_kwargs = msg.kwargs if msg.kwargs else dict()

                            if endpoint.details_arg:

                                if msg.receive_progress:

                                    def progress(*args, **kwargs):
                                        assert(args is None or type(args) in (list, tuple))
                                        assert(kwargs is None or type(kwargs) == dict)

                                        encoded_payload = None
                                        if msg.enc_algo:
                                            if not self._payload_codec:
                                                raise Exception("trying to send encrypted payload, but no keyring active")
                                            encoded_payload = self._payload_codec.encode(False, proc, args, kwargs)

                                        if encoded_payload:
                                            progress_msg = message.Yield(msg.request,
                                                                         payload=encoded_payload.payload,
                                                                         progress=True,
                                                                         enc_algo=encoded_payload.enc_algo,
                                                                         enc_key=encoded_payload.enc_key,
                                                                         enc_serializer=encoded_payload.enc_serializer)
                                        else:
                                            progress_msg = message.Yield(msg.request,
                                                                         args=args,
                                                                         kwargs=kwargs,
                                                                         progress=True)

                                        self._transport.send(progress_msg)
                                else:
                                    progress = None

                                invoke_kwargs[endpoint.details_arg] = types.CallDetails(registration,
                                                                                        progress=progress,
                                                                                        caller=msg.caller,
                                                                                        caller_authid=msg.caller_authid,
                                                                                        caller_authrole=msg.caller_authrole,
                                                                                        procedure=proc,
                                                                                        transaction_hash=msg.transaction_hash,
                                                                                        enc_algo=msg.enc_algo)

                            on_reply = txaio.as_future(endpoint.fn, *invoke_args, **invoke_kwargs)

                            def success(res):
                                del self._invocations[msg.request]

                                encoded_payload = None
                                if msg.enc_algo:
                                    if not self._payload_codec:
                                        log_msg = "trying to send encrypted payload, but no keyring active"
                                        self.log.warning(log_msg)
                                    else:
                                        try:
                                            if isinstance(res, types.CallResult):
                                                encoded_payload = self._payload_codec.encode(False, proc, res.results, res.kwresults)
                                            else:
                                                encoded_payload = self._payload_codec.encode(False, proc, [res])
                                        except Exception as e:
                                            self.log.warning(
                                                "failed to encrypt application payload: {err}",
                                                err=e,
                                            )

                                if encoded_payload:
                                    if isinstance(res, types.CallResult):
                                        reply = message.Yield(msg.request,
                                                              payload=encoded_payload.payload,
                                                              enc_algo=encoded_payload.enc_algo,
                                                              enc_key=encoded_payload.enc_key,
                                                              enc_serializer=encoded_payload.enc_serializer,
                                                              callee=res.callee,
                                                              callee_authid=res.callee_authid,
                                                              callee_authrole=res.callee_authrole,
                                                              forward_for=res.forward_for)
                                    else:
                                        reply = message.Yield(msg.request,
                                                              payload=encoded_payload.payload,
                                                              enc_algo=encoded_payload.enc_algo,
                                                              enc_key=encoded_payload.enc_key,
                                                              enc_serializer=encoded_payload.enc_serializer)
                                else:
                                    if isinstance(res, types.CallResult):
                                        reply = message.Yield(msg.request,
                                                              args=res.results,
                                                              kwargs=res.kwresults,
                                                              callee=res.callee,
                                                              callee_authid=res.callee_authid,
                                                              callee_authrole=res.callee_authrole,
                                                              forward_for=res.forward_for)
                                    else:
                                        reply = message.Yield(msg.request,
                                                              args=[res])

                                if self._transport is None:
                                    self.log.debug('Skipping result of "{}", request {} because transport disconnected.'.format(registration.procedure, msg.request))
                                    return

                                try:
                                    self._transport.send(reply)
                                except SerializationError as e:
                                    # the application-level payload returned from the invoked procedure can't be serialized
                                    error_reply = message.Error(message.Invocation.MESSAGE_TYPE, msg.request, ApplicationError.INVALID_PAYLOAD,
                                                                args=['success return value (args={}, kwargs={}) from invoked procedure "{}" could not be serialized: {}'.format(reply.args,
                                                                                                                                                                                 reply.kwargs,
                                                                                                                                                                                 registration.procedure,
                                                                                                                                                                                 e)])
                                    self._transport.send(error_reply)
                                except PayloadExceededError as e:
                                    # the application-level payload returned from the invoked procedure, when serialized and framed
                                    # for the transport, exceeds the transport message/frame size limit
                                    error_reply = message.Error(message.Invocation.MESSAGE_TYPE, msg.request, ApplicationError.PAYLOAD_SIZE_EXCEEDED,
                                                                args=['success return value (args={}, kwargs={}) from invoked procedure "{}" exceeds transport size limit: {}'.format(reply.args,
                                                                                                                                                                                      reply.kwargs,
                                                                                                                                                                                      registration.procedure,
                                                                                                                                                                                      e)])
                                    self._transport.send(error_reply)

                            def error(err):
                                del self._invocations[msg.request]

                                errmsg = txaio.failure_message(err)

                                try:
                                    self.onUserError(err, errmsg)
                                except:
                                    pass

                                formatted_tb = None
                                if self.traceback_app:
                                    formatted_tb = txaio.failure_format_traceback(err)

                                reply = self._message_from_exception(
                                    message.Invocation.MESSAGE_TYPE,
                                    msg.request,
                                    err.value,
                                    formatted_tb,
                                    msg.enc_algo
                                )

                                try:
                                    self._transport.send(reply)
                                except SerializationError as e:
                                    # the application-level payload returned from the invoked procedure can't be serialized
                                    reply = message.Error(message.Invocation.MESSAGE_TYPE, msg.request, ApplicationError.INVALID_PAYLOAD,
                                                          args=['error return value from invoked procedure "{0}" could not be serialized: {1}'.format(registration.procedure, e)])
                                    self._transport.send(reply)
                                except PayloadExceededError as e:
                                    # the application-level payload returned from the invoked procedure, when serialized and framed
                                    # for the transport, exceeds the transport message/frame size limit
                                    reply = message.Error(message.Invocation.MESSAGE_TYPE, msg.request, ApplicationError.PAYLOAD_SIZE_EXCEEDED,
                                                          args=['success return value from invoked procedure "{0}" exceeds transport size limit: {1}'.format(registration.procedure, e)])
                                    self._transport.send(reply)

                                # we have handled the error, so we eat it
                                return None

                            self._invocations[msg.request] = InvocationRequest(msg.request, on_reply)

                            txaio.add_callbacks(on_reply, success, error)

            elif isinstance(msg, message.Interrupt):

                if msg.request not in self._invocations:
                    # raise ProtocolError("INTERRUPT received for non-pending invocation {0}".format(msg.request))
                    self.log.debug('INTERRUPT received for non-pending invocation {request}', request=msg.request)
                else:
                    invoked = self._invocations[msg.request]
                    # this will result in a CancelledError which will
                    # be captured by the error handler around line 979
                    # to delete the invocation..
                    txaio.cancel(invoked.on_reply)

            elif isinstance(msg, message.Registered):

                if msg.request in self._register_reqs:

                    # get and pop outstanding register request
                    request = self._register_reqs.pop(msg.request)

                    if txaio.is_future(request.on_reply) and txaio.is_called(request.on_reply):
                        return

                    # create new registration if not yet tracked
                    if msg.registration not in self._registrations:
                        registration = Registration(self, msg.registration, request.procedure, request.endpoint)
                        self._registrations[msg.registration] = registration
                    else:
                        raise ProtocolError("REGISTERED received for already existing registration ID {0}".format(msg.registration))

                    txaio.resolve(request.on_reply, registration)
                else:
                    raise ProtocolError("REGISTERED received for non-pending request ID {0}".format(msg.request))

            elif isinstance(msg, message.Unregistered):

                if msg.request == 0:
                    # this is a forced un-register either from a call
                    # to the wamp.* meta-api or the force_reregister
                    # option
                    try:
                        reg = self._registrations[msg.registration]
                    except KeyError:
                        raise ProtocolError(
                            "UNREGISTERED received for non-existant registration"
                            " ID {0}".format(msg.registration)
                        )
                    self.log.debug(
                        "Router unregistered procedure '{proc}' with ID {id}",
                        proc=reg.procedure,
                        id=msg.registration,
                    )
                elif msg.request in self._unregister_reqs:

                    # get and pop outstanding subscribe request
                    request = self._unregister_reqs.pop(msg.request)

                    if txaio.is_future(request.on_reply) and txaio.is_called(request.on_reply):
                        return

                    # if the registration still exists, mark as inactive and remove ..
                    if request.registration_id in self._registrations:
                        self._registrations[request.registration_id].active = False
                        del self._registrations[request.registration_id]

                    # resolve deferred/future for unregistering successfully
                    txaio.resolve(request.on_reply)
                else:
                    raise ProtocolError("UNREGISTERED received for non-pending request ID {0}".format(msg.request))

            elif isinstance(msg, message.Error):

                # remove outstanding request and get the reply deferred/future
                on_reply = None

                # ERROR reply to CALL
                if msg.request_type == message.Call.MESSAGE_TYPE and msg.request in self._call_reqs:
                    on_reply = self._call_reqs.pop(msg.request).on_reply

                # ERROR reply to PUBLISH
                elif msg.request_type == message.Publish.MESSAGE_TYPE and msg.request in self._publish_reqs:
                    on_reply = self._publish_reqs.pop(msg.request).on_reply

                # ERROR reply to SUBSCRIBE
                elif msg.request_type == message.Subscribe.MESSAGE_TYPE and msg.request in self._subscribe_reqs:
                    on_reply = self._subscribe_reqs.pop(msg.request).on_reply

                # ERROR reply to UNSUBSCRIBE
                elif msg.request_type == message.Unsubscribe.MESSAGE_TYPE and msg.request in self._unsubscribe_reqs:
                    on_reply = self._unsubscribe_reqs.pop(msg.request).on_reply

                # ERROR reply to REGISTER
                elif msg.request_type == message.Register.MESSAGE_TYPE and msg.request in self._register_reqs:
                    on_reply = self._register_reqs.pop(msg.request).on_reply

                # ERROR reply to UNREGISTER
                elif msg.request_type == message.Unregister.MESSAGE_TYPE and msg.request in self._unregister_reqs:
                    on_reply = self._unregister_reqs.pop(msg.request).on_reply

                if on_reply:
                    if not txaio.is_called(on_reply):
                        txaio.reject(on_reply, self._exception_from_message(msg))
                else:
                    raise ProtocolError("WampAppSession.onMessage(): ERROR received for non-pending request_type {0} and request ID {1}".format(msg.request_type, msg.request))

            else:

                raise ProtocolError("Unexpected message {0}".format(msg.__class__))

    @public
    def onClose(self, wasClean):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransportHandler.onClose`
        """
        self._transport = None

        if self._session_id:
            # fire callback and close the transport
            details = types.CloseDetails(
                reason=types.CloseDetails.REASON_TRANSPORT_LOST,
                message='WAMP transport was lost without closing the session {} before'.format(self._session_id),
            )
            d = txaio.as_future(self.onLeave, details)

            def success(arg):
                # XXX also: handle async
                self.fire('leave', self, details)
                return arg

            def _error(e):
                return self._swallow_error(e, "While firing onLeave")
            txaio.add_callbacks(d, success, _error)

            self._session_id = None

        d = txaio.as_future(self.onDisconnect)

        def success(arg):
            # XXX do we care about returning 'arg' properly?
            return self.fire('disconnect', self, was_clean=wasClean)

        def _error(e):
            return self._swallow_error(e, "While firing onDisconnect")
        txaio.add_callbacks(d, success, _error)

    @public
    def onChallenge(self, challenge: Challenge) -> str:
        """
        Implements :func:`autobahn.wamp.interfaces.ISession.onChallenge`
        """
        # Note: if we use NotImplementedError in below, the type checking in PyCharm
        # will recognize that, and complain about "not implemented abstract method"
        # in e.g. autobahn.twisted.wamp.ApplicationSession even though the latter
        # derives from this base class! IOW: don't change it;)
        raise RuntimeError('received authentication challenge, but onChallenge not implemented')

    @public
    def onJoin(self, details: SessionDetails):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onJoin`
        """

    @public
    def onWelcome(self, welcome: message.Welcome) -> Optional[str]:
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onWelcome`
        """

    def _errback_outstanding_requests(self, exc):
        """
        Errback any still outstanding requests with exc.
        """
        d = txaio.create_future_success(None)
        all_requests = [
            self._publish_reqs,
            self._subscribe_reqs,
            self._unsubscribe_reqs,
            self._call_reqs,
            self._register_reqs,
            self._unregister_reqs
        ]
        outstanding = []
        for requests in all_requests:
            outstanding.extend(requests.values())
            requests.clear()

        if outstanding:
            self.log.info(
                'Cancelling {count} outstanding requests',
                count=len(outstanding),
            )
        for request in outstanding:
            self.log.debug(
                'cleaning up outstanding {request_type} request {request_id}, '
                'firing errback on user handler {request_on_reply}',
                request_on_reply=request.on_reply,
                request_id=request.request_id,
                request_type=request.__class__.__name__,
            )
            if not txaio.is_called(request.on_reply):
                txaio.reject(request.on_reply, exc)

            # wait for any async-ness in the error handlers for on_reply
            txaio.add_callbacks(d, lambda _: request.on_reply, lambda _: request.on_reply)
        return d

    @public
    def onLeave(self, details: CloseDetails):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onLeave`
        """
        if details.reason != CloseDetails.REASON_DEFAULT:
            self.log.warning('session closed with reason {reason} [{message}]', reason=details.reason, message=details.message)

        # fire ApplicationError on any currently outstanding requests
        exc = ApplicationError(details.reason, details.message)
        d = self._errback_outstanding_requests(exc)

        def disconnect(_):
            if self._transport:
                self.disconnect()
        txaio.add_callbacks(d, disconnect, disconnect)
        return d

    @public
    def leave(self, reason: Optional[str] = None, message: Optional[str] = None):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.leave`
        """
        if not self._session_id:
            self.log.warning('session is not joined on a realm - no session to leave')
            return

        if not self._goodbye_sent:
            if not reason:
                reason = "wamp.close.normal"
            msg = wamp.message.Goodbye(reason=reason, message=message)
            self._transport.send(msg)
            self._goodbye_sent = True
        else:
            self.log.warning('session was already requested to leave - not sending GOODBYE again')

        is_closed = self._transport is None or self._transport.is_closed

        return is_closed

    @public
    def onDisconnect(self):
        """
        Implements :meth:`autobahn.wamp.interfaces.ISession.onDisconnect`
        """
        # fire TransportLost on any _still_ outstanding requests
        # (these should have been already cleaned up in onLeave() - when
        # this actually has fired)
        exc = exception.TransportLost()
        self._errback_outstanding_requests(exc)

    # FIXME:
    # def publish(self, topic: str, *args: Optional[List[Any]], **kwargs: Optional[Dict[str, Any]]) -> Optional[Publication]:

    @public
    def publish(self, topic: str, *args, **kwargs) -> Optional[Publication]:
        """
        Implements :meth:`autobahn.wamp.interfaces.IPublisher.publish`
        """
        assert(type(topic) == str)
        assert(args is None or type(args) in (list, tuple))
        assert(kwargs is None or type(kwargs) == dict)

        message.check_or_raise_uri(topic,
                                   message='{}.publish()'.format(self.__class__.__name__),
                                   strict=False,
                                   allow_empty_components=False,
                                   allow_none=False)

        options = kwargs.pop('options', None)
        if options and not isinstance(options, types.PublishOptions):
            raise Exception("options must be of type a.w.t.PublishOptions")

        if not self._transport:
            raise exception.TransportLost()

        request_id = self._request_id_gen.next()

        encoded_payload = None
        if self._payload_codec:
            encoded_payload = self._payload_codec.encode(True, topic, args, kwargs)

        if encoded_payload:
            if options:
                msg = message.Publish(request_id,
                                      topic,
                                      payload=encoded_payload.payload,
                                      enc_algo=encoded_payload.enc_algo,
                                      enc_key=encoded_payload.enc_key,
                                      enc_serializer=encoded_payload.enc_serializer,
                                      **options.message_attr())
            else:
                msg = message.Publish(request_id,
                                      topic,
                                      payload=encoded_payload.payload,
                                      enc_algo=encoded_payload.enc_algo,
                                      enc_key=encoded_payload.enc_key,
                                      enc_serializer=encoded_payload.enc_serializer)
        else:
            if options:
                msg = message.Publish(request_id,
                                      topic,
                                      args=args,
                                      kwargs=kwargs,
                                      **options.message_attr())
            else:
                msg = message.Publish(request_id,
                                      topic,
                                      args=args,
                                      kwargs=kwargs)

        if options:
            if options.correlation_id is not None:
                msg.correlation_id = options.correlation_id
            if options.correlation_uri is not None:
                msg.correlation_uri = options.correlation_uri
            if options.correlation_is_anchor is not None:
                msg.correlation_is_anchor = options.correlation_is_anchor
            if options.correlation_is_last is not None:
                msg.correlation_is_last = options.correlation_is_last

        if options and options.acknowledge:
            # only acknowledged publications expect a reply ..
            on_reply = txaio.create_future()
            self._publish_reqs[request_id] = PublishRequest(request_id, on_reply, was_encrypted=(encoded_payload is not None))
        else:
            on_reply = None

        try:
            # Notes:
            #
            # * this might raise autobahn.wamp.exception.SerializationError
            #   when the user payload cannot be serialized
            # * we have to setup a PublishRequest() in _publish_reqs _before_
            #   calling transpor.send(), because a mock- or side-by-side transport
            #   will immediately lead on an incoming WAMP message in onMessage()
            #
            self._transport.send(msg)
        except Exception as e:
            if request_id in self._publish_reqs:
                del self._publish_reqs[request_id]
            raise e

        return on_reply

    @public
    def subscribe(self, handler: Union[Callable, Any], topic: Optional[str] = None,
                  options: Optional[SubscribeOptions] = None, check_types: Optional[bool] = None) -> \
            Union[Subscription, List[Subscription]]:
        """
        Implements :meth:`autobahn.wamp.interfaces.ISubscriber.subscribe`
        """
        assert((callable(handler) and topic is not None) or (hasattr(handler, '__class__') and not check_types))
        assert(topic is None or type(topic) == str)
        assert(options is None or isinstance(options, types.SubscribeOptions))

        if not self._transport:
            raise exception.TransportLost()

        def _subscribe(obj, fn, topic, options, check_types):
            message.check_or_raise_uri(topic,
                                       message='{}.subscribe()'.format(self.__class__.__name__),
                                       strict=False,
                                       allow_empty_components=True,
                                       allow_none=False)

            request_id = self._request_id_gen.next()
            on_reply = txaio.create_future()
            if check_types:
                fn = self.type_check(fn)
            handler_obj = Handler(fn, obj, options.details_arg if options else None)
            self._subscribe_reqs[request_id] = SubscribeRequest(request_id, topic, on_reply, handler_obj)

            if options:
                msg = message.Subscribe(request_id, topic, **options.message_attr())
            else:
                msg = message.Subscribe(request_id, topic)

            if options:
                if options.correlation_id is not None:
                    msg.correlation_id = options.correlation_id
                if options.correlation_uri is not None:
                    msg.correlation_uri = options.correlation_uri
                if options.correlation_is_anchor is not None:
                    msg.correlation_is_anchor = options.correlation_is_anchor
                if options.correlation_is_last is not None:
                    msg.correlation_is_last = options.correlation_is_last

            self._transport.send(msg)
            return on_reply

        if callable(handler):
            # subscribe a single handler
            return _subscribe(None, handler, topic, options, check_types)

        else:

            # subscribe all methods on an object decorated with "wamp.subscribe"
            on_replies = []
            for k in inspect.getmembers(handler.__class__, is_method_or_function):
                proc = k[1]
                if "_wampuris" in proc.__dict__:
                    for pat in proc.__dict__["_wampuris"]:
                        if pat.is_handler():
                            _uri = pat.uri()
                            subopts = pat.options or options
                            if subopts is None:
                                if pat.uri_type == uri.Pattern.URI_TYPE_WILDCARD:
                                    subopts = types.SubscribeOptions(match="wildcard")
                                else:
                                    subopts = types.SubscribeOptions(match="exact")
                            on_replies.append(_subscribe(handler, proc, _uri, subopts, pat._check_types))

            return txaio.gather(on_replies, consume_exceptions=True)

    def _unsubscribe(self, subscription):
        """
        Called from :meth:`autobahn.wamp.protocol.Subscription.unsubscribe`
        """
        assert(isinstance(subscription, Subscription))
        assert subscription.active
        assert(subscription.id in self._subscriptions)
        assert(subscription in self._subscriptions[subscription.id])

        if not self._transport:
            raise exception.TransportLost()

        # remove handler subscription and mark as inactive
        self._subscriptions[subscription.id].remove(subscription)
        subscription.active = False

        # number of handler subscriptions left ..
        scount = len(self._subscriptions[subscription.id])

        if scount == 0:
            # if the last handler was removed, unsubscribe from broker ..
            request_id = self._request_id_gen.next()

            on_reply = txaio.create_future()
            self._unsubscribe_reqs[request_id] = UnsubscribeRequest(request_id, on_reply, subscription.id)

            msg = message.Unsubscribe(request_id, subscription.id)

            self._transport.send(msg)
            return on_reply
        else:
            # there are still handlers active on the subscription!
            return txaio.create_future_success(scount)

    @public
    def call(self, procedure: str, *args, **kwargs) -> Union[Any, CallResult]:
        """
        Implements :meth:`autobahn.wamp.interfaces.ICaller.call`

        .. note::

            Regarding type hints for ``*args`` and ``**kwargs``, doesn't work as we
            can receive any Python types as list items or dict values, and because
            of what is discussed here
            https://adamj.eu/tech/2021/05/11/python-type-hints-args-and-kwargs/
        """
        assert(type(procedure) == str)
        assert(args is None or type(args) in (list, tuple))
        assert(kwargs is None or type(kwargs) == dict)

        message.check_or_raise_uri(procedure,
                                   message='{}.call()'.format(self.__class__.__name__),
                                   strict=False,
                                   allow_empty_components=False,
                                   allow_none=False)

        options = kwargs.pop('options', None)
        if options and not isinstance(options, types.CallOptions):
            raise Exception("options must be of type a.w.t.CallOptions")

        if not self._transport:
            raise exception.TransportLost()

        request_id = self._request_id_gen.next()

        encoded_payload = None
        if self._payload_codec:
            try:
                encoded_payload = self._payload_codec.encode(True, procedure, args, kwargs)
            except:
                self.log.failure()
                raise

        if encoded_payload:
            if options:
                msg = message.Call(request_id,
                                   procedure,
                                   payload=encoded_payload.payload,
                                   enc_algo=encoded_payload.enc_algo,
                                   enc_key=encoded_payload.enc_key,
                                   enc_serializer=encoded_payload.enc_serializer,
                                   **options.message_attr())
            else:
                msg = message.Call(request_id,
                                   procedure,
                                   payload=encoded_payload.payload,
                                   enc_algo=encoded_payload.enc_algo,
                                   enc_key=encoded_payload.enc_key,
                                   enc_serializer=encoded_payload.enc_serializer)
        else:
            if options:
                msg = message.Call(request_id,
                                   procedure,
                                   args=args,
                                   kwargs=kwargs,
                                   **options.message_attr())
            else:
                msg = message.Call(request_id,
                                   procedure,
                                   args=args,
                                   kwargs=kwargs)

        if options:
            if options.correlation_id is not None:
                msg.correlation_id = options.correlation_id
            if options.correlation_uri is not None:
                msg.correlation_uri = options.correlation_uri
            if options.correlation_is_anchor is not None:
                msg.correlation_is_anchor = options.correlation_is_anchor
            if options.correlation_is_last is not None:
                msg.correlation_is_last = options.correlation_is_last

        def canceller(d):
            cancel_msg = message.Cancel(request_id)
            self._transport.send(cancel_msg)
            # since we announced support for cancelling, we should
            # definitely get an Error back for our Cancel which will
            # clean up this invocation

        on_reply = txaio.create_future(canceller=canceller)
        self._call_reqs[request_id] = CallRequest(request_id, procedure, on_reply, options)

        try:
            # Notes:
            #
            # * this might raise autobahn.wamp.exception.SerializationError
            #   when the user payload cannot be serialized
            # * we have to setup a CallRequest() in _call_reqs _before_
            #   calling transpor.send(), because a mock- or side-by-side transport
            #   will immediately lead on an incoming WAMP message in onMessage()
            #
            self._transport.send(msg)
        except:
            if request_id in self._call_reqs:
                del self._call_reqs[request_id]
            raise

        return on_reply

    @public
    def register(self, endpoint: Union[Callable, Any], procedure: Optional[str] = None,
                 options: Optional[RegisterOptions] = None, prefix: Optional[str] = None,
                 check_types: Optional[bool] = None) -> Union[Registration, List[Registration]]:
        """
        Implements :meth:`autobahn.wamp.interfaces.ICallee.register`
        """
        assert((callable(endpoint) and procedure is not None) or (hasattr(endpoint, '__class__') and not check_types))

        if not self._transport:
            raise exception.TransportLost()

        def _register(obj, fn, procedure, options, check_types):
            message.check_or_raise_uri(procedure,
                                       message='{}.register()'.format(self.__class__.__name__),
                                       strict=False,
                                       allow_empty_components=True,
                                       allow_none=False)

            request_id = self._request_id_gen.next()
            on_reply = txaio.create_future()
            if check_types:
                fn = self.type_check(fn)
            endpoint_obj = Endpoint(fn, obj, options.details_arg if options else None)
            if prefix is not None:
                procedure = "{}{}".format(prefix, procedure)
            self._register_reqs[request_id] = RegisterRequest(request_id, on_reply, procedure, endpoint_obj)

            if options:
                msg = message.Register(request_id, procedure, **options.message_attr())
            else:
                msg = message.Register(request_id, procedure)

            if options:
                if options.correlation_id is not None:
                    msg.correlation_id = options.correlation_id
                if options.correlation_uri is not None:
                    msg.correlation_uri = options.correlation_uri
                if options.correlation_is_anchor is not None:
                    msg.correlation_is_anchor = options.correlation_is_anchor
                if options.correlation_is_last is not None:
                    msg.correlation_is_last = options.correlation_is_last

            self._transport.send(msg)
            return on_reply

        if callable(endpoint):

            # register a single callable
            return _register(None, endpoint, procedure, options, check_types)

        else:

            # register all methods on an object decorated with "wamp.register"
            on_replies = []
            for k in inspect.getmembers(endpoint.__class__, is_method_or_function):
                proc = k[1]
                if "_wampuris" in proc.__dict__:
                    for pat in proc.__dict__["_wampuris"]:
                        if pat.is_endpoint():
                            _uri = pat.uri()
                            regopts = pat.options or options
                            on_replies.append(_register(endpoint, proc, _uri, regopts, pat._check_types))

            return txaio.gather(on_replies, consume_exceptions=True)

    def _unregister(self, registration):
        """
        Called from :meth:`autobahn.wamp.protocol.Registration.unregister`
        """
        assert(isinstance(registration, Registration))
        assert registration.active
        assert(registration.id in self._registrations)

        if not self._transport:
            raise exception.TransportLost()

        request_id = self._request_id_gen.next()

        on_reply = txaio.create_future()
        self._unregister_reqs[request_id] = UnregisterRequest(request_id, on_reply, registration.id)

        msg = message.Unregister(request_id, registration.id)

        self._transport.send(msg)
        return on_reply


class _SessionShim(ApplicationSession):
    """
    shim that lets us present pep8 API for user-classes to override,
    but also backwards-compatible for existing code using
    ApplicationSession "directly".

    **NOTE:** this is not public or intended for use; you should import
    either autobahn.asyncio.wamp.Session or
    autobahn.twisted.wamp.Session depending on which async
    framework yo're using.
    """

    #: name -> IAuthenticator
    _authenticators = None

    def onJoin(self, details):
        return self.on_join(details)

    def onConnect(self):
        if self._authenticators:
            # authid, authrole *must* match across all authenticators
            # (checked in add_authenticator) so these lists are either
            # [None] or [None, 'some_authid']
            authid = [x._args.get('authid', None) for x in self._authenticators.values()][-1]
            authrole = [x._args.get('authrole', None) for x in self._authenticators.values()][-1]
            # we need a "merged" authextra here because we can send a
            # list of acceptable authmethods, but only a single
            # authextra dict
            authextra = self._merged_authextra()
            self.join(
                self.config.realm,
                authmethods=list(self._authenticators.keys()),
                authid=authid,
                authrole=authrole,
                authextra=authextra,
            )
        else:
            self.on_connect()

    def onChallenge(self, challenge):
        try:
            authenticator = self._authenticators[challenge.method]
        except KeyError:
            raise RuntimeError(
                "Received challenge for unknown authmethod '{}' [authenticators={}]".format(
                    challenge.method,
                    str(sorted(self._authenticators.keys()))
                )
            )
        return authenticator.on_challenge(self, challenge)

    def onWelcome(self, msg):
        if msg.authmethod is None or self._authenticators is None:
            # no authentication
            return
        try:
            authenticator = self._authenticators[msg.authmethod]
        except KeyError:
            raise RuntimeError(
                "Received onWelcome for unknown authmethod '{}' [authenticators={}]".format(
                    msg.authmethod,
                    str(sorted(self._authenticators.keys()))
                )
            )
        return authenticator.on_welcome(self, msg.authextra)

    def onLeave(self, details):
        return self.on_leave(details)

    def onDisconnect(self):
        return self.on_disconnect()

    # experimental authentication API

    def add_authenticator(self, authenticator):
        assert isinstance(authenticator, IAuthenticator)
        if self._authenticators is None:
            self._authenticators = {}

        # before adding this authenticator we need to validate that
        # it's consistent with any other authenticators we may have --
        # for example, they must all agree on "authid" etc because
        # .join() only takes one value for all of those.

        def at_most_one(name):
            uni = set([
                a._args[name]
                for a in list(self._authenticators.values()) + [authenticator]
                if name in a._args
            ])
            if len(uni) > 1:
                raise ValueError(
                    "Inconsistent {}s: {}".format(
                        name,
                        ' '.join(uni),
                    )
                )

        # all authids must match
        at_most_one('authid')

        # all authroles must match
        at_most_one('authrole')

        # can we do anything else other than merge all authextra keys?
        # here we check that any duplicate keys have the same values
        authextra = authenticator.authextra
        merged = self._merged_authextra()
        for k, v in merged.items():
            if k in authextra and authextra[k] != v:
                raise ValueError(
                    "Inconsistent authextra values for '{}': '{}' vs '{}'".format(
                        k, v, authextra[k],
                    )
                )

        # validation complete, add it
        self._authenticators[authenticator.name] = authenticator

    def _merged_authextra(self):
        """
        internal helper

        :returns: a single 'authextra' dict, consisting of all keys
            from any authenticator's authextra.

        Note that when the authenticator was added, we already checked
        that any keys it does contain has the same value as any
        existing authextra.
        """
        authextras = [a.authextra for a in self._authenticators.values()]

        def extract_keys(x, y):
            return x | set(y.keys())

        unique_keys = reduce(extract_keys, authextras, set())

        def first_value_for(k):
            """
            for anything already in self._authenticators, we checked
            that it has the same value for any keys in its authextra --
            so here we just extract the first one
            """
            for authextra in authextras:
                if k in authextra:
                    return authextra[k]
            # "can't" happen
            raise ValueError(
                "No values for '{}'".format(k)
            )

        return {
            k: first_value_for(k)
            for k in unique_keys
        }

    # these are the actual "new API" methods (i.e. snake_case)
    #

    def on_join(self, details):
        pass

    def on_leave(self, details):
        self.disconnect()

    def on_connect(self):
        self.join(self.config.realm)

    def on_disconnect(self):
        pass


# ISession.register collides with the abc.ABCMeta.register method
ISession.abc_register(ApplicationSession)


class ApplicationSessionFactory(object):
    """
    WAMP endpoint session factory.
    """

    session = ApplicationSession
    """
    WAMP application session class to be used in this factory.
    """

    def __init__(self, config=None):
        """

        :param config: The default component configuration.
        :type config: instance of :class:`autobahn.wamp.types.ComponentConfig`
        """
        self.config = config or types.ComponentConfig(realm="realm1")

    def __call__(self):
        """
        Creates a new WAMP application session.

        :returns: -- An instance of the WAMP application session class as
                     given by `self.session`.
        """
        session = self.session(self.config)
        session.factory = self
        return session
