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
import binascii
import os
import uuid

from autobahn.wamp.types import RegisterOptions, CallDetails
from autobahn.wamp.exception import ApplicationError, TransportLost
from autobahn.wamp.protocol import ApplicationSession
from ._util import unpack_uint256, pack_uint256
from txaio import time_ns

import cbor2
import eth_keys
import nacl.secret
import nacl.utils
import nacl.public
import txaio

from ..util import hl, hlval
from ._eip712_channel_close import sign_eip712_channel_close, recover_eip712_channel_close


class KeySeries(object):
    """
    Data encryption key series with automatic (time-based) key rotation
    and key offering (to the XBR market maker).
    """

    def __init__(self, api_id, price, interval=None, count=None, on_rotate=None):
        """

        :param api_id: ID of the API for which to generate keys.
        :type api_id: bytes

        :param price: Price per key in key series.
        :type price: int

        :param interval: Interval in seconds after which to auto-rotate key.
        :type interval: int

        :param count: Number of encryption operations after which to auto-rotate key.
        :type count: int

        :param on_rotate: Optional user callback fired after key was rotated.
        :type on_rotate: callable
        """
        assert type(api_id) == bytes and len(api_id) == 16
        assert type(price) == int and price >= 0
        assert interval is None or (type(interval) == int and interval > 0)
        assert count is None or (type(count) == int and count > 0)
        assert (interval is None and count is not None) or (interval is not None and count is None)
        assert on_rotate is None or callable(on_rotate)

        self._api_id = api_id
        self._price = price
        self._interval = interval
        self._count = count
        self._count_current = 0
        self._on_rotate = on_rotate

        self._id = None
        self._key = None
        self._box = None
        self._archive = {}

    @property
    def key_id(self):
        """
        Get current XBR data encryption key ID (of the keys being rotated
        in a series).

        :return: Current key ID in key series (16 bytes).
        :rtype: bytes
        """
        return self._id

    async def encrypt(self, payload):
        """
        Encrypt data with the current XBR data encryption key.

        :param payload: Application payload to encrypt.
        :type payload: object

        :return: The ciphertext for the encrypted application payload.
        :rtype: bytes
        """
        data = cbor2.dumps(payload)

        if self._count is not None:
            self._count_current += 1
            if self._count_current >= self._count:
                await self._rotate()
                self._count_current = 0

        ciphertext = self._box.encrypt(data)

        return self._id, 'cbor', ciphertext

    def encrypt_key(self, key_id, buyer_pubkey):
        """
        Encrypt a (previously used) XBR data encryption key with a buyer public key.

        :param key_id: ID of the data encryption key to encrypt.
        :type key_id: bytes

        :param buyer_pubkey: Buyer WAMP public key (Ed25519) to asymmetrically encrypt
            the data encryption key (selected by ``key_id``) against.
        :type buyer_pubkey: bytes

        :return: The ciphertext for the encrypted data encryption key.
        :rtype: bytes
        """
        assert type(key_id) == bytes and len(key_id) == 16
        assert type(buyer_pubkey) == bytes and len(buyer_pubkey) == 32

        key, _ = self._archive[key_id]

        sendkey_box = nacl.public.SealedBox(nacl.public.PublicKey(buyer_pubkey,
                                                                  encoder=nacl.encoding.RawEncoder))

        encrypted_key = sendkey_box.encrypt(key, encoder=nacl.encoding.RawEncoder)

        return encrypted_key

    def start(self):
        raise NotImplementedError()

    def stop(self):
        raise NotImplementedError()

    async def _rotate(self):
        # generate new ID for next key in key series
        self._id = os.urandom(16)

        # generate next data encryption key in key series
        self._key = nacl.utils.random(nacl.secret.SecretBox.KEY_SIZE)

        # create secretbox from new key
        self._box = nacl.secret.SecretBox(self._key)

        # add key to archive
        self._archive[self._id] = (self._key, self._box)

        self.log.debug(
            '{tx_type} key "{key_id}" rotated [api_id="{api_id}"]',
            tx_type=hl('XBR ROTATE', color='magenta'),
            key_id=hl(uuid.UUID(bytes=self._id)),
            api_id=hl(uuid.UUID(bytes=self._api_id)))

        # maybe fire user callback
        if self._on_rotate:
            await self._on_rotate(self)


class PayingChannel(object):
    def __init__(self, adr, seq, balance):
        assert type(adr) == bytes and len(adr) == 16
        assert type(seq) == int and seq >= 0
        assert type(balance) == int and balance >= 0
        self._adr = adr
        self._seq = seq
        self._balance = balance


class SimpleSeller(object):

    log = None
    KeySeries = None

    STATE_NONE = 0
    STATE_STARTING = 1
    STATE_STARTED = 2
    STATE_STOPPING = 3
    STATE_STOPPED = 4

    def __init__(self, market_maker_adr, seller_key, provider_id=None):
        """

        :param market_maker_adr: Market maker public Ethereum address (20 bytes).
        :type market_maker_adr: bytes

        :param seller_key: Seller (delegate) private Ethereum key (32 bytes).
        :type seller_key: bytes

        :param provider_id: Optional explicit data provider ID. When not given, the seller delegate
            public WAMP key (Ed25519 in Hex) is used as the provider ID. This must be a valid WAMP URI part.
        :type provider_id: string
        """
        assert type(market_maker_adr) == bytes and len(market_maker_adr) == 20, 'market_maker_adr must be bytes[20], but got "{}"'.format(market_maker_adr)
        assert type(seller_key) == bytes and len(seller_key) == 32, 'seller delegate must be bytes[32], but got "{}"'.format(seller_key)
        assert provider_id is None or type(provider_id) == str, 'provider_id must be None or string, but got "{}"'.format(provider_id)

        self.log = txaio.make_logger()

        # current seller state
        self._state = SimpleSeller.STATE_NONE

        # market maker address
        self._market_maker_adr = market_maker_adr
        self._xbrmm_config = None

        # seller raw ethereum private key (32 bytes)
        self._pkey_raw = seller_key

        # seller ethereum private key object
        self._pkey = eth_keys.keys.PrivateKey(seller_key)

        # seller ethereum private account from raw private key
        # FIXME
        # self._acct = Account.privateKeyToAccount(self._pkey)
        self._acct = None

        # seller ethereum account canonical address
        self._addr = self._pkey.public_key.to_canonical_address()

        # seller ethereum account canonical checksummed address
        # FIXME
        # self._caddr = web3.Web3.toChecksumAddress(self._addr)
        self._caddr = None

        # seller provider ID
        self._provider_id = provider_id or str(self._pkey.public_key)

        self._channels = {}

        # will be filled with on-chain payment channel contract, once started
        self._channel = None

        # channel current (off-chain) balance
        self._balance = 0

        # channel sequence number
        self._seq = 0

        self._keys = {}
        self._keys_map = {}

        # after start() is running, these will be set
        self._session = None
        self._session_regs = None

    @property
    def public_key(self):
        """
        This seller delegate public Ethereum key.

        :return: Ethereum public key of this seller delegate.
        :rtype: bytes
        """
        return self._pkey.public_key

    def add(self, api_id, prefix, price, interval=None, count=None, categories=None):
        """
        Add a new (rotating) private encryption key for encrypting data on the given API.

        :param api_id: API for which to create a new series of rotating encryption keys.
        :type api_id: bytes

        :param price: Price in XBR token per key.
        :type price: int

        :param interval: Interval (in seconds) after which to auto-rotate the encryption key.
        :type interval: int

        :param count: Number of encryption operations after which to auto-rotate the encryption key.
        :type count: int
        """
        assert type(api_id) == bytes and len(api_id) == 16 and api_id not in self._keys
        assert type(price) == int and price >= 0
        assert interval is None or (type(interval) == int and interval > 0)
        assert count is None or (type(count) == int and count > 0)
        assert (interval is None and count is not None) or (interval is not None and count is None)
        assert categories is None or (type(categories) == dict and (type(k) == str for k in categories.keys()) and (type(v) == str for v in categories.values())), 'invalid categories type (must be dict) or category key or value type (must both be string)'

        async def on_rotate(key_series):

            key_id = key_series.key_id

            self._keys_map[key_id] = key_series

            # FIXME: expose the knobs hard-coded in below ..

            # offer the key to the market maker (retry 5x in specific error cases)
            retries = 5
            while retries:
                try:
                    valid_from = time_ns() - 10 * 10 ** 9
                    delegate = self._addr
                    # FIXME: sign the supplied offer information using self._pkey
                    signature = os.urandom(65)
                    provider_id = self._provider_id

                    offer = await self._session.call('xbr.marketmaker.place_offer',
                                                     key_id,
                                                     api_id,
                                                     prefix,
                                                     valid_from,
                                                     delegate,
                                                     signature,
                                                     privkey=None,
                                                     price=pack_uint256(price) if price is not None else None,
                                                     categories=categories,
                                                     expires=None,
                                                     copies=None,
                                                     provider_id=provider_id)

                    self.log.debug(
                        '{tx_type} key "{key_id}" offered for {price} [api_id={api_id}, prefix="{prefix}", delegate="{delegate}"]',
                        tx_type=hl('XBR OFFER ', color='magenta'),
                        key_id=hl(uuid.UUID(bytes=key_id)),
                        api_id=hl(uuid.UUID(bytes=api_id)),
                        price=hl(str(int(price / 10 ** 18) if price is not None else 0) + ' XBR', color='magenta'),
                        delegate=hl(binascii.b2a_hex(delegate).decode()),
                        prefix=hl(prefix))

                    self.log.debug('offer={offer}', offer=offer)

                    break

                except ApplicationError as e:
                    if e.error == 'wamp.error.no_such_procedure':
                        self.log.warning('xbr.marketmaker.offer: procedure unavailable!')
                    else:
                        self.log.failure()
                        break
                except TransportLost:
                    self.log.warning('TransportLost while calling xbr.marketmaker.offer!')
                    break
                except:
                    self.log.failure()

                retries -= 1
                self.log.warning('Failed to place offer for key! Retrying {retries}/5 ..', retries=retries)
                await asyncio.sleep(1)

        key_series = self.KeySeries(api_id, price, interval=interval, count=count, on_rotate=on_rotate)
        self._keys[api_id] = key_series
        self.log.debug('Created new key series {key_series}', key_series=key_series)

        return key_series

    async def start(self, session):
        """
        Start rotating keys and placing key offers with the XBR market maker.

        :param session: WAMP session over which to communicate with the XBR market maker.
        :type session: :class:`autobahn.wamp.protocol.ApplicationSession`
        """
        assert isinstance(session, ApplicationSession), 'session must be an ApplicationSession, was "{}"'.format(session)
        assert self._state in [SimpleSeller.STATE_NONE, SimpleSeller.STATE_STOPPED], 'seller already running'

        self._state = SimpleSeller.STATE_STARTING
        self._session = session
        self._session_regs = []

        self.log.debug('Start selling from seller delegate address {address} (public key 0x{public_key}..)',
                       address=hl(self._caddr),
                       public_key=binascii.b2a_hex(self._pkey.public_key[:10]).decode())

        # get the currently active (if any) paying channel for the delegate
        self._channel = await session.call('xbr.marketmaker.get_active_paying_channel', self._addr)
        if not self._channel:
            raise Exception('no active paying channel found')

        channel_oid = self._channel['channel_oid']
        assert type(channel_oid) == bytes and len(channel_oid) == 16
        self._channel_oid = uuid.UUID(bytes=channel_oid)

        procedure = 'xbr.provider.{}.sell'.format(self._provider_id)
        reg = await session.register(self.sell, procedure, options=RegisterOptions(details_arg='details'))
        self._session_regs.append(reg)
        self.log.debug('Registered procedure "{procedure}"', procedure=hl(reg.procedure))

        procedure = 'xbr.provider.{}.close_channel'.format(self._provider_id)
        reg = await session.register(self.close_channel, procedure, options=RegisterOptions(details_arg='details'))
        self._session_regs.append(reg)
        self.log.debug('Registered procedure "{procedure}"', procedure=hl(reg.procedure))

        for key_series in self._keys.values():
            await key_series.start()

        self._xbrmm_config = await session.call('xbr.marketmaker.get_config')

        # get the current (off-chain) balance of the paying channel
        paying_balance = await session.call('xbr.marketmaker.get_paying_channel_balance', self._channel_oid.bytes)
        # FIXME
        if type(paying_balance['remaining']) == bytes:
            paying_balance['remaining'] = unpack_uint256(paying_balance['remaining'])

        if not paying_balance['remaining'] > 0:
            raise Exception('no off-chain balance remaining on paying channel')

        self._channels[channel_oid] = PayingChannel(channel_oid, paying_balance['seq'], paying_balance['remaining'])
        self._state = SimpleSeller.STATE_STARTED

        # FIXME
        self._balance = paying_balance['remaining']
        if type(self._balance) == bytes:
            self._balance = unpack_uint256(self._balance)
        self._seq = paying_balance['seq']

        self.log.info('Ok, seller delegate started [active paying channel {channel_oid} with remaining balance {remaining} at sequence {seq}]',
                      channel_oid=hl(self._channel_oid), remaining=hlval(self._balance), seq=hlval(self._seq))

        return paying_balance['remaining']

    async def stop(self):
        """
        Stop rotating/offering keys to the XBR market maker.
        """
        assert self._state in [SimpleSeller.STATE_STARTED], 'seller not running'

        self._state = SimpleSeller.STATE_STOPPING

        dl = []
        for key_series in self._keys.values():
            d = key_series.stop()
            dl.append(d)

        if self._session_regs:
            if self._session and self._session.is_attached():
                # voluntarily unregister interface
                for reg in self._session_regs:
                    d = reg.unregister()
                    dl.append(d)
            self._session_regs = None

        d = txaio.gather(dl)

        try:
            await d
        except:
            self.log.failure()
        finally:
            self._state = SimpleSeller.STATE_STOPPED
            self._session = None

        self.log.info('Ok, seller delegate stopped.')

    async def balance(self):
        """
        Return current (off-chain) balance of paying channel:

        * ``amount``: The initial amount with which the paying channel was opened.
        * ``remaining``: The remaining amount of XBR in the paying channel that can be earned.
        * ``inflight``: The amount of XBR allocated to sell transactions that are currently processed.

        :return: Current paying balance.
        :rtype: dict
        """
        if self._state not in [SimpleSeller.STATE_STARTED]:
            raise RuntimeError('seller not running')
        if not self._session or not self._session.is_attached():
            raise RuntimeError('market-maker session not attached')

        paying_balance = await self._session.call('xbr.marketmaker.get_paying_channel_balance', self._channel['channel_oid'])

        return paying_balance

    async def wrap(self, api_id, uri, payload):
        """
        Encrypt and wrap application payload for a given API and destined for a specific WAMP URI.

        :param api_id: API for which to encrypt and wrap the application payload for.
        :type api_id: bytes

        :param uri: WAMP URI the application payload is destined for (eg the procedure or topic URI).
        :type uri: str

        :param payload: Application payload to encrypt and wrap.
        :type payload: object

        :return: The encrypted and wrapped application payload: a tuple with ``(key_id, serializer, ciphertext)``.
        :rtype: tuple
        """
        assert type(api_id) == bytes and len(api_id) == 16 and api_id in self._keys
        assert type(uri) == str
        assert payload is not None

        keyseries = self._keys[api_id]

        key_id, serializer, ciphertext = await keyseries.encrypt(payload)

        return key_id, serializer, ciphertext

    def close_channel(self, market_maker_adr, channel_oid, channel_seq, channel_balance, channel_is_final,
                      marketmaker_signature, details=None):
        """
        Called by a XBR Market Maker to close a paying channel.
        """
        assert type(market_maker_adr) == bytes and len(market_maker_adr) == 20, 'market_maker_adr must be bytes[20], but was {}'.format(type(market_maker_adr))
        assert type(channel_oid) == bytes and len(channel_oid) == 16, 'channel_oid must be bytes[16], but was {}'.format(type(channel_oid))
        assert type(channel_seq) == int, 'channel_seq must be int, but was {}'.format(type(channel_seq))
        assert type(channel_balance) == bytes and len(channel_balance) == 32, 'channel_balance must be bytes[32], but was {}'.format(type(channel_balance))
        assert type(channel_is_final) == bool, 'channel_is_final must be bool, but was {}'.format(type(channel_is_final))
        assert type(marketmaker_signature) == bytes and len(marketmaker_signature) == (32 + 32 + 1), 'marketmaker_signature must be bytes[65], but was {}'.format(type(marketmaker_signature))
        assert details is None or isinstance(details, CallDetails), 'details must be autobahn.wamp.types.CallDetails'

        # check that the delegate_adr fits what we expect for the market maker
        if market_maker_adr != self._market_maker_adr:
            raise ApplicationError('xbr.error.unexpected_delegate_adr',
                                   '{}.sell() - unexpected market maker (delegate) address: expected 0x{}, but got 0x{}'.format(self.__class__.__name__, binascii.b2a_hex(self._market_maker_adr).decode(), binascii.b2a_hex(market_maker_adr).decode()))

        # FIXME: must be the currently active channel .. and we need to track all of these
        if channel_oid != self._channel['channel_oid']:
            self._session.leave()
            raise ApplicationError('xbr.error.unexpected_channel_oid',
                                   '{}.sell() - unexpected paying channel address: expected 0x{}, but got 0x{}'.format(self.__class__.__name__, binascii.b2a_hex(self._channel['channel_oid']).decode(), binascii.b2a_hex(channel_oid).decode()))

        # channel sequence number: check we have consensus on off-chain channel state with peer (which is the market maker)
        if channel_seq != self._seq:
            raise ApplicationError('xbr.error.unexpected_channel_seq',
                                   '{}.sell() - unexpected channel (after tx) sequence number: expected {}, but got {}'.format(self.__class__.__name__, self._seq + 1, channel_seq))

        # channel balance: check we have consensus on off-chain channel state with peer (which is the market maker)
        channel_balance = unpack_uint256(channel_balance)
        if channel_balance != self._balance:
            raise ApplicationError('xbr.error.unexpected_channel_balance',
                                   '{}.sell() - unexpected channel (after tx) balance: expected {}, but got {}'.format(self.__class__.__name__, self._balance, channel_balance))

        # XBRSIG: check the signature (over all input data for the buying of the key)
        signer_address = recover_eip712_channel_close(channel_oid, channel_seq, channel_balance, channel_is_final, marketmaker_signature)
        if signer_address != market_maker_adr:
            self.log.warning('{klass}.sell()::XBRSIG[4/8] - EIP712 signature invalid: signer_address={signer_address}, delegate_adr={delegate_adr}',
                             klass=self.__class__.__name__,
                             signer_address=hl(binascii.b2a_hex(signer_address).decode()),
                             delegate_adr=hl(binascii.b2a_hex(market_maker_adr).decode()))
            raise ApplicationError('xbr.error.invalid_signature', '{}.sell()::XBRSIG[4/8] - EIP712 signature invalid or not signed by market maker'.format(self.__class__.__name__))

        # XBRSIG: compute EIP712 typed data signature
        seller_signature = sign_eip712_channel_close(self._pkey_raw, channel_oid, channel_seq, channel_balance, channel_is_final)

        receipt = {
            'delegate': self._addr,
            'seq': channel_seq,
            'balance': pack_uint256(channel_balance),
            'is_final': channel_is_final,
            'signature': seller_signature,
        }

        self.log.debug('{klass}.close_channel() - {tx_type} closing channel {channel_oid}, closing balance {channel_balance}, closing sequence {channel_seq} [caller={caller}, caller_authid="{caller_authid}"]',
                       klass=self.__class__.__name__,
                       tx_type=hl('XBR CLOSE  ', color='magenta'),
                       channel_balance=hl(str(int(channel_balance / 10 ** 18)) + ' XBR', color='magenta'),
                       channel_seq=hl(channel_seq),
                       channel_oid=hl(binascii.b2a_hex(channel_oid).decode()),
                       caller=hl(details.caller),
                       caller_authid=hl(details.caller_authid))

        return receipt

    def sell(self, market_maker_adr, buyer_pubkey, key_id, channel_oid, channel_seq, amount, balance, signature, details=None):
        """
        Called by a XBR Market Maker to buy a data encyption key. The XBR Market Maker here is
        acting for (triggered by) the XBR buyer delegate.

        :param market_maker_adr: The market maker Ethereum address. The technical buyer is usually the
            XBR market maker (== the XBR delegate of the XBR market operator).
        :type market_maker_adr: bytes of length 20

        :param buyer_pubkey: The buyer delegate Ed25519 public key.
        :type buyer_pubkey: bytes of length 32

        :param key_id: The UUID of the data encryption key to buy.
        :type key_id: bytes of length 16

        :param channel_oid: The on-chain channel contract address.
        :type channel_oid: bytes of length 16

        :param channel_seq: Paying channel sequence off-chain transaction number.
        :type channel_seq: int

        :param amount: The amount paid by the XBR Buyer via the XBR Market Maker.
        :type amount: bytes

        :param balance: Balance remaining in the payment channel (from the market maker to the
            seller) after successfully buying the key.
        :type balance: bytes

        :param signature: Signature over the supplied buying information, using the Ethereum
            private key of the market maker (which is the delegate of the marker operator).
        :type signature: bytes of length 65

        :param details: Caller details. The call will come from the XBR Market Maker.
        :type details: :class:`autobahn.wamp.types.CallDetails`

        :return: The data encryption key, itself encrypted to the public key of the original buyer.
        :rtype: bytes
        """
        assert type(market_maker_adr) == bytes and len(market_maker_adr) == 20, 'delegate_adr must be bytes[20]'
        assert type(buyer_pubkey) == bytes and len(buyer_pubkey) == 32, 'buyer_pubkey must be bytes[32]'
        assert type(key_id) == bytes and len(key_id) == 16, 'key_id must be bytes[16]'
        assert type(channel_oid) == bytes and len(channel_oid) == 16, 'channel_oid must be bytes[16]'
        assert type(channel_seq) == int, 'channel_seq must be int'
        assert type(amount) == bytes and len(amount) == 32, 'amount_paid must be bytes[32], but was {}'.format(type(amount))
        assert type(balance) == bytes and len(amount) == 32, 'post_balance must be bytes[32], but was {}'.format(type(balance))
        assert type(signature) == bytes and len(signature) == (32 + 32 + 1), 'signature must be bytes[65]'
        assert details is None or isinstance(details, CallDetails), 'details must be autobahn.wamp.types.CallDetails'

        amount = unpack_uint256(amount)
        balance = unpack_uint256(balance)

        # check that the delegate_adr fits what we expect for the market maker
        if market_maker_adr != self._market_maker_adr:
            raise ApplicationError('xbr.error.unexpected_marketmaker_adr',
                                   '{}.sell() - unexpected market maker address: expected 0x{}, but got 0x{}'.format(self.__class__.__name__, binascii.b2a_hex(self._market_maker_adr).decode(), binascii.b2a_hex(market_maker_adr).decode()))

        # get the key series given the key_id
        if key_id not in self._keys_map:
            raise ApplicationError('crossbar.error.no_such_object', '{}.sell() - no key with ID "{}"'.format(self.__class__.__name__, key_id))
        key_series = self._keys_map[key_id]

        # FIXME: must be the currently active channel .. and we need to track all of these
        if channel_oid != self._channel['channel_oid']:
            self._session.leave()
            raise ApplicationError('xbr.error.unexpected_channel_oid',
                                   '{}.sell() - unexpected paying channel address: expected 0x{}, but got 0x{}'.format(self.__class__.__name__, binascii.b2a_hex(self._channel['channel_oid']).decode(), binascii.b2a_hex(channel_oid).decode()))

        # channel sequence number: check we have consensus on off-chain channel state with peer (which is the market maker)
        if channel_seq != self._seq + 1:
            raise ApplicationError('xbr.error.unexpected_channel_seq',
                                   '{}.sell() - unexpected channel (after tx) sequence number: expected {}, but got {}'.format(self.__class__.__name__, self._seq + 1, channel_seq))

        # channel balance: check we have consensus on off-chain channel state with peer (which is the market maker)
        if balance != self._balance - amount:
            raise ApplicationError('xbr.error.unexpected_channel_balance',
                                   '{}.sell() - unexpected channel (after tx) balance: expected {}, but got {}'.format(self.__class__.__name__, self._balance - amount, balance))

        # FIXME
        current_block_number = 1
        verifying_chain_id = self._xbrmm_config['verifying_chain_id']
        verifying_contract_adr = binascii.a2b_hex(self._xbrmm_config['verifying_contract_adr'][2:])

        market_oid = self._channel['market_oid']

        # XBRSIG[4/8]: check the signature (over all input data for the buying of the key)
        signer_address = recover_eip712_channel_close(verifying_chain_id, verifying_contract_adr, current_block_number,
                                                      market_oid, channel_oid, channel_seq, balance, False, signature)
        if signer_address != market_maker_adr:
            self.log.warning('{klass}.sell()::XBRSIG[4/8] - EIP712 signature invalid: signer_address={signer_address}, delegate_adr={delegate_adr}',
                             klass=self.__class__.__name__,
                             signer_address=hl(binascii.b2a_hex(signer_address).decode()),
                             delegate_adr=hl(binascii.b2a_hex(market_maker_adr).decode()))
            raise ApplicationError('xbr.error.invalid_signature', '{}.sell()::XBRSIG[4/8] - EIP712 signature invalid or not signed by market maker'.format(self.__class__.__name__))

        # now actually update our local knowledge of the channel state
        # FIXME: what if code down below fails?
        self._seq += 1
        self._balance -= amount

        # encrypt the data encryption key against the original buyer delegate Ed25519 public key
        sealed_key = key_series.encrypt_key(key_id, buyer_pubkey)

        assert type(sealed_key) == bytes and len(sealed_key) == 80, '{}.sell() - unexpected sealed key computed (expected bytes[80]): {}'.format(self.__class__.__name__, sealed_key)

        # XBRSIG[5/8]: compute EIP712 typed data signature
        seller_signature = sign_eip712_channel_close(self._pkey_raw, verifying_chain_id, verifying_contract_adr,
                                                     current_block_number, market_oid, channel_oid, self._seq,
                                                     self._balance, False)

        receipt = {
            # key ID that has been bought
            'key_id': key_id,

            # seller delegate address that sold the key
            'delegate': self._addr,

            # buyer delegate Ed25519 public key with which the bought key was sealed
            'buyer_pubkey': buyer_pubkey,

            # finally return what the consumer (buyer) was actually interested in:
            # the data encryption key, sealed (public key Ed25519 encrypted) to the
            # public key of the buyer delegate
            'sealed_key': sealed_key,

            # paying channel off-chain transaction sequence numbers
            'channel_seq': self._seq,

            # amount paid for the key
            'amount': amount,

            # paying channel amount remaining
            'balance': self._balance,

            # seller (delegate) signature
            'signature': seller_signature,
        }

        self.log.info('{klass}.sell() - {tx_type} key "{key_id}" sold for {amount_earned} - balance is {balance} [caller={caller}, caller_authid="{caller_authid}", buyer_pubkey="{buyer_pubkey}"]',
                      klass=self.__class__.__name__,
                      tx_type=hl('XBR SELL  ', color='magenta'),
                      key_id=hl(uuid.UUID(bytes=key_id)),
                      amount_earned=hl(str(int(amount / 10 ** 18)) + ' XBR', color='magenta'),
                      balance=hl(str(int(self._balance / 10 ** 18)) + ' XBR', color='magenta'),
                      # paying_channel=hl(binascii.b2a_hex(paying_channel).decode()),
                      caller=hl(details.caller),
                      caller_authid=hl(details.caller_authid),
                      buyer_pubkey=hl(binascii.b2a_hex(buyer_pubkey).decode()))

        return receipt
