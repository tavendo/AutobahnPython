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

# this module is available as the 'wamp' command-line tool or as
# 'python -m autobahn'

import os
import sys
import argparse
import json
from copy import copy

try:
    from autobahn.twisted.component import Component
except ImportError:
    print("The 'wamp' command-line tool requires Twisted.")
    print("  pip install autobahn[twisted]")
    sys.exit(1)
from twisted.internet.defer import Deferred, ensureDeferred
from twisted.internet.task import react, deferLater
from autobahn.wamp.exception import ApplicationError
from autobahn.wamp.types import PublishOptions
from autobahn.wamp.types import RegisterOptions
from autobahn.wamp.types import SubscribeOptions


## XXX other ideas to get 'connection config':
## - if there .crossbar/ here, load that config and accept a --name or
##   so to idicate which transport to use

# wamp [options] {call,publish,subscribe,register} wamp-uri [args] [kwargs]
#
# kwargs are spec'd with a 2-value-consuming --keyword option:
# --keyword name value


top = argparse.ArgumentParser(prog="wamp")
top.add_argument(
    '--url',
    action='store',
    help='A WAMP URL to connect to, like ws://127.0.0.1:8080/ws or rs://localhost:1234/',
    required=True,
)
top.add_argument(
    '--realm', '-r',
    action='store',
    help='The realm to join',
    default='default',
)
top.add_argument(
    '--private-key', '-k',
    action='store',
    help='Hex-encoded private key (via WAMP_PRIVATE_KEY if not provided here)',
    default=os.environ.get('WAMP_PRIVATE_KEY', None),
)
top.add_argument(
    '--authid',
    action='store',
    help='The authid to use, if authenticating',
    default=None,
)
top.add_argument(
    '--authrole',
    action='store',
    help='The role to use, if authenticating',
    default=None,
)
sub = top.add_subparsers(
    title="subcommands",
    dest="subcommand_name",
#    help="ohai what goes here?",
)


call = sub.add_parser(
    'call',
    help='Do a WAMP call() and print any results',
)
call.add_argument(
    'uri',
    type=str,
    help="A WAMP URI to call"
)
call.add_argument(
    'call_args',
    nargs='*',
    help="All additional arguments are positional args",
)
call.add_argument(
    '--keyword',
    nargs=2,
    action='append',
    help="Specify a keyword argument to send: name value",
)


publish = sub.add_parser(
    'publish',
    help='Do a WAMP publish() with the given args, kwargs',
)
publish.add_argument(
    'uri',
    type=str,
    help="A WAMP URI to publish"
)
publish.add_argument(
    'publish_args',
    nargs='*',
    help="All additional arguments are positional args",
)
publish.add_argument(
    '--keyword',
    nargs=2,
    action='append',
    help="Specify a keyword argument to send: name value",
)


register = sub.add_parser(
    'register',
    help='Do a WAMP register() and run a command when called',
)
register.add_argument(
    'uri',
    type=str,
    help="A WAMP URI to call"
)
register.add_argument(
    '--times',
    type=int,
    default=0,
    help="Listen for this number of events, then exit. Default: forever",
)
register.add_argument(
    'command',
    type=str,
    help="The command to run when called. WAMP_ARGS, WAMP_KWARGS and _JSON variants are set in the environment"
)


subscribe = sub.add_parser(
    'subscribe',
    help='Do a WAMP subscribe() and print one line of JSON per event',
)
subscribe.add_argument(
    'uri',
    type=str,
    help="A WAMP URI to call"
)
subscribe.add_argument(
    '--times',
    type=int,
    default=0,
    help="Listen for this number of events, then exit. Default: forever",
)
subscribe.add_argument(
    '--match',
    type=str,
    default='exact',
    choices=['exact', 'prefix'],
    help="Massed in the SubscribeOptions, how to match the URI",
)


def _create_component(options):
    """
    Configure and return a Component instance according to the given
    `options`
    """
    if options.url.startswith('ws://'):
        kind = 'websocket'
    elif options.url.startswith('rs://'):
        kind = 'rawsocket'
    else:
        raise ValueError(
            "URL should start with ws:// or rs://"
        )

    authentication = dict()
    if options.private_key:
        if not options.authid:# or not options.authrole:
            raise ValueError(
                "Require --authid and --authrole if --private-key (or WAMP_PRIVATE_KEY) is provided"
            )
        authentication["cryptosign"] = {
                "authid": options.authid,
                "authrole": options.authrole,
                "privkey": options.private_key,
        }

    return Component(
        transports=[{
            "type": kind,
            "url": options.url,
        }],
        authentication=authentication if authentication else None,
        realm=options.realm,
    )


async def do_call(reactor, session, options):
    call_args = list(options.call_args)
    call_kwargs = {
        k: v
        for k, v in options.keyword
    }

    results = await session.call(options.uri, *call_args, **call_kwargs)
    print("result: {}".format(results))


async def do_publish(reactor, session, options):
    publish_args = list(options.publish_args)
    publish_kwargs = {
        k: v
        for k, v in options.keyword
    }

    await session.publish(
        options.uri,
        *publish_args,
        options=PublishOptions(acknowledge=True),
        **publish_kwargs,
    )


async def do_register(reactor, session, options):
    """
    run a command-line upon an RPC call
    """

    all_done = Deferred()
    countdown = [options.times]

    async def called(*args, **kw):
        print("called: args={}, kwargs={}".format(args, kw))
        env = copy(os.environ)
        env['WAMP_ARGS'] = ' '.join(args)
        env['WAMP_ARGS_JSON'] = json.dumps(args)
        env['WAMP_KWARGS'] = ' '.join('{}={}'.format(k, v) for k, v in kw.items())
        env['WAMP_KWARGS_JSON'] = json.dumps(kw)
        print(options.command)
        if countdown[0]:
            countdown[0] -= 1
            if countdown[0] <= 0:
                reactor.callLater(0, all_done.callback, None)

    reg = await session.register(called, options.uri)
    await all_done


async def do_subscribe(reactor, session, options):
    """
    print events (one line of JSON per event)
    """

    all_done = Deferred()
    countdown = [options.times]

    async def published(*args, **kw):
        print(
            json.dumps({
                "args": args,
                "kwargs": kw,
            })
        )
        if countdown[0]:
            countdown[0] -= 1
            if countdown[0] <= 0:
                reactor.callLater(0, all_done.callback, None)

    reg = await session.subscribe(published, options.uri, options=SubscribeOptions(match=options.match))
    await all_done


def main():
    react(
        lambda reactor: ensureDeferred(
            _real_main(reactor)
        )
    )

async def _real_main(reactor):
    options = top.parse_args()
    component = _create_component(options)

    if options.subcommand_name is None:
        print("Must select a subcommand")
        sys.exit(1)

    subcommands = {
        "call": do_call,
        "register": do_register,
        "subscribe": do_subscribe,
        "publish": do_publish,
    }
    command_fn = subcommands[options.subcommand_name]

    exit_code = [0]

    @component.on_join
    async def _(session, details):
        print("connected: authrole={} authmethod={}".format(details.authrole, details.authmethod), file=sys.stderr)
        try:
            await command_fn(reactor, session, options)
        except ApplicationError as e:
            print("\n{}: {}\n".format(e.error, ''.join(e.args)))
            exit_code[0] = 5
        await session.leave()

    await component.start(reactor)
    sys.exit(exit_code[0])


if __name__ == "__main__":
    _main()
