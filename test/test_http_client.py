from collections import namedtuple
import functools
from unittest import TestCase

import reactivex as rx
from reactivex.subject import Subject
import cyclotron_aiohttp.http as http

class HttpClientTestCase(TestCase):
    def setUp(self):
        self.actual = {}

    def create_actual(self):
        return {
            'next': [],
            'error': None,
            'completed': False
        }

    def on_next(self, key, i):
        if not key in self.actual:
            self.actual[key] = self.create_actual()
        self.actual[key]['next'].append(i)

    def on_error(self, key, e):
        if not key in self.actual:
            self.actual[key] = self.create_actual()
        self.actual[key]['error'] = e

    def on_completed(self, key):
        if not key in self.actual:
            self.actual[key] = self.create_actual()
        self.actual[key]['completed'] = True  

    def test_request(self):
        http_response = Subject()
        source = http.ClientSource(http_response=http_response)

        client = http.client(source)

        client.sink.http_request.subscribe(
            on_next=functools.partial(self.on_next, 'http_request'),
            on_error=functools.partial(self.on_error, 'http_request'),
            on_completed=functools.partial(self.on_completed, 'http_request'))

        response = client.api.request('GET', 'http://foo.com')

        response.subscribe(
            on_next=functools.partial(self.on_next, 'response'),
            on_error=functools.partial(self.on_error, 'response'),
            on_completed=functools.partial(self.on_completed, 'response'))

        self.assertEqual(
            http.Request(id=response, method='GET', url='http://foo.com'),
            self.actual['http_request']['next'][0])

        result = http.HttpResponse(
            status=200, reason='OK', 
            method='GET', url='http://foo.com',
            data=b'bar', cookies=[], 
            headers=[], content_type='text/plain'
        )
        http_response.on_next(http.Response(
            id=response,
            response=rx.just(result)
        ))

        self.assertIs(
            result,
            self.actual['response']['next'][0])
