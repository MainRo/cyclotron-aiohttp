import asyncio
import threading
from unittest import TestCase
import urllib.request

import reactivex as rx
import reactivex.operators as ops
from reactivex.subject import Subject
import cyclotron_aiohttp.httpd as httpd


class HttpdServerTestCase(TestCase):

    def test_start_server_item(self):
        self.assertRaises(TypeError, httpd.StartServer)

        item = httpd.StartServer(host='localhost', port=80)
        self.assertEqual('localhost', item.host)
        self.assertEqual(80, item.port)


    def test_start_server(self):
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        asyncio.set_event_loop(loop)

        sink = httpd.Sink(
            control = Subject()
        )

        def on_httpd_item(i):
            if type(i) is httpd.ServerStarted:
                sink.control.on_next(httpd.StopServer())
            elif type(i) == httpd.ServerStopped:
                asyncio.get_event_loop().stop()

        def control_stream(sink):
            sink.control.on_next(httpd.Initialize())
            sink.control.on_next(httpd.StartServer(host='localhost', port=9999))

        loop.call_soon(control_stream, sink)
        source = httpd.make_driver(loop).call(sink)
        source.server.subscribe(on_httpd_item)

        loop.run_forever()
        loop.close()

    def test_add_route(self):
        routes = [
            httpd.AddRoute(methods=['GET'], path='/foo', id='foo'),
            httpd.AddRoute(methods=['POST'], path='/bar', id='bar'),
            httpd.AddRoute(methods=['PUT'], path='/biz', id='biz'),
        ]
        actual_routes = []
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        asyncio.set_event_loop(loop)

        sink = httpd.Sink(control=Subject())

        def setup(sink):
            sink.control.on_next(httpd.Initialize()),
            sink.control.on_next(httpd.StartServer(host='localhost', port=9999)),
            for route in routes:
                sink.control.on_next(route)

        def on_route_item(i):
            if type(i) is httpd.RouteAdded:
                actual_routes.append(i)
                # stop mainloop when last route is created
                if i.id == routes[-1].id:
                    asyncio.get_event_loop().stop()

        loop.call_soon(setup, sink)
        source = httpd.make_driver(loop).call(sink)
        source.route.subscribe(on_route_item)
        loop.run_forever()
        loop.close()

        self.assertEqual(len(routes), len(actual_routes))
        for index,route in enumerate(actual_routes):
            self.assertEqual(routes[index].path, route.path)
            self.assertEqual(routes[index].id, route.id)
            self.assertIsInstance(route.request, rx.Observable)

    def test_get(self):
        client_thread = None
        response = None
        loop = asyncio.new_event_loop()
        loop.set_debug(True)
        asyncio.set_event_loop(loop)

        sink = httpd.Sink(control=Subject())

        def setup(sink):
            sink.control.on_next(httpd.Initialize()),
            sink.control.on_next(httpd.AddRoute(
                methods=['GET'], path='/foo', id='foo'))
            sink.control.on_next(httpd.StartServer(host='localhost', port=8080)),

        def do_get():
            nonlocal response
            req = urllib.request.urlopen('http://localhost:8080/foo')
            response = req.read()

        # todo rxpy threadpool
        client_thread = threading.Thread(target=do_get)

        def on_server_item(i):
            if type(i) is httpd.ServerStarted:
                nonlocal client_thread
                client_thread.start()
            elif type(i) == httpd.ServerStopped:
                asyncio.get_event_loop().stop()

        def on_route_item(i):
            sink.control.on_next(httpd.Response(context=i.context, data=b'foo'))
            loop.call_soon(sink.control.on_next, httpd.StopServer())

        loop.call_soon(setup, sink)
        source = httpd.make_driver(loop).call(sink)
        source.route.pipe(
            ops.filter(lambda i : i.id == 'foo'),
            ops.flat_map(lambda i: i.request),
        ).subscribe(on_route_item)

        source.server \
            .subscribe(on_server_item)

        loop.run_forever()
        loop.close()
        client_thread.join()

        self.assertEqual(b'foo', response)
