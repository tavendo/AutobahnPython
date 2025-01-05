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
import platform
import shutil

from setuptools import setup

CPY = platform.python_implementation() == 'CPython'

# read version string
with open('autobahn/_version.py') as f:
    exec(f.read())  # defines __version__

# read package long description
with open('README.rst') as f:
    docstr = f.read()

# Twisted dependencies (be careful bumping these minimal versions,
# as we make claim to support older Twisted!)
extras_require_twisted = [
    "zope.interface>=5.2.0",        # Zope Public License
    "twisted>=24.3.0",              # MIT license (https://pypi.org/project/Twisted/24.3.0/)
    "attrs>=20.3.0"                 # MIT license (https://pypi.org/project/attrs/19.2.0/)
]

# C-based WebSocket acceleration (only use on CPython, not PyPy!)
# wsaccel does not provide wheels: https://github.com/methane/wsaccel/issues/12
extras_require_accelerate = [
    # "wsaccel>=0.6.3 ; platform_python_implementation == 'CPython' and sys_platform != 'win32'"  # Apache 2.0
]

# non-standard WebSocket compression support (FIXME: consider removing altogether)
# Ubuntu: sudo apt-get install libsnappy-dev
extras_require_compress = [
    "python-snappy>=0.6.0",         # BSD license
]

# accelerated JSON and non-JSON WAMP serialization support (namely MessagePack, CBOR and UBJSON)
extras_require_serialization = []
extras_require_serialization.extend([
    'msgpack>=1.0.2 ; platform_python_implementation == "CPython"',           # Apache 2.0 license
    'ujson>=4.0.2 ; platform_python_implementation == "CPython"',             # BSD license
    'u-msgpack-python>=2.1 ; platform_python_implementation != "CPython"',    # MIT license
])
if not CPY:
    os.environ['PYUBJSON_NO_EXTENSION'] = '1'  # enforce use of pure Python py-ubjson (no Cython)

extras_require_serialization.extend([
    'cbor2>=5.2.0',             # MIT license
    'py-ubjson>=0.16.1',        # Apache 2.0 license
    'flatbuffers>=22.12.6',     # Apache 2.0 license
])

# TLS transport encryption
# WAMP-cryptosign end-to-end encryption
# WAMP-cryptosign authentication
os.environ['SODIUM_INSTALL'] = 'bundled'  # enforce use of bundled libsodium
extras_require_encryption = [
    'pyopenssl>=20.0.1',            # Apache 2.0 license
    'service_identity>=18.1.0',     # MIT license
    'pynacl>=1.4.0',                # Apache license
    'pytrie>=0.4.0',                # BSD license
    'qrcode>=7.3.1',                # BSD license
]

# Support for WAMP-SCRAM authentication
extras_require_scram = [
    'cffi>=1.14.5',             # MIT license
    'argon2_cffi>=20.1.0',      # MIT license
    'passlib>=1.7.4',           # BSD license
]

# Support native vector (SIMD) acceleration included with Autobahn
extras_require_nvx = [
    'cffi>=1.14.5',             # MIT license
]

# cffi based extension modules to build, currently only NVX
cffi_modules = []
if 'AUTOBAHN_USE_NVX' not in os.environ or os.environ['AUTOBAHN_USE_NVX'] not in ['0', 'false']:
    cffi_modules.append('autobahn/nvx/_utf8validator.py:ffi')

# https://peps.python.org/pep-0440/#direct-references
# https://stackoverflow.com/a/63688209/884770
extras_require_xbr = [
    # bitarray is required by eth-account, but on pypy
    # see discussion/links on https://github.com/crossbario/autobahn-python/pull/1617
    'bitarray>=2.7.5',          # PSF
    # 'bitarray @ git+https://github.com/ilanschnell/bitarray.git@master#egg=bitarray',

    # XBR contracts and ABI file bundle
    'xbr>=21.2.1',              # Apache 2.0

    # CLI handling and color terminal output
    'click>=8.1.2',             # BSD license

    # the following is needed for XBR basics and XBR IDL code generation
    'cbor2>=5.2.0',             # MIT license
    'zlmdb>=21.2.1',            # MIT license
    'twisted>=20.3.0',          # MIT license

    # ImportError: cannot import name 'getargspec' from 'inspect'
    # https://github.com/ethereum/web3.py/issues/2704#issuecomment-1369041219
    # pip install git+https://github.com/ethereum/web3.py.git
    'web3[ipfs]>=6.0.0',        # MIT license

    # the following is needed for EIP712 ("signed typed data"):
    'rlp>=2.0.1',               # MIT license
    'py-eth-sig-utils>=0.4.0',  # MIT license (https://github.com/rmeissner/py-eth-sig-utils)
    'py-ecc>=5.1.0',            # MIT license (https://github.com/ethereum/py_ecc)

    'eth-abi>=4.0.0',           # MIT license (https://github.com/ethereum/eth-abi)

    # the following is needed (at least) for BIP32/39 mnemonic processing
    'mnemonic>=0.19',           # MIT license (https://github.com/trezor/python-mnemonic)
    'base58>=2.1.0',            # MIT license (https://github.com/keis/base58)
    'ecdsa>=0.16.1',            # MIT license (https://github.com/warner/python-ecdsa)
    'py-multihash>=2.0.1',      # MIT license (https://github.com/multiformats/py-multihash / https://pypi.org/project/py-multihash/)

    # the following is needed for the WAMP/XBR IDL code generator
    'jinja2>=2.11.3',           # BSD license
    'yapf==0.29.0',             # Apache 2.0

    # the following is needed for XBR account synch and device pairing
    'spake2>=0.8',              # MIT license (https://github.com/warner/python-spake2/blob/master/LICENSE)
    'hkdf>=0.0.3',              # BSD 2-Clause "Simplified" License
]

# required for UI based tools, e.g. xbrnetwork-ui (autobahn.xbr._gui:_main)
extras_require_ui = [
    # the following is needed for the graphical XBR onboarding UI
    'PyGObject>=3.40.0',        # GNU Lesser General Public License v2 or later (LGPLv2+) (GNU LGPL)
]

# everything
extras_require_all = extras_require_twisted + extras_require_accelerate + extras_require_compress + \
                     extras_require_serialization + extras_require_encryption + extras_require_scram + \
                     extras_require_nvx + extras_require_xbr + extras_require_ui

packages = [
    'autobahn',
    'autobahn.test',
    'autobahn.wamp',
    'autobahn.wamp.gen',
    'autobahn.wamp.gen.wamp',
    'autobahn.wamp.gen.wamp.proto',
    'autobahn.wamp.test',
    'autobahn.websocket',
    'autobahn.websocket.test',
    'autobahn.rawsocket',
    'autobahn.rawsocket.test',
    'autobahn.asyncio',
    'autobahn.twisted',
    'autobahn.twisted.test',
    'autobahn.twisted.testing',
    'autobahn.nvx',
    'autobahn.nvx.test',
    'twisted.plugins',
]

xbr_packages = [
    'autobahn.xbr',
    'autobahn.xbr.test',
    'autobahn.asyncio.xbr',
    'autobahn.twisted.xbr',
]

package_data = {'autobahn.asyncio': ['./test/*']}

entry_points = {
    "console_scripts": [
        "wamp = autobahn.__main__:_main",
    ]
}

if 'AUTOBAHN_STRIP_XBR' in os.environ:
    # force regeneration of egg-info manifest for stripped install
    shutil.rmtree('autobahn.egg-info', ignore_errors=True)
else:
    extras_require_all += extras_require_xbr
    packages += xbr_packages
    package_data['xbr'] = [
        './xbr/templates/py-autobahn/*.py.jinja2',
        './xbr/templates/sol-eip712/*.sol.jinja2',
    ]
    entry_points['console_scripts'] += ["xbrnetwork = autobahn.xbr._cli:_main"]
    entry_points['console_scripts'] += ["xbrnetwork-ui = autobahn.xbr._gui:_main"]

# development dependencies
extras_require_dev = []
with open('requirements-dev.txt') as f:
    for line in f.read().splitlines():
        line = line.strip()
        if not line.startswith('#'):
            extras_require_dev.append(line)

setup(
    name='autobahn',
    version=__version__,  # noqa
    description='WebSocket client & server library, WAMP real-time framework',
    long_description=docstr,
    license='MIT License',
    author='typedef int GmbH',
    url='https://github.com/crossbario/autobahn-python',
    project_urls={
        'Source': 'https://github.com/crossbario/autobahn-python',
    },
    platforms='Any',
    install_requires=[
        'txaio>=21.2.1',        # MIT license (https://github.com/crossbario/txaio)
        'cryptography>=3.4.6',  # BSD *or* Apache license (https://github.com/pyca/cryptography)
        'hyperlink>=21.0.0',    # MIT license (https://github.com/python-hyper/hyperlink)
        'importlib.resources>=5.0.0 ; python_version < "3.10"',    # Apache license (https://github.com/python/importlib_resources/blob/main/LICENSE)

    ],
    extras_require={
        'all': extras_require_all,
        'asyncio': [],  # backwards compatibility
        'twisted': extras_require_twisted,
        'accelerate': extras_require_accelerate,
        'compress': extras_require_compress,
        'serialization': extras_require_serialization,
        'encryption': extras_require_encryption,
        'scram': extras_require_scram,
        'nvx': extras_require_nvx,
        'dev': extras_require_dev,
        'xbr': extras_require_xbr,
        'ui': extras_require_ui,
    },
    packages=packages,
    package_data=package_data,
    cffi_modules=cffi_modules,

    entry_points=entry_points,

    # this flag will make files from MANIFEST.in go into _source_ distributions only
    include_package_data=True,

    zip_safe=False,

    python_requires='>=3.9',

    # http://pypi.python.org/pypi?%3Aaction=list_classifiers
    classifiers=["License :: OSI Approved :: MIT License",
                 "Development Status :: 5 - Production/Stable",
                 "Environment :: No Input/Output (Daemon)",
                 "Framework :: Twisted",
                 "Intended Audience :: Developers",
                 "Operating System :: OS Independent",
                 "Programming Language :: Python",
                 "Programming Language :: Python :: 3",
                 "Programming Language :: Python :: 3.9",
                 "Programming Language :: Python :: 3.10",
                 "Programming Language :: Python :: 3.11",
                 "Programming Language :: Python :: Implementation :: CPython",
                 "Programming Language :: Python :: Implementation :: PyPy",
                 "Topic :: Internet",
                 "Topic :: Internet :: WWW/HTTP",
                 "Topic :: Communications",
                 "Topic :: System :: Distributed Computing",
                 "Topic :: Software Development :: Libraries",
                 "Topic :: Software Development :: Libraries :: Python Modules",
                 "Topic :: Software Development :: Object Brokering"],
    keywords='autobahn crossbar websocket realtime rfc6455 wamp rpc pubsub twisted asyncio xbr data-markets blockchain ethereum'
)


# regenerate Twisted plugin cache
try:
    from twisted.internet import reactor
    print("Twisted found (default reactor is {0})".format(reactor.__class__))
except ImportError:
    # the user doesn't have Twisted, so skip
    pass
else:
    # Make Twisted regenerate the dropin.cache, if possible. This is necessary
    # because in a site-wide install, dropin.cache cannot be rewritten by
    # normal users.
    try:
        from twisted.plugin import IPlugin, getPlugins
        list(getPlugins(IPlugin))
    except Exception as e:
        print("Failed to update Twisted plugin cache: {0}".format(e))
    else:
        print("Twisted dropin.cache regenerated.")
