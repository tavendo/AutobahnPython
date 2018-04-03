from autobahn.asyncio.component import Component, run
from asyncio import sleep
from autobahn.wamp.types import RegisterOptions

# to see how this works on the Crossbar.io side, see the example
# router configuration in:
# https://github.com/crossbario/autobahn-python/blob/master/examples/router/.crossbar/config.json

component = Component(
    # you can configure multiple transports; here we use two different
    # transports which both exist in the demo router
    transports=[
        {
            u"type": u"websocket",
            u"url": u"ws://localhost:8080/auth_ws",
            u"endpoint": {
                u"type": u"tcp",
                u"host": u"localhost",
                u"port": 8080,
            },
            # you can set various websocket options here if you want
            u"options": {
                u"open_handshake_timeout": 100,
            }
        },
    ],
    # authentication can also be configured (this will only work on
    # the demo router on the first transport above)
    authentication={
        u"cryptosign": {
            u'authid': u'alice',
            # this key should be loaded from disk, database etc never burned into code like this...
            u'privkey': '6e3a302aa67d55ffc2059efeb5cf679470b37a26ae9ac18693b56ea3d0cd331c',
        }
    },
    # must provide a realm
    realm=u"crossbardemo",
)


@component.on_join
async def join(session, details):
    print("joined {}: {}".format(session, details))
    await sleep(1)
    print("Calling 'com.example'")
    res = await session.call(u"example.foo", 42, something="nothing")
    print("Result: {}".format(res))
    await session.leave()


@component.register(
    u"example.foo",
    options=RegisterOptions(details_arg='details'),
)
async def foo(*args, **kw):
    print("foo called: {}, {}".format(args, kw))
    for x in range(5, 0, -1):
        print("  returning in {}".format(x))
        await sleep(1)
    print("returning '42'")
    return 42


if __name__ == "__main__":
    run([component])
