XBR Programming
===============

Autobahn comes with built-in support for `XBR <https://xbr.network/>`_. This chapter contains
documentation of writing XBR buyers and sellers in Python using Autobahn.

.. contents:: :local:

----------

On-chain XBR smart contracts
----------------------------

The root anchor of the XBR network is a set of smart contracts on the Ethereum blockchain. The contracts
are written in Solidity and published as open-source `on GitHub <https://github.com/crossbario/xbr-protocol>`_.

To talk to the XBR smart contracts on the blockchain, you need two things:

1. the XBR smart contract addresses and
2. the XBR smart contract ABI files (JSON)

Both of which are built into the Autobahn library.

While you *can* use just the raw addresses and ABI blobs contained in Autobahn, and use whatever
way and form to talk directly to the blockchain fully on your own, Autobahn *also* provides a convenient
blockchain client with specific functions directly supporting XBR.

Here is a complete example blockchain client:

.. code-block:: python

    import argparse
    from binascii import a2b_hex, b2a_hex
    from autobahn import xbr
    from twisted.internet.task import react
    from twisted.internet.defer import inlineCallbacks


    @inlineCallbacks
    def main(reactor, gateway, adr):
        sbc = xbr.SimpleBlockchain(gateway)
        yield sbc.start()

        print('status for address 0x{}:'.format(b2a_hex(adr).decode()))

        # get ETH and XBR account balances for address
        balances = yield sbc.get_balances(adr)
        print('balances: {}'.format(balances))

        # get XBR network membership status for address
        member_status = yield sbc.get_member_status(adr)
        print('member status: {}'.format(member_status))


    if __name__ == '__main__':
        parser = argparse.ArgumentParser()

        parser.add_argument('--gateway',
                            dest='gateway',
                            type=str,
                            default=None,
                            help='Ethereum HTTP gateway URL or None for auto-select.')

        parser.add_argument('--adr',
                            dest='adr',
                            type=str,
                            default=None,
                            help='Ethereum address to lookup.')

        args = parser.parse_args()

        react(main, (args.gateway, a2b_hex(args.adr[2:],)))

Here is example output of above program with two different addresses, only one being a member,
and with different balances of ETH and XBR.

.. code-block:: console

    connected to network 5777 at provider "http://localhost:1545"
    status for address 0x90f8bf6a479f320ead074411a4b0e7944ea8c9c1:
    balances: {'ETH': 9999866871000000000000, 'XBR': 1000000000000000000000000000}
    member status: None

    connected to network 5777 at provider "http://localhost:1545"
    status for address 0xffcf8fdee72ac11b5c542428b35eef5769c409f0:
    balances: {'ETH': 9999999999999999625429, 'XBR': 0}
    member status: {'eula': 'QmU7Gizbre17x6V2VR1Q2GJEjz6m8S1bXmBtVxS2vmvb81', 'profile': None}


Using the ABI files
...................

To directly use the embedded ABI files:

.. code-block:: python

    import json
    import importlib.resources
    from pprint import pprint

    text = (importlib.resources.files('xbr.abi') / 'XBRToken.json').read_text()
    data = json.loads(text)
    abi = data['abi']
    pprint(abi)


Data stored on-chain
....................

See the `XBRNetwork contract <https://github.com/crossbario/xbr-protocol/blob/master/contracts/XBRNetwork.sol>`_:

.. code-block:: console

    /// Current XBR Network members ("member directory").
    mapping(address => Member) private members;

    /// Current XBR Domains ("domain directory")
    mapping(bytes16 => Domain) private domains;

    /// Current XBR Nodes ("node directory");
    mapping(bytes16 => Node) private nodes;

    /// Index: node public key => (market ID, node ID)
    mapping(bytes32 => bytes16) private nodesByKey;

    /// Current XBR Markets ("market directory")
    mapping(bytes16 => Market) private markets;

    /// Index: maker address => market ID
    mapping(address => bytes16) private marketsByMaker;


SimpleBuyer
...........

Autobahn includes a "simple buyer" for use in buyer delegate user services which is able
to automatically quote and buy data encryption keys via the market maker from sellers
in a market.

The simple buyer operates in the background and automatically buys keys on demand, as the
user calls "unwrap(ciphertext)" on received XBR encrypted application payload.

Here is a complete example buyer:

.. code-block:: python

    import binascii
    import os

    from autobahn.twisted.component import Component, run
    from autobahn.xbr import SimpleBuyer
    from autobahn.wamp.types import SubscribeOptions

    comp = Component(
        transports=os.environ.get('XBR_INSTANCE', 'wss://continental2.crossbario.com/ws'),
        realm=os.environ.get('XBR_REALM', 'realm1'),
        extra={
            'market_maker_adr': os.environ.get('XBR_MARKET_MAKER_ADR',
                '0xff035c911accf7c7154c51cb62460b50f43ea54f'),
            'buyer_privkey': os.environ.get('XBR_BUYER_PRIVKEY',
                '646f1ce2fdad0e6deeeb5c7e8e5543bdde65e86029e2fd9fc169899c440a7913'),
        }
    )


    @comp.on_join
    async def joined(session, details):
        print('Buyer session joined', details)

        market_maker_adr = binascii.a2b_hex(session.config.extra['market_maker_adr'][2:])
        print('Using market maker adr:', session.config.extra['market_maker_adr'])

        buyer_privkey = binascii.a2b_hex(session.config.extra['buyer_privkey'])

        buyer = SimpleBuyer(market_maker_adr, buyer_privkey, 100)
        balance = await buyer.start(session, details.authid)
        print("Remaining balance={}".format(balance))

        async def on_event(key_id, enc_ser, ciphertext, details=None):
            payload = await buyer.unwrap(key_id, enc_ser, ciphertext)
            print('Received event {}:'.format(details.publication), payload)

        await session.subscribe(on_event, "io.crossbar.example",
            options=SubscribeOptions(details=True))


    if __name__ == '__main__':
        run([comp])


SimpleSeller
............

Autobahn includes a "simple seller" for use in seller delegate user services which is able
to automatically offer and sell data encryption keys via the market maker to buyers
in a market.

Here is a complete example seller:

.. code-block:: python

    import binascii
    import os
    from time import sleep
    from uuid import UUID

    from autobahn.twisted.component import Component, run
    from autobahn.twisted.util import sleep
    from autobahn.wamp.types import PublishOptions
    from autobahn.xbr import SimpleSeller

    comp = Component(
        transports=os.environ.get('XBR_INSTANCE', 'wss://continental2.crossbario.com/ws'),
        realm=os.environ.get('XBR_REALM', 'realm1'),
        extra={
            'market_maker_adr': os.environ.get('XBR_MARKET_MAKER_ADR',
                '0xff035c911accf7c7154c51cb62460b50f43ea54f'),
            'seller_privkey': os.environ.get('XBR_SELLER_PRIVKEY',
                '646f1ce2fdad0e6deeeb5c7e8e5543bdde65e86029e2fd9fc169899c440a7913'),
        }
    )

    running = False


    @comp.on_join
    async def joined(session, details):
        print('Seller session joined', details)
        global running
        running = True

        market_maker_adr = binascii.a2b_hex(session.config.extra['market_maker_adr'][2:])
        print('Using market maker adr:', session.config.extra['market_maker_adr'])

        seller_privkey = binascii.a2b_hex(session.config.extra['seller_privkey'])

        api_id = UUID('627f1b5c-58c2-43b1-8422-a34f7d3f5a04').bytes
        topic = 'io.crossbar.example'
        counter = 1

        seller = SimpleSeller(market_maker_adr, seller_privkey)
        seller.add(api_id, topic, 35, 10, None)
        await seller.start(session)

        print('Seller has started')

        while running:
            payload = {'data': 'py-seller', 'counter': counter}
            key_id, enc_ser, ciphertext = await seller.wrap(api_id,
                                                            topic,
                                                            payload)
            pub = await session.publish(topic, key_id, enc_ser, ciphertext,
                                        options=PublishOptions(acknowledge=True))

            print('Published event {}: {}'.format(pub.id, payload))

            counter += 1
            await sleep(1)


    @comp.on_leave
    def left(session, details):
        print('Seller session left', details)
        global running
        running = False


    if __name__ == '__main__':
        run([comp])
