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

from flask import Flask, request
from crochet import setup, run_in_reactor, wait_for

# this MUST be called _before_ any Autobahn or Twisted imports!
setup()

from autobahn.twisted.util import sleep  # noqa
from autobahn.twisted.wamp import Application  # noqa


# our WAMP app
#
wapp = Application()


@wapp.register('com.example.square')
def square(x):
    print("square() called with {}".format(x))
    return x * x


@wapp.register('com.example.slowsquare')
def slowsquare(x):
    print("slowsquare() called with {}".format(x))
    yield sleep(2)
    return x * x


# the following are synchronous wrappers around the asynchronous WAMP code
#
@wait_for(timeout=1)
def call_square(x):
    return wapp.session.call('com.example.square', x)


@wait_for(timeout=5)
def call_slowsquare(x):
    return wapp.session.call('com.example.slowsquare', x)


# our Flask app
#
app = Flask(__name__)


@app.route('/square/submit', methods=['POST'])
def square_submit():
    x = int(request.form.get('x', 0))
    res = call_square(x)
    return "{} squared is {}".format(x, res)


@app.route('/slowsquare/submit', methods=['POST'])
def slowsquare_submit():
    x = int(request.form.get('x', 0))
    res = call_slowsquare(x)
    return "{} squared is {}".format(x, res)


if __name__ == '__main__':
    import sys
    import logging
    logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

    # this will start the WAMP app on a background thread and setup communication
    # with the main thread that runs a (blocking) Flask server
    #
    @run_in_reactor
    def start_wamp():
        wapp.run("ws://127.0.0.1:9000", "realm1", standalone=True, start_reactor=False)

    start_wamp()

    # now start the Flask dev server (which is a regular blocking WSGI server)
    #
    app.run(port=8080)
