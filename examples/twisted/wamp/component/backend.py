

from autobahn.twisted.component import Component, run
from autobahn.twisted.util import sleep
from autobahn.wamp.types import RegisterOptions
from twisted.internet.defer import inlineCallbacks
from twisted.internet._sslverify import OpenSSLCertificateAuthorities
from twisted.internet.ssl import CertificateOptions
from twisted.internet.ssl import optionsForClientTLS, Certificate
from OpenSSL import crypto
from os.path import join, split


examples_dir = join(split(__file__)[0], '..', '..', '..')
cert_fname = join(examples_dir, 'router', '.crossbar', 'server.crt')
if False:
    cert = crypto.load_certificate(
        crypto.FILETYPE_PEM,
        open(cert_fname, 'r').read()
    )
    # tell Twisted to use just the one certificate we loaded to verify connections
    options = CertificateOptions(
        trustRoot=OpenSSLCertificateAuthorities([cert]),
    )
else:
    cert = Certificate.loadPEM(open(cert_fname, 'r').read())
    options = optionsForClientTLS(
        hostname='localhost',
        trustRoot=cert,
    )

component = Component(
    transports=[
        {
            "type": "websocket",
            "url": "ws://localhost:8080/ws",
            "endpoint": {
                "type": "tcp",
                "host": "localhost",
                "port": 8080,
#                "tls": options,
#                "tls": {
#                    "hostname": "localhost",
#                    "trust_root": cert_fname,
#                },
            },
            "options": {
                "open_handshake_timeout": 100,
            }
        },
    ],
    realm="crossbardemo",
)


@component.on_join
def join(session, details):
    print("joined {}: {}".format(session, details))
    # if you want full trackbacks on the client-side, you enable that
    # here:
    # session.traceback_app = True


@component.register(
    "example.foo",
    options=RegisterOptions(details_arg='details'),
)
@inlineCallbacks
def foo(*args, **kw):
    # raise RuntimeError("bad stuff")
    print("foo({}, {})".format(args, kw))
    for x in range(5, 0, -1):
        print("  returning in {}".format(x))
        yield sleep(1)
    print("returning '42'")
    return 42


if __name__ == "__main__":
    run([component])
