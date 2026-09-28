---
name: tq-relay
description: 通过 TQRelay 局域网 HTTP 网关跨机调用通达信TQ量化服务（tqcenter）全部接口：K线、实时快照、公式引擎原生筹码（WINNER/COST）、基础信息、股本、涨跌停、交易查询与下单。当用户提到 TQRelay、TQ转发器、跨机调用通达信、QMT 策略要拿通达信数据、tqcenter 远程访问、17710/17711 端口、通达信在另一台机器上，或本机直连 17709 失败且通达信在局域网其他机器时使用。ZCode 与通达信同机直连请用「通达信TQ-Local」skill。
---

# 通达信TQ转发器（TQRelay）

把通达信 TQ 量化服务（tqcenter，只监听 `127.0.0.1:17709`）以 HTTP 方式暴露给局域网：ZCode/大QMT/任意 Python 在**另一台机器**上即可调用通达信全部接口。

```
本机(ZCode/QMT) --HTTP POST--> 通达信机(TQRelay :17710, token鉴权) --127.0.0.1:17709--> tqcenter
```

## 先判断走哪条路

| 场景 | 用法 |
|---|---|
| ZCode 与通达信**同机** | 不用本 skill——直连 `127.0.0.1:17709`（见「通达信TQ-Local」skill） |
| ZCode 与通达信**不同机**、通达信机已部署 TQRelay | 本 skill，网关地址 `http://<通达信机IP>:17710` |
| 通达信机还没部署 TQRelay | 先部署（见下文「部署」），项目即本仓库（GitHub: foxneet/tq-relay） |

不确定网关通不通，先做健康检查（本 skill 自带客户端一步完成）：

```bash
py -3.14 <本skill目录>/scripts/tq_client.py ping --host <通达信机IP> --token <token>
```

## token 从哪来

TQRelay 首次运行在**通达信机**上自动生成配置文件 `TQ转发器_配置.json`（token 在里面，GUI 也可查/改）；服务端也可用环境变量 `SIGNAL_TOKEN`。拿到 token 后再调用。**token 是机密，不要写进代码仓库。**

## 调用方式（推荐用自带客户端）

### 命令行

```bash
S=<本skill目录>/scripts/tq_client.py        # 安装后位于 ~/.zcode/skills/tq-relay/scripts/tq_client.py
py -3.14 $S ping --host 192.168.1.100 --token XXX
py -3.14 $S call --host 192.168.1.100 --token XXX --method get_market_snapshot \
  --params "{\"stock_code\":\"159582.SZ\"}"
```

### Python 内嵌

```python
import sys; sys.path.insert(0, r'<本skill目录>/scripts')
from tq_client import TQRelay, TQRelayError

relay = TQRelay('192.168.1.100', token='XXX', timeout=300)
snap = relay.call('get_market_snapshot', {'stock_code': '159582.SZ'})
k = relay.call('get_market_data', {'stock_list': ['159582.SZ'], 'period': '1d',
               'start_time': '20260901', 'end_time': '20260924',
               'dividend_type': 'front', 'fill_data': False})
bars = k['result']['Value']['159582.SZ']
```

客户端已内置两层错误检查与清晰报错，直接 try `TQRelayError` 即可。

## 调用规范（必须遵守，全部实测踩坑）

1. **两层错误都要查**：转发层 `{"error": "..."}`（连接/超时/token），TQ 层 `result.ErrorId != "0"`（业务失败）。客户端已封装。
2. **复权参数类型不统一**：`get_market_data` 用字符串 `'none'/'front'/'back'`；formula 接口（`formula_process_mul_zb`）用**整数** `0=不复权, 1=前复权`。搞混会静默返回错数据。
3. **K线分页**：单窗超约 2 年只回一页（`KlinePaged=true`/`has_more`）——按年份分窗拼接，不要一次拉全历史。
4. **公式喂入窗口影响筹码结果**：要与通达信图一致就 `start_time=19900101` 喂全历史 + `return_count` 只取末尾 N 根；**筹码函数（WINNER/COST）必须走公式接口让通达信原生算**——纯 Python 复现对图吻合度仅约 73%，不要自己算。
5. **公式输出默认四舍五入**：阈值判断（如 高度控盘>0）必须 `xsflag=3` 以上精度。
6. **串行化**：TQ 调用全局锁排队，不会并行；批量任务预估排队时间、加大 timeout（重公式建议 300s）。
7. **品种"查无此码"**：先在通达信手动打开该品种促发本地数据下载。
8. **交易接口**：`query_stock_positions`/`order_stock` 需通达信端登录资金账户；服务端 `allow_trade=false` 时整体禁用（研究部署建议关闭）。

## 部署（通达信机上，一次性）

```bash
python tq_relay.py            # GUI 模式，自动生成配置与随机 token
python tq_relay.py --serve    # 无界面后台
netsh advfirewall firewall add rule name="TQRelay" dir=in action=allow protocol=TCP localport=17710
```

透明端口模式（可选，17711 无 token 纯透传）：让写死 `127.0.0.1:17709` 的存量 tqcenter.py 旧代码零改动跨机——客户端执行
`netsh interface portproxy add v4tov4 listenaddress=127.0.0.1 listenport=17709 connectaddress=<通达信机IP> connectport=17711`。
透明端口无鉴权，务必配 `allow_ips` 白名单、不需要交易就关 `allow_trade`。

## 深入参考

- 全量 TQ 接口速查（参数/返回结构/实测要点）：读本目录 `references/interfaces.md`
- 完整使用文档与 QMT 内嵌模板：仓库 `README.md`；agent 维护指南：仓库 `AGENTS.md`
- QMT 端 16 项双机自测策略：仓库 `tests/selftest_qmt.py`
