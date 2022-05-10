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
import sys
from binascii import a2b_hex
# from binascii import b2a_hex
from unittest import skipIf

from twisted.internet.defer import inlineCallbacks
from twisted.trial.unittest import TestCase

from py_eth_sig_utils.eip712 import encode_typed_data
from py_eth_sig_utils.utils import ecsign
from py_eth_sig_utils.signing import v_r_s_to_signature, signature_to_v_r_s
from py_eth_sig_utils.signing import sign_typed_data, recover_typed_data

from autobahn.xbr import HAS_XBR
from autobahn.xbr import make_w3, EthereumKey
from autobahn.xbr._eip712_member_register import _create_eip712_member_register
from autobahn.xbr._eip712_market_create import _create_eip712_market_create

# https://web3py.readthedocs.io/en/stable/providers.html#infura-mainnet
HAS_INFURA = 'WEB3_INFURA_PROJECT_ID' in os.environ and len(os.environ['WEB3_INFURA_PROJECT_ID']) > 0

# TypeError: As of 3.10, the *loop* parameter was removed from Lock() since it is no longer necessary
IS_CPY_310 = sys.version_info.minor == 10


@skipIf(not os.environ.get('USE_TWISTED', False), 'only for Twisted')
@skipIf(not HAS_INFURA, 'env var WEB3_INFURA_PROJECT_ID not defined')
@skipIf(not HAS_XBR, 'package autobahn[xbr] not installed')
class TestEthereumKey(TestCase):

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

    def test_key_from_seedphrase(self):
        """
        Create key from seedphrase and index.
        """
        for i in range(len(self._keys)):
            key = EthereumKey.from_seedphrase(self._seedphrase, i)
            self.assertEqual(key.address(binary=False), self._addresses[i])

    def test_key_from_bytes(self):
        """
        Create key from raw bytes.
        """
        for i in range(len(self._keys)):
            key_raw = a2b_hex(self._keys[i][2:])
            key = EthereumKey.from_bytes(key_raw)
            self.assertEqual(key.address(binary=False), self._addresses[i])
            self.assertEqual(key._key.key, key_raw)

    def test_sign_typed_data_pesu_manual(self):
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

    def test_sign_typed_data_pesu_highlevel(self):
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
    def test_sign_typed_data_ab_async(self):
        """
        Test using autobahn with async functions.
        """
        key_raw = a2b_hex(self._keys[0][2:])
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]

            key = EthereumKey.from_bytes(key_raw)
            signature = yield key.sign_typed_data(data)

            self.assertEqual(signature, a2b_hex(self._eip_data_obj_signatures[i]))

    def test_verify_typed_data_pesu_highlevel(self):
        """
        Test using py_eth_sig_utils with high level functions.
        """
        for i in range(len(self._eip_data_objects)):
            data = self._eip_data_objects[i]
            signature = a2b_hex(self._eip_data_obj_signatures[i])
            signature_vrs = signature_to_v_r_s(signature)
            address = recover_typed_data(data, *signature_vrs)
            self.assertEqual(address, self._addresses[0])

    # def test_verify_typed_data_pesu_manual(self):
    #     pass
    #
    # def test_verify_typed_data_ab_async(self):
    #     pass
