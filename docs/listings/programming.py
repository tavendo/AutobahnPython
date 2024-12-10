from autobahn.twisted.component import Component, run
from autobahn.twisted.util import sleep
from autobahn.wamp.types import RegisterOptions
from twisted.internet.defer import inlineCallbacks

# to see how this works on the Crossbar.io side, see the example
# router configuration in:
# https://github.com/crossbario/autobahn-python/blob/master/examples/router/.crossbar/config.json

component = Component(
    # you can configure multiple transports; here we use two different
    # transports which both exist in the demo router
    transports=[
        {
            "type": "websocket",
            "url": "ws://localhost:8080/auth_ws",
            "endpoint": {
                "type": "tcp",
                "host": "localhost",
                "port": 8080,
            },
            # you can set various websocket options here if you want
            "options": {
                "open_handshake_timeout": 100,
            }
        },
    ],
    # authentication can also be configured (this will only work on
    # the demo router on the first transport above)
    authentication={
        "cryptosign": {
            'authid': 'alice',
            # this key should be loaded from disk, database etc never burned into code like this...
            'privkey': '6e3a302aa67d55ffc2059efeb5cf679470b37a26ae9ac18693b56ea3d0cd331c',
        }
    },
    # must provide a realm
    realm="crossbardemo",
)


@component.on_join
@inlineCallbacks
def join(session, details):
    print("joined {}: {}".format(session, details))
    yield sleep(1)
    print("Calling 'com.example'")
    res = yield session.call("example.foo", 42, something="nothing")
    print("Result: {}".format(res))
    yield session.leave()


@component.register(
    "example.foo",
    options=RegisterOptions(details_arg='details'),
)
@inlineCallbacks
def foo(*args, **kw):
    print("foo called: {}, {}".format(args, kw))
    for x in range(5, 0, -1):
        print("  returning in {}".format(x))
        yield sleep(1)
    print("returning '42'")
    return 42


if __name__ == "__main__":
    run([component])
