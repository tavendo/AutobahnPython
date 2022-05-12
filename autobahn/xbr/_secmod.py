###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) Crossbar.io Technologies GmbH
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

import os
from collections.abc import MutableMapping
from typing import Optional, Union, Dict, Any, List, Iterator
from threading import Lock

import txaio
import nacl

from eth_account.account import Account
from eth_account.signers.local import LocalAccount

from py_eth_sig_utils.eip712 import encode_typed_data
from py_eth_sig_utils.utils import ecsign, ecrecover_to_pub, checksum_encode, sha3
from py_eth_sig_utils.signing import v_r_s_to_signature, signature_to_v_r_s

from autobahn.wamp.interfaces import ISecurityModule, IEthereumKey, IKey
from autobahn.xbr._mnemonic import mnemonic_to_private_key
from autobahn.wamp.cryptosign import CryptosignKey

__all__ = ('EthereumKey', 'SecurityModuleMemory', )


class EthereumKey(object):
    """
    Base class to implement :class:`autobahn.wamp.interfaces.IEthereumKey`.
    """

    def __init__(self, key_or_address: Union[LocalAccount, str, bytes], can_sign: bool,
                 security_module: Optional[ISecurityModule] = None,
                 key_no: Optional[int] = None) -> None:
        if can_sign:
            # https://eth-account.readthedocs.io/en/latest/eth_account.html#eth_account.account.Account
            assert type(key_or_address) == LocalAccount
            self._key = key_or_address
            self._address = key_or_address.address
        else:
            assert type(key_or_address) in (str, bytes)
            self._key = None
            self._address = key_or_address
        self._can_sign = can_sign
        self._security_module = security_module
        self._key_no = key_no

    @property
    def security_module(self) -> Optional['ISecurityModule']:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.security_module`.
        """
        return self._security_module

    @property
    def key_no(self) -> Optional[int]:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.key_no`.
        """
        return self._key_no

    @property
    def key_type(self) -> str:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.key_type`.
        """
        return 'ethereum'

    def public_key(self, binary: bool = False) -> Union[str, bytes]:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.public_key`.
        """
        raise NotImplementedError()

    @property
    def can_sign(self) -> bool:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.can_sign`.
        """
        return self._can_sign

    def address(self, binary: bool = False) -> Union[str, bytes]:
        """
        Implements :meth:`autobahn.wamp.interfaces.IEthereumKey.address`.
        """
        # FIXME: implement "binary"
        return self._address

    def sign(self, data: bytes) -> bytes:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.sign`.
        """
        # FIXME: implement signing of raw data
        raise NotImplementedError()

    def recover(self, data: bytes, signature: bytes) -> bytes:
        """
        Implements :meth:`autobahn.wamp.interfaces.IKey.recover`.
        """
        # FIXME: implement signing address recovery from signature of raw data
        raise NotImplementedError()

    def sign_typed_data(self, data: Dict[str, Any]) -> bytes:
        """
        Implements :meth:`autobahn.wamp.interfaces.IEthereumKey.sign_typed_data`.
        """
        if self._security_module:
            assert (self._security_module.is_open and
                    not self._security_module.is_locked), 'security module must be open and unlocked'
        try:
            # encode typed data dict and return message hash
            msg_hash = encode_typed_data(data)

            # ECDSA signatures in Ethereum consist of three parameters: v, r and s.
            # The signature is always 65-bytes in length.
            #     r = first 32 bytes of signature
            #     s = second 32 bytes of signature
            #     v = final 1 byte of signature
            signature_vrs = ecsign(msg_hash, self._key.key)

            # concatenate signature components into byte string
            signature = v_r_s_to_signature(*signature_vrs)
        except Exception as e:
            return txaio.create_future_error(e)
        else:
            return txaio.create_future_success(signature)

    def verify_typed_data(self, data: Dict[str, Any], signature: bytes) -> bool:
        """
        Implements :meth:`autobahn.wamp.interfaces.IEthereumKey.verify_typed_data`.
        """
        if self._security_module:
            assert (self._security_module.is_open and
                    not self._security_module.is_locked), 'security module must be open and unlocked'
        try:
            msg_hash = encode_typed_data(data)
            signature_vrs = signature_to_v_r_s(signature)
            public_key = ecrecover_to_pub(msg_hash, *signature_vrs)
            address_bytes = sha3(public_key)[-20:]
            address = checksum_encode(address_bytes)
        except Exception as e:
            return txaio.create_future_error(e)
        else:
            return txaio.create_future_success(address == self._address)

    @classmethod
    def from_address(cls, address: Union[str, bytes]) -> 'EthereumKey':
        """
        Create a public key from an address, which can be used to verify signatures.

        :param address: The Ethereum address (20 octets).
        :return: New instance of :class:`EthereumKey`
        """
        return EthereumKey(key_or_address=address, can_sign=False)

    @classmethod
    def from_bytes(cls, key: bytes) -> 'EthereumKey':
        """
        Create a private key from seed bytes, which can be used to sign and create signatures.

        :param key: The Ethereum private key seed (32 octets).
        :return: New instance of :class:`EthereumKey`
        """
        if type(key) != bytes:
            raise ValueError("invalid seed type {} (expected binary)".format(type(key)))

        if len(key) != 32:
            raise ValueError("invalid seed length {} (expected 32)".format(len(key)))

        account: LocalAccount = Account.from_key(key)
        return EthereumKey(key_or_address=account, can_sign=True)

    @classmethod
    def from_seedphrase(cls, seedphrase: str, index: int = 0) -> 'EthereumKey':
        """
        Create a private key from the given BIP-39 mnemonic seed phrase and index,
        which can be used to sign and create signatures.

        :param seedphrase: The BIP-39 seedphrase ("Mnemonic") from which to derive the account.
        :param index: The account index in account hierarchy defined by the seedphrase.
        :return: New instance of :class:`EthereumKey`
        """
        # Base HD Path:  m/44'/60'/0'/0/{account_index}
        derivation_path = "m/44'/60'/0'/0/{}".format(index)

        key = mnemonic_to_private_key(seedphrase, str_derivation_path=derivation_path)
        assert type(key) == bytes
        assert len(key) == 32

        account: LocalAccount = Account.from_key(key)
        return EthereumKey(key_or_address=account, can_sign=True)


IEthereumKey.register(EthereumKey)


class SecurityModuleMemory(MutableMapping):
    """
    A transient, memory-based implementation of :class:`ISecurityModule`.
    """

    def __init__(self, keys: Optional[List[Union[CryptosignKey, EthereumKey]]] = None):
        self._mutex = Lock()
        self._is_open = False
        self._is_locked = True
        self._keys: Dict[int, Union[CryptosignKey, EthereumKey]] = {}
        self._counters: Dict[int, int] = {}
        if keys:
            for i, key in enumerate(keys):
                self._keys[i] = key

    def __len__(self) -> int:
        """
        Implements :meth:`ISecurityModule.__len__`
        """
        assert self._is_open, 'security module not open'

        return len(self._keys)

    def __contains__(self, key_no: int) -> bool:
        assert self._is_open, 'security module not open'

        return key_no in self._keys

    def __iter__(self) -> Iterator[int]:
        """
        Implements :meth:`ISecurityModule.__iter__`
        """
        assert self._is_open, 'security module not open'

        yield from self._keys

    def __getitem__(self, key_no: int) -> Union[CryptosignKey, EthereumKey]:
        """
        Implements :meth:`ISecurityModule.__getitem__`
        """
        assert self._is_open, 'security module not open'

        if key_no in self._keys:
            return self._keys[key_no]
        else:
            raise IndexError('key_no {} not found'.format(key_no))

    def __setitem__(self, key_no: int, key: Union[CryptosignKey, EthereumKey]) -> None:
        assert self._is_open, 'security module not open'

        assert key_no >= 0
        if key_no in self._keys:
            # FIXME
            pass
        self._keys[key_no] = key

    def __delitem__(self, key_no: int) -> None:
        assert self._is_open, 'security module not open'

        if key_no in self._keys:
            del self._keys[key_no]
        else:
            raise IndexError()

    def open(self):
        """
        Implements :meth:`ISecurityModule.open`
        """
        assert not self._is_open, 'security module already open'

        self._is_open = True
        return txaio.create_future_success(None)

    def close(self):
        """
        Implements :meth:`ISecurityModule.close`
        """
        assert self._is_open, 'security module not open'

        self._is_open = False
        self._is_locked = True
        return txaio.create_future_success(None)

    @property
    def is_open(self) -> bool:
        """
        Implements :meth:`ISecurityModule.is_open`
        """
        return self._is_open

    @property
    def can_lock(self) -> bool:
        """
        Implements :meth:`ISecurityModule.can_lock`
        """
        return True

    @property
    def is_locked(self) -> bool:
        """
        Implements :meth:`ISecurityModule.is_locked`
        """
        return self._is_locked

    def lock(self):
        """
        Implements :meth:`ISecurityModule.lock`
        """
        assert self._is_open, 'security module not open'
        assert not self._is_locked

        self._is_locked = True
        return txaio.create_future_success(None)

    def unlock(self):
        """
        Implements :meth:`ISecurityModule.unlock`
        """
        assert self._is_open, 'security module not open'
        assert self._is_locked

        self._is_locked = False
        return txaio.create_future_success(None)

    def create_key(self, key_type: str) -> int:
        assert self._is_open, 'security module not open'

        key_no = len(self._keys)
        if key_type == 'cryptosign':
            key = CryptosignKey(key=nacl.signing.SigningKey(os.urandom(32)),
                                can_sign=True,
                                security_module=self,
                                key_no=key_no)
        elif key_type == 'ethereum':
            key = EthereumKey(key_or_address=Account.from_key(os.urandom(32)),
                              can_sign=True,
                              security_module=self,
                              key_no=key_no)
        else:
            raise ValueError('invalid key_type "{}"'.format(key_type))
        self._keys[key_no] = key
        return txaio.create_future_success(key_no)

    def delete_key(self, key_no: int):
        assert self._is_open, 'security module not open'

        if key_no in self._keys:
            del self._keys[key_no]
            return txaio.create_future_success(key_no)
        else:
            return txaio.create_future_success(None)

    def get_random(self, octets: int) -> bytes:
        """
        Implements :meth:`ISecurityModule.get_random`
        """
        assert self._is_open, 'security module not open'

        data = os.urandom(octets)
        return txaio.create_future_success(data)

    def get_counter(self, counter_no: int) -> int:
        """
        Implements :meth:`ISecurityModule.get_counter`
        """
        assert self._is_open, 'security module not open'

        self._mutex.acquire()
        res = self._counters.get(counter_no, 0)
        self._mutex.release()
        return txaio.create_future_success(res)

    def increment_counter(self, counter_no: int) -> int:
        """
        Implements :meth:`ISecurityModule.increment_counter`
        """
        assert self._is_open, 'security module not open'

        self._mutex.acquire()
        if counter_no not in self._counters:
            self._counters[counter_no] = 0
        self._counters[counter_no] += 1
        res = self._counters[counter_no]
        self._mutex.release()
        return txaio.create_future_success(res)

    @classmethod
    def from_seedphrase(cls, seedphrase: str, num_client_keys: int = 1,
                        num_delegate_keys: int = 1) -> 'SecurityModuleMemory':
        """

        :param seedphrase:
        :param num_client_keys:
        :param num_delegate_keys:
        :return:
        """
        keys: List[IKey] = []
        for i in range(num_delegate_keys):
            key = EthereumKey.from_seedphrase(seedphrase, i)
            keys.append(key)
        for i in range(num_client_keys):
            # FIXME
            # key = CryptosignKey.from_seedphrase(seedphrase, i)
            key = CryptosignKey.from_key_bytes(os.urandom(32))
            keys.append(key)
        sm = SecurityModuleMemory(keys=keys)
        return sm


ISecurityModule.register(SecurityModuleMemory)
