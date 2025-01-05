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
import json
import binascii
import sys

if sys.version_info < (3, 10):
    import importlib_resources as resources
else:
    from importlib import resources


os.environ['ETH_HASH_BACKEND'] = 'pycryptodome'

# from eth_hash.backends.pycryptodome import keccak256  # noqa
# print('Using eth_hash backend {}'.format(keccak256))
import web3

import xbr


XBR_ABI_VERSION = xbr.__version__
"""
XBR Protocol contracts ABI bundle (Python package) version.
"""


#
# Set default XBR contract addresses to
# XBR v20.5.1. @ Rinkeby (https://github.com/crossbario/xbr-protocol/issues/127)
#
if 'XBR_DEBUG_TOKEN_ADDR' in os.environ:
    _token_adr = os.environ['XBR_DEBUG_TOKEN_ADDR']
    try:
        _token_adr = binascii.a2b_hex(_token_adr[2:])
        _token_adr = web3.Web3.toChecksumAddress(_token_adr)
    except Exception as e:
        raise RuntimeError('could not parse Ethereum address for XBR_DEBUG_TOKEN_ADDR={} - {}'.format(_token_adr, e))
    XBR_DEBUG_TOKEN_ADDR = _token_adr
    XBR_DEBUG_TOKEN_ADDR_SRC = 'envvar $XBR_DEBUG_TOKEN_ADDR'
else:
    XBR_DEBUG_TOKEN_ADDR = '0xaCef957D54c639575f4DB68b1992B36504f33FEA'
    XBR_DEBUG_TOKEN_ADDR_SRC = 'builtin'

if 'XBR_DEBUG_NETWORK_ADDR' in os.environ:
    _netw_adr = os.environ['XBR_DEBUG_NETWORK_ADDR']
    try:
        _netw_adr = binascii.a2b_hex(_netw_adr[2:])
        _netw_adr = web3.Web3.toChecksumAddress(_netw_adr)
    except Exception as e:
        raise RuntimeError('could not parse Ethereum address for XBR_DEBUG_NETWORK_ADDR={} - {}'.format(_netw_adr, e))
    XBR_DEBUG_NETWORK_ADDR = _netw_adr
    XBR_DEBUG_NETWORK_ADDR_SRC = 'envvar $XBR_DEBUG_NETWORK_ADDR'
else:
    XBR_DEBUG_NETWORK_ADDR = '0x7A3d22c59e8F8f1b88ba7205f3f5a65Bc86D04Bc'
    XBR_DEBUG_NETWORK_ADDR_SRC = 'builtin'

if 'XBR_DEBUG_DOMAIN_ADDR' in os.environ:
    _domain_adr = os.environ['XBR_DEBUG_DOMAIN_ADDR']
    try:
        _domain_adr = binascii.a2b_hex(_domain_adr[2:])
        _domain_adr = web3.Web3.toChecksumAddress(_domain_adr)
    except Exception as e:
        raise RuntimeError('could not parse Ethereum address for XBR_DEBUG_DOMAIN_ADDR={} - {}'.format(_domain_adr, e))
    XBR_DEBUG_DOMAIN_ADDR = _domain_adr
    XBR_DEBUG_DOMAIN_ADDR_SRC = 'envvar $XBR_DEBUG_DOMAIN_ADDR'
else:
    XBR_DEBUG_DOMAIN_ADDR = '0xf5fb56886f033855C1a36F651E927551749361bC'
    XBR_DEBUG_DOMAIN_ADDR_SRC = 'builtin'

if 'XBR_DEBUG_CATALOG_ADDR' in os.environ:
    _ctlg_adr = os.environ['XBR_DEBUG_CATALOG_ADDR']
    try:
        _ctlg_adr = binascii.a2b_hex(_ctlg_adr[2:])
        _ctlg_adr = web3.Web3.toChecksumAddress(_ctlg_adr)
    except Exception as e:
        raise RuntimeError('could not parse Ethereum address for XBR_DEBUG_CATALOG_ADDR={} - {}'.format(_ctlg_adr, e))
    XBR_DEBUG_CATALOG_ADDR = _ctlg_adr
    XBR_DEBUG_CATALOG_ADDR_SRC = 'envvar $XBR_DEBUG_CATALOG_ADDR'
else:
    XBR_DEBUG_CATALOG_ADDR = '0x2C77E46Ea9502B363343e8c826c41c7fdb25Db66'
    XBR_DEBUG_CATALOG_ADDR_SRC = 'builtin'

if 'XBR_DEBUG_MARKET_ADDR' in os.environ:
    _mrkt_adr = os.environ['XBR_DEBUG_MARKET_ADDR']
    try:
        _mrkt_adr = binascii.a2b_hex(_mrkt_adr[2:])
        _mrkt_adr = web3.Web3.toChecksumAddress(_mrkt_adr)
    except Exception as e:
        raise RuntimeError('could not parse Ethereum address for XBR_DEBUG_MARKET_ADDR={} - {}'.format(_mrkt_adr, e))
    XBR_DEBUG_MARKET_ADDR = _mrkt_adr
    XBR_DEBUG_MARKET_ADDR_SRC = 'envvar $XBR_DEBUG_MARKET_ADDR'
else:
    XBR_DEBUG_MARKET_ADDR = '0x0DcF924ab0846101d31514E9fb3adf5070d4B83d'
    XBR_DEBUG_MARKET_ADDR_SRC = 'builtin'

if 'XBR_DEBUG_CHANNEL_ADDR' in os.environ:
    _chnl_adr = os.environ['XBR_DEBUG_CHANNEL_ADDR']
    try:
        _chnl_adr = binascii.a2b_hex(_chnl_adr[2:])
        _chnl_adr = web3.Web3.toChecksumAddress(_chnl_adr)
    except Exception as e:
        raise RuntimeError('could not parse Ethereum address for XBR_DEBUG_CHANNEL_ADDR={} - {}'.format(_chnl_adr, e))
    XBR_DEBUG_CHANNEL_ADDR = _chnl_adr
    XBR_DEBUG_CHANNEL_ADDR_SRC = 'envvar $XBR_DEBUG_CHANNEL_ADDR'
else:
    XBR_DEBUG_CHANNEL_ADDR = '0x670497A012322B99a5C18B8463940996141Cb952'
    XBR_DEBUG_CHANNEL_ADDR_SRC = 'builtin'


def _load_json(contract_name):
    fn = resources.files('xbr.abi') / f'{contract_name}.json'
    text = fn.read_text()
    data = json.loads(text)
    return data


#
# XBR contract ABI file names
#
XBR_TOKEN_FN = str(resources.files('xbr.abi') / 'XBRToken.json')
XBR_NETWORK_FN = str(resources.files('xbr.abi') / 'XBRNetwork.json')
XBR_DOMAIN_FN = str(resources.files('xbr.abi') / 'XBRDomain.json')
XBR_CATALOG_FN = str(resources.files('xbr.abi') / 'XBRCatalog.json')
XBR_MARKET_FN = str(resources.files('xbr.abi') / 'XBRMarket.json')
XBR_CHANNEL_FN = str(resources.files('xbr.abi') / 'XBRChannel.json')


#
# XBR contract ABIs
#
XBR_TOKEN_ABI = _load_json('XBRToken')['abi']
XBR_NETWORK_ABI = _load_json('XBRNetwork')['abi']
XBR_DOMAIN_ABI = _load_json('XBRDomain')['abi']
XBR_CATALOG_ABI = _load_json('XBRCatalog')['abi']
XBR_MARKET_ABI = _load_json('XBRMarket')['abi']
XBR_CHANNEL_ABI = _load_json('XBRChannel')['abi']
