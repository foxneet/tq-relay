#coding:gbk
# =====================================================================
# TQRelay self test v1 (run INSIDE QMT strategy editor, client machine)
# Tests every category of the TQ relay via remote HTTP:
#   auth / ping / kline / snapshot / stock info / name search /
#   stock list / more info / shares history / dividends / ZDT /
#   formula(batch, real chips) / positions query / transparent port
# Usage: paste as new QMT python strategy, click Run (debug ok).
#        Read the [PASS]/[FAIL] lines and the final summary.
#
# Encoding note: this file contains Chinese protocol strings (formula
# name / output-line name). Before loading into QMT, save it as GBK
# bytes (declared #coding:gbk), or keep it pure ASCII yourself.
# =====================================================================
import os
import json
import time
import urllib.parse
import urllib.request

SIGNAL_HOST = '192.168.1.100'   # <- machine A LAN IP (TQRelay)
PORT = 17710
TPORT = 17711                   # transparent port; set 0 to skip that test
TOKEN_FALLBACK = ''             # <- paste token here if env var is empty
TOKEN = os.environ.get('SIGNAL_TOKEN', '') or TOKEN_FALLBACK
TEST_CODE = '159582.SZ'
POOL_HEAD = '518880.SH'

URL_BASE = 'http://%s:%d' % (SIGNAL_HOST, PORT)
RESULTS = []


def _post(url, body, timeout=120):
    req = urllib.request.Request(url,
        data=json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    r = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(r.read().decode('utf-8', 'replace'))


def _get(url, timeout=30):
    r = urllib.request.urlopen(url, timeout=timeout)
    return json.loads(r.read().decode('utf-8', 'replace'))


def relay_tq(method, params, timeout=120):
    """generic TQ call through relay; returns (ok, resp)"""
    url = URL_BASE + '/tq?token=' + TOKEN
    try:
        resp = _post(url, {'method': method, 'params': params}, timeout)
    except Exception as e:
        return False, {'relay_error': repr(e)}
    if not isinstance(resp, dict) or 'error' in resp:
        return False, resp
    return True, resp


def record(name, ok, detail):
    tag = '[PASS]' if ok else '[FAIL]'
    if ok is None:
        tag = '[WARN]'
    RESULTS.append((name, ok))
    print('%s %-22s %s' % (tag, name, detail))


def t_ping():
    r = _get(URL_BASE + '/ping?token=' + TOKEN)
    record('ping/token', isinstance(r, dict) and r.get('ok') is True, str(r)[:100])


def t_token_reject():
    r = _get(URL_BASE + '/ping?token=wrong')
    ok = isinstance(r, dict) and 'error' in r
    record('wrong-token rejected', ok, str(r)[:100])


def t_market_data():
    ok, r = relay_tq('get_market_data', {
        'stock_list': [TEST_CODE], 'period': '1d', 'start_time': '20260901',
        'end_time': '20260924', 'dividend_type': 'front', 'fill_data': False})
    d = (r.get('result', {}).get('Value') or {}).get(TEST_CODE) or {}
    n = len(d.get('Date') or [])
    record('get_market_data', ok and n > 0, '%d bars, last=%s' % (n, (d.get('Date') or ['-'])[-1]))


def t_snapshot():
    ok, r = relay_tq('get_market_snapshot', {'stock_code': TEST_CODE})
    v = r.get('result', {})
    now = v.get('Now', '')
    record('get_market_snapshot', ok and now != '', 'Now=%s' % now)


def t_stock_info():
    ok, r = relay_tq('get_stock_info', {'stock_code': TEST_CODE})
    v = r.get('result', {})
    name = v.get('Name', '')
    record('get_stock_info', ok and name != '', 'Name=%s FloatShares=%s' % (name, v.get('ActiveCapital', '?')))


def t_match_stkinfo():
    ok, r = relay_tq('get_match_stkinfo', {'key_word': '50ETF'})
    ok_net = ok and 'error' not in r            # interface reachable
    v = r.get('result', {})
    lst = v.get('Value') or []
    record('get_match_stkinfo', ok_net, '%d matches' % len(lst))


def t_stock_list():
    ok, r = relay_tq('get_stock_list', {'market': '31', 'list_type': 0})
    v = r.get('result', {})
    lst = v.get('Value') or v.get('Code') or []
    record('get_stock_list(ETF)', ok and len(lst) > 0, '%d codes' % len(lst))


def t_trading_dates():
    ok, r = relay_tq('get_trading_dates', {
        'market': 'SH', 'start_time': '20260901', 'end_time': '20260924'})
    v = r.get('result', {})
    val = v.get('Value') or []
    record('get_trading_dates', ok, '%s dates' % len(val))


def t_more_info():
    ok, r = relay_tq('get_more_info', {'stock_code': TEST_CODE})
    v = r.get('result', {})
    keys = sorted(v.keys())[:6] if isinstance(v, dict) else []
    record('get_more_info', ok and isinstance(v, dict) and len(keys) > 0,
           'keys=%s fHSL=%s' % (keys, v.get('fHSL')))


def t_gb_info():
    ok, r = relay_tq('get_gb_info_by_date', {
        'stock_code': TEST_CODE, 'start_date': '20260101', 'end_date': '20260924'})
    v = r.get('result', {}) or {}
    val = v.get('Value') or []
    record('get_gb_info_by_date', ok, '%d share records' % len(val))


def t_divid_factors():
    ok, r = relay_tq('get_divid_factors', {'stock_code': TEST_CODE})
    v = r.get('result', {})
    val = v.get('Value')
    record('get_divid_factors', ok, 'Value=%s' % (str(val)[:60]))


def t_zdt():
    ok, r = relay_tq('get_zdt_data', {'stock_list': [TEST_CODE]})
    v = r.get('result', {})
    val = v.get('Value')
    record('get_zdt_data', ok, 'Value=%s' % (str(val)[:60]))


def t_formula_batch():
    ok, r = relay_tq('formula_process_mul_zb', {
        'formula_name': 'MA',   # replace with your own formula name
        'stock_list': [TEST_CODE],
        'stock_period': '1d', 'start_time': '19900101', 'end_time': '20260924',
        'return_date': True, 'return_count': 3, 'dividend_type': 1, 'xsflag': 3}, timeout=180)
    d = (r.get('result') or {}).get(TEST_CODE) or {}
    lines = list(d.keys())
    record('formula_process_mul_zb', ok and len(lines) > 0,
           'output lines=%s' % lines[:4])


def t_positions():
    ok, r = relay_tq('query_stock_positions', {'account_id': 0})
    v = r.get('result', {})
    errid = str(v.get('ErrorId', '0'))
    val = v.get('Value')
    record('query_stock_positions', ok and errid == '0',
           'ErrorId=%s positions=%s' % (errid, len(val) if isinstance(val, list) else val))


def t_transparent():
    if TPORT <= 0:
        record('transparent port', None, 'skipped (TPORT=0)')
        return
    url = 'http://%s:%d/' % (SIGNAL_HOST, TPORT)
    body = {'method': 'get_market_data', 'params': {
        'stock_list': [POOL_HEAD], 'period': '1d', 'start_time': '20260901',
        'end_time': '20260924', 'dividend_type': 'front', 'fill_data': False}}
    try:
        r = _post(url, body, timeout=120)
        d = (r.get('result', {}).get('Value') or {}).get(POOL_HEAD) or {}
        n = len(d.get('Date') or [])
        record('transparent port', n > 0, '%d bars (no token)' % n)
    except Exception as e:
        record('transparent port', False, repr(e))


TESTS = [t_ping, t_token_reject, t_market_data, t_snapshot, t_stock_info,
         t_match_stkinfo, t_stock_list, t_trading_dates, t_more_info,
         t_gb_info, t_divid_factors, t_zdt, t_formula_batch,
         t_positions, t_transparent]


def run_all(ContextInfo):
    print('===== TQRelay self test start =====')
    print('target=%s token_set=%s' % (URL_BASE, bool(TOKEN)))
    if not TOKEN:
        print('!! TOKEN empty. Two ways:')
        print('!!   1. setx SIGNAL_TOKEN <value>  then FULLY restart QMT')
        print('!!   2. paste <value> into TOKEN_FALLBACK in this file and rerun')
        print('!! token value: see relay machine config json or relay GUI')
    n_pass = n_fail = n_warn = 0
    t0 = time.time()
    for t in TESTS:
        try:
            t()
        except Exception as e:
            record(t.__name__, False, 'EXCEPTION %r' % e)
    for name, ok in RESULTS:
        if ok is True:
            n_pass += 1
        elif ok is False:
            n_fail += 1
        else:
            n_warn += 1
    print('===== summary: %d/%d PASS, %d FAIL, %d WARN, %.1fs ====='
          % (n_pass, len(RESULTS), n_fail, n_warn, time.time() - t0))
    if n_fail == 0:
        print('===== ALL FUNCTIONAL OK - relay fully operational =====')


def init(ContextInfo):
    print('TQRelay self test v1 init. host=%s port=%d tport=%d'
          % (SIGNAL_HOST, PORT, TPORT))
    run_all(ContextInfo)


def handlebar(ContextInfo):
    pass
