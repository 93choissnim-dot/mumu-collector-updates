"""Transient update failures, bounded retries, and complete download integrity."""
import io
import json
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError

import updater as u
import exe_updater as exe

URL='https://example.test/latest.json'


class Response:
    def __init__(self,raw=b'ok',fail=False):self.raw=io.BytesIO(raw);self.fail=fail
    def __enter__(self):return self
    def __exit__(self,*args):self.raw.close()
    def geturl(self):return URL
    def read(self,n):
        block=self.raw.read(n)
        if not block and self.fail:raise ConnectionResetError('connection interrupted')
        return block


def http_error(code):return HTTPError(URL,code,'server error',{},None)


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.stop=threading.Event()
        wait_patch=patch.object(self.stop,'wait',return_value=False)
        opener_patch=patch.object(u,'build_opener')
        self.wait=wait_patch.start();self.addCleanup(wait_patch.stop)
        self.opener=opener_patch.start().return_value;self.addCleanup(opener_patch.stop)

    def test_504_retries_then_checks_both_feed_formats(self):
        for module in (u,exe):
            info={'app_id':module.APP_ID,'protocol':1,'version':'1.0.0',
                  'url':'https://example.test/update.zip','sha256':'a'*64,'size':100}
            self.opener.open.reset_mock()
            self.opener.open.side_effect=[http_error(504),http_error(502),Response(json.dumps(info).encode())]
            self.assertEqual(module.check_feed(URL,'0.7.28',self.stop),info)
            self.assertEqual(self.opener.open.call_count,3)

    def test_repeated_504_stops_after_three_attempts(self):
        self.opener.open.side_effect=lambda *a,**k: http_raise(504)
        with self.assertRaisesRegex(u.UpdateError,'HTTP 504.*3회'):
            u.read_url(URL,self.stop,100)
        self.assertEqual(self.opener.open.call_count,3)
        self.assertEqual(self.wait.call_count,2)

    def test_partial_download_is_replaced_not_appended(self):
        self.opener.open.side_effect=[Response(b'broken bytes',fail=True),Response(b'complete')]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'download.zip';progress=[]
            self.assertEqual(u.read_url(URL,self.stop,100,path,progress.append),8)
            self.assertEqual(path.read_bytes(),b'complete')
            self.assertEqual(progress.count(0),2)

    def test_missing_file_and_certificate_errors_are_not_retried(self):
        for error in (http_error(404),URLError(ssl.SSLCertVerificationError('invalid certificate'))):
            self.opener.open.reset_mock();self.opener.open.side_effect=error
            with self.assertRaises(type(error)):u.read_url(URL,self.stop,100)
            self.assertEqual(self.opener.open.call_count,1)

    def test_cancel_during_backoff_prevents_another_request(self):
        self.opener.open.side_effect=http_error(503);self.wait.return_value=True
        with self.assertRaisesRegex(u.UpdateError,'취소'):u.read_url(URL,self.stop,100)
        self.assertEqual(self.opener.open.call_count,1)

    def test_cancel_before_request_does_not_contact_server(self):
        self.stop.set()
        with self.assertRaisesRegex(u.UpdateError,'취소'):u.read_url(URL,self.stop,100)
        self.opener.open.assert_not_called()

    def test_oversized_response_is_rejected_without_retry(self):
        self.opener.open.return_value=Response(b'too large')
        with self.assertRaisesRegex(u.UpdateError,'크기'):u.read_url(URL,self.stop,3)
        self.assertEqual(self.opener.open.call_count,1)

    def test_retry_does_not_reset_total_deadline(self):
        self.opener.open.side_effect=http_error(504)
        with patch.object(u.time,'monotonic',side_effect=[0,0,0,181,181]):
            with self.assertRaisesRegex(u.UpdateError,'시간이 초과'):u.read_url(URL,self.stop,100)
        self.assertEqual(self.opener.open.call_count,1)


def http_raise(code):raise http_error(code)


if __name__=='__main__':unittest.main()
