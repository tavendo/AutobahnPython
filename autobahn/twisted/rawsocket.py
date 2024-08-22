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

import copy
import math
from typing import Optional

import txaio

from twisted.internet.protocol import Factory
from twisted.protocols.basic import Int32StringReceiver
from twisted.internet.error import ConnectionDone
from twisted.internet.defer import CancelledError

from autobahn.util import public, _LazyHexFormatter
from autobahn.twisted.util import create_transport_details, transport_channel_id
from autobahn.wamp.types import TransportDetails
from autobahn.wamp.exception import ProtocolError, SerializationError, TransportLost, InvalidUriError
from autobahn.exception import PayloadExceededError

__all__ = (
    'WampRawSocketServerProtocol',
    'WampRawSocketClientProtocol',
    'WampRawSocketServerFactory',
    'WampRawSocketClientFactory'
)


class WampRawSocketProtocol(Int32StringReceiver):
    """
    Base class for Twisted-based WAMP-over-RawSocket protocols.
    """
    log = txaio.make_logger()

    peer: Optional[str] = None
    is_server: Optional[bool] = None

    def __init__(self):
        # set the RawSocket maximum message size by default
        self._max_message_size = 2**24
        self._transport_details = None

    @property
    def transport_details(self) -> Optional[TransportDetails]:
        """
        Implements :func:`autobahn.wamp.interfaces.ITransport.transport_details`
        """
        return self._transport_details

    def lengthLimitExceeded(self, length):
        # override hook in Int32StringReceiver base class that is fired when a message is (to be) received
        # that is larger than what we agreed to handle (by negotiation in the RawSocket opening handshake)
        emsg = 'RawSocket connection: length of received message exceeded (message was {} bytes, but current maximum is {} bytes)'.format(length, self.MAX_LENGTH)
        raise PayloadExceededError(emsg)

    def connectionMade(self):
        # Twisted networking framework entry point, called by Twisted
        # when the connection is established (either a client or a server)

        # determine preliminary transport details (what is know at this point)
        self._transport_details = create_transport_details(self.transport, self.is_server)
        self._transport_details.channel_framing = TransportDetails.CHANNEL_FRAMING_RAWSOCKET

        # backward compatibility
        self.peer = self._transport_details.peer

        # a Future/Deferred that fires when we hit STATE_CLOSED
        self.is_closed = txaio.create_future()

        # this will hold an ApplicationSession object
        # once the RawSocket opening handshake has been
        # completed
        #
        self._session = None

        # Will hold the negotiated serializer once the opening handshake is complete
        #
        self._serializer = None

        # Will be set to True once the opening handshake is complete
        #
        self._handshake_complete = False

        # Buffer for opening handshake received bytes.
        #
        self._handshake_bytes = b''

        # Peer requested to _receive_ this maximum length of serialized messages - hence we must not send larger msgs!
        #
        self._max_len_send = None

    def _on_handshake_complete(self):
        # RawSocket connection established. Now let the user WAMP session factory
        # create a new WAMP session and fire off session open callback.
        try:
            if self._transport_details.is_secure:
                # now that the TLS opening handshake is complete, the actual TLS channel ID
                # will be available. make sure to set it!
                channel_id = {
                    'tls-unique': transport_channel_id(self.transport, self._transport_details.is_server, 'tls-unique'),
                }
                self._transport_details.channel_id = channel_id

            self._session = self.factory._factory()
            self.log.debug('{klass}._on_handshake_complete(): calling {method}', session=self._session,
                           klass=self.__class__.__name__, method=self._session.onOpen)
            res = self._session.onOpen(self)
        except Exception as e:
            # Exceptions raised in onOpen are fatal ..
            self.log.warning("{klass}._on_handshake_complete(): ApplicationSession constructor / onOpen raised ({err})",
                             klass=self.__class__.__name__, err=e)
            self.abort()
        else:
            self.log.debug('{klass}._on_handshake_complete(): {session} started (res={res}).',
                           klass=self.__class__.__name__,
                           session=self._session, res=res)

    def connectionLost(self, reason):
        self.log.debug('{klass}.connectionLost(reason="{reason}"', klass=self.__class__.__name__, reason=reason)
        txaio.resolve(self.is_closed, self)
        try:
            wasClean = isinstance(reason.value, ConnectionDone)
            if self._session:
                self._session.onClose(wasClean)
        except Exception as e:
            # silently ignore exceptions raised here ..
            self.log.warning('{klass}.connectionLost(): ApplicationSession.onClose raised "{err}"',
                             klass=self.__class__.__name__, err=e)
        self._session = None

    def stringReceived(self, payload):
        self.log.trace('{klass}.stringReceived(): RX {octets} octets',
                       klass=self.__class__.__name__, octets=_LazyHexFormatter(payload))
        try:
            for msg in self._serializer.unserialize(payload):
                self.log.trace("{klass}.stringReceived: RX WAMP message: {msg}",
                               klass=self.__class__.__name__, msg=msg)
                self._session.onMessage(msg)

        except CancelledError as e:
            self.log.debug("{klass}.stringReceived: WAMP CancelledError - connection will continue!\n{err}",
                           klass=self.__class__.__name__,
                           err=e)

        except InvalidUriError as e:
            self.log.warning("{klass}.stringReceived: WAMP InvalidUriError - aborting connection!\n{err}",
                             klass=self.__class__.__name__,
                             err=e)
            self.abort()

        except ProtocolError as e:
            self.log.warning("{klass}.stringReceived: WAMP ProtocolError - aborting connection!\n{err}",
                             klass=self.__class__.__name__,
                             err=e)
            self.abort()

        except PayloadExceededError as e:
            self.log.warning("{klass}.stringReceived: WAMP PayloadExceededError - aborting connection!\n{err}",
                             klass=self.__class__.__name__,
                             err=e)
            self.abort()

        except SerializationError as e:
            self.log.warning("{klass}.stringReceived: WAMP SerializationError - aborting connection!\n{err}",
                             klass=self.__class__.__name__,
                             err=e)
            self.abort()

        except Exception as e:
            self.log.failure()
            self.log.warning("{klass}.stringReceived: WAMP Exception - aborting connection!\n{err}",
                             klass=self.__class__.__name__,
                             err=e)
            self.abort()

    def send(self, msg):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransport.send`
        """
        if self.isOpen():
            self.log.trace('{klass}.send() (serializer={serializer}): TX WAMP message: "{msg}"',
                           klass=self.__class__.__name__, msg=msg, serializer=self._serializer)
            try:
                payload, _ = self._serializer.serialize(msg)
            except SerializationError as e:
                # all exceptions raised from above should be serialization errors ..
                raise SerializationError("WampRawSocketProtocol: unable to serialize WAMP application payload ({0})".format(e))
            else:
                payload_len = len(payload)
                if 0 < self._max_len_send < payload_len:
                    emsg = 'tried to send RawSocket message with size {} exceeding payload limit of {} octets'.format(
                        payload_len, self._max_len_send)
                    self.log.warning(emsg)
                    raise PayloadExceededError(emsg)
                else:
                    self.sendString(payload)
                    self.log.trace('{klass}.send(): TX {octets} octets',
                                   klass=self.__class__.__name__, octets=_LazyHexFormatter(payload))
        else:
            raise TransportLost()

    def isOpen(self):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransport.isOpen`
        """
        return self._session is not None

    def close(self):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransport.close`
        """
        if self.isOpen():
            self.transport.loseConnection()
        else:
            raise TransportLost()

    def abort(self):
        """
        Implements :func:`autobahn.wamp.interfaces.ITransport.abort`
        """
        if self.isOpen():
            if hasattr(self.transport, 'abortConnection'):
                # ProcessProtocol lacks abortConnection()
                self.transport.abortConnection()
            else:
                self.transport.loseConnection()
        else:
            raise TransportLost()


@public
class WampRawSocketServerProtocol(WampRawSocketProtocol):
    """
    Twisted-based WAMP-over-RawSocket server protocol.

    Implements:

        * :class:`autobahn.wamp.interfaces.ITransport`
    """

    def dataReceived(self, data):

        if self._handshake_complete:
            WampRawSocketProtocol.dataReceived(self, data)
        else:
            remaining = 4 - len(self._handshake_bytes)
            self._handshake_bytes += data[:remaining]

            if len(self._handshake_bytes) == 4:

                self.log.debug(
                    "WampRawSocketServerProtocol: opening handshake received - 0x{octets}",
                    octets=_LazyHexFormatter(self._handshake_bytes),
                )

                # first octet must be magic octet 0x7f
                #
                _magic = ord(self._handshake_bytes[0:1])
                if _magic != 127:
                    self.log.warning(
                        "WampRawSocketServerProtocol: invalid magic byte (octet 1) in"
                        " opening handshake: was {magic}, but expected 127",
                        magic=_magic,
                    )
                    self.abort()
                else:
                    self.log.debug('WampRawSocketServerProtocol: correct magic byte received')

                # peer requests us to send messages of maximum length 2**max_len_exp
                #
                self._max_len_send = 2 ** (9 + (ord(self._handshake_bytes[1:2]) >> 4))
                self.log.debug(
                    "WampRawSocketServerProtocol: client requests us to send out most {max_bytes} bytes per message",
                    max_bytes=self._max_len_send,
                )

                # client wants to speak this serialization format
                #
                ser_id = ord(self._handshake_bytes[1:2]) & 0x0F
                if ser_id in self.factory._serializers:
                    self._serializer = copy.copy(self.factory._serializers[ser_id])
                    self.log.debug(
                        "WampRawSocketServerProtocol: client wants to use serializer '{serializer}'",
                        serializer=ser_id,
                    )
                else:
                    self.log.warning(
                        "WampRawSocketServerProtocol: opening handshake - no suitable serializer found (client requested {serializer}, and we have {serializers}",
                        serializer=ser_id,
                        serializers=self.factory._serializers.keys(),
                    )
                    self.abort()

                # we request the client to send message of maximum length 2**reply_max_len_exp
                #
                reply_max_len_exp = int(math.ceil(math.log(self._max_message_size, 2)))

                # this is an instance attribute on the Twisted base class for maximum size
                # of _received_ messages
                self.MAX_LENGTH = 2**reply_max_len_exp

                # send out handshake reply
                #
                reply_octet2 = bytes(bytearray([
                    ((reply_max_len_exp - 9) << 4) | self._serializer.RAWSOCKET_SERIALIZER_ID]))
                self.transport.write(b'\x7F')       # magic byte
                self.transport.write(reply_octet2)  # max length / serializer
                self.transport.write(b'\x00\x00')   # reserved octets

                self._handshake_complete = True

                self._on_handshake_complete()

                self.log.debug(
                    "WampRawSocketServerProtocol: opening handshake completed: {serializer}",
                    serializer=self._serializer,
                )

            # consume any remaining data received already ..
            #
            data = data[remaining:]
            if data:
                self.dataReceived(data)


@public
class WampRawSocketClientProtocol(WampRawSocketProtocol):
    """
    Twisted-based WAMP-over-RawSocket client protocol.

    Implements:

        * :class:`autobahn.wamp.interfaces.ITransport`
    """

    def connectionMade(self):
        WampRawSocketProtocol.connectionMade(self)
        self._serializer = copy.copy(self.factory._serializer)

        # we request the peer to send messages of maximum length 2**reply_max_len_exp
        request_max_len_exp = int(math.ceil(math.log(self._max_message_size, 2)))

        # this is an instance attribute on the Twisted base class for maximum size
        # of _received_ messages
        self.MAX_LENGTH = 2**request_max_len_exp

        # send out handshake request
        #
        request_octet2 = bytes(bytearray([
            ((request_max_len_exp - 9) << 4) | self._serializer.RAWSOCKET_SERIALIZER_ID]))
        self.transport.write(b'\x7F')         # magic byte
        self.transport.write(request_octet2)  # max length / serializer
        self.transport.write(b'\x00\x00')     # reserved octets

    def dataReceived(self, data):

        if self._handshake_complete:
            WampRawSocketProtocol.dataReceived(self, data)
        else:
            remaining = 4 - len(self._handshake_bytes)
            self._handshake_bytes += data[:remaining]

            if len(self._handshake_bytes) == 4:

                self.log.debug(
                    "WampRawSocketClientProtocol: opening handshake received - {handshake}",
                    handshake=_LazyHexFormatter(self._handshake_bytes),
                )

                if ord(self._handshake_bytes[0:1]) != 0x7f:
                    self.log.debug(
                        "WampRawSocketClientProtocol: invalid magic byte (octet 1) in opening handshake: was 0x{magic}, but expected 0x7f",
                        magic=_LazyHexFormatter(self._handshake_bytes[0]),
                    )
                    self.abort()

                # peer requests us to _send_ messages of maximum length 2**max_len_exp
                #
                self._max_len_send = 2 ** (9 + (ord(self._handshake_bytes[1:2]) >> 4))
                self.log.debug(
                    "WampRawSocketClientProtocol: server requests us to send out most {max} bytes per message",
                    max=self._max_len_send,
                )

                # client wants to speak this serialization format
                #
                ser_id = ord(self._handshake_bytes[1:2]) & 0x0F
                if ser_id != self._serializer.RAWSOCKET_SERIALIZER_ID:
                    self.log.error(
                        "WampRawSocketClientProtocol: opening handshake - no suitable serializer found (server replied {serializer}, and we requested {serializers})",
                        serializer=ser_id,
                        serializers=self._serializer.RAWSOCKET_SERIALIZER_ID,
                    )
                    self.abort()

                self._handshake_complete = True

                self._on_handshake_complete()

                self.log.debug(
                    "WampRawSocketClientProtocol: opening handshake completed (using serializer {serializer})",
                    serializer=self._serializer,
                )

            # consume any remaining data received already ..
            #
            data = data[remaining:]
            if data:
                self.dataReceived(data)


class WampRawSocketFactory(Factory):
    """
    Base class for Twisted-based WAMP-over-RawSocket factories.
    """
    log = txaio.make_logger()

    def __init__(self, factory):
        """

        :param factory: A callable that produces instances that implement
            :class:`autobahn.wamp.interfaces.ITransportHandler`
        :type factory: callable
        """
        if callable(factory):
            self._factory = factory
        else:
            self._factory = lambda: factory

        # RawSocket max payload size is 16M (https://wamp-proto.org/_static/gen/wamp_latest_ietf.html#handshake)
        self._max_message_size = 2**24

    def resetProtocolOptions(self):
        self._max_message_size = 2**24

    def setProtocolOptions(self, maxMessagePayloadSize=None):
        self.log.debug('{klass}.setProtocolOptions(maxMessagePayloadSize={maxMessagePayloadSize})',
                       klass=self.__class__.__name__, maxMessagePayloadSize=maxMessagePayloadSize)
        assert maxMessagePayloadSize is None or (type(maxMessagePayloadSize) == int and maxMessagePayloadSize >= 512 and maxMessagePayloadSize <= 2**24)
        if maxMessagePayloadSize is not None and maxMessagePayloadSize != self._max_message_size:
            self._max_message_size = maxMessagePayloadSize

    def buildProtocol(self, addr):
        self.log.debug('{klass}.buildProtocol(addr={addr})', klass=self.__class__.__name__, addr=addr)
        p = self.protocol()
        p.factory = self
        p.MAX_LENGTH = self._max_message_size
        p._max_message_size = self._max_message_size
        self.log.debug('{klass}.buildProtocol() -> proto={proto}, max_message_size={max_message_size}, MAX_LENGTH={MAX_LENGTH}',
                       klass=self.__class__.__name__, proto=p, max_message_size=p._max_message_size, MAX_LENGTH=p.MAX_LENGTH)
        return p


@public
class WampRawSocketServerFactory(WampRawSocketFactory):
    """
    Twisted-based WAMP-over-RawSocket server protocol factory.
    """

    protocol = WampRawSocketServerProtocol

    def __init__(self, factory, serializers=None):
        """

        :param factory: A callable that produces instances that implement
            :class:`autobahn.wamp.interfaces.ITransportHandler`
        :type factory: callable

        :param serializers: A list of WAMP serializers to use (or ``None``
            for all available serializers).
        :type serializers: list of objects implementing
            :class:`autobahn.wamp.interfaces.ISerializer`
        """
        WampRawSocketFactory.__init__(self, factory)

        if serializers is None:
            serializers = []

            # try CBOR WAMP serializer
            try:
                from autobahn.wamp.serializer import CBORSerializer
                serializers.append(CBORSerializer(batched=True))
                serializers.append(CBORSerializer())
            except ImportError:
                pass

            # try MsgPack WAMP serializer
            try:
                from autobahn.wamp.serializer import MsgPackSerializer
                serializers.append(MsgPackSerializer(batched=True))
                serializers.append(MsgPackSerializer())
            except ImportError:
                pass

            # try UBJSON WAMP serializer
            try:
                from autobahn.wamp.serializer import UBJSONSerializer
                serializers.append(UBJSONSerializer(batched=True))
                serializers.append(UBJSONSerializer())
            except ImportError:
                pass

            # try JSON WAMP serializer
            try:
                from autobahn.wamp.serializer import JsonSerializer
                serializers.append(JsonSerializer(batched=True))
                serializers.append(JsonSerializer())
            except ImportError:
                pass

            if not serializers:
                raise Exception("could not import any WAMP serializers")

        self._serializers = {}
        for ser in serializers:
            self._serializers[ser.RAWSOCKET_SERIALIZER_ID] = ser


@public
class WampRawSocketClientFactory(WampRawSocketFactory):
    """
    Twisted-based WAMP-over-RawSocket client protocol factory.
    """

    protocol = WampRawSocketClientProtocol

    def __init__(self, factory, serializer=None):
        """

        :param factory: A callable that produces instances that implement
            :class:`autobahn.wamp.interfaces.ITransportHandler`
        :type factory: callable

        :param serializer: The WAMP serializer to use (or ``None`` for
           "best" serializer, chosen as the first serializer available from
           this list: CBOR, MessagePack, UBJSON, JSON).
        :type serializer: object implementing :class:`autobahn.wamp.interfaces.ISerializer`
        """
        WampRawSocketFactory.__init__(self, factory)

        # Reduce the factory logs noise
        self.noisy = False

        if serializer is None:

            # try CBOR WAMP serializer
            try:
                from autobahn.wamp.serializer import CBORSerializer
                serializer = CBORSerializer()
            except ImportError:
                pass

        if serializer is None:

            # try MsgPack WAMP serializer
            try:
                from autobahn.wamp.serializer import MsgPackSerializer
                serializer = MsgPackSerializer()
            except ImportError:
                pass

        if serializer is None:

            # try UBJSON WAMP serializer
            try:
                from autobahn.wamp.serializer import UBJSONSerializer
                serializer = UBJSONSerializer()
            except ImportError:
                pass

        if serializer is None:
            # try JSON WAMP serializer
            try:
                from autobahn.wamp.serializer import JsonSerializer
                serializer = JsonSerializer()
            except ImportError:
                pass

        if serializer is None:
            raise Exception("could not import any WAMP serializer")

        self._serializer = serializer
