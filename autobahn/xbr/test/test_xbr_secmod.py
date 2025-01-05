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

import os
import sys
if sys.version_info < (3, 10):
    import importlib_resources as resources
else:
    from importlib import resources
from random import randint, random
from binascii import a2b_hex
from typing import List
from unittest import skipIf

from twisted.internet.defer import inlineCallbacks
from twisted.trial.unittest import TestCase

from autobahn.wamp.cryptosign import HAS_CRYPTOSIGN
from autobahn.xbr import HAS_XBR

if HAS_XBR and HAS_CRYPTOSIGN:
    from py_eth_sig_utils.eip712 import encode_typed_data
    from py_eth_sig_utils.utils import ecsign, ecrecover_to_pub, checksum_encode, sha3
    from py_eth_sig_utils.signing import v_r_s_to_signature, signature_to_v_r_s
    from py_eth_sig_utils.signing import sign_typed_data, recover_typed_data

    from autobahn.xbr import make_w3, EthereumKey, mnemonic_to_private_key
    from autobahn.xbr._eip712_member_register import _create_eip712_member_register
    from autobahn.xbr._eip712_market_create import _create_eip712_market_create
    from autobahn.xbr._secmod import SecurityModuleMemory
    from autobahn.wamp.cryptosign import CryptosignKey


# https://web3py.readthedocs.io/en/stable/providers.html#infura-mainnet
HAS_INFURA = 'WEB3_INFURA_PROJECT_ID' in os.environ and len(os.environ['WEB3_INFURA_PROJECT_ID']) > 0

# TypeError: As of 3.10, the *loop* parameter was removed from Lock() since it is no longer necessary
IS_CPY_310 = sys.version_info.minor == 10


@skipIf(not os.environ.get('USE_TWISTED', False), 'only for Twisted')
@skipIf(not HAS_INFURA, 'env var WEB3_INFURA_PROJECT_ID not defined')
@skipIf(not (HAS_XBR and HAS_CRYPTOSIGN), 'package autobahn[encryption,xbr] not installed')
class TestSecurityModule(TestCase):

    def setUp(self):
        self._gw_config = {
            'type': 'infura',
            'key': os.environ.get('WEB3_INFURA_PROJECT_ID', ''),
            'network': 'mainnet',
        }
        self._w3 = make_w3(self._gw_config)

        self._seedphrase = "avocado style uncover thrive same grace crunch want essay reduce current edge"
        self._addresses = [
            '0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57',
            '0xf5173a6111B2A6B3C20fceD53B2A8405EC142bF6',
            '0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047',
            '0x2F070c2f49a59159A0346396f1139203355ACA43',
            '0x66290fA8ADcD901Fd994e4f64Cfb53F4c359a326',
        ]
        self._keys = [
            '0x805f84af7e182359db0610ffb07c801012b699b5610646937704aa5cfc28b15e',
            '0x991c8f7609f3236ad5ef6d498b2ec0c9793c2865dd337ddc3033067c1da0e735',
            '0x75848ddb1155cd1cdf6d74a6e7fbed06aeaa21ef2d8a05df7af2d95cdc127672',
            '0x5be599a34927a1110922d7704ba316144b31699d8e7f229e2684d5575a84214e',
            '0xc1bb7ce3481e95b28bb8c026667b6009c504c79a98e6c7237ba0788c37b473c9',
        ]

        # create EIP712 typed data dicts from message data and schemata

        verifying_contract = a2b_hex(self._addresses[0][2:])
        member = a2b_hex(self._addresses[1][2:])
        maker = a2b_hex(self._addresses[2][2:])
        coin = a2b_hex(self._addresses[3][2:])

        eula = 'QmU7Gizbre17x6V2VR1Q2GJEjz6m8S1bXmBtVxS2vmvb81'
        profile = 'QmcNsPV7QZFHKb2DNn8GWsU5dtd8zH5DNRa31geC63ceb4'
        terms = 'QmaozNR7DZHQK1ZcU9p7QdrshMvXqWK6gpu5rmrkPdT3L4'
        meta = 'Qmf412jQZiuVUtdgnB36FXFX7xg5V6KEbSJ4dpQuhkLyfD'

        market_id = a2b_hex('5b7ee23c9353479ca49a2461c0a1deb2')

        self._eip_data_objects = [
            _create_eip712_member_register(chainId=1, verifyingContract=verifying_contract, member=member,
                                           registered=666, eula=eula, profile=profile),
            _create_eip712_member_register(chainId=23, verifyingContract=a2b_hex(self._addresses[0][2:]),
                                           member=a2b_hex(self._addresses[1][2:]), registered=9999, eula=eula,
                                           profile=profile),
            _create_eip712_market_create(chainId=1, verifyingContract=verifying_contract, member=member, created=666,
                                         marketId=market_id, coin=coin, terms=terms, meta=meta, maker=maker,
                                         providerSecurity=10 ** 6, consumerSecurity=10 ** 6, marketFee=100),
        ]
        self._eip_data_obj_hashes = [
            '8abee87b2cf457841d173083d5f205183f3e78c6cee30ca77776344e11f612b3',
            '6a4f10dc41080c445a86acaae652ce80878fe768f6b459af08d14465c5310138',
            'f1b80df26ec6cc7dafeb8a5c69de77e8ec5a2c0e93f5d6e475124f18cf4c595f',
        ]
        self._eip_data_obj_signatures = [
            '17ed35d8fd41fcb507ae11a3745d9775f37ff1c155257074fe2245cfb186f4336151fd018bf83a5e9902d825b645213a111630f78bbbc3c96f68d60b7e65dafd1c',
            '1c0fa4d8e2b2d0d0391c4b7c5cf2f494eab5c7074aa46cfd11a2d8a6b8c087030db7a5b74128d9bb04f6baa12abaa45457e0cfe790e9ebbd62721c075d79335e1c',
            '236660f4cc04df21289538bf15e83d5bd2858b9dad27022d6b83fc3374ce887d5789e1d40126823abf7ccef04d06e4a1717e6b6a00cbfacf5cc2e7b2e4cb384e1c',
        ]

    def test_ethereum_key_from_seedphrase(self):
        """
        Create key from seedphrase and index.
        """
        for i in range(len(self._keys)):
            key = EthereumKey.from_seedphrase(self._seedphrase, i)
            self.assertEqual(key.address(binary=False), self._addresses[i])

    def test_ethereum_key_from_bytes(self):
        """
        Create key from raw bytes.
        """
        for i in range(len(self._keys)):
            key_raw = a2b_hex(self._keys[i][2:])
            key = EthereumKey.from_bytes(key_raw)
            self.assertEqual(key.address(binary=False), self._addresses[i])
            self.assertEqual(key._key.key, key_raw)

    def test_ethereum_sign_typed_data_pesu_manual(self):
        """
        Test using py_eth_sig_utils by doing individual steps / manually.
        """
        key_raw = a2b_hex(self._keys[0][2:])

        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]

            # encode typed data dict and return message hash
            msg_hash = encode_typed_data(data)
            # print('0' * 100, b2a_hex(msg_hash).decode())
            self.assertEqual(msg_hash, a2b_hex(self._eip_data_obj_hashes[i]))

            # sign message hash with private key
            signature_vrs = ecsign(msg_hash, key_raw)

            # concatenate signature components into byte string
            signature = v_r_s_to_signature(*signature_vrs)
            # print('1' * 100, b2a_hex(signature).decode())

            # ECDSA signatures in Ethereum consist of three parameters: v, r and s.
            # The signature is always 65-bytes in length.
            #     r = first 32 bytes of signature
            #     s = second 32 bytes of signature
            #     v = final 1 byte of signature
            self.assertEqual(len(signature), 65)
            self.assertEqual(signature, a2b_hex(self._eip_data_obj_signatures[i]))

    def test_ethereum_sign_typed_data_pesu_highlevel(self):
        """
        Test using py_eth_sig_utils with high level functions.
        """
        key_raw = a2b_hex(self._keys[0][2:])
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]

            signature_vrs = sign_typed_data(data, key_raw)
            signature = v_r_s_to_signature(*signature_vrs)
            # print('2' * 100, b2a_hex(signature).decode())

            self.assertEqual(len(signature), 65)
            self.assertEqual(signature, a2b_hex(self._eip_data_obj_signatures[i]))

    @inlineCallbacks
    def test_ethereum_sign_typed_data_ab_async(self):
        """
        Test using autobahn with async functions.
        """
        key_raw = a2b_hex(self._keys[0][2:])
        key = EthereumKey.from_bytes(key_raw)
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]
            signature = yield key.sign_typed_data(data)
            self.assertEqual(signature, a2b_hex(self._eip_data_obj_signatures[i]))

    def test_ethereum_verify_typed_data_pesu_manual(self):
        """
        Test using py_eth_sig_utils by doing individual steps / manually.
        """
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]

            # encode typed data dict and return message hash
            msg_hash = encode_typed_data(data)

            signature = a2b_hex(self._eip_data_obj_signatures[i])
            signature_vrs = signature_to_v_r_s(signature)

            public_key = ecrecover_to_pub(msg_hash, *signature_vrs)
            address_bytes = sha3(public_key)[-20:]
            address = checksum_encode(address_bytes)

            self.assertEqual(address, self._addresses[0])

    def test_ethereum_verify_typed_data_pesu_highlevel(self):
        """
        Test using py_eth_sig_utils with high level functions.
        """
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]

            signature = a2b_hex(self._eip_data_obj_signatures[i])
            signature_vrs = signature_to_v_r_s(signature)

            address = recover_typed_data(data, *signature_vrs)

            self.assertEqual(address, self._addresses[0])

    @inlineCallbacks
    def test_ethereum_verify_typed_data_ab_async(self):
        """
        Test using autobahn with async functions.
        """
        key = EthereumKey.from_address(self._addresses[0])
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]
            signature = a2b_hex(self._eip_data_obj_signatures[i])
            sig_valid = yield key.verify_typed_data(data, signature)
            self.assertTrue(sig_valid)

    @inlineCallbacks
    def test_secmod_iterable(self):
        """
        This tests:

        * :meth:`SecurityModuleMemory.from_seedphrase`
        * :meth:`SecurityModuleMemory.__len__`
        * :meth:`SecurityModuleMemory.__iter__`
        * :meth:`SecurityModuleMemory.__getitem__`
        """
        sm = SecurityModuleMemory.from_seedphrase(self._seedphrase, 5, 5)
        yield sm.open()

        self.assertEqual(len(sm), 10)

        for i, key in sm.items():
            self.assertTrue(isinstance(key, EthereumKey) or isinstance(key, CryptosignKey),
                            'unexpected type {} returned in security module'.format(type(key)))
            key_ = sm[i]
            self.assertEqual(key_, key)

    @inlineCallbacks
    def test_secmod_create_key(self):
        """
        This tests:

        * :meth:`SecurityModuleMemory.create_key`
        """
        sm = SecurityModuleMemory()
        yield sm.open()

        self.assertEqual(len(sm), 0)

        for i in range(3):
            idx = yield sm.create_key('ethereum')
            self.assertEqual(idx, i * 2)
            self.assertEqual(len(sm), i * 2 + 1)
            key = sm[idx]
            self.assertTrue(isinstance(key, EthereumKey))
            self.assertEqual(key.security_module, sm)
            self.assertEqual(key.key_no, i * 2)
            self.assertEqual(key.key_type, 'ethereum')
            self.assertEqual(key.can_sign, True)

            idx = yield sm.create_key('cryptosign')
            self.assertEqual(idx, i * 2 + 1)
            self.assertEqual(len(sm), i * 2 + 2)
            key = sm[idx]
            self.assertTrue(isinstance(key, CryptosignKey))
            self.assertEqual(key.security_module, sm)
            self.assertEqual(key.key_no, i * 2 + 1)
            self.assertEqual(key.key_type, 'cryptosign')
            self.assertEqual(key.can_sign, True)

        self.assertEqual(len(sm), 6)

    @inlineCallbacks
    def test_secmod_delete_key(self):
        """
        This tests:

        * :meth:`SecurityModuleMemory.create_key`
        * :meth:`SecurityModuleMemory.delete_key`
        """
        sm = SecurityModuleMemory()
        yield sm.open()

        self.assertEqual(len(sm), 0)

        n = 10
        keys = []

        for i in range(n):
            if random() > .5:
                yield sm.create_key('ethereum')
            else:
                yield sm.create_key('cryptosign')
            key = sm[i]
            keys.append(key)
        self.assertEqual(len(sm), 10)

        for i in range(n):
            self.assertTrue(i in sm)
            yield sm.delete_key(i)
            self.assertFalse(i in sm)
            self.assertEqual(len(sm), n - i - 1)

    @inlineCallbacks
    def test_secmod_counters(self):
        """
        This tests:

        * :meth:`SecurityModuleMemory.__init__`
        * :meth:`SecurityModuleMemory.get_counter`
        * :meth:`SecurityModuleMemory.increment_counter`
        """
        sm = SecurityModuleMemory()
        yield sm.open()

        # counters are indexed beginning with 0
        counter = 0

        # initially, no counters exist, and hence value must be 0
        value = yield sm.get_counter(counter)
        self.assertEqual(value, 0)

        yield sm.get_counter(randint(0, 100))
        self.assertEqual(value, 0)

        # once incremented, counters exist
        for counter in range(10):
            for i in range(100):
                value = yield sm.increment_counter(counter)
                self.assertEqual(value, i + 1)

                value = yield sm.get_counter(counter)
                self.assertEqual(value, i + 1)

    def test_cryptosign_key_from_seedphrase(self):
        # seedphrase to compute keys from
        seedphrase = "myth like bonus scare over problem client lizard pioneer submit female collect"

        # pubkeys we expect
        pubs_keys: List[str] = [
            '30b2e1af1406c5f5254ddc456a045808796d13417f3b56500b0321a908cd89ca',
            '262b6812802deac81dd2be53d69cb32a05eb9296265e9698f02772867ede002f',
            '2d2ae42f8927b6c20fe4463151c3468367852c370a3b7db73ef10f97ce262739',
            'fab0eab3e14b24288b816dd590f21f90700a96306648cb2a031c7451dc5ee616',
            '1ce310832e5acb0359516400a881cf41d94ca60d9a529ce48a1b5f857cde0aa8',
        ]

        # create keys from seedphrase
        keys: List[CryptosignKey] = []
        for i in range(5):

            # BIP44 path for WAMP
            # https://github.com/wamp-proto/wamp-proto/issues/401
            # https://github.com/satoshilabs/slips/pull/1322
            derivation_path = "m/44'/655'/0'/0/{}".format(i)

            # compute private key from WAMP-Cryptosign from seedphrase and BIP44 path
            key_raw = mnemonic_to_private_key(seedphrase, derivation_path)
            assert type(key_raw) == bytes
            assert len(key_raw) == 32

            # create WAMP-Cryptosign key object from raw bytes
            key = CryptosignKey.from_bytes(key_raw)
            keys.append(key)

        # check public keys we expect
        for i in range(5):
            pub_key = keys[i].public_key(binary=False)
            self.assertEqual(pub_key, pubs_keys[i])

    @inlineCallbacks
    def test_secmod_from_seedphrase(self):
        # seedphrase to compute keys from
        seedphrase = "myth like bonus scare over problem client lizard pioneer submit female collect"

        sm = SecurityModuleMemory.from_seedphrase(seedphrase)
        yield sm.open()
        self.assertEqual(len(sm), 2)
        self.assertTrue(isinstance(sm[0], EthereumKey), 'unexpected type {} at index 0'.format(type(sm[0])))
        self.assertTrue(isinstance(sm[1], CryptosignKey), 'unexpected type {} at index 1'.format(type(sm[1])))
        yield sm.close()

        sm = SecurityModuleMemory.from_seedphrase(seedphrase, num_eth_keys=5, num_cs_keys=5)
        yield sm.open()
        self.assertEqual(len(sm), 10)
        for i in range(5):
            self.assertTrue(isinstance(sm[i], EthereumKey))
        for i in range(5, 10):
            self.assertTrue(isinstance(sm[i], CryptosignKey))
        yield sm.close()

    @inlineCallbacks
    def test_secmod_from_config(self):
        config = str(resources.files('autobahn.xbr.test.profile') / 'config.ini')

        sm = SecurityModuleMemory.from_config(config)
        yield sm.open()
        self.assertEqual(len(sm), 2)

        self.assertTrue(isinstance(sm[0], EthereumKey), 'unexpected type {} at index 0'.format(type(sm[0])))
        self.assertTrue(isinstance(sm[1], CryptosignKey), 'unexpected type {} at index 1'.format(type(sm[1])))

        key1: EthereumKey = sm[0]
        key2: CryptosignKey = sm[1]

        # public-key-ed25519: 15cfa4acef5cc312e0b9ba77634849d0a8c6222a546f90eb5123667935d2f561
        # public-adr-eth: 0xe59C7418403CF1D973485B36660728a5f4A8fF9c
        self.assertEqual(key1.address(binary=False), '0xe59C7418403CF1D973485B36660728a5f4A8fF9c')
        self.assertEqual(key2.public_key(binary=False), '15cfa4acef5cc312e0b9ba77634849d0a8c6222a546f90eb5123667935d2f561')

        yield sm.close()

    @inlineCallbacks
    def test_secmod_from_keyfile(self):
        keyfile = str(resources.files('autobahn.xbr.test.profile') / 'default.priv')

        sm = SecurityModuleMemory.from_keyfile(keyfile)
        yield sm.open()
        self.assertEqual(len(sm), 2)

        self.assertTrue(isinstance(sm[0], EthereumKey), 'unexpected type {} at index 0'.format(type(sm[0])))
        self.assertTrue(isinstance(sm[1], CryptosignKey), 'unexpected type {} at index 1'.format(type(sm[1])))

        key1: EthereumKey = sm[0]
        key2: CryptosignKey = sm[1]

        # public-key-ed25519: 15cfa4acef5cc312e0b9ba77634849d0a8c6222a546f90eb5123667935d2f561
        # public-adr-eth: 0xe59C7418403CF1D973485B36660728a5f4A8fF9c
        self.assertEqual(key1.address(binary=False), '0xe59C7418403CF1D973485B36660728a5f4A8fF9c')
        self.assertEqual(key2.public_key(binary=False), '15cfa4acef5cc312e0b9ba77634849d0a8c6222a546f90eb5123667935d2f561')

        yield sm.close()
