import os
import copy
import sys
if sys.version_info < (3, 10):
    import importlib_resources as resources
else:
    from importlib import resources

from random import randint, random
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
    from autobahn.xbr import FbsRepository


@skipIf(not HAS_XBR, 'package autobahn[xbr] not installed')
class TestFbsBase(unittest.TestCase):
    """
    FlatBuffers tests base class, loads test schemas.
    """

    def setUp(self):
        self.repo = FbsRepository('autobahn')
        self.archives = []
        for fbs_file in ['demo.bfbs', 'wamp-control.bfbs']:
            archive = str(resources.files('autobahn.xbr.test.catalog.schema') / fbs_file)
            self.repo.load(archive)
            self.archives.append(archive)


class TestFbsValidateTestTableA(TestFbsBase):

    def test_validate_TestTableA_valid(self):
        valid_args = [
            True,
            randint(-127, -1),
            randint(1, 255),
            randint(-2 ** 15, -1),
            randint(1, 2 ** 16 - 1),
            randint(-2 ** 31, -1),
            randint(1, 2 ** 32 - 1),
            randint(-2 ** 63, -1),
            randint(1, 2 ** 64 - 1),
            2.0 + random(),
            2.0 + random(),
        ]

        try:
            self.repo.validate('demo.TestTableA', args=valid_args, kwargs={})
        except Exception as exc:
            self.assertTrue(False, f'Inventory.validate() raised an exception: {exc}')

    def test_validate_TestTableA_invalid(self):
        valid_args = [
            True,
            randint(-127, -1),
            randint(1, 255),
            randint(-2 ** 15, -1),
            randint(1, 2 ** 16 - 1),
            randint(-2 ** 31, -1),
            randint(1, 2 ** 32 - 1),
            randint(-2 ** 63, -1),
            randint(1, 2 ** 64 - 1),
            2.0 + random(),
            2.0 + random(),
        ]

        # mandatory field with wrong type
        for i in range(len(valid_args)):
            # copy valid value, and set one column to a value of wrong type
            invalid_args = copy.copy(valid_args)
            if i == 0:
                # first column should be bool, so make it invalid with an int value
                invalid_args[0] = 666
            else:
                # all other columns are something different from bool, so make it invalid with a bool value
                invalid_args[i] = True
            self.assertRaisesRegex(InvalidPayload, 'invalid type', self.repo.validate,
                                   'demo.TestTableA', invalid_args, {})

        # mandatory field with wrong type `None`
        if True:
            for i in range(len(valid_args)):
                # copy valid value, and set one column to a value of wrong type
                invalid_args = copy.copy(valid_args)
                invalid_args[i] = None
                self.assertRaisesRegex(InvalidPayload, 'invalid type', self.repo.validate,
                                       'demo.TestTableA', invalid_args, {})

        # mandatory field missing
        if True:
            for i in range(len(valid_args)):
                invalid_args = valid_args[:i]
                self.assertRaisesRegex(InvalidPayload, 'missing positional argument', self.repo.validate,
                                       'demo.TestTableA', invalid_args, {})
