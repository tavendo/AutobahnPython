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
from binascii import a2b_hex, b2a_hex
from unittest import skipIf

from twisted.internet.defer import inlineCallbacks
from twisted.trial.unittest import TestCase

from autobahn.wamp.cryptosign import HAS_CRYPTOSIGN
from autobahn.xbr import HAS_XBR

if HAS_XBR and HAS_CRYPTOSIGN:
    from autobahn.wamp.cryptosign import CryptosignKey
    from autobahn.xbr import make_w3, EthereumKey
    from autobahn.xbr._secmod import SecurityModuleMemory
    from autobahn.xbr import create_eip712_delegate_certificate, create_eip712_authority_certificate
    from autobahn.xbr._eip712_delegate_certificate import EIP712DelegateCertificate

# https://web3py.readthedocs.io/en/stable/providers.html#infura-mainnet
HAS_INFURA = 'WEB3_INFURA_PROJECT_ID' in os.environ and len(os.environ['WEB3_INFURA_PROJECT_ID']) > 0

# TypeError: As of 3.10, the *loop* parameter was removed from Lock() since it is no longer necessary
IS_CPY_310 = sys.version_info.minor == 10


@skipIf(not os.environ.get('USE_TWISTED', False), 'only for Twisted')
@skipIf(not HAS_INFURA, 'env var WEB3_INFURA_PROJECT_ID not defined')
@skipIf(not (HAS_XBR and HAS_CRYPTOSIGN), 'package autobahn[encryption,xbr] not installed')
class TestEip712Certificate(TestCase):

    def setUp(self):
        self._gw_config = {
            'type': 'infura',
            'key': os.environ.get('WEB3_INFURA_PROJECT_ID', ''),
            'network': 'mainnet',
        }
        self._w3 = make_w3(self._gw_config)

        self._seedphrase = "avocado style uncover thrive same grace crunch want essay reduce current edge"
        self._sm: SecurityModuleMemory = SecurityModuleMemory.from_seedphrase(self._seedphrase, num_eth_keys=5,
                                                                              num_cs_keys=5)

    @inlineCallbacks
    def test_eip712_delegate_certificate(self):
        yield self._sm.open()

        delegate_eth_key: EthereumKey = self._sm[1]
        delegate_cs_key: CryptosignKey = self._sm[6]

        chainId = 1
        verifyingContract = a2b_hex('0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57'[2:])
        validFrom = 15124128
        delegate = delegate_eth_key.address(binary=True)
        csPubKey = delegate_cs_key.public_key(binary=True)
        bootedAt = 1657579546469365046  # txaio.time_ns()

        cert_data = create_eip712_delegate_certificate(chainId=chainId, verifyingContract=verifyingContract,
                                                       validFrom=validFrom, delegate=delegate, csPubKey=csPubKey,
                                                       bootedAt=bootedAt)

        # print('\n\n{}\n\n'.format(pformat(cert_data)))

        cert_sig = yield delegate_eth_key.sign_typed_data(cert_data, binary=False)

        self.assertEqual(cert_sig,
                         'fcf69947bceac2d7b224dcbc739e6e824f9fcabc526dbcaf8c28de7e9a44969d4b332584bbd8a34c0a12f57041146d888d6fd5b9db1031d5b083f169bf70edeb1c')

        yield self._sm.close()

    @inlineCallbacks
    def test_eip712_authority_certificate(self):
        yield self._sm.open()

        trustroot_eth_key: EthereumKey = self._sm[0]
        delegate_eth_key: EthereumKey = self._sm[1]

        chainId = 1
        verifyingContract = a2b_hex('0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57'[2:])
        validFrom = 15124128
        authority = a2b_hex('0xe78ea2fE1533D4beD9A10d91934e109A130D0ad8'[2:])
        delegate = delegate_eth_key.address(binary=True)
        domain = a2b_hex('0x5f61F4c611501c1084738c0c8c5EbB5D3d8f2B6E'[2:])
        realm = a2b_hex('0xA6e693CC4A2b4F1400391a728D26369D9b82ef96'[2:])
        role = 'consumer'
        reservation = a2b_hex('0x52d66f36A7927cF9612e1b40bD6549d08E0513Ff'[2:])

        cert_data = create_eip712_authority_certificate(chainId=chainId, verifyingContract=verifyingContract,
                                                        validFrom=validFrom, authority=authority, delegate=delegate,
                                                        domain=domain, realm=realm, role=role, reservation=reservation)

        # print('\n\n{}\n\n'.format(pformat(cert_data)))

        cert_sig = yield trustroot_eth_key.sign_typed_data(cert_data, binary=False)

        self.assertEqual(cert_sig,
                         'd13a710d10a2ab1b3466db7a890eec48d0b9e35a7f8595baa43cdfdc44854a9a07db9489d368db2a461e6fb7d554d1129df3076a1830b22992e7ed660ab10d101c')

        yield self._sm.close()


@skipIf(not os.environ.get('USE_TWISTED', False), 'only for Twisted')
@skipIf(not HAS_INFURA, 'env var WEB3_INFURA_PROJECT_ID not defined')
@skipIf(not (HAS_XBR and HAS_CRYPTOSIGN), 'package autobahn[encryption,xbr] not installed')
class TestEip712CertificateChain(TestCase):

    def setUp(self):
        self._gw_config = {
            'type': 'infura',
            'key': os.environ.get('WEB3_INFURA_PROJECT_ID', ''),
            'network': 'mainnet',
        }
        self._w3 = make_w3(self._gw_config)

        self._seedphrase = "avocado style uncover thrive same grace crunch want essay reduce current edge"
        self._sm: SecurityModuleMemory = SecurityModuleMemory.from_seedphrase(self._seedphrase, num_eth_keys=5,
                                                                              num_cs_keys=5)

        # HELLO.Details.authextra.certificates
        #
        self._certs_expected1 = [
            ({'domain': {'name': 'WMP', 'version': '1'},
              'message': {'bootedAt': 1657781999086394759,
                          'chainId': 1,
                          'csPubKey': '12ae0184b180e9a9c5e45be4a1afbce3c6491320063701cd9c4011a777d04089',
                          'delegate': '0xf5173a6111B2A6B3C20fceD53B2A8405EC142bF6',
                          'validFrom': 15139218,
                          'verifyingContract': '0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57'},
              'primaryType': 'EIP712DelegateCertificate',
              'types': {'EIP712DelegateCertificate': [{'name': 'chainId', 'type': 'uint256'},
                                                      {'name': 'verifyingContract', 'type': 'address'},
                                                      {'name': 'validFrom', 'type': 'uint256'},
                                                      {'name': 'delegate', 'type': 'address'},
                                                      {'name': 'csPubKey', 'type': 'bytes32'},
                                                      {'name': 'bootedAt', 'type': 'uint64'}],
                        'EIP712Domain': [{'name': 'name', 'type': 'string'},
                                         {'name': 'version', 'type': 'string'}]}},
             '7a54cb99f1dc5ea004484691a2f18ce8b40ebe32b026897bb31f12414e4d0db61c1870df5c1f721926c95f38d41034eec00f6c7a4e10ba6bf41ba45b78e4cb521b'),
            ({'domain': {'name': 'WMP', 'version': '1'},
              'message': {'authority': '0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57',
                          'chainId': 1,
                          'delegate': '0xf5173a6111B2A6B3C20fceD53B2A8405EC142bF6',
                          'domain': '0x5f61F4c611501c1084738c0c8c5EbB5D3d8f2B6E',
                          'realm': '0xA6e693CC4A2b4F1400391a728D26369D9b82ef96',
                          'reservation': '0x52d66f36A7927cF9612e1b40bD6549d08E0513Ff',
                          'role': 'consumer',
                          'validFrom': 15139218,
                          'verifyingContract': '0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57'},
              'primaryType': 'EIP712AuthorityCertificate',
              'types': {'EIP712AuthorityCertificate': [{'name': 'chainId', 'type': 'uint256'},
                                                       {'name': 'verifyingContract', 'type': 'address'},
                                                       {'name': 'validFrom', 'type': 'uint256'},
                                                       {'name': 'authority', 'type': 'address'},
                                                       {'name': 'delegate', 'type': 'address'},
                                                       {'name': 'domain', 'type': 'address'},
                                                       {'name': 'realm', 'type': 'address'},
                                                       {'name': 'role', 'type': 'string'},
                                                       {'name': 'reservation', 'type': 'address'}],
                        'EIP712Domain': [{'name': 'name', 'type': 'string'},
                                         {'name': 'version', 'type': 'string'}]}},
             'fbde7089eca0299678e6f106ea5b55c2b52276b381d66de0855b9e13a5ad601a019343b853f02307510cacd3168942b04c31ed019a8b536e451095115062196e1c')
        ]

    @inlineCallbacks
    def test_eip712_create_certificate_chain(self):
        yield self._sm.open()

        # keys needed to create all certificates in certificate chain
        #
        trustroot_eth_key: EthereumKey = self._sm[0]
        delegate_eth_key: EthereumKey = self._sm[1]
        delegate_cs_key: CryptosignKey = self._sm[6]

        # data needed for delegate certificate
        #
        chainId = 1  # self._w3.eth.chain_id
        verifyingContract = a2b_hex('0xf766Dc789CF04CD18aE75af2c5fAf2DA6650Ff57'[2:])
        validFrom = 15139218  # self._w3.eth.block_number
        delegate = delegate_eth_key.address(binary=True)
        csPubKey = delegate_cs_key.public_key(binary=True)
        bootedAt = 1657781999086394759  # txaio.time_ns()

        # data needed for authority certificate
        #
        authority = trustroot_eth_key.address(binary=True)
        domain = a2b_hex('0x5f61F4c611501c1084738c0c8c5EbB5D3d8f2B6E'[2:])
        realm = a2b_hex('0xA6e693CC4A2b4F1400391a728D26369D9b82ef96'[2:])
        role = 'consumer'
        reservation = a2b_hex('0x52d66f36A7927cF9612e1b40bD6549d08E0513Ff'[2:])

        # create delegate certificate
        #
        cert1_data = create_eip712_delegate_certificate(chainId=chainId, verifyingContract=verifyingContract,
                                                        validFrom=validFrom, delegate=delegate, csPubKey=csPubKey,
                                                        bootedAt=bootedAt)

        cert1_sig = yield delegate_eth_key.sign_typed_data(cert1_data, binary=False)

        cert1_data['message']['csPubKey'] = b2a_hex(cert1_data['message']['csPubKey']).decode()
        cert1_data['message']['delegate'] = self._w3.toChecksumAddress(cert1_data['message']['delegate'])
        cert1_data['message']['verifyingContract'] = self._w3.toChecksumAddress(
            cert1_data['message']['verifyingContract'])

        # create authority certificate
        #
        cert2_data = create_eip712_authority_certificate(chainId=chainId, verifyingContract=verifyingContract,
                                                         validFrom=validFrom, authority=authority, delegate=delegate,
                                                         domain=domain, realm=realm, role=role, reservation=reservation)

        cert2_sig = yield trustroot_eth_key.sign_typed_data(cert2_data, binary=False)

        cert2_data['message']['delegate'] = self._w3.toChecksumAddress(cert2_data['message']['delegate'])
        cert2_data['message']['verifyingContract'] = self._w3.toChecksumAddress(
            cert2_data['message']['verifyingContract'])
        cert2_data['message']['authority'] = self._w3.toChecksumAddress(cert2_data['message']['authority'])
        cert2_data['message']['domain'] = self._w3.toChecksumAddress(cert2_data['message']['domain'])
        cert2_data['message']['realm'] = self._w3.toChecksumAddress(cert2_data['message']['realm'])
        cert2_data['message']['reservation'] = self._w3.toChecksumAddress(cert2_data['message']['reservation'])

        # create certificates chain
        #
        certificates = [(cert1_data, cert1_sig), (cert2_data, cert2_sig)]

        self.assertEqual(cert1_sig, '7a54cb99f1dc5ea004484691a2f18ce8b40ebe32b026897bb31f12414e4d0db61c1870df5c1f721926c95f38d41034eec00f6c7a4e10ba6bf41ba45b78e4cb521b')
        self.assertEqual(cert2_sig, 'fbde7089eca0299678e6f106ea5b55c2b52276b381d66de0855b9e13a5ad601a019343b853f02307510cacd3168942b04c31ed019a8b536e451095115062196e1c')


        self.assertEqual(certificates, self._certs_expected1)

        yield self._sm.close()

    @inlineCallbacks
    def test_eip712_verify_certificate_chain(self):
        yield self._sm.open()

        # keys needed to create all certificates in certificate chain
        #
        trustroot_eth_key: EthereumKey = self._sm[0]
        delegate_eth_key: EthereumKey = self._sm[1]
        delegate_cs_key: CryptosignKey = self._sm[6]

        for cert_data, cert_sig in self._certs_expected1:
            self.assertIn('domain', cert_data)
            self.assertIn('message', cert_data)
            self.assertIn('primaryType', cert_data)
            self.assertIn('types', cert_data)
            self.assertIn(cert_data['primaryType'], cert_data['types'])

            self.assertIn(cert_data['primaryType'], ['EIP712DelegateCertificate', 'EIP712AuthorityCertificate'])

            if cert_data['primaryType'] == 'EIP712DelegateCertificate':
                cert = EIP712DelegateCertificate.parse(cert_data['message'])

        yield self._sm.close()
