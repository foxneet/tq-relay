# -*- coding: utf-8 -*-
"""
TQRelay —— 通达信TQ转发器 (局域网通用网关)
=============================================

把通达信TQ量化服务(tqcenter, 默认只监听 127.0.0.1:17709)以 HTTP 方式
暴露给局域网内其他机器, 让大QMT等客户端跨机调用通达信的全部接口:
K线/实时快照/公式引擎(含WINNER,COST等筹码函数, 由通达信原生计算)/
基础信息/板块/财务/股本/涨跌停/交易查询/下单等。

接口:
  主端口(默认17710, 需token, 见配置文件):
    POST /tq?token=...    通用转发: body={"method":"接口名","params":{...}}
                          原样转发给本机TQ, 返回TQ原始JSON结果。
    GET  /ping?token=...  连通测试
  透明端口(可选, 无token):
    POST /<任意路径>      body原样转发给本机TQ, 兼容写死127.0.0.1:17709的
                          tqcenter.py旧代码(配合客户端 netsh portproxy)。
                          受 allow_ips 白名单与 allow_trade 约束。

配置: 同目录 TQ转发器_配置.json (首次运行自动生成; token 自动随机生成,
      或采纳环境变量 SIGNAL_TOKEN; GUI 可改端口/token/通达信路径/日志目录/
      TQ地址/超时/allow_trade/透明端口开关与端口/allow_ips)。
日志: <日志目录>/TQ转发器_YYYYMMDD.log 按日期分文件; 错误单独文件。

运行:
  python tq_relay.py          -> GUI(自动开服务)
  python tq_relay.py --serve  -> 无界面后台服务(日志走文件)

打包单文件exe(可选):
  py -3.14 -m PyInstaller --onefile --windowed --name TQRelay tq_relay.py
"""
import sys
import os
import json
import socket
import secrets
import threading
import datetime
import urllib.parse
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
import traceback

VERSION = '1.0.0'

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w', encoding='utf-8')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w', encoding='utf-8')
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

# ---------------- 配置 ----------------
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'TQ转发器_配置.json')
DEFAULT_CONFIG = {
    'port': 17710,                   # 主端口(需token)
    'token': '',                     # 首次运行自动生成, 或采纳环境变量 SIGNAL_TOKEN
    'tdx_path': '',                  # 通达信安装目录(展示/备用)
    'log_dir': '日志',                # 相对exe目录或绝对路径
    'tq_url': 'http://127.0.0.1:17709/',   # 本机TQ服务地址
    'timeout_sec': 300,              # 转发TQ调用的超时
    'allow_trade': True,             # False时拒绝交易类接口
    'max_body_mb': 20,               # 请求包体上限
    'transparent_enabled': False,    # 透明端口模式开关
    'transparent_port': 17711,       # 透明端口(勿与TQ本尊17709冲突)
    'allow_ips': '',                 # 透明端口来源IP白名单(逗号分隔, 空=全部允许)
}
TRADE_METHODS = {'stock_account', 'query_stock_positions', 'order_stock',
                 'cancel_order_stock', 'query_stock_asset', 'query_stock_orders'}
TEST_CODE = '518880.SH'              # 通达信连通性测试用代码

CONFIG = dict(DEFAULT_CONFIG)
TQ_LOCK = threading.Lock()           # TQ串行化(不耐并发)


def load_config():
    global CONFIG
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            CONFIG.update(json.load(f))
    except Exception:
        pass
    if not CONFIG.get('token'):
        CONFIG['token'] = os.environ.get('SIGNAL_TOKEN', '') or secrets.token_hex(8)
    for k in ('port', 'timeout_sec', 'max_body_mb', 'transparent_port'):
        CONFIG[k] = int(CONFIG.get(k) or DEFAULT_CONFIG.get(k, 0))
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(CONFIG, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def log_dir_abs():
    d = CONFIG.get('log_dir') or '日志'
    return d if os.path.isabs(d) else os.path.join(BASE_DIR, d)


def dlog(msg, error=False):
    try:
        d = log_dir_abs()
        os.makedirs(d, exist_ok=True)
        name = 'TQ转发器_错误_%s.log' if error else 'TQ转发器_%s.log'
        p = os.path.join(d, name % datetime.date.today().strftime('%Y%m%d'))
        with open(p, 'a', encoding='utf-8') as f:
            f.write('[%s] %s\n' % (datetime.datetime.now().strftime('%H:%M:%S'), msg))
    except Exception:
        pass


def tq_code(c):
    return c + ('.SH' if c.startswith('5') else '.SZ')


def tq_forward(method, params, timeout):
    payload = {'id': 1, 'method': method, 'params': params}
    req = urllib.request.Request(
        CONFIG['tq_url'], data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with TQ_LOCK:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', errors='replace'))


def tq_forward_raw(body, timeout):
    """透明转发: body原样POST给本机TQ, 返回原始字节"""
    req = urllib.request.Request(
        CONFIG['tq_url'], data=body,
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with TQ_LOCK:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read()


def ip_allowed(ip):
    allow = (CONFIG.get('allow_ips') or '').replace(' ', '')
    if not allow:
        return True
    return ip in [x for x in allow.split(',') if x]


# ---------------- HTTP 服务 ----------------
def make_handler(log):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, obj):
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _auth(self, q):
            if q.get('token', [''])[0] != CONFIG.get('token'):
                self._send({'error': 'token错误'})
                return False
            return True

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            path, ip = u.path, self.client_address[0]
            if not self._auth(q):
                log('[拒绝] %s from %s: token错误' % (path, ip))
                return
            if path == '/ping':
                self._send({'ok': True, 'service': 'tq_relay', 'version': VERSION,
                            'time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')})
            else:
                self._send({'error': 'unknown path, POST /tq?token=...'})

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            q = urllib.parse.parse_qs(u.query)
            path, ip = u.path, self.client_address[0]
            if not self._auth(q):
                log('[拒绝] %s from %s: token错误' % (path, ip))
                return
            if path != '/tq':
                self._send({'error': 'unknown path, POST /tq?token=...'})
                return
            try:
                ln = int(self.headers.get('Content-Length') or 0)
            except Exception:
                ln = 0
            if ln <= 0 or ln > int(CONFIG['max_body_mb']) * 1024 * 1024:
                self._send({'error': 'body size invalid (max %sMB)' % CONFIG['max_body_mb']})
                return
            try:
                payload = json.loads(self.rfile.read(ln).decode('utf-8'))
                method = str(payload.get('method') or '')
                params = payload.get('params') or {}
            except Exception as e:
                self._send({'error': 'bad json body: %r' % e})
                return
            if not method:
                self._send({'error': 'method required'})
                return
            if (not CONFIG.get('allow_trade', True)) and method in TRADE_METHODS:
                log('[拒绝交易] %s from %s: %s' % (ip, method, CONFIG))
                self._send({'error': 'allow_trade=False, 交易类接口已禁用: %s' % method})
                return
            t0 = datetime.datetime.now()
            try:
                res = tq_forward(method, params, int(CONFIG['timeout_sec']))
                dt = (datetime.datetime.now() - t0).total_seconds()
                log('[转发] %s <- %s(%s...) 耗时%.2fs' % (ip, method, json.dumps(params, ensure_ascii=False)[:80], dt))
                self._send(res)
            except Exception as e:
                dt = (datetime.datetime.now() - t0).total_seconds()
                log('[转发失败] %s %s: %r (%.1fs)' % (ip, method, e, dt))
                dlog('转发失败 %s %s: %s' % (ip, method, traceback.format_exc()), error=True)
                self._send({'error': 'TQ forward failed: %r' % e})

        def log_message(self, *args):
            pass
    return Handler


def make_transparent_handler(log):
    """无token纯透传: body原样转发给本机TQ。受 allow_ips 与 allow_trade 约束。"""
    class TransparentHandler(BaseHTTPRequestHandler):
        def _read_body(self):
            try:
                ln = int(self.headers.get('Content-Length') or 0)
            except Exception:
                ln = 0
            if ln <= 0 or ln > int(CONFIG['max_body_mb']) * 1024 * 1024:
                return None
            return self.rfile.read(ln)

        def _is_trade(self, body):
            try:
                return str(json.loads(body.decode('utf-8')).get('method') or '') in TRADE_METHODS
            except Exception:
                return False

        def do_POST(self):
            ip = self.client_address[0]
            if not ip_allowed(ip):
                log('[透明拒绝] %s: 不在allow_ips白名单' % ip)
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b'{"error":"ip not allowed"}')
                return
            body = self._read_body()
            if body is None:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"error":"body size invalid"}')
                return
            if (not CONFIG.get('allow_trade', True)) and self._is_trade(body):
                log('[透明拒绝交易] %s' % ip)
                self.send_response(200)
                self.end_headers()
                self.wfile.write('{"error":"allow_trade=False, 交易类接口已禁用"}'.encode('utf-8'))
                return
            t0 = datetime.datetime.now()
            try:
                res = tq_forward_raw(body, int(CONFIG['timeout_sec']))
                dt = (datetime.datetime.now() - t0).total_seconds()
                log('[透明] %s %s body=%s... 耗时%.2fs'
                    % (ip, self.path, body.decode('utf-8', 'replace')[:80], dt))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(res)))
                self.end_headers()
                self.wfile.write(res)
            except Exception as e:
                log('[透明失败] %s: %r (%.1fs)' % (ip, e, (datetime.datetime.now() - t0).total_seconds()))
                dlog('透明转发失败: %s' % traceback.format_exc(), error=True)
                self.send_response(200)
                self.end_headers()
                self.wfile.write('{"error":"TQ forward failed"}'.encode('utf-8'))

        do_GET = do_POST     # tqcenter.py 全部走POST; GET也透传以防万一

        def log_message(self, *args):
            pass
    return TransparentHandler


def lan_ips():
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        ips.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except Exception:
        pass
    return [i for i in dict.fromkeys(ips) if not i.startswith('127.')]


def start_servers(log):
    srv = HTTPServer(('0.0.0.0', int(CONFIG['port'])), make_handler(log))
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    tsrv, tth = None, None
    if CONFIG.get('transparent_enabled'):
        tsrv = HTTPServer(('0.0.0.0', int(CONFIG['transparent_port'])),
                          make_transparent_handler(log))
        tth = threading.Thread(target=tsrv.serve_forever, daemon=True)
        tth.start()
    return srv, th, tsrv, tth


def stop_servers(state):
    for key in ('server', 'tsrv'):
        if state.get(key) is not None:
            state[key].shutdown()
            state[key].server_close()
            state[key] = None
    for key in ('thread', 'tthread'):
        if state.get(key) is not None:
            state[key].join(timeout=3)
            state[key] = None


HELP_TEXT = ('客户端端口映射方法(让写死127.0.0.1:17709的tqcenter.py旧代码零改动跨机可用):\n'
             '  1. 勾选"透明端口模式"并应用配置(本机将额外监听透明端口 %s);\n'
             '  2. 在【QMT机器】以管理员身份运行:\n'
             '     netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=17709 '
             'connectaddress=<本机LAN IP> connectport=<透明端口>\n'
             '  3. 本机防火墙放行透明端口(首次弹窗允许, 或: netsh advfirewall firewall add rule '
             'name="TQRelay透明端口" dir=in action=allow protocol=TCP localport=<透明端口>);\n'
             '  4. 之后QMT机器上的 tqcenter.py 老代码照常运行, 数据实际经本机转发。\n'
             '安全提示: 透明端口无token, 建议在配置文件 allow_ips 填入QMT机器IP做白名单。')


# ---------------- GUI ----------------
def run_gui():
    import tkinter as tk
    from tkinter import scrolledtext, filedialog, messagebox

    root = tk.Tk()
    root.title('通达信TQ转发器 v%s (通达信机, 局域网网关)' % VERSION)
    root.geometry('820x620')
    logq = queue.Queue()
    state = {'server': None, 'thread': None, 'tsrv': None, 'tthread': None}

    def log(msg):
        logq.put(msg)
        dlog(msg)

    tk.Label(root, text='设置(修改后点"应用配置"重启服务生效):').pack(anchor='w', padx=8, pady=(6, 0))
    cfgf = tk.Frame(root)
    cfgf.pack(fill='x', padx=8)
    e_port = tk.Entry(cfgf, width=7)
    e_token = tk.Entry(cfgf, width=22)
    e_tdx = tk.Entry(cfgf, width=22)
    e_log = tk.Entry(cfgf, width=12)
    e_tq = tk.Entry(cfgf, width=20)
    e_tport = tk.Entry(cfgf, width=7)
    for i, lab in enumerate(['端口', 'token', '通达信路径', '日志目录', 'TQ地址', '透明端口']):
        tk.Label(cfgf, text=lab).grid(row=0, column=i * 2)
    e_port.grid(row=1, column=0); e_token.grid(row=1, column=2)
    e_tdx.grid(row=1, column=4); e_log.grid(row=1, column=6)
    e_tq.grid(row=1, column=8); e_tport.grid(row=1, column=10)
    e_port.insert(0, str(CONFIG['port']))
    e_token.insert(0, CONFIG['token'])
    e_tdx.insert(0, CONFIG.get('tdx_path') or '')
    e_log.insert(0, CONFIG.get('log_dir') or '')
    e_tq.insert(0, CONFIG.get('tq_url') or '')
    e_tport.insert(0, str(CONFIG['transparent_port']))

    var_trade = tk.BooleanVar(value=bool(CONFIG.get('allow_trade', True)))
    c_trade = tk.Checkbutton(cfgf, text='允许交易接口', variable=var_trade)
    var_trans = tk.BooleanVar(value=bool(CONFIG.get('transparent_enabled', False)))
    c_trans = tk.Checkbutton(cfgf, text='透明端口模式', variable=var_trans)

    def browse_tdx():
        d = filedialog.askdirectory(title='选择通达信安装目录',
                                    initialdir=e_tdx.get() or os.path.expanduser('~'))
        if d:
            e_tdx.delete(0, 'end')
            e_tdx.insert(0, os.path.normpath(d))

    def browse_log():
        d = filedialog.askdirectory(title='选择日志目录',
                                    initialdir=log_dir_abs() if os.path.isdir(log_dir_abs())
                                    else os.path.expanduser('~'))
        if d:
            e_log.delete(0, 'end')
            e_log.insert(0, os.path.normpath(d))
    tk.Button(cfgf, text='浏览...', width=6, command=browse_tdx).grid(row=2, column=4, sticky='we', pady=(3, 0))
    tk.Button(cfgf, text='浏览...', width=6, command=browse_log).grid(row=2, column=6, sticky='we', pady=(3, 0))
    c_trade.grid(row=2, column=8, sticky='w', pady=(3, 0))
    c_trans.grid(row=2, column=10, sticky='w', pady=(3, 0))

    def apply_cfg():
        try:
            CONFIG['port'] = int(e_port.get().strip())
        except Exception:
            pass
        try:
            CONFIG['transparent_port'] = int(e_tport.get().strip())
        except Exception:
            pass
        CONFIG['token'] = e_token.get().strip()
        CONFIG['tdx_path'] = e_tdx.get().strip()
        CONFIG['log_dir'] = e_log.get().strip()
        CONFIG['tq_url'] = e_tq.get().strip() or CONFIG['tq_url']
        CONFIG['allow_trade'] = bool(var_trade.get())
        CONFIG['transparent_enabled'] = bool(var_trans.get())
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(CONFIG, f, ensure_ascii=False, indent=2)
        except Exception as e:
            log('配置保存失败: %r' % e)
        stop_all()
        start_all()
        log('配置已应用: 端口=%s token=%s... allow_trade=%s 透明=%s(%s) tq=%s'
            % (CONFIG['port'], CONFIG['token'][:4], CONFIG['allow_trade'],
               CONFIG['transparent_enabled'], CONFIG['transparent_port'], CONFIG['tq_url']))
    tk.Button(cfgf, text='应用配置', command=apply_cfg).grid(row=1, column=11, padx=6)

    def start_all():
        state['server'], state['thread'], state['tsrv'], state['tthread'] = start_servers(log)
        status.configure(text='● 运行中 0.0.0.0:%s%s' % (
            CONFIG['port'], ' + 透明:%s' % CONFIG['transparent_port'] if state['tsrv'] else ''), fg='green')
        btn.configure(text='停止服务')
        log('服务已启动 通用转发POST /tq | 透明端口=%s | allow_trade=%s'
            % (CONFIG['transparent_port'] if state['tsrv'] else '关', CONFIG['allow_trade']))

    def stop_all():
        stop_servers(state)
        status.configure(text='● 已停止', fg='red')
        btn.configure(text='启动服务')
        log('服务已停止')

    top = tk.Frame(root)
    top.pack(fill='x', padx=8, pady=6)
    status = tk.Label(top, text='● 已停止', fg='red', font=('微软雅黑', 11, 'bold'))
    status.pack(side='left')

    def toggle():
        if state['server'] is None:
            try:
                start_all()
            except Exception as e:
                log('启动失败: %r' % e)
                dlog('启动失败: %s' % traceback.format_exc(), error=True)
                messagebox.showerror('启动失败', repr(e))
                return
        else:
            stop_all()
    btn = tk.Button(top, text='启动服务', width=12)
    btn.configure(command=toggle)
    btn.pack(side='left', padx=8)

    def self_test():
        def run():
            try:
                r = urllib.request.urlopen(
                    'http://127.0.0.1:%d/ping?token=%s' % (CONFIG['port'], urllib.parse.quote(CONFIG['token'])),
                    timeout=5)
                log('[自检] %s' % r.read().decode('utf-8'))
            except Exception as e:
                log('[自检] 失败: %r' % e)
        threading.Thread(target=run, daemon=True).start()
    tk.Button(top, text='自检', width=8, command=self_test).pack(side='left', padx=4)

    def test_tdx():
        def run():
            try:
                t0 = datetime.datetime.now()
                res = tq_forward('get_market_data', {
                    'stock_list': [TEST_CODE], 'period': '1d',
                    'start_time': datetime.date.today().strftime('%Y%m%d'),
                    'end_time': datetime.date.today().strftime('%Y%m%d'),
                    'dividend_type': 'front', 'fill_data': False}, 60)
                d = (res.get('result', {}).get('Value') or {}).get(TEST_CODE) or {}
                ok = bool(d.get('Date'))
                log('[通达信测试] %s 耗时%.2fs' % (
                    '正常, 今日K线%d根' % len(d['Date']) if ok else '无数据(客户端未登录/未下载?)',
                    (datetime.datetime.now() - t0).total_seconds()))
            except Exception as e:
                log('[通达信测试] 失败: %r' % e)
        threading.Thread(target=run, daemon=True).start()
    tk.Button(top, text='测试通达信', width=12, command=test_tdx).pack(side='left', padx=4)

    ips = lan_ips()
    tk.Label(root, text='本机局域网IP(填客户端SIGNAL_HOST/portproxy的connectaddress): %s\n'
                        '局域网客户端用法: POST http://<本IP>:%s/tq?token=<token>  body={"method":"接口名","params":{...}}\n'
                        '支持TQ全部接口(行情/K线/公式引擎/板块/财务/交易查询/下单等)'
             % (' 或 '.join(ips) if ips else '?', CONFIG['port']),
             fg='blue', justify='left', anchor='w', wraplength=790).pack(fill='x', padx=10)

    helpf = tk.Label(root, text=HELP_TEXT % CONFIG['transparent_port'],
                     fg='gray', justify='left', anchor='w', wraplength=790)
    helpf.pack(fill='x', padx=10)

    txt = scrolledtext.ScrolledText(root, font=('Consolas', 9))
    txt.pack(fill='both', expand=True, padx=8, pady=6)
    txt.configure(state='disabled')

    def poll():
        try:
            while True:
                msg = logq.get_nowait()
                txt.configure(state='normal')
                txt.insert('end', msg + '\n')
                txt.see('end')
                txt.configure(state='disabled')
        except queue.Empty:
            pass
        root.after(200, poll)

    root.after(200, poll)
    root.protocol('WM_DELETE_WINDOW', root.destroy)
    toggle()
    root.mainloop()


def main():
    load_config()
    if '--serve' in sys.argv:
        srv, _th, tsrv, _tth = start_servers(dlog)
        dlog('--serve 模式启动 端口=%s 透明端口=%s' % (CONFIG['port'],
             CONFIG['transparent_port'] if tsrv else '关'))
        print('serving on 0.0.0.0:%s token=%s  transparent=%s'
              % (CONFIG['port'], CONFIG['token'][:4] + '***',
                 CONFIG['transparent_port'] if tsrv else 'off'))
        sys.stdout.flush()
        srv.serve_forever()
    else:
        run_gui()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        try:
            d = log_dir_abs()
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, 'TQ转发器_错误_%s.log' % datetime.date.today().strftime('%Y%m%d')),
                      'a', encoding='utf-8') as f:
                f.write('\n[%s]\n%s\n' % (datetime.datetime.now().isoformat(),
                                          traceback.format_exc()))
        except Exception:
            pass
        raise
