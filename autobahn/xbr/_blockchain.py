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

import web3
import txaio
from autobahn import xbr


class SimpleBlockchain(object):
    """
    Simple Ethereum blockchain XBR client.
    """
    DomainStatus_NULL = 0
    DomainStatus_ACTIVE = 1
    DomainStatus_CLOSED = 2

    NodeType_NULL = 0
    NodeType_MASTER = 1
    NodeType_CORE = 2
    NodeType_EDGE = 3

    NodeLicense_NULL = 0
    NodeLicense_INFINITE = 1
    NodeLicense_FREE = 2

    log = None
    backgroundCaller = None

    def __init__(self, gateway=None):
        """

        :param gateway: Optional explicit Ethereum gateway URL to use.
            If no explicit gateway is specified, let web3 auto-choose.
        :type gateway: str
        """
        self.log = txaio.make_logger()
        self._gateway = gateway
        self._w3 = None
        assert self.backgroundCaller is not None

    def start(self):
        """
        Start the blockchain client using the configured blockchain gateway.
        """
        assert self._w3 is None

        if self._gateway:
            w3 = web3.Web3(web3.Web3.HTTPProvider(self._gateway))
        else:
            # using automatic provider detection:
            from web3.auto import w3

        # check we are connected, and check network ID
        if not w3.isConnected():
            emsg = 'could not connect to Web3/Ethereum at: {}'.format(self._gateway or 'auto')
            self.log.warning(emsg)
            raise RuntimeError(emsg)
        else:
            print('connected to network {} at provider "{}"'.format(w3.version.network,
                                                                    self._gateway or 'auto'))

        self._w3 = w3

        # set new provider on XBR library
        xbr.setProvider(self._w3)

    def stop(self):
        """
        Stop the blockchain client.
        """
        assert self._w3 is not None

        self._w3 = None

    async def get_market_status(self, market_id):
        """

        :param market_id:
        :return:
        """
        def _get_market_status(_market_id):
            owner = xbr.xbrnetwork.functions.getMarketOwner(_market_id).call()
            if not owner or owner == '0x0000000000000000000000000000000000000000':
                return None
            else:
                return {
                    'owner': owner,
                }
        return self.backgroundCaller(_get_market_status, market_id)

    async def get_domain_status(self, domain_id):
        """

        :param domain_id:
        :type domain_id: bytes

        :return:
        :rtype: dict
        """
        def _get_domain_status(_domain_id):
            status = xbr.xbrnetwork.functions.getDomainStatus(_domain_id).call()
            if status == SimpleBlockchain.DomainStatus_NULL:
                return None
            elif status == SimpleBlockchain.DomainStatus_ACTIVE:
                return {'status': 'ACTIVE'}
            elif status == SimpleBlockchain.DomainStatus_CLOSED:
                return {'status': 'CLOSED'}
        return self.backgroundCaller(_get_domain_status, domain_id)

    def get_node_status(self, delegate_adr):
        """

        :param delegate_adr:
        :type delegate_adr: bytes

        :return:
        :rtype: dict
        """
        raise NotImplementedError()

    def get_actor_status(self, delegate_adr):
        """

        :param delegate_adr:
        :type delegate_adr: bytes

        :return:
        :rtype: dict
        """
        raise NotImplementedError()

    def get_delegate_status(self, delegate_adr):
        """

        :param delegate_adr:
        :type delegate_adr: bytes

        :return:
        :rtype: dict
        """
        raise NotImplementedError()

    def get_channel_status(self, channel_adr):
        """

        :param channel_adr:
        :type channel_adr: bytes

        :return:
        :rtype: dict
        """
        raise NotImplementedError()

    async def get_member_status(self, member_adr):
        """

        :param member_adr:
        :type member_adr: bytes

        :return:
        :rtype: dict
        """
        assert type(member_adr) == bytes and len(member_adr) == 20

        def _get_member_status(_member_adr):
            level = xbr.xbrnetwork.functions.getMemberLevel(member_adr).call()
            if not level:
                return None
            else:
                eula = xbr.xbrnetwork.functions.getMemberEula(member_adr).call()
                if not eula or eula.strip() == '':
                    return None
                profile = xbr.xbrnetwork.functions.getMemberProfile(member_adr).call()
                if not profile or profile.strip() == '':
                    profile = None
                return {
                    'eula': eula,
                    'profile': profile,
                }
        return self.backgroundCaller(_get_member_status, member_adr)

    async def get_balances(self, account_adr):
        """
        Return current ETH and XBR balances of account with given address.

        :param account_adr: Ethereum address of account to get balances for.
        :type account_adr: bytes

        :return: A dictionary with ``"ETH"`` and ``"XBR"`` keys and respective
            current on-chain balances as values.
        :rtype: dict
        """
        assert type(account_adr) == bytes and len(account_adr) == 20

        def _get_balances(_adr):
            balance_eth = self._w3.eth.getBalance(_adr)
            balance_xbr = xbr.xbrtoken.functions.balanceOf(_adr).call()
            return {
                'ETH': balance_eth,
                'XBR': balance_xbr,
            }
        return self.backgroundCaller(_get_balances, account_adr)

    def get_contract_adrs(self):
        """
        Get XBR smart contract addresses.

        :return: A dictionary with ``"XBRToken"``  and ``"XBRNetwork"`` keys and Ethereum
            contract addresses as values.
        :rtype: dict
        """
        return {
            'XBRToken': xbr.xbrtoken.address,
            'XBRNetwork': xbr.xbrnetwork.address,
        }
