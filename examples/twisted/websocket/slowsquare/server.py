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

from autobahn.twisted.websocket import WebSocketServerProtocol, \
    WebSocketServerFactory

import json
from twisted.internet.defer import Deferred, \
    inlineCallbacks


def sleep(delay):
    d = Deferred()
    reactor.callLater(delay, d.callback, None)
    return d


class SlowSquareServerProtocol(WebSocketServerProtocol):

    @inlineCallbacks
    def slowsquare(self, x):
        if x > 5:
            raise Exception("number too large")
        else:
            yield sleep(1)
            return x * x

    @inlineCallbacks
    def onMessage(self, payload, isBinary):
        if not isBinary:
            x = json.loads(payload.decode('utf8'))
            try:
                res = yield self.slowsquare(x)
            except Exception as e:
                self.sendClose(1000, "Exception raised: {0}".format(e))
            else:
                self.sendMessage(json.dumps(res).encode('utf8'))


if __name__ == '__main__':

    import sys

    from twisted.python import log
    from twisted.internet import reactor

    log.startLogging(sys.stdout)

    factory = WebSocketServerFactory("ws://127.0.0.1:9000")
    factory.protocol = SlowSquareServerProtocol

    reactor.listenTCP(9000, factory)
    reactor.run()
