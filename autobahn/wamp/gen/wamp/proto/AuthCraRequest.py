# automatically generated by the FlatBuffers compiler, do not modify

# namespace: proto

import flatbuffers
from flatbuffers.compat import import_numpy
np = import_numpy()

class AuthCraRequest(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAs(cls, buf, offset=0):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = AuthCraRequest()
        x.Init(buf, n + offset)
        return x

    @classmethod
    def GetRootAsAuthCraRequest(cls, buf, offset=0):
        """This method is deprecated. Please switch to GetRootAs."""
        return cls.GetRootAs(buf, offset)
    # AuthCraRequest
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)

def Start(builder): builder.StartObject(0)
def AuthCraRequestStart(builder):
    """This method is deprecated. Please switch to Start."""
    return Start(builder)
def End(builder): return builder.EndObject()
def AuthCraRequestEnd(builder):
    """This method is deprecated. Please switch to End."""
    return End(builder)