# TQRelay — 通达信TQ转发器

![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)

把通达信 TQ 量化服务（tqcenter，默认只监听 `127.0.0.1:17709`）以 HTTP 方式暴露给局域网内其他机器，让**大QMT、其他 Python 进程、任何能发 HTTP 的客户端**跨机调用通达信的**全部接口**：K线、实时快照、公式引擎（含 `WINNER`/`COST` 等筹码函数，由通达信原生计算）、基础信息、板块、财务、股本、涨跌停、交易查询与下单。

```
机器B(大QMT/任意Python) --HTTP POST--> 机器A(TQRelay 0.0.0.0:17710) --127.0.0.1:17709--> 通达信TQ服务
```

## 为什么需要它

- 通达信与 QMT 不装在同一台机器时，QMT 策略无法访问 TQ 服务。
- 部分 QMT 平台策略**禁止读写外部文件**、**MiniQMT 接口已停用**——HTTP 是少数可行通道。
- 公式类接口由通达信引擎原生计算：**WINNER/COST 等筹码函数与通达信图上指标 100% 一致**。
  （用换手率衰减+三角分布纯 Python 复现筹码，信号段起点当日吻合度实测只有约 73%，不要在客户端重算筹码。）

## 特性

- `POST /tq` **通用透传**：任意 TQ 接口零维护支持，返回 TQ 原始 JSON
- token 鉴权；交易类接口可用 `allow_trade` 开关整体禁用
- **透明端口模式**（可选）：无 token 纯透传端口，配合客户端 `netsh portproxy`，让写死 `127.0.0.1:17709` 的 tqcenter.py 旧代码零改动跨机运行
- GUI（tkinter）：启停、端口/token/通达信路径/日志目录/TQ地址/透明端口全部可视化配置、连通自检、通达信测试、来源 IP 日志
- 按日期分文件日志；错误独立落盘；TQ 调用全局锁串行化
- **纯 Python 标准库**，无第三方依赖；PyInstaller 可打包单文件 exe

## 快速开始

0. **免安装运行**：从 [Releases](https://github.com/foxneet/tq-relay/releases/latest) 下载 `TQRelay_1.0.1.exe`（PyInstaller 单文件），双击运行即可，首次启动自动生成配置与随机 token；发行说明附 sha256 可核对文件完整性。
1. 在**通达信所在机器**（机器A）运行 `python tq_relay.py`（GUI 自动开服务），或
   `python tq_relay.py --serve`（无界面后台）。首次运行自动生成配置文件 `TQ转发器_配置.json`（token 自动随机生成）。
2. 放行防火墙：首次弹窗允许，或
   `netsh advfirewall firewall add rule name="TQRelay" dir=in action=allow protocol=TCP localport=17710`
3. 在局域网其他机器测试：

```bash
curl "http://<机器A_IP>:17710/ping?token=<token>"
```

## 配置（TQ转发器_配置.json）

| 字段 | 默认 | 说明 |
|---|---|---|
| `port` | 17710 | 主端口（token 鉴权） |
| `token` | 自动生成 | 鉴权令牌；首次运行也会采纳环境变量 `SIGNAL_TOKEN` |
| `tdx_path` | 空 | 通达信安装目录（展示/备用） |
| `log_dir` | 日志 | 日志目录（相对 exe 目录或绝对路径），按日期分文件 |
| `tq_url` | http://127.0.0.1:17709/ | 本机 TQ 服务地址 |
| `timeout_sec` | 300 | 转发 TQ 调用超时（重公式计算建议加大） |
| `allow_trade` | true | false 时拒绝交易类接口（order_stock 等） |
| `max_body_mb` | 20 | 请求包体上限 |
| `transparent_enabled` | false | 透明端口模式开关 |
| `transparent_port` | 17711 | 透明端口（勿与 TQ 本尊 17709 冲突） |
| `allow_ips` | 空 | 透明端口来源 IP 白名单（逗号分隔，空=全部允许） |

## 接口规范

### POST /tq?token=...（核心）

```
Body: {"method": "<TQ接口名>", "params": {<参数字典>}}
返回: TQ 原始 JSON（原样透传）
```

错误分两层，**都要检查**：

```json
转发层: {"error": "TQ forward failed: ..."}          // 连接/超时/参数问题
TQ层:   {"id":1, "result": {"ErrorId":"0", ...}}      // ErrorId != "0" 表示 TQ 业务失败
```

### GET /ping?token=...

`{"ok": true, "service": "tq_relay", "version": "1.0.1", ...}`

### 透明端口（勾选开启后）

`POST http://<机器A>:<透明端口>/<任意路径>` —— body 原样转发给 TQ，无 token。
客户端端口映射（让 tqcenter.py 旧代码零改动跨机）：

```
netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=17709 connectaddress=<机器A_IP> connectport=<透明端口>
```

## 客户端示例

### 自带封装客户端（推荐）

`skills/tq-relay/scripts/tq_client.py`——纯标准库，CLI 与 Python 类两种用法，已封装两层错误检查（转发层 + TQ 层），失败统一抛 `TQRelayError`：

```bash
py -3.14 skills/tq-relay/scripts/tq_client.py ping --host <机器A_IP> --token <token>
py -3.14 skills/tq-relay/scripts/tq_client.py call --host <机器A_IP> --token <token> \
    --method get_market_snapshot --params "{\"stock_code\":\"159582.SZ\"}"
```

接口速查见 [`skills/tq-relay/references/interfaces.md`](skills/tq-relay/references/interfaces.md)。

### Python（任意机器、任意 Python 3.x）

```python
import json
import urllib.request

RELAY = 'http://192.168.1.100:17710'
TOKEN = '你的token'

def tq(method, params, timeout=300):
    url = '%s/tq?token=%s' % (RELAY, urllib.parse.quote(TOKEN))
    req = urllib.request.Request(url,
        data=json.dumps({'method': method, 'params': params}, ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))

def tq_ok(resp):
    """TQ层成功判断（部分接口 result 直接是数据）"""
    if 'error' in resp:
        return False
    r = resp.get('result', resp)
    return not (isinstance(r, dict) and str(r.get('ErrorId', '0')) not in ('0', ''))

# 例：取日线
resp = tq('get_market_data', {'stock_list': ['159582.SZ'], 'period': '1d',
          'start_time': '20260901', 'end_time': '20260924',
          'dividend_type': 'front', 'fill_data': False})
k = resp['result']['Value']['159582.SZ']
print(len(k['Date']), k['Date'][-1], k['Close'][-1])
```

### 大QMT 策略内

平台实测限制（2026-09，国信 iQuant 平台）：

1. 策略**禁止读写外部文件** → 配置/信号一律走 HTTP；
2. MiniQMT 接口已停用 → 不要走 xtquant；
3. **策略进程读不到 setx 的用户环境变量** → token 用常量手工粘贴；
4. 内置 Python 的 `urllib` 可用（HTTP 实测通过）；
5. 源码声明 `#coding:gbk` 时，文件字节必须真是 GBK（含中文协议字符串——如公式名——的文件需转 GBK 保存；纯 ASCII 文件无此问题）。

```python
#coding:gbk
# QMT strategy calling TDX via LAN relay (template)
import json
import os

SIGNAL_HOST = '192.168.1.100'      # machine A LAN IP
SIGNAL_PORT = 17710
TOKEN_FALLBACK = ''                # <- paste token here (env var NOT reliable
                                   #    on some QMT platforms)
TOKEN = os.environ.get('SIGNAL_TOKEN', '') or TOKEN_FALLBACK
URL_TQ = 'http://%s:%d/tq?token=%s' % (SIGNAL_HOST, SIGNAL_PORT, TOKEN)


def tq(method, params, timeout=300):
    import urllib.request
    req = urllib.request.Request(URL_TQ,
        data=json.dumps({'method': method, 'params': params},
                        ensure_ascii=False).encode('utf-8'),
        headers={'Content-Type': 'application/json; charset=utf-8'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode('utf-8', 'replace'))


def handlebar(ContextInfo):
    resp = tq('get_market_data', {'stock_list': ['518880.SH'], 'period': '1d',
               'start_time': '20260901', 'end_time': '20260924',
               'dividend_type': 'front', 'fill_data': False})
    d = resp['result']['Value']['518880.SH']
    print('bars:', len(d['Date']), 'last close:', d['Close'][-1])


def init(ContextInfo):
    handlebar(ContextInfo)     # debug mode: fire once


def main_on_tick(ContextInfo):
    pass
```

策略结构建议：用 `ContextInfo.run_time('task', '1nDay', '2026-01-01 14:50:00')` 做收盘前定时动作
（仅实盘/模拟模式生效；调试模式在 `init` 里直接调用一次做干跑）；下单
`passorder(23, 1101, ACCOUNT, code, 5, -1, vol, '策略名', 2, '备注', ContextInfo)`（23=买 24=卖，quicktrade=2）；
持仓用 `get_trade_detail_data(ACCOUNT, 'stock', 'position')` 的 `m_nCanUseVolume` 尊重 T+1；
**失败安全**：转发失败/超时/日期不符 → 当日不动仓位并打日志。

## 常用 TQ 接口速查（全部经本转发器实测）

> 代码格式 `159582.SZ`/`518880.SH`；`dividend_type`：get_market_data 用字符串 `'none'/'front'/'back'`，
> formula 接口用**整数** `0=不复权, 1=前复权`（实测确认）。返回值挂在 `resp['result']` 下。

| method | 关键 params | result 要点 |
|---|---|---|
| `get_market_data` | stock_list, period='1d', start_time/end_time(YYYYMMDD), dividend_type, fill_data=False | `Value['<code>'].{Date,Open,High,Low,Close,Volume(股),Amount(万元),VolInStock,ForwardFactor,...}`；**窗口>约2年会分页**（`KlinePaged`/`has_more`），全历史按年份分窗拼接 |
| `formula_process_mul_zb` | formula_name, stock_list, stock_period, start_time(建议19900101), end_time, return_date=True, return_count(末尾N根), dividend_type(1=前复权), xsflag(小数位) | `result['<code>']['<输出行名>'] = [{'Date','Value'},...]`；输出行名/公式名为中文；未命名行叫 OUTPUTn；筹码函数由通达信原生计算 |
| `get_market_snapshot` | stock_code | `result.Now/LastClose/Volume/...` |
| `get_stock_info` | stock_code | `result.Name/ActiveCapital(流通股本,万股)/J_start(上市日)/HSStockKind(7=基金)...` |
| `get_match_stkinfo` | key_word(中文名) | `result.Value=[{Code,Name},...]` |
| `get_stock_list` | market('31'=全部ETF基金), list_type 0/1 | `result.Value` |
| `get_more_info` | stock_code | `result.fHSL(换手)/Zsz/Ltsz/ZTPrice/...`（个别字段对部分品种为空） |
| `get_gb_info_by_date` | stock_code, start_date, end_date | `result.Value=[{Date,Zgb,Ltgb},...]`（历史逐日股本→精确换手率） |
| `get_divid_factors` | stock_code | `result.Value`（ETF可能为空） |
| `get_zdt_data` | stock_list | `result.Value['<code>'].{ZDTStatusNow,...}` |
| `get_trading_dates` | market, start_time, end_time | `result.Value`（个别参数组合实测返回空，用前自验） |
| `query_stock_positions` | account_id(默认0) | `result.{ErrorId,Value}`；需通达信端登录资金账户 |
| `order_stock` | account_id, stock_code, order_type(0买1卖), order_volume, price_type, price | 交易类；受 `allow_trade` 约束；需通达信端登录资金账户 |

完整接口清单见通达信官方 `help.tdx.com.cn/quant/`——tqcenter 有的接口，转发器都能调。

## 已知坑（实测踩过的）

1. **K线分页**：单次窗口>约2年时 `KlinePaged=true` 只回一页——按年份分窗拼接并核对 `has_more`。
2. **筹码函数别在客户端重算**：精确算法私有，近似复现信号段起点当日命中率约 73%。
3. **公式喂入窗口影响筹码**：要与通达信图一致就 `start_time=19900101` 喂全历史，用 `return_count` 只取末尾 N 根。
4. **复权参数类型**：get_market_data 用字符串，formula 接口用整数（`0=不复权, 1=前复权`）。
5. **公式输出默认四舍五入**：阈值判断（如 高度控盘>0）必须 `xsflag=3` 以上精度。
6. **品种覆盖**：部分品种通达信端"查无此码"（基金市场资料未下载全），先在通达信手动打开该品种促使下载。
7. **串行化**：全局锁排队，并发请求不会并行；批量任务预估排队时间。
8. **代码执行类用法不支持**：转发器转发接口调用，不转发"整段策略代码交给通达信跑"的托管模式。

## 故障排查

| 现象 | 原因 | 处理 |
|---|---|---|
| `{'error': 'token错误'}` | token 不对/为空 | 机器A 配置文件或 GUI 查 token |
| ConnectionRefused | 转发器没运行/端口错/防火墙 | 机器A 起 exe；放行端口 |
| 超时 | 重公式计算中/TQ 卡死 | 加大客户端超时；看机器A日志 |
| `result.Error`="资金账户未登录" | 通达信端无交易账户 | 登录资金账户，或不用交易接口 |
| K线根数不符 | 分页 | 按年份分窗拼接 |
| 公式返回空/值全0 | 喂入窗口太短或品种无本地数据 | start_time=19900101；先在通达信打开该品种 |

## 安全说明

- 主端口有 token，但 token 经 URL 查询参数传递——请确保局域网可信，或在前端加反向代理做 header 鉴权。
- 透明端口**无 token**（兼容性设计），务必：只在可信局域网开启、配置 `allow_ips` 白名单、不需要交易时关掉 `allow_trade`。
- 所有请求（来源 IP、方法、参数摘要、耗时）按日期记录在日志目录。

## 验证状态

双机环境（通达信机 + 国信 iQuant QMT 端）实测：16 项功能自测全部通过
（鉴权/K线/快照/基础信息/名称检索/ETF列表/交易日历/扩展信息/股本/除权/涨跌停/公式真筹码/持仓查询/便捷接口/透明端口）。
测试脚本见 [`tests/selftest_qmt.py`](tests/selftest_qmt.py)。

## 仓库结构

```
├── README.md                    本文件(完整使用文档)
├── AGENTS.md                    面向 AI agent 的使用与维护指南
├── tq_relay.py                  服务端(纯标准库, GUI + --serve 双模式)
├── tests/selftest_qmt.py        QMT端16项双机自测策略(GBK, 整段粘贴进QMT运行)
├── skills/tq-relay/             ZCode skill: SKILL.md + scripts/tq_client.py 客户端
│                                + references/interfaces.md 接口速查
└── requirements.txt             无第三方依赖说明(仅打包需要 PyInstaller)
```

## 版本

- **1.0.1**：修复 GUI 模式缺失 `import queue` 导致的启动崩溃（`--serve` 模式不受影响，故此前未被发现）。Release 提供 `TQRelay_1.0.1.exe` 免安装版。
- **1.0.0**：首个发布版，双机 16 项自测通过。

## License

[MIT](LICENSE) — 可自由使用、修改、商用（含闭源衍生），需保留版权声明；软件按"现状"提供，不含任何担保。
