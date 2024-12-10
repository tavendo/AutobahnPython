WAMP Application
================

Introduction
------------

Flask-like syntaxe for WAMP projects.

This is intended to make it easier to start with autobahn/crossbar.io
and abstract a lot of things : you don't have to think about the main
loop, the application session class lifecycle, etc.

It lets you react, using callback defined via decorators, to 3 things :
   - PUB/SUB events : regular WAMP PUB/SUB events.
   - RPC calls : expose a function as callable from the outside.
   - app signals : internal app events allowing you to react to the app
                   lifecycle.

:Example:

.. code-block:: python

   from autobahn.twisted.wamp import Application
   from autobahn.wamp.types import PublishOptions

   app = Application()

   # Register a function to allow calling it from outside
   # via RPC
   @app.register('a_procedure_name')
   def a_procedure(arg1, arg2):
      print('The procedure is called with these arguments :')
      print(arg1, arg2)
      # publish the event
      app.session.publish('an_event',
                          "Some data attached to the event",
                          # force publisher to receive its
                          # own event
                          options=PublishOptions(excludeMe=False))

   # Register a callback that will be called when the
   # event 'an_event' is triggered
   @app.subscribe('an_event')
   def an_event(val):
      print('Received an event with something :')
      print(val)

   # This will be called once the application is connected
   # to the server
   @app.signal('onjoin')
   def entry_point():
      print('The application is connected !')
      # Calling a_procedure()
      app.session.call('a_procedure_name', True, False)

   if __name__ == "__main__":
      # By default, the application run on port 8080
      print('Before the app start')
      app.run()


# Now, in a Terminal:

.. code-block:: console

   $ python script.py
   Running on 'ws://localhost:8080'
   Before the app start
   The application is connected !
   The procedure is called with these arguments :
   (True, False)
   Received an event with something :
   Some data attached to the event

Ok, this example is cheating a little bit because the application triggers
events and listen to them, and it calls it's own code via RPC. You may want
to call them from a Web page using autobahn.js (http://crossbar.io/autobahn#js) for
a more convincing demo.

If you use "yield" inside any of the callbacks, `@inlineCallbacks` will
be applied automatically. It means every yielded line will be be added in
a Deferred so they execute sequentially, in regards to the other yielded
lines in the same function.

:Example:

.. code-block:: python

   from autobahn.twisted.wamp import Application

   from twisted.web.client import Agent

   app = Application()

   @app.register('statuscode')
   def statuscode(url):
      ''' Return the status code of a GET request on a URL '''

      # Little hack to add asynchronous requests to our app
      # It's not very clean, but for the example, it will do :)
      from twisted.internet import reactor
      agent = Agent(reactor)

      # Asynchronous GET request on the url
      d = yield agent.request('GET', url)

      return d.code

   @app.signal('onjoin')
   def entry_point():
      # Calling statuscode
      url = "http://crossbar.io"
      code = yield app.session.call('statuscode', url)
      print("GET on '%s' returned status '%s'" % (url, code))

   if __name__ == "__main__":
       app.run()


Now, in a Terminal:

.. code-block:: console

   $ python script.py
   Running on 'ws://localhost:8080'
   GET on 'http://crossbar.io' returned status '200'
