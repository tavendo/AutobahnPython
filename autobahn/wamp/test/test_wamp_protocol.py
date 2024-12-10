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
import unittest.mock as mock

if os.environ.get('USE_TWISTED', False):

    from twisted.internet.defer import inlineCallbacks, Deferred
    from twisted.internet.defer import succeed, fail, DeferredList
    from twisted.trial import unittest
    import twisted

    from autobahn import util
    from autobahn.twisted.wamp import ApplicationSession
    from autobahn.twisted.wamp import Session
    from autobahn.wamp import message, role, serializer, types, uri, CloseDetails
    from autobahn.wamp.request import CallRequest
    from autobahn.wamp.exception import ApplicationError, NotAuthorized
    from autobahn.wamp.exception import InvalidUri, ProtocolError
    from autobahn.wamp.auth import create_authenticator
    from autobahn.wamp.interfaces import IAuthenticator
    from autobahn.wamp.types import TransportDetails

    class MockTransport(object):

        def __init__(self, handler):
            self._log = False
            self._handler = handler
            self._serializer = serializer.JsonSerializer()
            self._registrations = {}
            self._invocations = {}
            #: str -> ID
            self._subscription_topics = {}

            self._handler.onOpen(self)

            self._my_session_id = util.id()

            roles = {'broker': role.RoleBrokerFeatures(), 'dealer': role.RoleDealerFeatures()}

            msg = message.Welcome(self._my_session_id, roles)
            self._handler.onMessage(msg)
            self._fake_router_session = ApplicationSession()

            self._transport_details = TransportDetails()

        def transport_details(self):
            return self._transport_details

        def drop_registration(self, reg_id):
            self._handler.onMessage(
                message.Unregistered(0, reg_id)
            )

        def send(self, msg):
            if self._log:
                payload, isbinary = self._serializer.serialize(msg)
                print("Send: {0}".format(payload))

            reply = None

            if isinstance(msg, message.Publish):
                if msg.topic.startswith('com.myapp'):
                    if msg.acknowledge:
                        reply = message.Published(msg.request, self._fake_router_session._request_id_gen.next())
                elif len(msg.topic) == 0:
                    reply = message.Error(message.Publish.MESSAGE_TYPE, msg.request, 'wamp.error.invalid_uri')
                elif msg.topic.startswith('noreply.'):
                    pass
                else:
                    reply = message.Error(message.Publish.MESSAGE_TYPE, msg.request, 'wamp.error.not_authorized')

            elif isinstance(msg, message.Call):
                if msg.procedure == 'com.myapp.procedure1':
                    reply = message.Result(msg.request, args=[100])
                elif msg.procedure == 'com.myapp.procedure2':
                    reply = message.Result(msg.request, args=[1, 2, 3])
                elif msg.procedure == 'com.myapp.procedure3':
                    reply = message.Result(msg.request, args=[1, 2, 3], kwargs={'foo': 'bar', 'baz': 23})

                elif msg.procedure.startswith('com.myapp.myproc'):
                    registration = self._registrations[msg.procedure]
                    request = self._fake_router_session._request_id_gen.next()
                    if request in self._invocations:
                        raise ProtocolError("duplicate invocation")
                    self._invocations[request] = msg.request
                    reply = message.Invocation(
                        request, registration,
                        args=msg.args,
                        kwargs=msg.kwargs,
                        receive_progress=msg.receive_progress,
                    )
                else:
                    reply = message.Error(message.Call.MESSAGE_TYPE, msg.request, 'wamp.error.no_such_procedure')

            elif isinstance(msg, message.Yield):
                if msg.request in self._invocations:
                    request = self._invocations[msg.request]
                    reply = message.Result(request, args=msg.args, kwargs=msg.kwargs, progress=msg.progress)

            elif isinstance(msg, message.Subscribe):
                topic = msg.topic
                if topic in self._subscription_topics:
                    reply_id = self._subscription_topics[topic]
                else:
                    reply_id = self._fake_router_session._request_id_gen.next()
                    self._subscription_topics[topic] = reply_id
                reply = message.Subscribed(msg.request, reply_id)

            elif isinstance(msg, message.Unsubscribe):
                reply = message.Unsubscribed(msg.request)

            elif isinstance(msg, message.Register):
                registration = self._fake_router_session._request_id_gen.next()
                self._registrations[msg.procedure] = registration
                reply = message.Registered(msg.request, registration)

            elif isinstance(msg, message.Unregister):
                reply = message.Unregistered(msg.request)

            elif isinstance(msg, message.Error):
                # since I'm basically a Dealer, I forward on the
                # error, but reply to my own request/invocation
                request = self._invocations[msg.request]
                reply = message.Error(
                    message.Call.MESSAGE_TYPE,
                    request,
                    msg.error,
                    args=msg.args,
                    kwargs=msg.kwargs,
                )

            if reply:
                if self._log:
                    payload, isbinary = self._serializer.serialize(reply)
                    print("Receive: {0}".format(payload))
                self._handler.onMessage(reply)

        def isOpen(self):
            return True

        def close(self):
            pass

        def abort(self):
            pass

    class TestClose(unittest.TestCase):
        def test_server_abort(self):
            handler = ApplicationSession()
            MockTransport(handler)

            # this should not raise an exception, but did when this
            # test-case was written
            handler.onClose(False)

        def test_reject_pending(self):
            handler = ApplicationSession()
            MockTransport(handler)

            # This could happen if the task waiting on a request gets cancelled
            deferred = fail(Exception())
            handler._call_reqs[1] = CallRequest(1, 'foo', deferred, {})
            handler.onLeave(CloseDetails())

    class TestRegisterDecorator(unittest.TestCase):

        def test_prefix(self):

            class Prefix(ApplicationSession):

                @uri.register('method_name')
                def some_method(self):
                    pass
            session = Prefix()

            session._transport = mock.Mock()
            session.register(session, prefix="com.example.prefix.")

            # we should have registered one method, with the prefix
            # put in front
            self.assertEqual(1, len(session._transport.mock_calls))
            call = session._transport.mock_calls[0]
            self.assertEqual("send", call[0])
            reg = call.call_list()[0][1][0]
            self.assertEqual("com.example.prefix.method_name", reg.procedure)

        def test_auto_name(self):

            class Magic(ApplicationSession):

                @uri.register(None)
                def some_method(self):
                    pass
            session = Magic()

            session._transport = mock.Mock()
            session.register(session, prefix="com.example.")

            # Should auto-discover name by passing uri=None above
            self.assertEqual(1, len(session._transport.mock_calls))
            call = session._transport.mock_calls[0]
            self.assertEqual("send", call[0])
            reg = call.call_list()[0][1][0]
            self.assertEqual("com.example.some_method", reg.procedure)

    class TestPublisher(unittest.TestCase):

        @inlineCallbacks
        def test_publish(self):
            handler = ApplicationSession()
            MockTransport(handler)

            publication = yield handler.publish('com.myapp.topic1')
            self.assertEqual(publication, None)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3)
            self.assertEqual(publication, None)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3, foo=23, bar='hello')
            self.assertEqual(publication, None)

            publication = yield handler.publish('com.myapp.topic1', options=types.PublishOptions(exclude_me=False))
            self.assertEqual(publication, None)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3, foo=23, bar='hello', options=types.PublishOptions(exclude_me=False, exclude=[100, 200, 300]))
            self.assertEqual(publication, None)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3, foo=23, bar='hello', options=types.PublishOptions(exclude_me=False, exclude=[100, 200, 300], retain=True))
            self.assertEqual(publication, None)

        @inlineCallbacks
        def test_publish_outstanding_errors(self):
            handler = ApplicationSession()
            MockTransport(handler)

            # this publish will "hang" because 'noreply.' URI is
            # handled specially in MockTransport; so this request will
            # be outstanding
            publication = handler.publish(
                'noreply.foo',
                options=types.PublishOptions(acknowledge=True),
            )
            # "leave" the session, which should trigger errbacks on
            # all outstanding requests.
            details = types.CloseDetails(reason='testing', message='how are you?')
            yield handler.onLeave(details)

            # ensure we got our errback
            try:
                yield publication
            except ApplicationError as e:
                self.assertEqual('testing', e.error)
                self.assertEqual('how are you?', e.message)

        @inlineCallbacks
        def test_publish_outstanding_errors_async_errback(self):
            handler = ApplicationSession()
            MockTransport(handler)
            error_d = Deferred()

            # this publish will "hang" because 'noreply.' URI is
            # handled specially in MockTransport; so this request will
            # be outstanding
            publication_d = handler.publish(
                'noreply.foo',
                options=types.PublishOptions(acknowledge=True),
            )
            # further, we add an errback that does some arbitrary async work
            got_errors = []

            def errback(fail):
                got_errors.append(fail)
                return error_d
            publication_d.addErrback(errback)
            # "leave" the session, which should trigger errbacks on
            # all outstanding requests.
            details = types.CloseDetails(reason='testing', message='how are you?')
            handler.onLeave(details)

            # since our errback is async, onLeave should not have
            # completed yet but we should have already failed the
            # publication
            self.assertEqual(1, len(got_errors))
            # ...now let the async errback continue by completing the
            # Deferred we returned in our errback (could be fail or
            # success, shoudln't matter)
            error_d.callback(None)

            # ensure we (now) get our errback
            try:
                yield publication_d
            except ApplicationError as e:
                self.assertEqual('testing', e.error)
                self.assertEqual('how are you?', e.message)

        @inlineCallbacks
        def test_publish_acknowledged(self):
            handler = ApplicationSession()
            MockTransport(handler)

            publication = yield handler.publish('com.myapp.topic1', options=types.PublishOptions(acknowledge=True))
            self.assertTrue(type(publication.id) == int)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3, options=types.PublishOptions(acknowledge=True))
            self.assertTrue(type(publication.id) == int)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3, foo=23, bar='hello', options=types.PublishOptions(acknowledge=True))
            self.assertTrue(type(publication.id) == int)

            publication = yield handler.publish('com.myapp.topic1', options=types.PublishOptions(exclude_me=False, acknowledge=True))
            self.assertTrue(type(publication.id) == int)

            publication = yield handler.publish('com.myapp.topic1', 1, 2, 3, foo=23, bar='hello', options=types.PublishOptions(exclude_me=False, exclude=[100, 200, 300], acknowledge=True))
            self.assertTrue(type(publication.id) == int)

        @inlineCallbacks
        def test_publish_undefined_exception(self):
            handler = ApplicationSession()
            MockTransport(handler)

            options = types.PublishOptions(acknowledge=True)

            yield self.assertFailure(handler.publish('de.myapp.topic1', options=options), ApplicationError)
            yield self.assertFailure(handler.publish('foobar', options=options), ApplicationError)

        @inlineCallbacks
        def test_publish_defined_exception(self):
            handler = ApplicationSession()
            MockTransport(handler)

            options = types.PublishOptions(acknowledge=True)

            handler.define(NotAuthorized)
            yield self.assertFailure(handler.publish('de.myapp.topic1', options=options), NotAuthorized)

            handler.define(InvalidUri)
            yield self.assertFailure(handler.publish('foobar', options=options), NotAuthorized)

        @inlineCallbacks
        def test_call(self):
            handler = ApplicationSession()
            MockTransport(handler)

            res = yield handler.call('com.myapp.procedure1')
            self.assertEqual(res, 100)

            res = yield handler.call('com.myapp.procedure1', 1, 2, 3)
            self.assertEqual(res, 100)

            res = yield handler.call('com.myapp.procedure1', 1, 2, 3, foo=23, bar='hello')
            self.assertEqual(res, 100)

            res = yield handler.call('com.myapp.procedure1', options=types.CallOptions(timeout=10000))
            self.assertEqual(res, 100)

            res = yield handler.call('com.myapp.procedure1', 1, 2, 3, foo=23, bar='hello', options=types.CallOptions(timeout=10000))
            self.assertEqual(res, 100)

        @inlineCallbacks
        def test_call_with_complex_result(self):
            handler = ApplicationSession()
            MockTransport(handler)

            res = yield handler.call('com.myapp.procedure2')
            self.assertIsInstance(res, types.CallResult)
            self.assertEqual(res.results, (1, 2, 3))
            self.assertEqual(res.kwresults, {})

            res = yield handler.call('com.myapp.procedure3')
            self.assertIsInstance(res, types.CallResult)
            self.assertEqual(res.results, (1, 2, 3))
            self.assertEqual(res.kwresults, {'foo': 'bar', 'baz': 23})

        @inlineCallbacks
        def test_subscribe(self):
            handler = ApplicationSession()
            MockTransport(handler)

            def on_event(*args, **kwargs):
                print("got event", args, kwargs)

            subscription = yield handler.subscribe(on_event, 'com.myapp.topic1')
            self.assertTrue(type(subscription.id) == int)

            subscription = yield handler.subscribe(on_event, 'com.myapp.topic1', options=types.SubscribeOptions(match='wildcard'))
            self.assertTrue(type(subscription.id) == int)

            subscription = yield handler.subscribe(on_event, 'com.myapp.topic1', options=types.SubscribeOptions(match='wildcard', get_retained=True))
            self.assertTrue(type(subscription.id) == int)

        @inlineCallbacks
        def test_double_subscribe(self):
            handler = ApplicationSession()
            MockTransport(handler)

            event0 = Deferred()
            event1 = Deferred()

            subscription0 = yield handler.subscribe(
                lambda: event0.callback(42), 'com.myapp.topic1')
            subscription1 = yield handler.subscribe(
                lambda: event1.callback('foo'), 'com.myapp.topic1')
            # same topic, same ID
            self.assertTrue(subscription0.id == subscription1.id)

            # do a publish (MockTransport fakes the acknowledgement
            # message) and then do an actual publish event. The IDs
            # are the same, so we just do one Event.
            publish = yield handler.publish(
                'com.myapp.topic1',
                options=types.PublishOptions(acknowledge=True, exclude_me=False),
            )
            handler.onMessage(message.Event(subscription0.id, publish.id))

            # ensure we actually got both callbacks
            self.assertTrue(event0.called, "Missing callback")
            self.assertTrue(event1.called, "Missing callback")

        @inlineCallbacks
        def test_double_subscribe_single_unsubscribe(self):
            '''
            Make sure we correctly deal with unsubscribing one of our handlers
            from the same topic.
            '''
            handler = ApplicationSession()
            MockTransport(handler)

            # monkey-patch ApplicationSession to ensure we DO NOT get
            # an Unsubscribed message -- since we only unsubscribe
            # from ONE of our handlers for com.myapp.topic1
            def onMessage(msg):
                assert not isinstance(msg, message.Unsubscribed)
                return ApplicationSession.onMessage(handler, msg)

            handler.onMessage = onMessage

            event0 = Deferred()
            event1 = Deferred()

            subscription0 = yield handler.subscribe(
                lambda: event0.callback(42), 'com.myapp.topic1')
            subscription1 = yield handler.subscribe(
                lambda: event1.callback('foo'), 'com.myapp.topic1')

            self.assertTrue(subscription0.id == subscription1.id)
            yield subscription1.unsubscribe()

            # do a publish (MockTransport fakes the acknowledgement
            # message) and then do an actual publish event. Note the
            # IDs are the same, so there's only one Event.
            publish = yield handler.publish(
                'com.myapp.topic1',
                options=types.PublishOptions(acknowledge=True, exclude_me=False),
            )
            handler.onMessage(message.Event(subscription0.id, publish.id))

            # since we unsubscribed the second event handler, we
            # should NOT have called its callback
            self.assertTrue(event0.called, "Missing callback")
            self.assertTrue(not event1.called, "Second callback fired.")

        @inlineCallbacks
        def test_double_subscribe_double_unsubscribe(self):
            '''
            If we subscribe twice, and unsubscribe twice, we should then get
            an Unsubscribed message.
            '''
            handler = ApplicationSession()
            MockTransport(handler)

            # monkey-patch ApplicationSession to ensure we get our message
            unsubscribed_d = Deferred()

            def onMessage(msg):
                if isinstance(msg, message.Unsubscribed):
                    unsubscribed_d.callback(msg)
                return ApplicationSession.onMessage(handler, msg)
            handler.onMessage = onMessage

            event0 = Deferred()
            event1 = Deferred()

            subscription0 = yield handler.subscribe(
                lambda: event0.callback(42), 'com.myapp.topic1')
            subscription1 = yield handler.subscribe(
                lambda: event1.callback('foo'), 'com.myapp.topic1')

            self.assertTrue(subscription0.id == subscription1.id)
            yield subscription0.unsubscribe()
            yield subscription1.unsubscribe()

            # after the second unsubscribe, we should have gotten an
            # Unsubscribed message
            assert unsubscribed_d.called

            # do a publish (MockTransport fakes the acknowledgement
            # message) and then do an actual publish event. Sending
            # the Event should be an error, as we have no
            # subscriptions left.
            publish = yield handler.publish(
                'com.myapp.topic1',
                options=types.PublishOptions(acknowledge=True, exclude_me=False),
            )
            try:
                handler.onMessage(message.Event(subscription0.id, publish.id))
                self.fail("Expected ProtocolError")
            except ProtocolError:
                pass

            # since we unsubscribed the second event handler, we
            # should NOT have called its callback
            self.assertTrue(not event0.called, "First callback fired.")
            self.assertTrue(not event1.called, "Second callback fired.")

        @inlineCallbacks
        def test_double_subscribe_errors(self):
            """
            Test various error-conditions when we try to add a second
            subscription-handler (its signature must match any
            existing handlers).
            """
            handler = ApplicationSession()
            MockTransport(handler)

            event0 = Deferred()
            event1 = Deferred()

            def second(*args, **kw):
                # our EventDetails should have been passed as the
                # "boom" kwarg; see "details_arg=" below
                self.assertTrue('boom' in kw)
                self.assertTrue(isinstance(kw['boom'], types.EventDetails))
                event1.callback(args)

            subscription0 = yield handler.subscribe(
                lambda arg: event0.callback(arg), 'com.myapp.topic1')
            subscription1 = yield handler.subscribe(
                second, 'com.myapp.topic1',
                types.SubscribeOptions(details_arg='boom'),
            )
            # same topic, same ID
            self.assertTrue(subscription0.id == subscription1.id)

            # MockTransport gives us the ack reply and then we do our
            # own event message.
            publish = yield handler.publish(
                'com.myapp.topic1',
                options=types.PublishOptions(acknowledge=True, exclude_me=False),
            )
            # note that the protocol serializer converts all sequences
            # to lists, so we pass "args" as a list, not a tuple on
            # purpose.
            handler.onMessage(
                message.Event(subscription0.id, publish.id, args=['arg0']))

            # each callback should have gotten called, each with its
            # own args (we check the correct kwarg in second() above)
            self.assertTrue(event0.called)
            self.assertTrue(event1.called)
            self.assertEqual(event0.result, 'arg0')
            self.assertEqual(event1.result, ('arg0',))

        @inlineCallbacks
        def test_publish_callback_exception(self):
            """
            Ensure we handle an exception from the user code.
            """
            handler = ApplicationSession()
            MockTransport(handler)

            error_instance = RuntimeError("we have a problem")
            got_err_d = Deferred()

            def observer(e, msg):
                if error_instance == e.value:
                    got_err_d.callback(True)
            handler.onUserError = observer

            def boom():
                raise error_instance

            sub = yield handler.subscribe(boom, 'com.myapp.topic1')

            # MockTransport gives us the ack reply and then we do our
            # own event message
            publish = yield handler.publish(
                'com.myapp.topic1',
                options=types.PublishOptions(acknowledge=True, exclude_me=False),
            )
            msg = message.Event(sub.id, publish.id)
            handler.onMessage(msg)

            # we know it worked if our observer worked and did
            # .callback on our Deferred above.
            self.assertTrue(got_err_d.called)

        @inlineCallbacks
        def test_unsubscribe(self):
            handler = ApplicationSession()
            MockTransport(handler)

            def on_event(*args, **kwargs):
                print("got event", args, kwargs)

            subscription = yield handler.subscribe(on_event, 'com.myapp.topic1')
            yield subscription.unsubscribe()

        @inlineCallbacks
        def test_register(self):
            handler = ApplicationSession()
            MockTransport(handler)

            def on_call(*args, **kwargs):
                print("got call", args, kwargs)

            registration = yield handler.register(on_call, 'com.myapp.procedure1')
            self.assertTrue(type(registration.id) == int)

            registration = yield handler.register(on_call, 'com.myapp.procedure1', options=types.RegisterOptions(match='prefix'))
            self.assertTrue(type(registration.id) == int)

        @inlineCallbacks
        def test_unregister(self):
            handler = ApplicationSession()
            MockTransport(handler)

            def on_call(*args, **kwargs):
                print("got call", args, kwargs)

            registration = yield handler.register(on_call, 'com.myapp.procedure1')
            yield registration.unregister()

        def test_unregister_no_such_registration(self):
            if twisted.version.major < 14:
                return
            handler = ApplicationSession()
            transport = MockTransport(handler)

            with self.assertRaises(ProtocolError) as ctx:
                transport.send(
                    message.Unregister(0, 1234)
                )
            self.assertIn(
                "UNREGISTERED received for non-existant registration",
                str(ctx.exception)
            )

        @inlineCallbacks
        def test_unregister_log(self):
            handler = ApplicationSession()
            transport = MockTransport(handler)

            def on_call(*args, **kwargs):
                on_call.called = True
            on_call.called = False

            registration = yield handler.register(on_call, 'com.myapp.procedure1')
            transport.drop_registration(registration.id)
            self.assertFalse(on_call.called)

        def test_on_disconnect_error(self):
            errors = []

            class AppSess(ApplicationSession):
                def onUserError(self, e, msg):
                    errors.append((e.value, msg))

                def onDisconnect(self, foo, bar, quux='snark'):
                    # this over-ridden onDisconnect takes the wrong args
                    raise RuntimeError("This shouldn't happen")

            s = AppSess()
            MockTransport(s)

            # when the transport closes, it calls onClose which should
            # dispatch onDisconnect
            s.onClose(False)

            # ...but we should collect an error, because our
            # onDisconnect takes the wrong arguments.
            self.assertEqual(len(errors), 1)
            self.assertTrue(isinstance(errors[0][0], TypeError))

    class TestInvoker(unittest.TestCase):
        @inlineCallbacks
        def test_invoke(self):
            handler = ApplicationSession()
            MockTransport(handler)

            def myproc1():
                return 23

            yield handler.register(myproc1, 'com.myapp.myproc1')

            res = yield handler.call('com.myapp.myproc1')
            self.assertEqual(res, 23)

        @inlineCallbacks
        def test_invoke_twice(self):
            handler = ApplicationSession()
            MockTransport(handler)

            def myproc1():
                return 23

            yield handler.register(myproc1, 'com.myapp.myproc1')

            d0 = handler.call('com.myapp.myproc1')
            d1 = handler.call('com.myapp.myproc1')
            res = yield DeferredList([d0, d1])
            self.assertEqual(res, [(True, 23), (True, 23)])

        @inlineCallbacks
        def test_invoke_request_id_sequences(self):
            """
            make sure each session independently generates sequential IDs
            """
            handler0 = ApplicationSession()
            handler1 = ApplicationSession()
            trans0 = MockTransport(handler0)
            trans1 = MockTransport(handler1)

            # the ID sequences for each session should both start at 0
            # (the register) and then increment for the call()
            def verify_seq_id(orig, msg):
                if isinstance(msg, message.Register):
                    self.assertEqual(msg.request, 1)
                elif isinstance(msg, message.Call):
                    self.assertEqual(msg.request, 2)
                return orig(msg)
            orig0 = trans0.send
            orig1 = trans1.send
            trans0.send = lambda msg: verify_seq_id(orig0, msg)
            trans1.send = lambda msg: verify_seq_id(orig1, msg)

            def myproc1():
                return 23

            yield handler0.register(myproc1, 'com.myapp.myproc1')
            yield handler1.register(myproc1, 'com.myapp.myproc1')

            d0 = handler0.call('com.myapp.myproc1')
            d1 = handler1.call('com.myapp.myproc1')
            res = yield DeferredList([d0, d1])
            self.assertEqual(res, [(True, 23), (True, 23)])

        @inlineCallbacks
        def test_invoke_user_raises(self):
            handler = ApplicationSession()
            handler.traceback_app = True
            MockTransport(handler)
            errors = []

            def log_error(e, msg):
                errors.append((e.value, msg))
            handler.onUserError = log_error

            name_error = NameError('foo')

            def bing():
                raise name_error

            # see MockTransport, must start with "com.myapp.myproc"
            yield handler.register(bing, 'com.myapp.myproc99')

            try:
                yield handler.call('com.myapp.myproc99')
                self.fail("Expected an error")
            except Exception as e:
                # XXX should/could we export all the builtin types?
                # right now, we always get ApplicationError
                # self.assertTrue(isinstance(e, NameError))
                self.assertTrue(isinstance(e, RuntimeError))

            # also, we should have logged the real NameError to
            # Twisted.
            self.assertEqual(1, len(errors))
            self.assertEqual(name_error, errors[0][0])

        @inlineCallbacks
        def test_invoke_progressive_result(self):
            handler = ApplicationSession()
            MockTransport(handler)

            @inlineCallbacks
            def bing(details=None):
                self.assertTrue(details is not None)
                self.assertTrue(details.progress is not None)
                for i in range(10):
                    details.progress(i)
                    yield succeed(i)
                return 42

            progressive = list(map(lambda _: Deferred(), range(10)))

            def progress(arg):
                progressive[arg].callback(arg)

            # see MockTransport, must start with "com.myapp.myproc"
            yield handler.register(
                bing,
                'com.myapp.myproc2',
                types.RegisterOptions(details_arg='details'),
            )
            res = yield handler.call(
                'com.myapp.myproc2',
                options=types.CallOptions(on_progress=progress),
            )
            self.assertEqual(42, res)
            # make sure we got *all* our progressive results
            for i in range(10):
                self.assertTrue(progressive[i].called)
                self.assertEqual(i, progressive[i].result)

        @inlineCallbacks
        def test_invoke_progressive_result_error(self):
            handler = ApplicationSession()
            MockTransport(handler)

            @inlineCallbacks
            def bing(arg, details=None, key=None):
                self.assertTrue(details is not None)
                self.assertTrue(details.progress is not None)
                self.assertEqual(key, 'word')
                self.assertEqual('arg', arg)
                details.progress('life', something='nothing')
                yield succeed('meaning of')
                return 42

            got_progress = Deferred()
            progress_error = NameError('foo')
            logged_errors = []

            def got_error(e, msg):
                logged_errors.append((e.value, msg))
            handler.onUserError = got_error

            def progress(arg, something=None):
                self.assertEqual('nothing', something)
                got_progress.callback(arg)
                raise progress_error

            # see MockTransport, must start with "com.myapp.myproc"
            yield handler.register(
                bing,
                'com.myapp.myproc2',
                types.RegisterOptions(details_arg='details'),
            )

            res = yield handler.call(
                'com.myapp.myproc2',
                'arg',
                options=types.CallOptions(on_progress=progress),
                key='word',
            )

            self.assertEqual(42, res)
            # our progress handler raised an error, but not before
            # recording success.
            self.assertTrue(got_progress.called)
            self.assertEqual('life', got_progress.result)
            # make sure our progress-handler error was logged
            self.assertEqual(1, len(logged_errors))
            self.assertEqual(progress_error, logged_errors[0][0])

        @inlineCallbacks
        def test_invoke_progressive_result_no_args(self):
            handler = ApplicationSession()
            MockTransport(handler)

            @inlineCallbacks
            def bing(details=None):
                self.assertTrue(details is not None)
                self.assertTrue(details.progress is not None)
                details.progress()
                yield succeed(True)
                return 42

            got_progress = Deferred()

            def progress():
                got_progress.callback('intentionally left blank')

            # see MockTransport, must start with "com.myapp.myproc"
            yield handler.register(
                bing,
                'com.myapp.myproc2',
                types.RegisterOptions(details_arg='details'),
            )

            res = yield handler.call(
                'com.myapp.myproc2',
                options=types.CallOptions(on_progress=progress),
            )
            self.assertEqual(42, res)
            self.assertTrue(got_progress.called)

        @inlineCallbacks
        def test_invoke_progressive_result_just_kwargs(self):
            handler = ApplicationSession()
            MockTransport(handler)

            @inlineCallbacks
            def bing(details=None):
                self.assertTrue(details is not None)
                self.assertTrue(details.progress is not None)
                details.progress(key='word')
                yield succeed(True)
                return 42

            got_progress = Deferred()

            def progress(key=None):
                got_progress.callback(key)

            # see MockTransport, must start with "com.myapp.myproc"
            yield handler.register(
                bing,
                'com.myapp.myproc2',
                types.RegisterOptions(details_arg='details'),
            )

            res = yield handler.call(
                'com.myapp.myproc2',
                options=types.CallOptions(on_progress=progress),
            )
            self.assertEqual(42, res)
            self.assertTrue(got_progress.called)
            self.assertEqual('word', got_progress.result)

        @inlineCallbacks
        def test_call_exception_runtimeerror(self):
            handler = ApplicationSession()
            MockTransport(handler)
            exception = RuntimeError("a simple error")

            def raiser():
                raise exception

            registration0 = yield handler.register(raiser, "com.myapp.myproc_error")
            try:
                yield handler.call('com.myapp.myproc_error')
                self.fail()
            except Exception as e:
                self.assertIsInstance(e, ApplicationError)
                self.assertEqual(e.error_message(), "wamp.error.runtime_error: a simple error")
            finally:
                yield registration0.unregister()

        @inlineCallbacks
        def test_call_exception_bare(self):
            handler = ApplicationSession()
            MockTransport(handler)
            exception = Exception()

            def raiser():
                raise exception

            registration0 = yield handler.register(raiser, "com.myapp.myproc_error")
            try:
                yield handler.call('com.myapp.myproc_error')
                self.fail()
            except Exception as e:
                self.assertIsInstance(e, ApplicationError)
            finally:
                yield registration0.unregister()

        # ## variant 1: works
        # def test_publish1(self):
        #    d = self.handler.publish('de.myapp.topic1')
        #    self.assertFailure(d, ApplicationError)

        # ## variant 2: works
        # @inlineCallbacks
        # def test_publish2(self):
        #    yield self.assertFailure(self.handler.publish('de.myapp.topic1'), ApplicationError)

        # ## variant 3: does NOT work
        # @inlineCallbacks
        # def test_publish3(self):
        #    with self.assertRaises(ApplicationError):
        #       yield self.handler.publish('de.myapp.topic1')

    class TestAuthenticator(unittest.TestCase):

        def test_inconsistent_authids(self):
            session = Session(mock.Mock())
            auth0 = create_authenticator(
                "wampcra",
                authid="alice",
                secret="p4ssw0rd",
            )
            auth1 = create_authenticator(
                "wampcra",
                authid="bob",
                secret="password42",
            )

            session.add_authenticator(auth0)
            with self.assertRaises(ValueError) as ctx:
                session.add_authenticator(auth1)
            assert "authids" in str(ctx.exception)

        def test_two_authenticators(self):
            session = Session(mock.Mock())

            class TestAuthenticator(IAuthenticator):

                name = "test"

                def on_challenge(self, session, challenge):
                    raise NotImplementedError

                def on_welcome(self, authextra):
                    raise NotImplementedError

            auth0 = TestAuthenticator()
            auth0.authextra = {
                "foo": "value0",
                "bar": "value1",
            }
            auth0._args = {}

            auth1 = TestAuthenticator()
            auth1.authextra = {
                "bar": "value1",
                "qux": "what",
            }
            auth1._args = {}

            session.add_authenticator(auth0)
            session.add_authenticator(auth1)

        def test_inconsistent_authextra(self):
            session = Session(mock.Mock())

            class TestAuthenticator(IAuthenticator):

                name = "test"

                def on_challenge(self, session, challenge):
                    raise NotImplementedError

                def on_welcome(self, authextra):
                    raise NotImplementedError

            auth0 = TestAuthenticator()
            auth0.authextra = {
                "foo": "value0",
                "bar": "value1",
            }
            auth0._args = {}

            auth1 = TestAuthenticator()
            auth1.authextra = {
                "foo": "value1",
            }
            auth1._args = {}

            session.add_authenticator(auth0)
            with self.assertRaises(ValueError) as ctx:
                session.add_authenticator(auth1)
            self.assertIn("Inconsistent authextra", str(ctx.exception))
