# automatically generated by the FlatBuffers compiler, do not modify

# namespace: proto

import flatbuffers
from flatbuffers.compat import import_numpy
np = import_numpy()

class AuthCryptosignRequest(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAs(cls, buf, offset=0):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = AuthCryptosignRequest()
        x.Init(buf, n + offset)
        return x

    @classmethod
    def GetRootAsAuthCryptosignRequest(cls, buf, offset=0):
        """This method is deprecated. Please switch to GetRootAs."""
        return cls.GetRootAs(buf, offset)
    # AuthCryptosignRequest
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)

    # AuthCryptosignRequest
    def Pubkey(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(4))
        if o != 0:
            return self._tab.String(o + self._tab.Pos)
        return None

    # AuthCryptosignRequest
    def ChannelBinding(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(6))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint8Flags, o + self._tab.Pos)
        return 0

def Start(builder): builder.StartObject(2)
def AuthCryptosignRequestStart(builder):
    """This method is deprecated. Please switch to Start."""
    return Start(builder)
def AddPubkey(builder, pubkey): builder.PrependUOffsetTRelativeSlot(0, flatbuffers.number_types.UOffsetTFlags.py_type(pubkey), 0)
def AuthCryptosignRequestAddPubkey(builder, pubkey):
    """This method is deprecated. Please switch to AddPubkey."""
    return AddPubkey(builder, pubkey)
def AddChannelBinding(builder, channelBinding): builder.PrependUint8Slot(1, channelBinding, 0)
def AuthCryptosignRequestAddChannelBinding(builder, channelBinding):
    """This method is deprecated. Please switch to AddChannelBinding."""
    return AddChannelBinding(builder, channelBinding)
def End(builder): return builder.EndObject()
def AuthCryptosignRequestEnd(builder):
    """This method is deprecated. Please switch to End."""
    return End(builder)