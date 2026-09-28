# -*- coding: utf-8 -*-
"""TQRelay 客户端 —— 跨机调用通达信TQ服务的轻量封装（纯标准库）

CLI:
  python tq_client.py ping --host 192.168.1.100 --token XXX
  python tq_client.py call --host 192.168.1.100 --token XXX \
      --method get_market_snapshot --params "{\"stock_code\":\"159582.SZ\"}"

Python:
  from tq_client import TQRelay, TQRelayError
  relay = TQRelay('192.168.1.100', token='XXX', timeout=300)
  resp = relay.call('get_market_data', {...})
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request

DEFAULT_PORT = 17710
DEFAULT_TIMEOUT = 60


class TQRelayError(Exception):
    """转发层错误（连接/超时/token）或 TQ 业务错误（ErrorId != '0'）"""


class TQRelay:
    def __init__(self, host, token, port=DEFAULT_PORT, timeout=DEFAULT_TIMEOUT):
        self.base = 'http://%s:%d' % (host, port)
        self.token = token
        self.timeout = timeout

    def ping(self):
        url = '%s/ping?token=%s' % (self.base, urllib.parse.quote(self.token))
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                return json.loads(r.read().decode('utf-8', 'replace'))
        except Exception as e:
            raise TQRelayError('ping 失败（转发器没运行/端口/防火墙/token 错误?）: %s' % e)

    def call(self, method, params=None, timeout=None):
        """调用任意 TQ 接口。返回 TQ 原始 JSON；两层错误任一发生即抛 TQRelayError。"""
        url = '%s/tq?token=%s' % (self.base, urllib.parse.quote(self.token))
        body = json.dumps({'method': method, 'params': params or {}},
                          ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=body,
            headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as r:
                resp = json.loads(r.read().decode('utf-8', 'replace'))
        except Exception as e:
            raise TQRelayError('转发层失败 [%s]: %s' % (method, e))
        if isinstance(resp, dict) and 'error' in resp:
            raise TQRelayError('转发层错误 [%s]: %s' % (method, resp['error']))
        result = resp.get('result', resp) if isinstance(resp, dict) else resp
        if isinstance(result, dict) and str(result.get('ErrorId', '0')) not in ('0', ''):
            raise TQRelayError('TQ业务错误 [%s]: ErrorId=%s %s' % (
                method, result.get('ErrorId'), result.get('Error', '')))
        return resp


def main():
    ap = argparse.ArgumentParser(description='TQRelay 客户端')
    ap.add_argument('action', choices=['ping', 'call'])
    ap.add_argument('--host', required=True, help='TQRelay 所在机器 IP')
    ap.add_argument('--token', required=True)
    ap.add_argument('--port', type=int, default=DEFAULT_PORT)
    ap.add_argument('--method', help='TQ 接口名（call 用）')
    ap.add_argument('--params', default='{}', help='JSON 字符串（call 用）')
    ap.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT)
    a = ap.parse_args()

    relay = TQRelay(a.host, token=a.token, port=a.port, timeout=a.timeout)
    if a.action == 'ping':
        out = relay.ping()
    else:
        if not a.method:
            ap.error('call 需要 --method')
        out = relay.call(a.method, json.loads(a.params), timeout=a.timeout)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
