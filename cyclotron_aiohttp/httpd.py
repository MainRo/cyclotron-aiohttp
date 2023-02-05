import traceback
import os
from enum import Enum
import asyncio
from collections import namedtuple
from cyclotron import Component

import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from aiohttp import web
from aiohttp import helpers
from aiohttp.log import access_logger

from multidict import MultiDict

Sink = namedtuple('Sink', ['control'])

# sink events
Initialize = namedtuple('Initialize', [
    'request_max_size'
])
Initialize.__new__.__defaults__ = (1024**2,)

StartServer = namedtuple('StartServer', [
    'port', 'host'
])
StartServer.__new__.defaults__ = ('localhost',)

StopServer = namedtuple('StopServer', [])

AddRoute = namedtuple('AddRoute', ['methods', 'path', 'id', 'headers'])
AddRoute.__new__.__defaults__ = (None,)

Response = namedtuple('Response', ['context', 'data', 'status'])
Response.__new__.__defaults__ = (None, 200,)

# source events
ServerStarted = namedtuple('ServerStarted', [])
ServerStopped = namedtuple('ServerStopped', [])
RouteAdded = namedtuple('RouteAdded', ['path', 'id', 'request'])
Request = namedtuple('Request', [
    'method', 'path', 'match_info', 'data',
    'headers',
    'context'
])

''' Httpd source. The server stream is a stream of
    - route is a stream of RouteAdded.
'''
Source = namedtuple('Source', ['server', 'route'])


def make_driver(loop=None):
    def driver(sink):
        '''
            Routes must be configured before starting the server.
        '''
        app = None
        runner = None
        server_observer = None
        route_observer = None

        def add_route(app, methods, path, id, headers=None):
            request_observer = None

            def on_request_subscribe(observer, scheduler):
                nonlocal request_observer
                request_observer = observer

            async def on_request_data(request, path):
                nonlocal request_observer
                data = await request.read()
                response_future = asyncio.Future()
                request_item = Request(
                    method=request.method,
                    path=path,
                    match_info=request.match_info,
                    data=data,
                    context=response_future,
                    headers=request.headers,
                )
                request_observer.on_next(request_item)
                await response_future
                data, status = response_future.result()

                response = web.StreamResponse(status=status, reason=None,
                    headers=None if headers is None else MultiDict(headers))
                await response.prepare(request)
                if data is not None:
                    await response.write(data)
                return response

            for method in methods:
                app.router.add_route(method, path, lambda r: on_request_data(r, path))

            if route_observer is not None:
                route = RouteAdded(
                    path=path,
                    id=id,
                    request=rx.create(on_request_subscribe)
                )
                route_observer.on_next(route)

        def create_server_observable():
            def on_server_subscribe(observer, scheduler):
                nonlocal server_observer
                server_observer = observer

            return rx.create(on_server_subscribe)

        def create_route_observable():
            def on_route_subscribe(observer, scheduler):
                nonlocal route_observer
                route_observer = observer

            return rx.create(on_route_subscribe).pipe(ops.share())

        def start_server(host, port, app):
            runner = web.AppRunner(app)

            async def _start_server(runner):
                await runner.setup()
                site = web.TCPSite(runner, host, port)
                await site.start()
                if server_observer is not None:
                    server_observer.on_next(ServerStarted())


            asyncio.ensure_future(_start_server(runner), loop=loop)
            return runner

        def stop_server(runner):
            async def _stop_server():
                await runner.cleanup()
                server_observer.on_next(ServerStopped())

            asyncio.ensure_future(_stop_server())

        def on_sink_item(i):
            nonlocal app
            nonlocal runner
            if type(i) is Response:
                response_future = i.context
                response_future.set_result((i.data, i.status))
            elif type(i) is AddRoute:
                add_route(app, i.methods, i.path, i.id, i.headers)
            elif type(i) is StartServer:
                runner = start_server(i.host, i.port, app)
            elif type(i) is StopServer:
                stop_server(runner)
            elif type(i) is Initialize:
                app_args = {
                    "client_max_size": i.request_max_size
                }
                app = web.Application(**app_args)
            else:
                print("received unknown item: {}".format(type(i)))

        def on_sink_error(e):
            print("http sink error: {}, {}".format(e, traceback.format_exc()))

        sink.control.subscribe(on_next=on_sink_item, on_error=on_sink_error)
        return Source(
            server=create_server_observable(),
            route=create_route_observable())

    return Component(call=driver, input=Sink)
