import os
import sys
if sys.version_info < (3, 10):
    import importlib_resources as resources
else:
    from importlib import resources
from binascii import a2b_hex
import txaio
from unittest import skipIf

if 'USE_TWISTED' in os.environ and os.environ['USE_TWISTED']:
    from twisted.trial import unittest

    txaio.use_twisted()
else:
    import unittest

    txaio.use_asyncio()

from autobahn.xbr import HAS_XBR
from autobahn.wamp.exception import InvalidPayload

if HAS_XBR:
    from autobahn.xbr._util import pack_ethadr, unpack_ethadr
    from autobahn.xbr import FbsType, FbsObject, FbsService, FbsRPCCall, FbsRepository, FbsSchema, FbsField, FbsEnum, \
        FbsEnumValue


@skipIf(not HAS_XBR, 'package autobahn[xbr] not installed')
class TestPackEthAdr(unittest.TestCase):
    """
    Test :func:`pack_ethadr` and :func:`unpack_ethadr` helpers.
    """

    def test_roundtrip(self):
        original_value_str = '0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047'
        original_value_bin = a2b_hex(original_value_str[2:])

        # count number of test cases run
        cnt = 0

        # test 2 cases for return_dict option
        for return_dict in [False, True]:

            # test 2 cases for input type
            for original_value in [original_value_str, original_value_bin]:
                packed_value = pack_ethadr(original_value, return_dict=return_dict)
                if return_dict:
                    self.assertIsInstance(packed_value, dict)
                    for i in range(5):
                        self.assertIn('w{}'.format(i), packed_value)
                        self.assertTrue(type(packed_value['w{}'.format(i)]) == int)
                else:
                    self.assertIsInstance(packed_value, list)
                    self.assertEqual(len(packed_value), 5)
                    for i in range(5):
                        self.assertTrue(type(packed_value[i]) == int)

                # test 2 cases for return_str option
                for return_str in [False, True]:
                    unpacked_value = unpack_ethadr(packed_value, return_str=return_str)
                    if return_str:
                        self.assertIsInstance(unpacked_value, str)
                        self.assertEqual(unpacked_value, original_value_str)
                    else:
                        self.assertIsInstance(unpacked_value, bytes)
                        self.assertEqual(unpacked_value, original_value_bin)

                    cnt += 1

        # assure we actually completed as many test cases as we expect
        self.assertEqual(cnt, 8)


@skipIf(not HAS_XBR, 'package autobahn[xbr] not installed')
class TestFbsBase(unittest.TestCase):
    """
    FlatBuffers tests base class, loads test schemas.
    """

    def setUp(self):
        self.repo = FbsRepository('autobahn')
        self.archives = []
        for fbs_file in ['wamp.bfbs', 'testsvc1.bfbs']:
            archive = str(resources.files('autobahn.xbr.test.catalog.schema') / fbs_file)
            self.repo.load(archive)
            self.archives.append(archive)


class TestFbsRepository(TestFbsBase):
    """
    Test :class:`FbsRepository` schema loading and verify loaded types.
    """

    def test_create_from_archive(self):
        self.assertIn('uint160_t', self.repo.objs)
        self.assertIsInstance(self.repo.objs['uint160_t'], FbsObject)
        self.assertIn('testsvc1.TestRequest', self.repo.objs)
        self.assertIsInstance(self.repo.objs['testsvc1.TestRequest'], FbsObject)
        self.assertIn('testsvc1.TestResponse', self.repo.objs)
        self.assertIsInstance(self.repo.objs['testsvc1.TestResponse'], FbsObject)
        self.assertIn('testsvc1.ITestService1', self.repo.services)
        self.assertIsInstance(self.repo.services['testsvc1.ITestService1'], FbsService)

    def test_loaded_schema(self):
        schema_fn = str(resources.files('autobahn.xbr.test.catalog.schema') / 'testsvc1.bfbs')

        # get reflection schema loaded
        schema: FbsSchema = self.repo.schemas[schema_fn]

        # get call from service defined in schema
        call: FbsRPCCall = schema.services['testsvc1.ITestService1'].calls['run_something1']

        # for each of the call request and call response type names ...
        call_type: FbsObject
        for call_type in [schema.objs[call.request.name], schema.objs[call.response.name]]:

            # ... iterate over all fields
            field: FbsField
            for field in call_type.fields_by_id:
                # we only need to process the "_type" fields auto-added for Union types
                if field.type.basetype == FbsType.UType:
                    assert field.name.endswith('_type')

                    # get the enum storing the Union
                    call_type_enum: FbsEnum = schema.enums_by_id[field.type.index]
                    assert call_type_enum.is_union

                    # get all enum values, which store Union types
                    union_type_value: FbsEnumValue
                    for union_type_value in call_type_enum.values:
                        if union_type_value != 'NONE':
                            # resolve union type value names in same namespace as containing union type [???]
                            if '.' in call_type_enum.name:
                                namespace = call_type_enum.name.split('.')[0]
                                union_type_qn = '{}.{}'.format(namespace, union_type_value)
                            else:
                                union_type_qn = union_type_value
                            # get type object for Union type by fully qualified name
                            union_type = schema.objs[union_type_qn]
                            print(union_type)

        # print(self.repo.objs['testsvc1.TestRequest'])
        # print(self.repo.enums['testsvc1.TestRequestAny'])
        # print(self.repo.objs['testsvc1.TestRequestArgument'])
        # print(self.repo.objs['testsvc1.TestRequestProgress'])
        # print()

        # print(self.repo.objs['testsvc1.TestResponse'])
        # print(self.repo.enums['testsvc1.TestResponseAny'])
        # print(self.repo.objs['testsvc1.TestResponseResult'])
        # print(self.repo.objs['testsvc1.TestResponseProgress'])
        # print(self.repo.objs['testsvc1.TestResponseError1'])
        # print(self.repo.objs['testsvc1.TestResponseError2'])
        # print()

        # svc1 = self.repo.services['testsvc1.ITestService1']
        # for key in svc1.calls.keys():
        #     ep: FbsRPCCall = svc1.calls[key]
        #     print(ep)

        # svc2 = self.repo.services['trading.ITradingClock']
        # for key in svc2.calls.keys():
        #     ep: FbsRPCCall = svc2.calls[key]
        #     print(ep)


class TestFbsValidateUint160(TestFbsBase):
    """
    Test struct uint160_t validation.
    """

    def test_validate_obj_uint160_valid(self):
        element_max = 2 ** 32 - 1
        valid_values = [
            [0, 0, 0, 0, 0],
            [element_max, element_max, element_max, element_max, element_max],
            pack_ethadr('0x0000000000000000000000000000000000000000'),
            pack_ethadr('0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047'),

            {'w0': 0, 'w1': 0, 'w2': 0, 'w3': 0, 'w4': 0},
            {'w0': element_max, 'w1': element_max, 'w2': element_max, 'w3': element_max, 'w4': element_max},
            pack_ethadr('0x0000000000000000000000000000000000000000', return_dict=True),
            pack_ethadr('0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047', return_dict=True),
        ]
        try:
            for value in valid_values:
                self.repo.validate_obj('uint160_t', value)
        except Exception as exc:
            self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

    def test_validate_obj_uint160_invalid(self):
        tests = [
            (None, 'invalid type'),
            ([], 'missing argument'),
            ({}, 'missing argument'),

            ([0, 0, None, 0, 0], 'invalid type'),
            ([0, 0, 0, 0, 'bogus'], 'invalid type'),
            ([0, 0, 0, 0], 'missing argument'),
            ([0, 0, 0, 0, 0, 0], 'unexpected argument'),

            ({'w0': 0, 'w1': 0, 'w2': None, 'w3': 0, 'w4': 0}, 'invalid type'),
            ({'w0': 0, 'w1': 0, 'w2': 0, 'w3': 0, 'w4': 'bogus'}, 'invalid type'),
            ({'w0': 0, 'w1': 0, 'w2': 0, 'w3': 0}, 'missing argument'),
            ({'w0': 0, 'w1': 0, 'w2': 0, 'w3': 0, 'w4': 0, 'w5': 0}, 'unexpected argument'),
        ]
        for value, expected_regex in tests:
            self.assertRaisesRegex(InvalidPayload, expected_regex,
                                   self.repo.validate_obj, 'uint160_t', value)


class TestFbsValidateEthAddress(TestFbsBase):

    def test_validate_obj_EthAddress_valid(self):

        for value in [
            {'value': {'w0': 0, 'w1': 0, 'w2': 0, 'w3': 0, 'w4': 0}},
            {'value': pack_ethadr('0x0000000000000000000000000000000000000000')},
            {'value': pack_ethadr('0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047')},
            {'value': pack_ethadr('0x0000000000000000000000000000000000000000', return_dict=True)},
            {'value': pack_ethadr('0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047', return_dict=True)},
        ]:
            try:
                self.repo.validate_obj('EthAddress', value)
            except Exception as exc:
                self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

    def test_validate_obj_EthAddress_invalid(self):
        tests = [
            # FIXME
            # (None, 'invalid type'),
            # ([], 'invalid type'),
            ({'invalid_key': pack_ethadr('0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047')}, 'unexpected argument'),
            ({'value': None}, 'invalid type'),
            ({'value': {}}, 'missing argument'),
            ({'value': []}, 'missing argument'),
        ]
        for value, expected_regex in tests:
            self.assertRaisesRegex(InvalidPayload, expected_regex,
                                   self.repo.validate_obj, 'EthAddress', value)


class TestFbsValidateKeyValue(TestFbsBase):

    def test_validate_KeyValue_valid(self):
        try:
            self.repo.validate('KeyValue', args=['foo', '23'], kwargs={})
        except Exception as exc:
            self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

    def test_validate_KeyValue_invalid(self):
        self.assertRaisesRegex(InvalidPayload, 'missing positional argument', self.repo.validate,
                               'KeyValue', [], {})

        self.assertRaisesRegex(InvalidPayload, 'missing positional argument', self.repo.validate,
                               'KeyValue', ['foo'], {})

        self.assertRaisesRegex(InvalidPayload, 'unexpected positional arguments', self.repo.validate,
                               'KeyValue', ['foo', '23', 'unexpected'], {})

        self.assertRaisesRegex(InvalidPayload, 'unexpected keyword arguments', self.repo.validate,
                               'KeyValue', ['foo', '23'], {'unexpected_kwarg': '23'})

        self.assertRaisesRegex(InvalidPayload, 'invalid type', self.repo.validate,
                               'KeyValue', ['foo', 23], {})

    def test_validate_KeyValues_valid(self):
        # empty list
        valid_value = {}
        try:
            self.repo.validate_obj('KeyValues', valid_value)
        except Exception as exc:
            self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

        # non-empty list
        valid_value = {
            'value': []
        }
        for i in range(10):
            # valid_value['value'].append(['key{}'.format(i), 'value{}'.format(i)])
            valid_value['value'].append({'key': 'key{}'.format(i), 'value': 'value{}'.format(i)})
        try:
            self.repo.validate_obj('KeyValues', valid_value)
        except Exception as exc:
            self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

    def test_validate_KeyValues_invalid(self):
        tests = [
            (None, 'invalid type'),
            ([], 'invalid type'),
            ({'invalid_key': 'something'}, 'unexpected argument'),
            ({'value': None}, 'invalid type'),
            ({'value': {}}, 'invalid type'),
        ]
        for value, expected_regex in tests:
            self.assertRaisesRegex(InvalidPayload, expected_regex,
                                   self.repo.validate_obj, 'KeyValues', value)


class TestFbsValidateVoid(TestFbsBase):

    def test_validate_Void_valid(self):
        try:
            self.repo.validate(None, args=[], kwargs={})
            self.repo.validate('Void', args=[], kwargs={})
        except Exception as exc:
            self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

    def test_validate_Void_invalid(self):
        valid_adr = pack_ethadr('0xecdb40C2B34f3bA162C413CC53BA3ca99ff8A047')

        self.assertRaisesRegex(InvalidPayload, 'unexpected positional argument', self.repo.validate,
                               'Void', [23], {})

        self.assertRaisesRegex(InvalidPayload, 'unexpected positional argument', self.repo.validate,
                               'Void', [{}], {})

        self.assertRaisesRegex(InvalidPayload, 'unexpected positional argument', self.repo.validate,
                               'Void', [None], {})

        self.assertRaisesRegex(InvalidPayload, 'unexpected positional argument', self.repo.validate,
                               'Void', [{'value': valid_adr}], {})

        self.assertRaisesRegex(InvalidPayload, 'unexpected keyword argument', self.repo.validate,
                               'Void', [], {'unexpected_kwarg': None})

        self.assertRaisesRegex(InvalidPayload, 'unexpected keyword argument', self.repo.validate,
                               'Void', [], {'unexpected_kwarg': 23})
