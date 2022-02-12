# automatically generated by the FlatBuffers compiler, do not modify

# namespace: proto

import flatbuffers
from flatbuffers.compat import import_numpy
np = import_numpy()

class Call(object):
    __slots__ = ['_tab']

    @classmethod
    def GetRootAs(cls, buf, offset=0):
        n = flatbuffers.encode.Get(flatbuffers.packer.uoffset, buf, offset)
        x = Call()
        x.Init(buf, n + offset)
        return x

    @classmethod
    def GetRootAsCall(cls, buf, offset=0):
        """This method is deprecated. Please switch to GetRootAs."""
        return cls.GetRootAs(buf, offset)
    # Call
    def Init(self, buf, pos):
        self._tab = flatbuffers.table.Table(buf, pos)

    # Call
    def Request(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(4))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint64Flags, o + self._tab.Pos)
        return 0

    # Call
    def Procedure(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(6))
        if o != 0:
            return self._tab.String(o + self._tab.Pos)
        return None

    # Call
    def Payload(self, j):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(8))
        if o != 0:
            a = self._tab.Vector(o)
            return self._tab.Get(flatbuffers.number_types.Uint8Flags, a + flatbuffers.number_types.UOffsetTFlags.py_type(j * 1))
        return 0

    # Call
    def PayloadAsNumpy(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(8))
        if o != 0:
            return self._tab.GetVectorAsNumpy(flatbuffers.number_types.Uint8Flags, o)
        return 0

    # Call
    def PayloadLength(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(8))
        if o != 0:
            return self._tab.VectorLen(o)
        return 0

    # Call
    def PayloadIsNone(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(8))
        return o == 0

    # Call
    def EncAlgo(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(10))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint8Flags, o + self._tab.Pos)
        return 0

    # Call
    def EncSerializer(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(12))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint8Flags, o + self._tab.Pos)
        return 0

    # Call
    def EncKey(self, j):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(14))
        if o != 0:
            a = self._tab.Vector(o)
            return self._tab.Get(flatbuffers.number_types.Uint8Flags, a + flatbuffers.number_types.UOffsetTFlags.py_type(j * 1))
        return 0

    # Call
    def EncKeyAsNumpy(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(14))
        if o != 0:
            return self._tab.GetVectorAsNumpy(flatbuffers.number_types.Uint8Flags, o)
        return 0

    # Call
    def EncKeyLength(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(14))
        if o != 0:
            return self._tab.VectorLen(o)
        return 0

    # Call
    def EncKeyIsNone(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(14))
        return o == 0

    # Call
    def Timeout(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(16))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint32Flags, o + self._tab.Pos)
        return 0

    # Call
    def ReceiveProgress(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(18))
        if o != 0:
            return bool(self._tab.Get(flatbuffers.number_types.BoolFlags, o + self._tab.Pos))
        return False

    # Call
    def Caller(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(20))
        if o != 0:
            return self._tab.Get(flatbuffers.number_types.Uint64Flags, o + self._tab.Pos)
        return 0

    # Call
    def CallerAuthid(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(22))
        if o != 0:
            return self._tab.String(o + self._tab.Pos)
        return None

    # Call
    def CallerAuthrole(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(24))
        if o != 0:
            return self._tab.String(o + self._tab.Pos)
        return None

    # Call
    def ForwardFor(self, j):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(26))
        if o != 0:
            x = self._tab.Vector(o)
            x += flatbuffers.number_types.UOffsetTFlags.py_type(j) * 8
            from wamp.proto.Principal import Principal
            obj = Principal()
            obj.Init(self._tab.Bytes, x)
            return obj
        return None

    # Call
    def ForwardForLength(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(26))
        if o != 0:
            return self._tab.VectorLen(o)
        return 0

    # Call
    def ForwardForIsNone(self):
        o = flatbuffers.number_types.UOffsetTFlags.py_type(self._tab.Offset(26))
        return o == 0

def Start(builder): builder.StartObject(12)
def CallStart(builder):
    """This method is deprecated. Please switch to Start."""
    return Start(builder)
def AddRequest(builder, request): builder.PrependUint64Slot(0, request, 0)
def CallAddRequest(builder, request):
    """This method is deprecated. Please switch to AddRequest."""
    return AddRequest(builder, request)
def AddProcedure(builder, procedure): builder.PrependUOffsetTRelativeSlot(1, flatbuffers.number_types.UOffsetTFlags.py_type(procedure), 0)
def CallAddProcedure(builder, procedure):
    """This method is deprecated. Please switch to AddProcedure."""
    return AddProcedure(builder, procedure)
def AddPayload(builder, payload): builder.PrependUOffsetTRelativeSlot(2, flatbuffers.number_types.UOffsetTFlags.py_type(payload), 0)
def CallAddPayload(builder, payload):
    """This method is deprecated. Please switch to AddPayload."""
    return AddPayload(builder, payload)
def StartPayloadVector(builder, numElems): return builder.StartVector(1, numElems, 1)
def CallStartPayloadVector(builder, numElems):
    """This method is deprecated. Please switch to Start."""
    return StartPayloadVector(builder, numElems)
def AddEncAlgo(builder, encAlgo): builder.PrependUint8Slot(3, encAlgo, 0)
def CallAddEncAlgo(builder, encAlgo):
    """This method is deprecated. Please switch to AddEncAlgo."""
    return AddEncAlgo(builder, encAlgo)
def AddEncSerializer(builder, encSerializer): builder.PrependUint8Slot(4, encSerializer, 0)
def CallAddEncSerializer(builder, encSerializer):
    """This method is deprecated. Please switch to AddEncSerializer."""
    return AddEncSerializer(builder, encSerializer)
def AddEncKey(builder, encKey): builder.PrependUOffsetTRelativeSlot(5, flatbuffers.number_types.UOffsetTFlags.py_type(encKey), 0)
def CallAddEncKey(builder, encKey):
    """This method is deprecated. Please switch to AddEncKey."""
    return AddEncKey(builder, encKey)
def StartEncKeyVector(builder, numElems): return builder.StartVector(1, numElems, 1)
def CallStartEncKeyVector(builder, numElems):
    """This method is deprecated. Please switch to Start."""
    return StartEncKeyVector(builder, numElems)
def AddTimeout(builder, timeout): builder.PrependUint32Slot(6, timeout, 0)
def CallAddTimeout(builder, timeout):
    """This method is deprecated. Please switch to AddTimeout."""
    return AddTimeout(builder, timeout)
def AddReceiveProgress(builder, receiveProgress): builder.PrependBoolSlot(7, receiveProgress, 0)
def CallAddReceiveProgress(builder, receiveProgress):
    """This method is deprecated. Please switch to AddReceiveProgress."""
    return AddReceiveProgress(builder, receiveProgress)
def AddCaller(builder, caller): builder.PrependUint64Slot(8, caller, 0)
def CallAddCaller(builder, caller):
    """This method is deprecated. Please switch to AddCaller."""
    return AddCaller(builder, caller)
def AddCallerAuthid(builder, callerAuthid): builder.PrependUOffsetTRelativeSlot(9, flatbuffers.number_types.UOffsetTFlags.py_type(callerAuthid), 0)
def CallAddCallerAuthid(builder, callerAuthid):
    """This method is deprecated. Please switch to AddCallerAuthid."""
    return AddCallerAuthid(builder, callerAuthid)
def AddCallerAuthrole(builder, callerAuthrole): builder.PrependUOffsetTRelativeSlot(10, flatbuffers.number_types.UOffsetTFlags.py_type(callerAuthrole), 0)
def CallAddCallerAuthrole(builder, callerAuthrole):
    """This method is deprecated. Please switch to AddCallerAuthrole."""
    return AddCallerAuthrole(builder, callerAuthrole)
def AddForwardFor(builder, forwardFor): builder.PrependUOffsetTRelativeSlot(11, flatbuffers.number_types.UOffsetTFlags.py_type(forwardFor), 0)
def CallAddForwardFor(builder, forwardFor):
    """This method is deprecated. Please switch to AddForwardFor."""
    return AddForwardFor(builder, forwardFor)
def StartForwardForVector(builder, numElems): return builder.StartVector(8, numElems, 8)
def CallStartForwardForVector(builder, numElems):
    """This method is deprecated. Please switch to Start."""
    return StartForwardForVector(builder, numElems)
def End(builder): return builder.EndObject()
def CallEnd(builder):
    """This method is deprecated. Please switch to End."""
    return End(builder)