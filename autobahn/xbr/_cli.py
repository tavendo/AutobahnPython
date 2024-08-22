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

import os
import sys
import pkg_resources

from jinja2 import Environment, FileSystemLoader

from autobahn import xbr
from autobahn import __version__

if not xbr.HAS_XBR:
    print("\nYou must install the [xbr] extra to use xbrnetwork")
    print("For example, \"pip install autobahn[xbr]\".")
    sys.exit(1)

from autobahn.xbr._abi import XBR_DEBUG_TOKEN_ADDR, XBR_DEBUG_NETWORK_ADDR, XBR_DEBUG_DOMAIN_ADDR, \
    XBR_DEBUG_CATALOG_ADDR, XBR_DEBUG_MARKET_ADDR, XBR_DEBUG_CHANNEL_ADDR

from autobahn.xbr._abi import XBR_DEBUG_TOKEN_ADDR_SRC, XBR_DEBUG_NETWORK_ADDR_SRC, XBR_DEBUG_DOMAIN_ADDR_SRC, \
    XBR_DEBUG_CATALOG_ADDR_SRC, XBR_DEBUG_MARKET_ADDR_SRC, XBR_DEBUG_CHANNEL_ADDR_SRC

from autobahn.xbr import FbsRepository

import uuid
import binascii
import argparse
import random
from pprint import pformat

import eth_keys
import web3
import hashlib
import multihash
import cbor2

import numpy as np

import txaio

txaio.use_twisted()

from twisted.internet import reactor
from twisted.internet.defer import inlineCallbacks
from twisted.internet.threads import deferToThread
from twisted.internet.error import ReactorNotRunning

from autobahn.twisted.wamp import ApplicationSession, ApplicationRunner
from autobahn.wamp.serializer import CBORSerializer
from autobahn.wamp import cryptosign
from autobahn.wamp.exception import ApplicationError

from autobahn.xbr import pack_uint256, unpack_uint256, sign_eip712_channel_open, make_w3
from autobahn.xbr import sign_eip712_member_register, sign_eip712_market_create, sign_eip712_market_join
from autobahn.xbr import ActorType, ChannelType

from autobahn.xbr._config import load_or_create_profile
from autobahn.util import hltype, hlid, hlval

_COMMANDS = ['version', 'get-member', 'register-member', 'register-member-verify',
             'get-market', 'create-market', 'create-market-verify',
             'get-actor', 'join-market', 'join-market-verify',
             'get-channel', 'open-channel', 'close-channel',
             'describe-schema', 'codegen-schema']


class Client(ApplicationSession):

    # when running over TLS, require TLS channel binding
    CHANNEL_BINDING = 'tls-unique'

    def __init__(self, config=None):
        ApplicationSession.__init__(self, config)

        # FIXME
        self._default_gas = 100000
        self._chain_id = 4

        profile = config.extra.get('profile', None)

        if profile and profile.cskey:
            assert type(profile.cskey) == bytes and len(profile.cskey) == 32
            self._cskey_raw = profile.cskey
            self._key = cryptosign.CryptosignKey.from_bytes(self._cskey_raw)
            self.log.info('WAMP-Cryptosign keys with public key {public_key} loaded', public_key=self._key.public_key)
        else:
            self._cskey_raw = os.urandom(32)
            self._key = cryptosign.CryptosignKey.from_bytes(self._cskey_raw)
            self.log.info('WAMP-Cryptosign keys initialized randomly')

        if profile and profile.ethkey:
            self.set_ethkey_from_profile(profile)
            self.log.info('XBR ETH keys loaded from profile')
        else:
            self._ethkey_raw = None
            self._ethkey = None
            self._ethadr = None
            self._ethadr_raw = None
            self.log.info('XBR ETH keys left unset')

        self._running = True

    def set_ethkey_from_profile(self, profile):
        """

        :param profile:
        :return:
        """
        assert type(
            profile.ethkey) == bytes, 'set_ethkey_from_profile::profile invalid type "{}" - must be bytes'.format(
            type(profile.ethkey))
        assert len(profile.ethkey) == 32, 'set_ethkey_from_profile::profile invalid length {} - must be 32'.format(
            len(profile.ethkey))
        self._ethkey_raw = profile.ethkey
        self._ethkey = eth_keys.keys.PrivateKey(self._ethkey_raw)
        self._ethadr = web3.Web3.toChecksumAddress(self._ethkey.public_key.to_canonical_address())
        self._ethadr_raw = binascii.a2b_hex(self._ethadr[2:])
        self.log.info('ETH keys with address {ethadr} loaded', ethadr=self._ethadr)

    def onConnect(self):
        if self.config.realm == 'xbrnetwork':
            authextra = {
                'pubkey': self._key.public_key(),
                'trustroot': None,
                'challenge': None,
                'channel_binding': self.CHANNEL_BINDING,
            }
            self.log.info('Client connected, now joining realm "{realm}" with WAMP-cryptosign authentication ..',
                          realm=hlid(self.config.realm))
            self.join(self.config.realm, authmethods=['cryptosign'], authextra=authextra)
        else:
            self.log.info('Client connected, now joining realm "{realm}" (no authentication) ..',
                          realm=hlid(self.config.realm))
            self.join(self.config.realm)

    def onChallenge(self, challenge):
        if challenge.method == 'cryptosign':
            signed_challenge = self._key.sign_challenge(challenge,
                                                        channel_id=self.transport.transport_details.channel_id.get(self.CHANNEL_BINDING, None),
                                                        channel_id_type=self.CHANNEL_BINDING)
            return signed_challenge
        else:
            raise RuntimeError('unable to process authentication method {}'.format(challenge.method))

    async def onJoin(self, details):
        self.log.info(
            'Ok, client joined on realm "{realm}" [session={session}, authid="{authid}", authrole="{authrole}"]',
            realm=hlid(details.realm),
            session=hlid(details.session),
            authid=hlid(details.authid),
            authrole=hlid(details.authrole),
            details=details)
        if 'ready' in self.config.extra:
            txaio.resolve(self.config.extra['ready'], (self, details))

        if 'command' in self.config.extra:
            try:
                if details.realm == 'xbrnetwork':
                    await self._do_xbrnetwork_realm(details)
                else:
                    await self._do_market_realm(details)
            except Exception as e:
                self.log.failure()
                self.config.extra['error'] = e
            finally:
                self.leave()

    def onLeave(self, details):
        self.log.info('Client left realm (reason="{reason}")', reason=hlval(details.reason))
        self._running = False

        if details.reason == 'wamp.close.normal':
            if self.config and self.config.runner:
                # user initiated leave => end the program
                self.config.runner.stop()
                self.disconnect()

    def onDisconnect(self):
        self.log.info('Client disconnected')
        try:
            reactor.stop()
        except ReactorNotRunning:
            pass

    async def _do_xbrnetwork_realm(self, details):
        command = self.config.extra['command']
        if details.authrole == 'anonymous':
            self.log.info('not yet a member in the XBR network')

            assert command in ['get-member', 'register-member', 'register-member-verify']
            if command == 'get-member':
                await self._do_get_member(self._ethadr_raw)
            elif command == 'register-member':
                username = self.config.extra['username']
                email = self.config.extra['email']
                await self._do_onboard_member(username, email)
            elif command == 'register-member-verify':
                vaction_oid = self.config.extra['vaction']
                vaction_code = self.config.extra['vcode']
                await self._do_onboard_member_verify(vaction_oid, vaction_code)
            else:
                assert False, 'should not arrive here'
        else:
            # WAMP authid on xbrnetwork follows this format: "member-"
            member_oid = uuid.UUID(details.authid[7:])
            # member_data = await self.call('xbr.network.get_member', member_oid.bytes)
            # self.log.info('Address is already a member in the XBR network:\n\n{member_data}', member_data=pformat(member_data))

            assert command in ['get-member', 'get-market', 'create-market', 'create-market-verify',
                               'get-actor', 'join-market', 'join-market-verify']
            if command == 'get-member':
                await self._do_get_member(self._ethadr_raw)
            elif command == 'get-market':
                market_oid = self.config.extra['market']
                await self._do_get_market(member_oid, market_oid)
            elif command == 'get-actor':
                if 'market' in self.config.extra and self.config.extra['market']:
                    market_oid = self.config.extra['market']
                else:
                    market_oid = None
                if 'actor' in self.config.extra and self.config.extra['actor']:
                    actor = self.config.extra['actor']
                else:
                    actor = self._ethadr_raw
                await self._do_get_actor(market_oid, actor)
            elif command == 'create-market':
                market_oid = self.config.extra['market']
                marketmaker = self.config.extra['marketmaker']
                market_title = self.config.extra['market_title']
                market_label = self.config.extra['market_label']
                market_homepage = self.config.extra['market_homepage']
                provider_security = self.config.extra['market_provider_security']
                consumer_security = self.config.extra['market_consumer_security']
                market_fee = self.config.extra['market_fee']
                await self._do_create_market(member_oid, market_oid, marketmaker, title=market_title,
                                             label=market_label, homepage=market_homepage,
                                             provider_security=provider_security, consumer_security=consumer_security,
                                             market_fee=market_fee)
            elif command == 'create-market-verify':
                vaction_oid = self.config.extra['vaction']
                vaction_code = self.config.extra['vcode']
                await self._do_create_market_verify(member_oid, vaction_oid, vaction_code)
            elif command == 'join-market':
                market_oid = self.config.extra['market']
                actor_type = self.config.extra['actor_type']
                await self._do_join_market(member_oid, market_oid, actor_type)
            elif command == 'join-market-verify':
                vaction_oid = self.config.extra['vaction']
                vaction_code = self.config.extra['vcode']
                await self._do_join_market_verify(member_oid, vaction_oid, vaction_code)
            else:
                assert False, 'should not arrive here'

    async def _do_market_realm(self, details):
        profile = self.config.extra['profile']

        blockchain_gateway = {
            "type": "infura",
            "network": profile.infura_network,
            "key": profile.infura_key,
            "secret": profile.infura_secret
        }

        self._w3 = make_w3(blockchain_gateway)
        xbr.setProvider(self._w3)

        command = self.config.extra['command']
        assert command in ['open-channel', 'get-channel']
        if command == 'get-channel':
            market_oid = self.config.extra['market']
            delegate = self.config.extra['delegate']
            channel_type = self.config.extra['channel_type']
            if channel_type == ChannelType.PAYMENT:
                await self._do_get_active_payment_channel(market_oid, delegate)
            elif channel_type == ChannelType.PAYING:
                await self._do_get_active_paying_channel(market_oid, delegate)
            else:
                assert False, 'should not arrive here'
        elif command == 'open-channel':
            # market in which to open the new buyer/seller (payment/paying) channel
            market_oid = self.config.extra['market']

            # read UUID of the new channel to be created from command line OR auto-generate a new one
            channel_oid = self.config.extra['channel'] or uuid.uuid4()

            # buyer/seller (payment/paying) channel
            channel_type = self.config.extra['channel_type']

            # the delgate allowed to use the channel
            delegate = self.config.extra['delegate']

            # amount of market coins for initial channel balance
            amount = self.config.extra['amount']

            # now open the channel ..
            await self._do_open_channel(market_oid, channel_oid, channel_type, delegate, amount)
        else:
            assert False, 'should not arrive here'

    async def _do_get_member(self, member_adr):
        is_member = await self.call('xbr.network.is_member', member_adr)
        if is_member:
            member_data = await self.call('xbr.network.get_member_by_wallet', member_adr)

            member_data['address'] = web3.Web3.toChecksumAddress(member_data['address'])
            member_data['oid'] = uuid.UUID(bytes=member_data['oid'])
            member_data['balance']['eth'] = web3.Web3.fromWei(unpack_uint256(member_data['balance']['eth']), 'ether')
            member_data['balance']['xbr'] = web3.Web3.fromWei(unpack_uint256(member_data['balance']['xbr']), 'ether')
            member_data['created'] = np.datetime64(member_data['created'], 'ns')

            member_level = member_data['level']
            MEMBER_LEVEL_TO_STR = {
                # Member is active.
                1: 'ACTIVE',
                # Member is active and verified.
                2: 'VERIFIED',
                # Member is retired.
                3: 'RETIRED',
                # Member is subject to a temporary penalty.
                4: 'PENALTY',
                # Member is currently blocked and cannot current actively participate in the market.
                5: 'BLOCKED',
            }
            member_data['level'] = MEMBER_LEVEL_TO_STR.get(member_level, None)

            self.log.info('Member {member_oid} found for address 0x{member_adr} - current member level {member_level}',
                          member_level=hlval(member_data['level']),
                          member_oid=hlid(member_data['oid']),
                          member_adr=hlval(member_data['address']))
            return member_data
        else:
            self.log.warning('Address 0x{member_adr} is not a member in the XBR network',
                             member_adr=hlval(binascii.b2a_hex(member_adr).decode()))

    async def _do_get_actor(self, market_oid, actor_adr):
        is_member = await self.call('xbr.network.is_member', actor_adr)
        if is_member:
            actor = await self.call('xbr.network.get_member_by_wallet', actor_adr)
            actor_oid = uuid.UUID(bytes=actor['oid'])
            actor_adr = web3.Web3.toChecksumAddress(actor['address'])
            actor_level = actor['level']
            actor_balance_eth = web3.Web3.fromWei(unpack_uint256(actor['balance']['eth']), 'ether')
            actor_balance_xbr = web3.Web3.fromWei(unpack_uint256(actor['balance']['xbr']), 'ether')
            self.log.info(
                'Found member with address {member_adr} (member level {member_level}, balances: {member_balance_eth} ETH, {member_balance_xbr} XBR)',
                member_adr=hlid(actor_adr),
                member_level=hlval(actor_level),
                member_balance_eth=hlval(actor_balance_eth),
                member_balance_xbr=hlval(actor_balance_xbr))

            if market_oid:
                market_oids = [market_oid.bytes]
            else:
                market_oids = await self.call('xbr.network.get_markets_by_actor', actor_oid.bytes)

            if market_oids:
                for market_oid in market_oids:
                    # market = await self.call('xbr.network.get_market', market_oid)
                    result = await self.call('xbr.network.get_actor_in_market', market_oid, actor['address'])
                    for actor in result:
                        actor['actor'] = web3.Web3.toChecksumAddress(actor['actor'])
                        actor['timestamp'] = np.datetime64(actor['timestamp'], 'ns')
                        actor['joined'] = unpack_uint256(actor['joined']) if actor['joined'] else None
                        actor['market'] = uuid.UUID(bytes=actor['market'])
                        actor['security'] = web3.Web3.fromWei(unpack_uint256(actor['security']), 'ether') if actor[
                            'security'] else None
                        actor['signature'] = '0x' + binascii.b2a_hex(actor['signature']).decode() if actor[
                            'signature'] else None
                        actor['tid'] = '0x' + binascii.b2a_hex(actor['tid']).decode() if actor['tid'] else None

                        actor_type = actor['actor_type']
                        ACTOR_TYPE_TO_STR = {
                            # Actor is a XBR Provider.
                            1: 'PROVIDER',
                            # Actor is a XBR Consumer.
                            2: 'CONSUMER',
                            # Actor is both a XBR Provider and XBR Consumer.
                            3: 'PROVIDER_CONSUMER',
                        }
                        actor['actor_type'] = ACTOR_TYPE_TO_STR.get(actor_type, None)

                        self.log.info('Actor is joined to market {market_oid}:\n\n{actor}\n',
                                      market_oid=hlid(uuid.UUID(bytes=market_oid)), actor=pformat(actor))
            else:
                self.log.info('Member is not yet actor in any market!')
        else:
            self.log.warning('Address 0x{member_adr} is not a member in the XBR network',
                             member_adr=binascii.b2a_hex(actor_adr).decode())

    @inlineCallbacks
    def _do_onboard_member(self, member_username, member_email, member_password=None):
        client_pubkey = binascii.a2b_hex(self._key.public_key())

        # fake wallet type "metamask"
        wallet_type = 'metamask'

        # delegate ethereum private key object
        wallet_key = self._ethkey
        wallet_raw = self._ethkey_raw

        # delegate ethereum account canonical address
        wallet_adr = wallet_key.public_key.to_canonical_address()

        config = yield self.call('xbr.network.get_config')
        status = yield self.call('xbr.network.get_status')

        verifyingChain = config['verifying_chain_id']
        verifyingContract = binascii.a2b_hex(config['verifying_contract_adr'][2:])

        registered = status['block']['number']
        eula = config['eula']['hash']

        # create an aux-data object with info only stored off-chain (in our xbrbackend DB) ..
        profile_obj = {
            'member_username': member_username,
            'member_email': member_email,
            'client_pubkey': client_pubkey,
            'wallet_type': wallet_type,
        }

        # .. hash the serialized aux-data object ..
        profile_data = cbor2.dumps(profile_obj)
        h = hashlib.sha256()
        h.update(profile_data)

        # .. compute the sha256 multihash b58-encoded string from that ..
        profile = multihash.to_b58_string(multihash.encode(h.digest(), 'sha2-256'))

        signature = sign_eip712_member_register(wallet_raw, verifyingChain, verifyingContract,
                                                wallet_adr, registered, eula, profile)

        # https://xbr.network/docs/network/api.html#xbrnetwork.XbrNetworkApi.onboard_member
        try:
            result = yield self.call('xbr.network.onboard_member',
                                     member_username, member_email, client_pubkey, wallet_type, wallet_adr,
                                     verifyingChain, registered, verifyingContract, eula, profile, profile_data,
                                     signature)
        except ApplicationError as e:
            self.log.error('ApplicationError: {error}', error=e)
            self.leave('wamp.error', str(e))
            return
        except Exception as e:
            raise e

        assert type(result) == dict
        assert 'timestamp' in result and type(result['timestamp']) == int and result['timestamp'] > 0
        assert 'action' in result and result['action'] == 'onboard_member'
        assert 'vaction_oid' in result and type(result['vaction_oid']) == bytes and len(result['vaction_oid']) == 16

        vaction_oid = uuid.UUID(bytes=result['vaction_oid'])
        self.log.info('On-boarding member - verification "{vaction_oid}" created', vaction_oid=vaction_oid)

        return result

    @inlineCallbacks
    def _do_onboard_member_verify(self, vaction_oid, vaction_code):

        self.log.info('Verifying member using vaction_oid={vaction_oid}, vaction_code={vaction_code} ..',
                      vaction_oid=vaction_oid, vaction_code=vaction_code)
        try:
            result = yield self.call('xbr.network.verify_onboard_member', vaction_oid.bytes, vaction_code)
        except ApplicationError as e:
            self.log.error('ApplicationError: {error}', error=e)
            raise e

        assert type(result) == dict
        assert 'member_oid' in result and type(result['member_oid']) == bytes and len(result['member_oid']) == 16
        assert 'created' in result and type(result['created']) == int and result['created'] > 0

        member_oid = result['member_oid']
        self.log.info('SUCCESS! New XBR Member onboarded: member_oid={member_oid}, transaction={transaction}',
                      member_oid=hlid(uuid.UUID(bytes=member_oid)),
                      transaction=hlval('0x' + binascii.b2a_hex(result['transaction']).decode()))

        return result

    async def _do_create_market(self, member_oid, market_oid, marketmaker, title=None, label=None, homepage=None,
                                provider_security=0, consumer_security=0, market_fee=0):
        member_data = await self.call('xbr.network.get_member', member_oid.bytes)
        member_adr = member_data['address']

        config = await self.call('xbr.network.get_config')

        verifyingChain = config['verifying_chain_id']
        verifyingContract = binascii.a2b_hex(config['verifying_contract_adr'][2:])

        coin_adr = binascii.a2b_hex(config['contracts']['xbrtoken'][2:])

        status = await self.call('xbr.network.get_status')
        block_number = status['block']['number']

        # count all markets before we create a new one:
        res = await self.call('xbr.network.find_markets')
        cnt_market_before = len(res)
        self.log.info('Total markets before: {cnt_market_before}', cnt_market_before=cnt_market_before)

        res = await self.call('xbr.network.get_markets_by_owner', member_oid.bytes)
        cnt_market_by_owner_before = len(res)
        self.log.info('Market for owner: {cnt_market_by_owner_before}',
                      cnt_market_by_owner_before=cnt_market_by_owner_before)

        # collect information for market creation that is stored on-chain

        # terms text: encode in utf8 and compute BIP58 multihash string
        terms_data = 'these are my market terms (randint={})'.format(random.randint(0, 1000)).encode('utf8')
        h = hashlib.sha256()
        h.update(terms_data)
        terms_hash = str(multihash.to_b58_string(multihash.encode(h.digest(), 'sha2-256')))

        # market meta data that doesn't change. the hash of this is part of the data that is signed and also
        # stored on-chain (only the hash, not the meta data!)
        meta_obj = {
            'chain_id': verifyingChain,
            'block_number': block_number,
            'contract_adr': verifyingContract,
            'member_adr': member_adr,
            'member_oid': member_oid.bytes,
            'market_oid': market_oid.bytes,
        }
        meta_data = cbor2.dumps(meta_obj)
        h = hashlib.sha256()
        h.update(meta_data)
        meta_hash = multihash.to_b58_string(multihash.encode(h.digest(), 'sha2-256'))

        # create signature for pre-signed transaction
        signature = sign_eip712_market_create(self._ethkey_raw, verifyingChain, verifyingContract, member_adr,
                                              block_number, market_oid.bytes, coin_adr, terms_hash, meta_hash,
                                              marketmaker, provider_security, consumer_security, market_fee)

        # for wire transfer, convert to bytes
        provider_security = pack_uint256(provider_security)
        consumer_security = pack_uint256(consumer_security)
        market_fee = pack_uint256(market_fee)

        # market settings that can change. even though changing might require signing, neither the data nor
        # and signatures are stored on-chain. however, even when only signed off-chain, this establishes
        # a chain of signature anchored in the on-chain record for this market!
        attributes = {
            'title': title,
            'label': label,
            'homepage': homepage,
        }

        # now provide everything of above:
        #   - market operator (owning member) and market oid
        #   - signed market data and signature
        #   - settings
        createmarket_request_submitted = await self.call('xbr.network.create_market', member_oid.bytes,
                                                         market_oid.bytes, verifyingChain, block_number,
                                                         verifyingContract, coin_adr, terms_hash, meta_hash, meta_data,
                                                         marketmaker, provider_security, consumer_security, market_fee,
                                                         signature, attributes)

        self.log.info('SUCCESS: Create market request submitted: \n{createmarket_request_submitted}\n',
                      createmarket_request_submitted=pformat(createmarket_request_submitted))

        assert type(createmarket_request_submitted) == dict
        assert 'timestamp' in createmarket_request_submitted and type(
            createmarket_request_submitted['timestamp']) == int and createmarket_request_submitted['timestamp'] > 0
        assert 'action' in createmarket_request_submitted and createmarket_request_submitted[
            'action'] == 'create_market'
        assert 'vaction_oid' in createmarket_request_submitted and type(
            createmarket_request_submitted['vaction_oid']) == bytes and len(
            createmarket_request_submitted['vaction_oid']) == 16

        vaction_oid = uuid.UUID(bytes=createmarket_request_submitted['vaction_oid'])
        self.log.info('SUCCESS: New Market verification "{vaction_oid}" created', vaction_oid=vaction_oid)

    async def _do_create_market_verify(self, member_oid, vaction_oid, vaction_code):
        self.log.info('Verifying create market using vaction_oid={vaction_oid}, vaction_code={vaction_code} ..',
                      vaction_oid=vaction_oid, vaction_code=vaction_code)

        create_market_request_verified = await self.call('xbr.network.verify_create_market', vaction_oid.bytes,
                                                         vaction_code)

        self.log.info('Create market request verified: \n{create_market_request_verified}\n',
                      create_market_request_verified=pformat(create_market_request_verified))

        assert type(create_market_request_verified) == dict
        assert 'market_oid' in create_market_request_verified and type(
            create_market_request_verified['market_oid']) == bytes and len(
            create_market_request_verified['market_oid']) == 16
        assert 'created' in create_market_request_verified and type(
            create_market_request_verified['created']) == int and create_market_request_verified['created'] > 0

        market_oid = create_market_request_verified['market_oid']
        self.log.info('SUCCESS! New XBR market created: market_oid={market_oid}, result=\n{result}',
                      market_oid=uuid.UUID(bytes=market_oid), result=pformat(create_market_request_verified))

        market_oids = await self.call('xbr.network.find_markets')
        self.log.info('SUCCESS - find_markets: found {cnt_markets} markets', cnt_markets=len(market_oids))

        # count all markets after we created a new market:
        cnt_market_after = len(market_oids)
        self.log.info('Total markets after: {cnt_market_after}', cnt_market_after=cnt_market_after)
        assert market_oid in market_oids, 'expected to find market ID {}, but not found in {} returned market IDs'.format(
            uuid.UUID(bytes=market_oid), len(market_oids))

        market_oids = await self.call('xbr.network.get_markets_by_owner', member_oid.bytes)
        self.log.info('SUCCESS - get_markets_by_owner: found {cnt_markets} markets', cnt_markets=len(market_oids))

        # count all markets after we created a new market:
        cnt_market_by_owner_after = len(market_oids)
        self.log.info('Market for owner: {cnt_market_by_owner_after}',
                      cnt_market_by_owner_before=cnt_market_by_owner_after)
        assert market_oid in market_oids, 'expected to find market ID {}, but not found in {} returned market IDs'.format(
            uuid.UUID(bytes=market_oid), len(market_oids))

        for market_oid in market_oids:
            self.log.info('xbr.network.get_market(market_oid={market_oid}) ..', market_oid=market_oid)
            market = await self.call('xbr.network.get_market', market_oid, include_attributes=True)
            self.log.info('SUCCESS: got market information\n\n{market}\n', market=pformat(market))

    async def _do_get_market(self, member_oid, market_oid):
        member_data = await self.call('xbr.network.get_member', member_oid.bytes)
        member_adr = member_data['address']
        market = await self.call('xbr.network.get_market', market_oid.bytes)
        if market:
            if market['owner'] == member_adr:
                self.log.info('You are market owner (operator)!')
            else:
                self.log.info('Marked is owned by {owner}', owner=hlid(web3.Web3.toChecksumAddress(market['owner'])))

            market['market'] = uuid.UUID(bytes=market['market'])
            market['owner'] = web3.Web3.toChecksumAddress(market['owner'])
            market['maker'] = web3.Web3.toChecksumAddress(market['maker'])
            market['coin'] = web3.Web3.toChecksumAddress(market['coin'])
            market['timestamp'] = np.datetime64(market['timestamp'], 'ns')

            self.log.info('Market {market_oid} information:\n\n{market}\n',
                          market_oid=hlid(market_oid), market=pformat(market))
        else:
            self.log.warning('No market {market_oid} found!', market_oid=hlid(market_oid))

    async def _do_join_market(self, member_oid, market_oid, actor_type):

        assert actor_type in [ActorType.CONSUMER, ActorType.PROVIDER, ActorType.PROVIDER_CONSUMER]

        member_data = await self.call('xbr.network.get_member', member_oid.bytes)
        member_adr = member_data['address']

        config = await self.call('xbr.network.get_config')
        verifyingChain = config['verifying_chain_id']
        verifyingContract = binascii.a2b_hex(config['verifying_contract_adr'][2:])

        status = await self.call('xbr.network.get_status')
        block_number = status['block']['number']

        meta_obj = {
        }
        meta_data = cbor2.dumps(meta_obj)
        h = hashlib.sha256()
        h.update(meta_data)
        meta_hash = multihash.to_b58_string(multihash.encode(h.digest(), 'sha2-256'))

        signature = sign_eip712_market_join(self._ethkey_raw, verifyingChain, verifyingContract, member_adr,
                                            block_number, market_oid.bytes, actor_type, meta_hash)

        request_submitted = await self.call('xbr.network.join_market', member_oid.bytes, market_oid.bytes,
                                            verifyingChain, block_number, verifyingContract,
                                            actor_type, meta_hash, meta_data, signature)

        vaction_oid = uuid.UUID(bytes=request_submitted['vaction_oid'])
        self.log.info('SUCCESS! XBR market join request submitted: vaction_oid={vaction_oid}', vaction_oid=vaction_oid)

    async def _do_join_market_verify(self, member_oid, vaction_oid, vaction_code):
        request_verified = await self.call('xbr.network.verify_join_market', vaction_oid.bytes, vaction_code)
        market_oid = request_verified['market_oid']
        actor_type = request_verified['actor_type']
        self.log.info(
            'SUCCESS! XBR market joined: member_oid={member_oid}, market_oid={market_oid}, actor_type={actor_type}',
            member_oid=member_oid, market_oid=market_oid, actor_type=actor_type)

    async def _do_get_active_payment_channel(self, market_oid, delegate_adr):
        channel = await self.call('xbr.marketmaker.get_active_payment_channel', delegate_adr)
        self.log.debug('{channel}', channel=pformat(channel))
        if channel:
            self.log.info('Active buyer (payment) channel found: {amount} amount',
                          amount=int(unpack_uint256(channel['amount']) / 10 ** 18))
            balance = await self.call('xbr.marketmaker.get_payment_channel_balance', channel['channel_oid'])
            self.log.debug('{balance}', channel=pformat(balance))
            self.log.info('Current off-chain amount remaining: {remaining} [sequence {sequence}]',
                          remaining=int(unpack_uint256(balance['remaining']) / 10 ** 18), sequence=balance['seq'])
        else:
            self.log.info('No active buyer (payment) channel found!')

    async def _do_get_active_paying_channel(self, market_oid, delegate_adr):
        channel = await self.call('xbr.marketmaker.get_active_paying_channel', delegate_adr)
        self.log.debug('{channel}', channel=pformat(channel))
        if channel:
            self.log.info('Active seller (paying) channel found: {amount} amount',
                          amount=int(unpack_uint256(channel['amount']) / 10 ** 18))
            balance = await self.call('xbr.marketmaker.get_paying_channel_balance', channel['channel_oid'])
            self.log.debug('{balance}', channel=pformat(balance))
            self.log.info('Current off-chain amount remaining: {remaining} [sequence {sequence}]',
                          remaining=int(unpack_uint256(balance['remaining']) / 10 ** 18), sequence=balance['seq'])
        else:
            self.log.info('No active seller (paying) channel found!')

    async def _do_open_channel(self, market_oid, channel_oid, channel_type, delegate, amount):
        member_key = self._ethkey_raw
        member_adr = self._ethkey.public_key.to_canonical_address()

        config = await self.call('xbr.marketmaker.get_config')
        marketmaker = binascii.a2b_hex(config['marketmaker'][2:])
        recipient = binascii.a2b_hex(config['owner'][2:])
        verifying_chain_id = config['verifying_chain_id']
        verifying_contract_adr = binascii.a2b_hex(config['verifying_contract_adr'][2:])

        status = await self.call('xbr.marketmaker.get_status')
        current_block_number = status['block']['number']

        if amount > 0:
            if channel_type == ChannelType.PAYMENT:
                from_adr = member_adr
                to_adr = xbr.xbrchannel.address
            elif channel_type == ChannelType.PAYING:
                from_adr = marketmaker
                to_adr = xbr.xbrchannel.address
            else:
                assert False, 'should not arrive here'

            # allowance1 = xbr.xbrtoken.functions.allowance(transact_from, xbr.xbrchannel.address).call()
            # xbr.xbrtoken.functions.approve(to_adr, amount).transact(
            #     {'from': transact_from, 'gas': transact_gas})
            # allowance2 = xbr.xbrtoken.functions.allowance(transact_from, xbr.xbrchannel.address).call()
            # assert allowance2 - allowance1 == amount

            try:
                txn_hash = await deferToThread(self._send_Allowance, from_adr, to_adr, amount)
                self.log.info('transaction submitted, txn_hash={txn_hash}', txn_hash=txn_hash)
            except Exception as e:
                self.log.failure()
                raise e

        # compute EIP712 signature, and sign using member private key
        signature = sign_eip712_channel_open(member_key, verifying_chain_id, verifying_contract_adr, channel_type,
                                             current_block_number, market_oid.bytes, channel_oid.bytes,
                                             member_adr, delegate, marketmaker, recipient, amount)
        attributes = None
        channel_request = await self.call('xbr.marketmaker.open_channel', member_adr, market_oid.bytes,
                                          channel_oid.bytes, verifying_chain_id, current_block_number,
                                          verifying_contract_adr, channel_type, delegate, marketmaker, recipient,
                                          pack_uint256(amount), signature, attributes)

        self.log.info('Channel open request submitted:\n\n{channel_request}\n',
                      channel_request=pformat(channel_request))

    def _send_Allowance(self, from_adr, to_adr, amount):
        # FIXME: estimate gas required for call
        gas = self._default_gas
        gasPrice = self._w3.toWei('10', 'gwei')

        from_adr = self._ethadr

        # each submitted transaction must contain a nonce, which is obtained by the on-chain transaction number
        # for this account, including pending transactions (I think ..;) ..
        nonce = self._w3.eth.getTransactionCount(from_adr, block_identifier='pending')
        self.log.info('{func}::[1/4] - Ethereum transaction nonce: nonce={nonce}',
                      func=hltype(self._send_Allowance),
                      nonce=nonce)

        # serialize transaction raw data from contract call and transaction settings
        raw_transaction = xbr.xbrtoken.functions.approve(to_adr, amount).buildTransaction({
            'from': from_adr,
            'gas': gas,
            'gasPrice': gasPrice,
            'chainId': self._chain_id,  # https://stackoverflow.com/a/57901206/884770
            'nonce': nonce,
        })
        self.log.info(
            '{func}::[2/4] - Ethereum transaction created: raw_transaction=\n{raw_transaction}\n',
            func=hltype(self._send_Allowance),
            raw_transaction=raw_transaction)

        # compute signed transaction from above serialized raw transaction
        signed_txn = self._w3.eth.account.sign_transaction(raw_transaction, private_key=self._ethkey_raw)
        self.log.info(
            '{func}::[3/4] - Ethereum transaction signed: signed_txn=\n{signed_txn}\n',
            func=hltype(self._send_Allowance),
            signed_txn=hlval(binascii.b2a_hex(signed_txn.rawTransaction).decode()))

        # now send the pre-signed transaction to the blockchain via the gateway ..
        # https://web3py.readthedocs.io/en/stable/web3.eth.html  # web3.eth.Eth.sendRawTransaction
        txn_hash = self._w3.eth.sendRawTransaction(signed_txn.rawTransaction)
        txn_hash = bytes(txn_hash)
        self.log.info(
            '{func}::[4/4] - Ethereum transaction submitted: txn_hash=0x{txn_hash}',
            func=hltype(self._send_Allowance),
            txn_hash=hlval(binascii.b2a_hex(txn_hash).decode()))

        return txn_hash


def print_version():
    print('')
    print(' XBR CLI {}\n'.format(hlval('v' + __version__)))
    print('')
    print('   Contract addresses:\n')
    print('      XBRToken   : {} [source: {}]'.format(hlid(XBR_DEBUG_TOKEN_ADDR), XBR_DEBUG_TOKEN_ADDR_SRC))
    print('      XBRNetwork : {} [source: {}]'.format(hlid(XBR_DEBUG_NETWORK_ADDR), XBR_DEBUG_NETWORK_ADDR_SRC))
    print('      XBRDomain  : {} [source: {}]'.format(hlid(XBR_DEBUG_DOMAIN_ADDR), XBR_DEBUG_DOMAIN_ADDR_SRC))
    print('      XBRCatalog : {} [source: {}]'.format(hlid(XBR_DEBUG_CATALOG_ADDR), XBR_DEBUG_CATALOG_ADDR_SRC))
    print('      XBRMarket  : {} [source: {}]'.format(hlid(XBR_DEBUG_MARKET_ADDR), XBR_DEBUG_MARKET_ADDR_SRC))
    print('      XBRChannel : {} [source: {}]'.format(hlid(XBR_DEBUG_CHANNEL_ADDR), XBR_DEBUG_CHANNEL_ADDR_SRC))
    print('')


def _main():
    parser = argparse.ArgumentParser()

    parser.add_argument('command',
                        type=str,
                        choices=_COMMANDS,
                        const='noop',
                        nargs='?',
                        help='Command to run')

    parser.add_argument('-d',
                        '--debug',
                        action='store_true',
                        help='Enable debug output.')

    parser.add_argument('-o',
                        '--output',
                        type=str,
                        help='Code output folder')

    parser.add_argument('-s',
                        '--schema',
                        dest='schema',
                        type=str,
                        help='FlatBuffers binary schema file to read (.bfbs)')

    parser.add_argument('-b',
                        '--basemodule',
                        dest='basemodule',
                        type=str,
                        help='Render to this base module')

    _LANGUAGES = ['python', 'json']
    parser.add_argument('-l',
                        '--language',
                        dest='language',
                        type=str,
                        help='Generated code language, one of {}'.format(_LANGUAGES))

    parser.add_argument('--url',
                        dest='url',
                        type=str,
                        default='wss://planet.xbr.network/ws',
                        help='The router URL (default: "wss://planet.xbr.network/ws").')

    parser.add_argument('--realm',
                        dest='realm',
                        type=str,
                        default='xbrnetwork',
                        help='The realm to join (default: "xbrnetwork").')

    parser.add_argument('--ethkey',
                        dest='ethkey',
                        type=str,
                        help='Private Ethereum key (32 bytes as HEX encoded string)')

    parser.add_argument('--cskey',
                        dest='cskey',
                        type=str,
                        help='Private WAMP-cryptosign authentication key (32 bytes as HEX encoded string)')

    parser.add_argument('--username',
                        dest='username',
                        type=str,
                        default=None,
                        help='For on-boarding, the new member username.')

    parser.add_argument('--email',
                        dest='email',
                        type=str,
                        default=None,
                        help='For on-boarding, the new member email address.')

    parser.add_argument('--market',
                        dest='market',
                        type=str,
                        default=None,
                        help='For creating new markets, the market UUID.')

    parser.add_argument('--market_title',
                        dest='market_title',
                        type=str,
                        default=None,
                        help='For creating new markets, the market title.')

    parser.add_argument('--market_label',
                        dest='market_label',
                        type=str,
                        default=None,
                        help='For creating new markets, the market label.')

    parser.add_argument('--market_homepage',
                        dest='market_homepage',
                        type=str,
                        default=None,
                        help='For creating new markets, the market homepage.')

    parser.add_argument('--provider_security',
                        dest='provider_security',
                        type=int,
                        default=None,
                        help='')

    parser.add_argument('--consumer_security',
                        dest='consumer_security',
                        type=int,
                        default=None,
                        help='')

    parser.add_argument('--market_fee',
                        dest='market_fee',
                        type=int,
                        default=None,
                        help='')

    parser.add_argument('--marketmaker',
                        dest='marketmaker',
                        type=str,
                        default=None,
                        help='For creating new markets, the market maker address.')

    parser.add_argument('--actor_type',
                        dest='actor_type',
                        type=int,
                        choices=sorted([ActorType.CONSUMER, ActorType.PROVIDER, ActorType.PROVIDER_CONSUMER]),
                        default=None,
                        help='Actor type: PROVIDER = 1, CONSUMER = 2, PROVIDER_CONSUMER (both) = 3')

    parser.add_argument('--vcode',
                        dest='vcode',
                        type=str,
                        default=None,
                        help='For verifications of actions, the verification UUID.')

    parser.add_argument('--vaction',
                        dest='vaction',
                        type=str,
                        default=None,
                        help='For verifications of actions (on-board, create-market, ..), the verification code.')

    parser.add_argument('--channel',
                        dest='channel',
                        type=str,
                        default=None,
                        help='For creating new channel, the channel UUID.')

    parser.add_argument('--channel_type',
                        dest='channel_type',
                        type=int,
                        choices=sorted([ChannelType.PAYING, ChannelType.PAYMENT]),
                        default=None,
                        help='Channel type: Seller (PAYING) = 1, Buyer (PAYMENT) = 2')

    parser.add_argument('--delegate',
                        dest='delegate',
                        type=str,
                        default=None,
                        help='For creating new channel, the delegate address.')

    parser.add_argument('--amount',
                        dest='amount',
                        type=int,
                        default=None,
                        help='Amount to open the channel with. In tokens of the market coin type, used as means of payment in the market of the channel.')

    args = parser.parse_args()

    if args.command == 'version':
        print_version()

    # describe schema in WAMP IDL FlatBuffers schema files
    elif args.command == 'describe-schema':
        repo = FbsRepository(basemodule=args.basemodule)
        repo.load(args.schema)

        total_count = len(repo.objs) + len(repo.enums) + len(repo.services)
        print('ok, loaded {} types ({} structs and tables, {} enums and {} service interfaces)'.format(
            hlval(total_count),
            hlval(len(repo.objs)),
            hlval(len(repo.enums)),
            hlval(len(repo.services))))
        print()

        repo.print_summary()

    # generate code from WAMP IDL FlatBuffers schema files
    elif args.command == 'codegen-schema':

        # load repository from flatbuffers schema files
        repo = FbsRepository(basemodule=args.basemodule)
        repo.load(args.schema)

        # print repository summary
        print(repo.summary(keys=True))

        # folder with jinja2 templates for python code sections
        templates = pkg_resources.resource_filename('autobahn', 'xbr/templates')

        # jinja2 template engine loader and environment
        loader = FileSystemLoader(templates, encoding='utf-8', followlinks=False)
        env = Environment(loader=loader, trim_blocks=True, lstrip_blocks=True)

        # output directory for generated code
        if not os.path.isdir(args.output):
            os.mkdir(args.output)

        # render python source code files
        repo.render(env, args.output, 'python')

    else:
        if args.command is None or args.command == 'noop':
            print('no command given. select from: {}'.format(', '.join(_COMMANDS)))
            sys.exit(0)

        # read or create a user profile
        profile = load_or_create_profile(default_url=args.url, default_realm=args.realm,
                                         default_username=args.username, default_email=args.email)

        # only start txaio logging after above, which runs click (interactively)
        if args.debug:
            txaio.start_logging(level='debug')
        else:
            txaio.start_logging(level='info')

        log = txaio.make_logger()

        log.info('XBR CLI {version}', version=hlid('v' + __version__))
        log.info('Profile {profile} loaded from {path}', profile=hlval(profile.name), path=hlval(profile.path))

        extra = {
            # user profile and defaults
            'profile': profile,

            # allow to override, and add more arguments from the command line
            'command': args.command,
            'username': args.username,
            'email': args.email,

            'ethkey': profile.ethkey,
            'cskey': profile.cskey,

            'market': uuid.UUID(args.market) if args.market else None,
            'market_title': args.market_title,
            'market_label': args.market_label,
            'market_homepage': args.market_homepage,
            'market_provider_security': args.provider_security or 0,
            'market_consumer_security': args.consumer_security or 0,
            'market_fee': args.market_fee or 0,
            'marketmaker': binascii.a2b_hex(args.marketmaker[2:]) if args.marketmaker else None,
            'actor_type': args.actor_type,
            'vcode': args.vcode,
            'vaction': uuid.UUID(args.vaction) if args.vaction else None,
            'channel': uuid.UUID(args.channel) if args.channel else None,
            'channel_type': args.channel_type,
            'delegate': binascii.a2b_hex(args.delegate[2:]) if args.delegate else None,
            'amount': args.amount or 0,
        }
        runner = ApplicationRunner(url=profile.network_url, realm=profile.network_realm, extra=extra,
                                   serializers=[CBORSerializer()])

        try:
            log.info('Connecting to "{url}" {realm} ..',
                     url=hlval(profile.network_url),
                     realm=('at realm "' + hlval(profile.network_realm) + '"' if profile.network_realm else ''))
            runner.run(Client, auto_reconnect=False)
        except Exception as e:
            print(e)
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == '__main__':
    _main()
