###############################################################################
#
# The MIT License (MIT)
#
# Copyright (c) Crossbar.io Technologies GmbH
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

from __future__ import absolute_import

from autobahn.websocket.interfaces import IWebSocketClientAgent


__all__ = (
    'create_memory_agent',
)


class _TwistedWebMemoryAgent(IWebSocketClientAgent):
    """
    A testing agent.
    """

    def __init__(self, reactor):
        self._reactor = reactor

    def open(self, transport_config, options):
        raise NotImplementedError


def create_memory_agent(reactor, resource):
    """
    return a new instance implementing `IWebSocketClientAgent`.

    connection attempts will be satisfied by traversing the Upgrade
    request path starting at `resource` to find a `WebSocketResource`
    and then exchange data between client and server using purely
    in-memory buffers.
    """
    # XXX FIXME
    return _TwistedWebMemoryAgent(reactor)
