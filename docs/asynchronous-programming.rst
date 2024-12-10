.. _async_programming:

Asynchronous Programming
========================

Introduction
------------

The asynchronous programming approach
.....................................

|Ab| is written according to a programming paradigm called *asynchronous programming* (or *event driven programming*) and implemented using *non-blocking* execution - and both go hand in hand.

A very good technical introduction to these concepts can be found in `this chapter <http://krondo.com/?p=1209>`_ of an "Introduction to Asynchronous Programming and Twisted".

Here are two more presentations that introduce event-driven programming in Python

* `Alex Martelli - Don't call us, we'll call you: callback patterns and idioms <https://www.youtube.com/watch?v=LCZRJStwkKM>`_
* `Glyph Lefkowitz - So Easy You Can Even Do It in JavaScript: Event-Driven Architecture for Regular Programmers <http://www.pyvideo.org/video/1681/so-easy-you-can-even-do-it-in-javascript-event-d>`_

Another highly recommended reading is `The Reactive Manifesto <http://www.reactivemanifesto.org>`_ which describes guiding principles, motivations and connects the dots

.. epigraph::

   Non-blocking means the ability to make continuous progress in order for the application to be responsive at all times, even under failure and burst scenarios. For this all resources needed for a response—for example CPU, memory and network—must not be monopolized. As such it can enable both lower latency, higher throughput and better scalability.

   -- `The Reactive Manifesto <http://www.reactivemanifesto.org>`_

The fact that |Ab| is implemented using asynchronous programming and non-blocking execution shouldn't come as a surprise, since both `Twisted <https://twistedmatrix.com/trac/>`__ and `asyncio <https://docs.python.org/3/library/asyncio.html>`__ - the foundations upon which |ab| runs - are *asynchronous network programming frameworks*.

On the other hand, the principles of asynchronous programming are independent of Twisted and asyncio. For example, other frameworks that fall into the same category are:

* `NodeJS <http://nodejs.org/>`_
* `Boost/ASIO <http://think-async.com/>`_
* `Netty <http://netty.io/>`_
* `Tornado <http://www.tornadoweb.org/>`_
* `React <http://reactphp.org/>`_

.. tip::
   While getting accustomed to the asynchronous way of thinking takes some time and effort, the knowledge and experience acquired can be translated more or less directly to other frameworks in the asynchronous category.


Other forms of Concurrency
..........................

Asynchronous programming is not the only approach to concurrency. Other styles of concurrency include

1. `OS Threads <http://en.wikipedia.org/wiki/Thread_%28computing%29>`_
2. `Green Threads <http://en.wikipedia.org/wiki/Green_threads>`_
3. `Actors <http://en.wikipedia.org/wiki/Actor_model>`_
4. `Software Transactional Memory (STM) <http://en.wikipedia.org/wiki/Software_transactional_memory>`_

Obviously, we cannot go into much detail with all of above. But here are some pointers for further reading if you want to compare and contrast asynchronous programming with other approaches.

With the **Actor model** a system is composed of a set of *actors* which are independently running, executing sequentially and communicate strictly by message passing. There is no shared state at all. This approach is used in systems like

* `Erlang <http://www.erlang.org/>`_
* `Akka <http://akka.io/>`_
* `Rust <http://www.rust-lang.org/>`_
* `C++ Actor Framework <http://actor-framework.org/>`_

**Software Transactional Memory (STM)** applies the concept of `Optimistic Concurrency Control <http://en.wikipedia.org/wiki/Optimistic_concurrency_control>`_ from the persistent database world to (transient) program memory. Instead of lettings programs directly modify memory, all operations are first logged (inside a transaction), and then applied atomically - but only if no conflicting transaction has committed in the meantime. Hence, it's "optimistic" in that it assumes to be able to commit "normally", but needs to handle the failing at commit time.

**Green Threads** is using light-weight, run-time level threads and thread scheduling instead of OS threads. Other than that, systems are implemented similar: green threads still block, and still do share state. Python has multiple efforts in this category:

* `Eventlet <http://eventlet.net/>`_
* `Gevent <http://gevent.org/>`_
* `Stackless <http://www.stackless.com/>`_


Twisted or asyncio?
...................

Since |Ab| runs on both Twisted and asyncio, which networking framework should you use?

Even more so, as the core of Twisted and asyncio is very similar and relies on the same concepts:

+------------------+------------------+-------------------------------------------------------------+
| Twisted          | asyncio          | Description                                                 |
+------------------+------------------+-------------------------------------------------------------+
| Deferred         | Future           | abstraction of a value which isn't available yet            |
+------------------+------------------+-------------------------------------------------------------+
| Reactor          | Event Loop       | waits for and dispatches events                             |
+------------------+------------------+-------------------------------------------------------------+
| Transport        | Transport        | abstraction of a communication channel (stream or datagram) |
+------------------+------------------+-------------------------------------------------------------+
| Protocol         | Protocol         | this is where actual networking protocols are implemented   |
+------------------+------------------+-------------------------------------------------------------+
| Protocol Factory | Protocol Factory | responsible for creating protocol instances                 |
+------------------+------------------+-------------------------------------------------------------+

In fact, I'd say the biggest difference between Twisted and asyncio is ``Deferred`` vs ``Future``. Although similar on surface, their semantics are different. ``Deferred`` supports the concept of chainable callbacks (which can mutate the return values), and separate error-backs (which can cancel errors). ``Future`` has just a callback, that always gets a single argument: the Future.

Also, asyncio is opinionated towards co-routines. This means idiomatic user code for asyncio is expected to use co-routines, and not plain Futures (which are considered too low-level for application code).

But anyway, with asyncio being part of the language standard library (since Python 3.4), wouldn't you just *always* use asyncio? At least if you don't have a need to support already existing Twisted based code.

The truth is that while the *core* of Twisted and asyncio are very similar, **Twisted has a much broader scope: Twisted is "batteries included" for network programming.**

So you get *tons* of actual network protocols already out-of-the-box - in production quality implementations!

asyncio does not include any actual application layer network protocols like HTTP. If you need those, you'll have to look for asyncio implementations *outside* the standard library. For example, `here <https://github.com/KeepSafe/aiohttp>`__ is a HTTP server and client library for asyncio.

Over time, an ecosystem of protocols will likely emerge around asyncio also. But right now, Twisted has a big advantage here.

If you want to read more on this, Glyph (Twisted original author) has a nice blog post `here <https://glyph.twistedmatrix.com/2014/05/the-report-of-our-death.html>`__.


Resources
---------

Below we are listing a couple of resources on the Web for Twisted and asyncio that you may find useful.


Twisted Resources
.................

We cannot give an introduction to asynchronous programming with Twisted here. And there is no need to, since there is lots of great stuff on the Web. In particular we'd like to recommend the following resources.

If you have limited time and nevertheless want to have an in-depth view of Twisted, Jessica McKellar has a great presentation recording with `Architecting an event-driven networking engine: Twisted Python <https://www.youtube.com/watch?v=3R4gP6Egh5M>`_. That's 45 minutes. Highly recommended.

If you really want to get it, Dave Peticolas has written an awesome `Introduction to Asynchronous Programming and Twisted <http://krondo.com/?page_id=1327>`_. This is a detailed, hands-on tutorial with lots of code examples that will take some time to work through - but you actually *learn* how to program with Twisted.

Then of course there is

* `The Twisted Documentation <https://twisted.readthedocs.org/>`_
* `The Twisted API Reference <https://twistedmatrix.com/documents/current/api/>`_

and lots and lots of awesome `Twisted talks <http://www.pyvideo.org/search?models=videos.video&q=twisted>`__ on PyVideo.


Asyncio Resources
.................

asyncio is very new (August 2014). So the amount of material on the Web is still limited. Here are some resources you may find useful:

* `Guido van Rossum's Keynote at PyCon US 2013 <http://pyvideo.org/video/1667/keynote-1>`_
* `Tulip: Async I/O for Python 3 <http://www.youtube.com/watch?v=1coLC-MUCJc>`_
* `Python 3.4 docs - asyncio <http://docs.python.org/3.4/library/asyncio.html>`_
* `PEP-3156 - Asynchronous IO Support Rebooted <http://www.python.org/dev/peps/pep-3156/>`_
* `OSB 2015 - How Do Python Coroutines Work? - A. Jesse Jiryu Davis <http://www.youtube.com/watch?v=GSk0tIjDT10>`_

However, we quickly introduce core asynchronous programming primitives provided by `Twisted <https://twistedmatrix.com/>`__ and `asyncio <https://docs.python.org/3.4/library/asyncio.html>`__:


Asynchronous Programming Primitives
-----------------------------------

In this section, we have a quick look at some of the asynchronous programming primitive provided by Twisted and asyncio to show similarities and differences.


Twisted Deferreds and inlineCallbacks
.....................................

Documentation pointers:

* `Introduction to Deferreds <https://twisted.readthedocs.org/en/latest/core/howto/defer-intro.html>`__
* `Deferreds Reference <https://twisted.readthedocs.org/en/latest/core/howto/defer.html>`__
* `Twisted inlineCallbacks <http://twistedmatrix.com/documents/current/api/twisted.internet.defer.html#inlineCallbacks>`__

Programming with Twisted Deferreds involves attaching *callbacks* to Deferreds which get called when the Deferred finally either resolves successfully or fails with an error

.. code-block:: python

   d = some_function() # returns a Twisted Deferred ..

   def on_success(res):
      print("result: {}".format(res))

   def on_error(err):
      print("error: {}".format(err))

   d.addCallbacks(on_success, on_error)


Using Deferreds offers the greatest flexibility since you are able to pass around Deferreds freely and can run code concurrently.

However, using plain Deferreds comes at a price: code in this style looks very different from synchronous/blocking code and the code can become hard to follow.

Now, `Twisted inlineCallbacks <http://twistedmatrix.com/documents/current/api/twisted.internet.defer.html#inlineCallbacks>`__ let you write code in a sequential looking manner that nevertheless executes asynchronously and non-blocking under the hood.

So converting above snipped to ``inlineCallbacks`` the code will look like

.. code-block:: python

   try:
      res = yield some_function()
      print("result: {}".format(res))
   except Exception as err:
      print("error: {}".format(err))

As you can see, this code looks very similar to regular synchronous/blocking Python code. The only difference (on surface) is the use of ``yield`` when calling a function that runs asynchronously. Otherwise, you process success result values and exceptions exactly as with regular code.

.. note::
   We'll only show basic usage here - for a more basic and complete introduction, please have a look at `this chapter <http://krondo.com/?p=2441>`__ from `this tutorial <http://krondo.com/?page_id=1327>`__.

--------

**Example**

The following demonstrates basic usage of ``inlineCallbacks`` in a complete example you can run.

First, consider this program using Deferreds. We simulate calling a slow function by sleeping (without blocking) inside the function ``slow_square``

.. code-block:: python
   :linenos:
   :emphasize-lines: 5,7,8,10,11

   from twisted.internet import reactor
   from twisted.internet.defer import Deferred

   def slow_square(x):
      d = Deferred()

      def resolve():
         d.callback(x * x)

      reactor.callLater(1, resolve)
      return d

   def test():
      d = slow_square(3)

      def on_success(res):
         print(res)
         reactor.stop()

      d.addCallback(on_success)

   test()
   reactor.run()

This is just regular Twisted code - nothing exciting here:

1. We create a ``Deferred`` to be returned by our ``slow_square`` function (line 5)
2. We create a function ``resolve`` (a closure) in which we resolve the previously created Deferred with the result (lines 7-8)
3. Then we ask the Twisted reactor to call ``resolve`` after 1 second (line 10)
4. And we return the previously created Deferred to the caller (line 11)

What you can see even with this trivial example already is that the code looks quite differently from synchronous/blocking code. It needs some practice until such code becomes natural to read.

Now, when converted to ``inlineCallbacks``, the code becomes:

.. code-block:: python
   :linenos:
   :emphasize-lines: 5,7,8

   from twisted.internet import reactor
   from twisted.internet.defer import inlineCallbacks
   from autobahn.twisted.util import sleep

   @inlineCallbacks
   def slow_square(x):
      yield sleep(1)
      return x * x

   @inlineCallbacks
   def test():
      res = yield slow_square(3)
      print(res)
      reactor.stop()

   test()
   reactor.run()


Have a look at the highlighted lines - here is what we do:

1. Decorating our squaring function with ``inlineCallbacks`` (line 5). Doing so marks the function as a coroutine which allows us to use this sequential looking coding style.
2. Inside the function, we simulate the slow execution by sleeping for a second (line 7). However, we are sleeping in a non-blocking way (``autobahn.twisted.util.sleep``). The ``yield`` will put the coroutine aside until the sleep returns.

In above, we are using a little helper ``autobahn.twisted.util.sleep`` for sleeping "inline". The helper is really trivial:

.. code-block:: python

   from twisted.internet import reactor
   from twisted.internet.defer import Deferred

   def sleep(delay):
      d = Deferred()
      reactor.callLater(delay, d.callback, None)
      return d

The rest of the program is just for driving our test function and running a Twisted reactor.



Asyncio Futures and Coroutines
..............................


`Asyncio Futures <http://docs.python.org/3.4/library/asyncio-task.html#future>`__ like Twisted Deferreds encapsulate the result of a future computation. At the time of creation, the result is (usually) not yet available, and will only be available eventually.

On the other hand, asyncio futures are quite different from Twisted Deferreds. One difference is that they have no built-in machinery for chaining.

`Asyncio Coroutines <http://docs.python.org/3.5/library/asyncio-task.html#coroutines>`__ are (on a certain level) quite similar to Twisted inline callbacks. Here is the code corresponding to our example above:


-------

**Example**

The following demonstrates basic usage of ``asyncio.coroutine`` in a complete example you can run.

First, consider this program using plain ``asyncio.Future``. We simulate calling a slow function by sleeping (without blocking) inside the function ``slow_square``

.. code-block:: python
   :linenos:
   :emphasize-lines: 4,6-7,10,12

   import asyncio

   def slow_square(x):
      f = asyncio.Future()

      def resolve():
         f.set_result(x * x)

      loop = asyncio.get_event_loop()
      loop.call_later(1, resolve)

      return f

   def test():
      f = slow_square(3)

      def done(f):
         res = f.result()
         print(res)

      f.add_done_callback(done)

      return f

   loop = asyncio.get_event_loop()
   loop.run_until_complete(test())
   loop.close()

Using asyncio in this way is probably quite unusual. This is because asyncio is opinionated towards using coroutines from the beginning. Anyway, here is what above code does:

1. We create a ``Future`` to be returned by our ``slow_square`` function (line 4)
2. We create a function ``resolve`` (a closure) in which we resolve the previously created Future with the result (lines 6-7)
3. Then we ask the asyncio event loop to call ``resolve`` after 1 second (line 10)
4. And we return the previously created Future to the caller (line 12)


What you can see even with this trivial example already is that the code looks quite differently from synchronous/blocking code. It needs some practice until such code becomes natural to read.

Now, when converted to ``asyncio.coroutine``, the code becomes:

.. code-block:: python
   :linenos:
   :emphasize-lines: 3,4,5

   import asyncio

   async def slow_square(x):
      await asyncio.sleep(1)
      return x * x


   async def test():
      res = await slow_square(3)
      print(res)

   loop = asyncio.get_event_loop()
   loop.run_until_complete(test())

The main differences (on surface) are:

1. The declaration of the function with ``async`` keyword (line 3) in asyncio versus the decorator ``@defer.inlineCallbacks`` with Twisted
2. The use of ``await`` in asyncio, versus ``yield`` in Twisted (line 5)
3. The auxiliary code to get the event loop started and stopped

Most of the examples that follow will show code for both Twisted and asyncio, unless the conversion is trivial.
