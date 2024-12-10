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

import jinja2
from klein import Klein

from twisted.internet.defer import inlineCallbacks
from autobahn.twisted.wamp import Application


# This is our WAMP application
##
wampapp = Application('com.example')


@wampapp.register()
def square(x):
    print("square() called with {}".format(x))
    return x * x


# This is our Web application
##
webapp = Klein()
webapp.visits = 0
webapp.templates = jinja2.Environment(loader=jinja2.FileSystemLoader('templates'))


@webapp.route('/')
def home(request):
    webapp.visits += 1
    wampapp.session.publish('com.example.onvisit', visits=webapp.visits)
    page = webapp.templates.get_template('index.html')
    return page.render(visits=webapp.visits)


@webapp.route('/square/<int:x>')
@inlineCallbacks
def square(request, x):
    result = yield wampapp.session.call('com.example.square', x)
    page = webapp.templates.get_template('result.html')
    return page.render(x=x, result=result)


@webapp.route('/square/submit', methods=['POST'])
def square_submit(request):
    x = int(request.args.get('x', [0])[0])
    return square(request, x)


if __name__ == "__main__":
    import sys
    from twisted.python import log
    from twisted.web.server import Site
    from twisted.internet import reactor
    log.startLogging(sys.stdout)

    reactor.listenTCP(8080, Site(webapp.resource()))
    wampapp.run("ws://127.0.0.1:9000", "realm1", standalone=True)
