# automatically generated by the FlatBuffers compiler, do not modify

# namespace: wamp

import flatbuffers
from flatbuffers.compat import import_numpy
np = import_numpy()

class Map(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAs(cls, buf, offset=0):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = Map()
        x.Init(buf, n + offset)
        return x

    @classmethod
    def GetRootAsMap(cls, buf, offset=0):
        """This method is deprecated. Please switch to GetRootAs."""
        return cls.GetRootAs(buf, offset)
    # Map
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)

    # Map
    def Key(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(4))
        if o != 0:
            return self._tab.String(o + self._tab.Pos)
        return None

    # Map
    def Value(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(6))
        if o != 0:
            return self._tab.String(o + self._tab.Pos)
        return None

def Start(builder): builder.StartObject(2)
def MapStart(builder):
    """This method is deprecated. Please switch to Start."""
    return Start(builder)
def AddKey(builder, key): builder.PrependUOffsetTRelativeSlot(0, flatbuffers.number_types.UOffsetTFlags.py_type(key), 0)
def MapAddKey(builder, key):
    """This method is deprecated. Please switch to AddKey."""
    return AddKey(builder, key)
def AddValue(builder, value): builder.PrependUOffsetTRelativeSlot(1, flatbuffers.number_types.UOffsetTFlags.py_type(value), 0)
def MapAddValue(builder, value):
    """This method is deprecated. Please switch to AddValue."""
    return AddValue(builder, value)
def End(builder): return builder.EndObject()
def MapEnd(builder):
    """This method is deprecated. Please switch to End."""
    return End(builder)