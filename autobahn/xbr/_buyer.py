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

import uuid
import binascii
from pprint import pformat

import os
import cbor2
import nacl.secret
import nacl.utils
import nacl.exceptions
import nacl.public

import txaio
from autobahn.wamp.exception import ApplicationError
from autobahn.wamp.protocol import ApplicationSession
from ._util import unpack_uint256, pack_uint256

import eth_keys

from ..util import hl, hlval
from ._eip712_channel_close import sign_eip712_channel_close, recover_eip712_channel_close


class Transaction(object):

    def __init__(self, channel, delegate, pubkey, key_id, channel_seq, amount, balance, signature):
        self.channel = channel
        self.delegate = delegate
        self.pubkey = pubkey
        self.key_id = key_id
        self.channel_seq = channel_seq
        self.amount = amount
        self.balance = balance
        self.signature = signature

    def marshal(self):
        res = {
            'channel': self.channel,
            'delegate': self.delegate,
            'pubkey': self.pubkey,
            'key_id': self.key_id,
            'channel_seq': self.channel_seq,
            'amount': self.amount,
            'balance': self.balance,
            'signature': self.signature,
        }
        return res

    def __str__(self):
        return pformat(self.marshal())


class SimpleBuyer(object):
    """
    Simple XBR buyer component. This component can be used by a XBR buyer delegate to
    handle the automated buying of data encryption keys from the XBR market maker.
    """
    log = None

    def __init__(self, market_maker_adr, buyer_key, max_price):
        """

        :param market_maker_adr:
        :type market_maker_adr:

        :param buyer_key: Consumer delegate (buyer) private Ethereum key.
        :type buyer_key: bytes

        :param max_price: Maximum price we are willing to buy per key.
        :type max_price: int
        """
        assert type(market_maker_adr) == bytes and len(market_maker_adr) == 20, 'market_maker_adr must be bytes[20], but got "{}"'.format(market_maker_adr)
        assert type(buyer_key) == bytes and len(buyer_key) == 32, 'buyer delegate must be bytes[32], but got "{}"'.format(buyer_key)
        assert type(max_price) == int and max_price > 0

        self.log = txaio.make_logger()

        # market maker address
        self._market_maker_adr = market_maker_adr
        self._xbrmm_config = None

        # buyer delegate raw ethereum private key (32 bytes)
        self._pkey_raw = buyer_key

        # buyer delegate ethereum private key object
        self._pkey = eth_keys.keys.PrivateKey(buyer_key)

        # buyer delegate ethereum private account from raw private key
        # FIXME
        # self._acct = Account.privateKeyToAccount(self._pkey)
        self._acct = None

        # buyer delegate ethereum account canonical address
        self._addr = self._pkey.public_key.to_canonical_address()

        # buyer delegate ethereum account canonical checksummed address
        # FIXME
        # self._caddr = web3.Web3.toChecksumAddress(self._addr)
        self._caddr = None

        # ephemeral data consumer key
        self._receive_key = nacl.public.PrivateKey.generate()

        # maximum price per key we are willing to pay
        self._max_price = max_price

        # will be filled with on-chain payment channel contract, once started
        self._channel = None

        # channel current (off-chain) balance
        self._balance = 0

        # channel sequence number
        self._seq = 0

        # this holds the keys we bought (map: key_id => nacl.secret.SecretBox)
        self._keys = {}
        self._session = None
        self._running = False

        # automatically initiate a close of the payment channel when running into
        # a transaction failing because of insufficient balance remaining in the channel
        self._auto_close_channel = True

        # FIXME: poor mans local transaction store
        self._transaction_idx = {}
        self._transactions = []

    async def start(self, session, consumer_id):
        """
        Start buying keys to decrypt XBR data by calling ``unwrap()``.

        :param session: WAMP session over which to communicate with the XBR market maker.
        :type session: :class:`autobahn.wamp.protocol.ApplicationSession`

        :param consumer_id: XBR consumer ID.
        :type consumer_id: str

        :return: Current remaining balance in payment channel.
        :rtype: int
        """
        assert isinstance(session, ApplicationSession)
        assert type(consumer_id) == str
        assert not self._running

        self._session = session
        self._running = True

        self.log.debug('Start buying from consumer delegate address {address} (public key 0x{public_key}..)',
                       address=hl(self._caddr),
                       public_key=binascii.b2a_hex(self._pkey.public_key[:10]).decode())

        try:
            self._xbrmm_config = await session.call('xbr.marketmaker.get_config')

            # get the currently active (if any) payment channel for the delegate
            assert type(self._addr) == bytes and len(self._addr) == 20
            self._channel = await session.call('xbr.marketmaker.get_active_payment_channel', self._addr)
            if not self._channel:
                raise Exception('no active payment channel found')

            channel_oid = self._channel['channel_oid']
            assert type(channel_oid) == bytes and len(channel_oid) == 16
            self._channel_oid = uuid.UUID(bytes=channel_oid)

            # get the current (off-chain) balance of the payment channel
            payment_balance = await session.call('xbr.marketmaker.get_payment_channel_balance', self._channel_oid.bytes)
        except:
            session.leave()
            raise

        # FIXME
        if type(payment_balance['remaining']) == bytes:
            payment_balance['remaining'] = unpack_uint256(payment_balance['remaining'])

        if not payment_balance['remaining'] > 0:
            raise Exception('no off-chain balance remaining on payment channel')

        self._balance = payment_balance['remaining']
        self._seq = payment_balance['seq']

        self.log.info('Ok, buyer delegate started [active payment channel {channel_oid} with remaining balance {remaining} at sequence {seq}]',
                      channel_oid=hl(self._channel_oid), remaining=hlval(self._balance), seq=hlval(self._seq))

        return self._balance

    async def stop(self):
        """
        Stop buying keys.
        """
        assert self._running

        self._running = False

        self.log.info('Ok, buyer delegate stopped.')

    async def balance(self):
        """
        Return current balance of payment channel:

        * ``amount``: The initial amount with which the payment channel was opened.
        * ``remaining``: The remaining amount of XBR in the payment channel that can be spent.
        * ``inflight``: The amount of XBR allocated to buy transactions that are currently processed.

        :return: Current payment balance.
        :rtype: dict
        """
        assert self._session and self._session.is_attached()

        payment_balance = await self._session.call('xbr.marketmaker.get_payment_channel_balance', self._channel['channel_oid'])

        return payment_balance

    async def open_channel(self, buyer_addr, amount, details=None):
        """

        :param amount:
        :type amount:

        :param details:
        :type details:

        :return:
        :rtype:
        """
        assert self._session and self._session.is_attached()

        # FIXME
        signature = os.urandom(64)

        payment_channel = await self._session.call('xbr.marketmaker.open_payment_channel',
                                                   buyer_addr,
                                                   self._addr,
                                                   amount,
                                                   signature)

        balance = {
            'amount': payment_channel['amount'],
            'remaining': payment_channel['remaining'],
            'inflight': payment_channel['inflight'],
        }

        return balance

    async def close_channel(self, details=None):
        """
        Requests to close the currently active payment channel.

        :return:
        """

    async def unwrap(self, key_id, serializer, ciphertext):
        """
        Decrypt XBR data. This functions will potentially make the buyer call the
        XBR market maker to buy data encryption keys from the XBR provider.

        :param key_id: ID of the data encryption used for decryption
            of application payload.
        :type key_id: bytes

        :param serializer: Application payload serializer.
        :type serializer: str

        :param ciphertext: Ciphertext of encrypted application payload to
            decrypt.
        :type ciphertext: bytes

        :return: Decrypted application payload.
        :rtype: object
        """
        assert type(key_id) == bytes and len(key_id) == 16
        # FIXME: support more app payload serializers
        assert type(serializer) == str and serializer in ['cbor']
        assert type(ciphertext) == bytes

        market_oid = self._channel['market_oid']
        channel_oid = self._channel['channel_oid']

        # FIXME
        current_block_number = 1
        verifying_chain_id = self._xbrmm_config['verifying_chain_id']
        verifying_contract_adr = binascii.a2b_hex(self._xbrmm_config['verifying_contract_adr'][2:])

        # if we don't have the key, buy it!
        if key_id in self._keys:
            self.log.debug('Key {key_id} already in key store (or currently being bought).',
                           key_id=hl(uuid.UUID(bytes=key_id)))
        else:
            self.log.debug('Key {key_id} not yet in key store - buying key ..', key_id=hl(uuid.UUID(bytes=key_id)))

            # mark the key as currently being bought already (the location of code here is multi-entrant)
            self._keys[key_id] = False

            # get (current) price for key we want to buy
            quote = await self._session.call('xbr.marketmaker.get_quote', key_id)

            # set price we pay set to the (current) quoted price
            amount = unpack_uint256(quote['price'])

            self.log.debug('Key {key_id} has current price quote {amount}',
                           key_id=hl(uuid.UUID(bytes=key_id)), amount=hl(int(amount / 10**18)))

            if amount > self._max_price:
                raise ApplicationError('xbr.error.max_price_exceeded',
                                       '{}.unwrap() - key {} needed cannot be bought: price {} exceeds maximum price of {}'.format(self.__class__.__name__, uuid.UUID(bytes=key_id), int(amount / 10 ** 18), int(self._max_price / 10 ** 18)))

            # check (locally) we have enough balance left in the payment channel to buy the key
            balance = self._balance - amount
            if balance < 0:
                if self._auto_close_channel:
                    # FIXME: sign last transaction (from persisted local history)
                    last_tx = None
                    txns = self.past_transactions()
                    if txns:
                        last_tx = txns[0]

                    if last_tx:
                        # tx1 is the delegate portion, and tx2 is the market maker portion:
                        # tx1, tx2 = last_tx
                        # close_adr = tx1.channel
                        # close_seq = tx1.channel_seq
                        # close_balance = tx1.balance
                        # close_is_final = True

                        close_seq = self._seq
                        close_balance = self._balance
                        close_is_final = True

                        signature = sign_eip712_channel_close(self._pkey_raw,
                                                              verifying_chain_id,
                                                              verifying_contract_adr,
                                                              current_block_number,
                                                              market_oid,
                                                              channel_oid,
                                                              close_seq,
                                                              close_balance,
                                                              close_is_final)

                        self.log.debug('auto-closing payment channel {channel_oid} [close_seq={close_seq}, close_balance={close_balance}, close_is_final={close_is_final}]',
                                       channel_oid=uuid.UUID(bytes=channel_oid),
                                       close_seq=close_seq,
                                       close_balance=int(close_balance / 10**18),
                                       close_is_final=close_is_final)

                        # call market maker to initiate closing of payment channel
                        await self._session.call('xbr.marketmaker.close_channel',
                                                 channel_oid,
                                                 verifying_chain_id,
                                                 current_block_number,
                                                 verifying_contract_adr,
                                                 pack_uint256(close_balance),
                                                 close_seq,
                                                 close_is_final,
                                                 signature)

                        # FIXME: wait for and acquire new payment channel instead of bailing out ..

                        raise ApplicationError('xbr.error.channel_closed',
                                               '{}.unwrap() - key {} cannot be bought: payment channel {} ran empty and we initiated close at remaining balance of {}'.format(self.__class__.__name__,
                                                                                                                                                                              uuid.UUID(bytes=key_id),
                                                                                                                                                                              channel_oid,
                                                                                                                                                                              int(close_balance / 10 ** 18)))
                raise ApplicationError('xbr.error.insufficient_balance',
                                       '{}.unwrap() - key {} cannot be bought: insufficient balance {} in payment channel for amount {}'.format(self.__class__.__name__,
                                                                                                                                                uuid.UUID(bytes=key_id),
                                                                                                                                                int(self._balance / 10 ** 18),
                                                                                                                                                int(amount / 10 ** 18)))

            buyer_pubkey = self._receive_key.public_key.encode(encoder=nacl.encoding.RawEncoder)
            channel_seq = self._seq + 1
            is_final = False

            # XBRSIG[1/8]: compute EIP712 typed data signature
            signature = sign_eip712_channel_close(self._pkey_raw, verifying_chain_id, verifying_contract_adr,
                                                  current_block_number, market_oid, channel_oid, channel_seq,
                                                  balance, is_final)

            # persist 1st phase of the transaction locally
            self._save_transaction_phase1(channel_oid, self._addr, buyer_pubkey, key_id, channel_seq, amount, balance, signature)

            # call the market maker to buy the key
            try:
                receipt = await self._session.call('xbr.marketmaker.buy_key',
                                                   self._addr,
                                                   buyer_pubkey,
                                                   key_id,
                                                   channel_oid,
                                                   channel_seq,
                                                   pack_uint256(amount),
                                                   pack_uint256(balance),
                                                   signature)
            except ApplicationError as e:
                if e.error == 'xbr.error.channel_closed':
                    self.stop()
                raise e
            except Exception as e:
                self.log.error('Encountered error while calling market maker to buy key!')
                self.log.failure()
                self._keys[key_id] = e
                raise e

            # XBRSIG[8/8]: check market maker signature
            marketmaker_signature = receipt['signature']
            marketmaker_channel_seq = receipt['channel_seq']
            marketmaker_amount_paid = unpack_uint256(receipt['amount_paid'])
            marketmaker_remaining = unpack_uint256(receipt['remaining'])
            marketmaker_inflight = unpack_uint256(receipt['inflight'])

            signer_address = recover_eip712_channel_close(verifying_chain_id, verifying_contract_adr,
                                                          current_block_number, market_oid, channel_oid,
                                                          marketmaker_channel_seq, marketmaker_remaining,
                                                          False, marketmaker_signature)
            if signer_address != self._market_maker_adr:
                self.log.warning('{klass}.unwrap()::XBRSIG[8/8] - EIP712 signature invalid: signer_address={signer_address}, delegate_adr={delegate_adr}',
                                 klass=self.__class__.__name__,
                                 signer_address=hl(binascii.b2a_hex(signer_address).decode()),
                                 delegate_adr=hl(binascii.b2a_hex(self._market_maker_adr).decode()))
                raise ApplicationError('xbr.error.invalid_signature',
                                       '{}.unwrap()::XBRSIG[8/8] - EIP712 signature invalid or not signed by market maker'.format(self.__class__.__name__))

            if self._seq + 1 != marketmaker_channel_seq:
                raise ApplicationError('xbr.error.invalid_transaction',
                                       '{}.buy_key(): invalid transaction (channel sequence number mismatch - expected {}, but got {})'.format(self.__class__.__name__, self._seq, receipt['channel_seq']))

            if self._balance - amount != marketmaker_remaining:
                raise ApplicationError('xbr.error.invalid_transaction',
                                       '{}.buy_key(): invalid transaction (channel remaining amount mismatch - expected {}, but got {})'.format(self.__class__.__name__, self._balance - amount, receipt['remaining']))

            self._seq = marketmaker_channel_seq
            self._balance = marketmaker_remaining

            # persist 2nd phase of the transaction locally
            self._save_transaction_phase2(channel_oid, self._market_maker_adr, buyer_pubkey, key_id, marketmaker_channel_seq,
                                          marketmaker_amount_paid, marketmaker_remaining, marketmaker_signature)

            # unseal the data encryption key
            sealed_key = receipt['sealed_key']
            unseal_box = nacl.public.SealedBox(self._receive_key)
            try:
                key = unseal_box.decrypt(sealed_key)
            except nacl.exceptions.CryptoError as e:
                self._keys[key_id] = e
                raise ApplicationError('xbr.error.decryption_failed', '{}.unwrap() - could not unseal data encryption key: {}'.format(self.__class__.__name__, e))

            # remember the key, so we can use it to actually decrypt application payload data
            self._keys[key_id] = nacl.secret.SecretBox(key)

            transactions_count = self.count_transactions()
            self.log.info(
                '{klass}.unwrap() - {tx_type} key {key_id} bought for {amount_paid} [payment_channel={payment_channel}, remaining={remaining}, inflight={inflight}, buyer_pubkey={buyer_pubkey}, transactions={transactions}]',
                klass=self.__class__.__name__,
                tx_type=hl('XBR BUY   ', color='magenta'),
                key_id=hl(uuid.UUID(bytes=key_id)),
                amount_paid=hl(str(int(marketmaker_amount_paid / 10 ** 18)) + ' XBR', color='magenta'),
                payment_channel=hl(binascii.b2a_hex(receipt['payment_channel']).decode()),
                remaining=hl(int(marketmaker_remaining / 10 ** 18)),
                inflight=hl(int(marketmaker_inflight / 10 ** 18)),
                buyer_pubkey=hl(binascii.b2a_hex(buyer_pubkey).decode()),
                transactions=transactions_count)

        # if the key is already being bought, wait until the one buying path of execution has succeeded and done
        log_counter = 0
        while self._keys[key_id] is False:
            if log_counter % 100:
                self.log.debug('{klass}.unwrap() - waiting for key "{key_id}" currently being bought ..',
                               klass=self.__class__.__name__, key_id=hl(uuid.UUID(bytes=key_id)))
                log_counter += 1
            await txaio.sleep(.2)

        # check if the key buying failed and fail the unwrapping in turn
        if isinstance(self._keys[key_id], Exception):
            e = self._keys[key_id]
            raise e

        # now that we have the data encryption key, decrypt the application payload
        # the decryption key here is an instance of nacl.secret.SecretBox
        try:
            message = self._keys[key_id].decrypt(ciphertext)
        except nacl.exceptions.CryptoError as e:
            # Decryption failed. Ciphertext failed verification
            raise ApplicationError('xbr.error.decryption_failed', '{}.unwrap() - failed to unwrap encrypted data: {}'.format(self.__class__.__name__, e))

        # deserialize the application payload
        # FIXME: support more app payload serializers
        try:
            payload = cbor2.loads(message)
        except cbor2.decoder.CBORDecodeError as e:
            # premature end of stream (expected to read 4187 bytes, got 27 instead)
            raise ApplicationError('xbr.error.deserialization_failed', '{}.unwrap() - failed to deserialize application payload: {}'.format(self.__class__.__name__, e))

        return payload

    def _save_transaction_phase1(self, channel_oid, delegate_adr, buyer_pubkey, key_id, channel_seq, amount, balance, signature):
        """

        :param channel_oid:
        :param delegate_adr:
        :param buyer_pubkey:
        :param key_id:
        :param channel_seq:
        :param amount:
        :param balance:
        :param signature:
        :return:
        """
        if key_id in self._transaction_idx:
            raise RuntimeError('save_transaction_phase1: duplicate transaction for key 0x{}'.format(binascii.b2a_hex(key_id)))

        tx1 = Transaction(channel_oid, delegate_adr, buyer_pubkey, key_id, channel_seq, amount, balance, signature)

        key_idx = len(self._transactions)
        self._transactions.append([tx1, None])
        self._transaction_idx[key_id] = key_idx

    def _save_transaction_phase2(self, channel_oid, delegate_adr, buyer_pubkey, key_id, channel_seq, amount, balance, signature):
        """

        :param channel_oid:
        :param delegate_adr:
        :param buyer_pubkey:
        :param key_id:
        :param channel_seq:
        :param amount:
        :param balance:
        :param signature:
        :return:
        """
        if key_id not in self._transaction_idx:
            raise RuntimeError('save_transaction_phase2: transaction for key 0x{} not found'.format(binascii.b2a_hex(key_id)))

        key_idx = self._transaction_idx[key_id]

        if self._transactions[key_idx][1]:
            raise RuntimeError(
                'save_transaction_phase2: duplicate transaction for key 0x{}'.format(binascii.b2a_hex(key_id)))

        tx1 = self._transactions[key_idx][0]
        tx2 = Transaction(channel_oid, delegate_adr, buyer_pubkey, key_id, channel_seq, amount, balance, signature)

        assert tx1.channel == tx2.channel
        # assert tx1.delegate == tx2.delegate
        assert tx1.pubkey == tx2.pubkey
        assert tx1.key_id == tx2.key_id
        assert tx1.channel_seq == tx2.channel_seq
        assert tx1.amount == tx2.amount
        assert tx1.balance == tx2.balance

        # note: signatures will differ (obviously)!
        assert tx1.signature != tx2.signature

        self._transactions[key_idx][1] = tx2

    def past_transactions(self, filter_complete=True, limit=1):
        """

        :param filter_complete:
        :param limit:
        :return:
        """
        assert type(filter_complete) == bool
        assert type(limit) == int and limit > 0

        n = 0
        res = []
        while n < limit:
            if len(self._transactions) > n:
                tx = self._transactions[-n]
                if not filter_complete or (tx[0] and tx[1]):
                    res.append(tx)
                    n += 1
            else:
                break
        return res

    def count_transactions(self):
        """

        :return:
        """
        res = {
            'complete': 0,
            'pending': 0,
        }
        for tx1, tx2 in self._transactions:
            if tx1 and tx2:
                res['complete'] += 1
            else:
                res['pending'] += 1
        return res

    def get_transaction(self, key_id):
        """

        :param key_id:
        :return:
        """
        idx = self._transaction_idx.get(key_id, None)
        if idx:
            return self._transactions[idx]

    def is_complete(self, key_id):
        """

        :param key_id:
        :return:
        """
        idx = self._transaction_idx.get(key_id, None)
        if idx:
            tx1, tx2 = self._transactions[idx]
            return tx1 and tx2
        return False
