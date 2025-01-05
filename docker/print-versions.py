import os
import sys
import platform
import importlib
import importlib.metadata

import txaio
txaio.use_twisted()  # noqa

from twisted.internet import reactor
from twisted.python.reflect import qual

import autobahn
from autobahn import xbr

from autobahn.websocket.protocol import WebSocketProtocol
from autobahn.websocket.utf8validator import Utf8Validator
from autobahn.websocket.xormasker import XorMaskerNull


def _get_version(name_or_module):
    if isinstance(name_or_module, str):
        name_or_module = importlib.import_module(name_or_module)

    if hasattr(name_or_module, '__version__'):
        v = name_or_module.__version__
    elif hasattr(name_or_module, 'version'):
        v = name_or_module.version
    else:
        try:
            v = importlib.metadata.version(name_or_module.__name__)
        except:
            # eg flatbuffers when run from single file EXE (pyinstaller): https://github.com/google/flatbuffers/issues/5299
            v = '?.?.?'

    if type(v) in (tuple, list):
        return '.'.join(str(x) for x in v)
    elif type(v) == str:
        return v
    else:
        raise RuntimeError('unexpected type {} for version in module "{}"'.format(type(v), name_or_module))

res = {}
res['executable'] = os.path.realpath(sys.executable)
res['platform'] = platform.platform()
res['machine'] = platform.machine()
res['py_ver'] = '.'.join([str(x) for x in list(sys.version_info[:3])])
res['py_ver_string'] = '%s' % sys.version.replace('\n', ' ')

if 'pypy_version_info' in sys.__dict__:
    res['py_ver_detail'] = '{}-{}'.format(platform.python_implementation(), '.'.join(str(x) for x in sys.pypy_version_info[:3]))
else:
    res['py_ver_detail'] = platform.python_implementation()

res['py_is_frozen'] = getattr(sys, 'frozen', False)

res['tx_ver'] = '%s-%s' % (_get_version('twisted'), reactor.__class__.__name__)
res['tx_loc'] = '%s' % qual(reactor.__class__)

res['txaio_ver'] = _get_version('txaio')

    # Autobahn
res['ab_ver'] = _get_version('autobahn')
res['ab_loc'] = '%s' % qual(WebSocketProtocol)

# UTF8 Validator
s = qual(Utf8Validator)
if 'wsaccel' in s:
    res['utf8_ver'] = 'wsaccel-%s' % _get_version('wsaccel')
elif s.startswith('autobahn'):
    res['utf8_ver'] = 'autobahn'
else:
    # could not detect UTF8 validator type/version
    res['utf8_ver'] = '?'
res['utf8_loc'] = '%s' % qual(Utf8Validator)

# XOR Masker
s = qual(XorMaskerNull)
if 'wsaccel' in s:
    res['xor_ver'] = 'wsaccel-%s' % _get_version('wsaccel')
elif s.startswith('autobahn'):
    res['xor_ver'] = 'autobahn'
else:
    # could not detect XOR masker type/version
    res['xor_ver'] = '?'
res['xor_loc'] = '%s' % qual(XorMaskerNull)

# JSON Serializer
supported_serializers = ['JSON']
from autobahn.wamp.serializer import JsonObjectSerializer
json_ver = JsonObjectSerializer.JSON_MODULE.__name__

# If it's just 'json' then it's the stdlib one...
if json_ver == 'json':
    res['json_ver'] = 'stdlib'
else:
    res['json_ver'] = (json_ver + '-%s') % _get_version(json_ver)

# MsgPack Serializer
try:
    from autobahn.wamp.serializer import MsgPackObjectSerializer
    msgpack = MsgPackObjectSerializer.MSGPACK_MODULE
    res['msgpack_ver'] = '{}-{}'.format(msgpack.__name__, _get_version(msgpack))
    supported_serializers.append('MessagePack')
except ImportError:
    res['msgpack_ver'] = None

# CBOR Serializer
try:
    from autobahn.wamp.serializer import CBORObjectSerializer
    cbor = CBORObjectSerializer.CBOR_MODULE
    res['cbor_ver'] = '{}-{}'.format(cbor.__name__, _get_version(cbor))
    supported_serializers.append('CBOR')
except ImportError:
    res['cbor_ver'] = None

# UBJSON Serializer
try:
    from autobahn.wamp.serializer import UBJSONObjectSerializer
    ubjson = UBJSONObjectSerializer.UBJSON_MODULE
    res['ubjson_ver'] = '{}-{}'.format(ubjson.__name__, _get_version(ubjson))
    supported_serializers.append('UBJSON')
except ImportError:
    res['ubjson_ver'] = None

# Flatbuffers Serializer
try:
    from autobahn.wamp.serializer import FlatBuffersObjectSerializer
    flatbuffers = FlatBuffersObjectSerializer.FLATBUFFERS_MODULE
    res['flatbuffers_ver'] = '{}-{}'.format(flatbuffers.__name__, _get_version(flatbuffers))
    supported_serializers.append('Flatbuffers')
except ImportError:
    res['flatbuffers_ver'] = None

res['supported_serializers'] = supported_serializers

try:
    import lmdb  # noqa
    lmdb_lib_ver = '.'.join([str(x) for x in lmdb.version()])
    res['lmdb_ver'] = '{}/lmdb-{}'.format(_get_version(lmdb), lmdb_lib_ver)
except ImportError:
    res['lmdb_ver'] = None

try:
    import zlmdb  # noqa
    res['zlmdb_ver'] = _get_version(zlmdb)
except ImportError:
    res['zlmdb_ver'] = None

try:
    import numpy  # noqa
    res['numpy_ver'] = _get_version(numpy)
except ImportError:
    res['numpy_ver'] = None

print('.' * 80)
print('Python version:')
print('')
print('    Host machine           : {}'.format(res['machine']))
print('    Operating system       : {}'.format(res['platform']))
print('    Python                 : {}/{}'.format(res['py_ver'], res['py_ver_detail']))
print('    Executable             : {}'.format(res['executable']))
print('.' * 80)
print('Autobahn version:')
print('')
print('    autobahn               : v{}'.format(autobahn.__version__))
print('    autobahn.xbr.HAS_XBR   : {}'.format(xbr.HAS_XBR))
print('.' * 80)
print('Autobahn build environment:')
print('')
print('    AUTOBAHN_BUILD_DATE    : {}'.format(os.environ.get('AUTOBAHN_BUILD_DATE', None)))
print('    AUTOBAHN_VERSION       : {}'.format(os.environ.get('AUTOBAHN_VERSION', None)))
print('    AUTOBAHN_VCS_REF       : {}'.format(os.environ.get('AUTOBAHN_VCS_REF', None)))
print('    AUTOBAHN_BUILD_ID      : {}'.format(os.environ.get('AUTOBAHN_BUILD_ID', None)))
print('.' * 80)
print('Autobahn dependencies and (optional) components:')
print('')
print('    txaio                  : {}'.format(res['txaio_ver']))
print('')
print('    UTF8 Validator         : {}'.format(res['utf8_ver']))
print('    XOR Masker             : {}'.format(res['xor_ver']))
print('    JSON Codec             : {}'.format(res['json_ver']))
print('    MsgPack Codec          : {}'.format(res['msgpack_ver']))
print('    CBOR Codec             : {}'.format(res['cbor_ver']))
print('    UBJSON Codec           : {}'.format(res['ubjson_ver']))
print('    FlatBuffers            : {}'.format(res['flatbuffers_ver']))
print('')
print('    Twisted                : {}'.format(res['tx_ver']))
print('    LMDB                   : {}'.format(res['lmdb_ver']))
print('    zLMDB                  : {}'.format(res['zlmdb_ver']))
print('    NumPy                  : {}'.format(res['numpy_ver']))
print('.' * 80)

if xbr.HAS_XBR:
    from autobahn.xbr._cli import print_version
    print_version()
