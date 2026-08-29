# 全市场选股器探索设计 — 2026-08-30

## 现状

`load_screener()` 仅使用 `REAL_UNIVERSE`（50 只精选标的），按代码批量查腾讯行情，按涨跌幅排序，前端无分页。

## 数据源探索

### 腾讯 `getBoardRankList`（⭐ 推荐，已验证）

- **端点**: `https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList`
- **参数**: `board_code=aStock`（全 A 股站内），`sort_type=price|turnover`，`direct=down|up`，`offset=N`，`count=N`
- **总标的**: 4596 只（沪深 A 股，不含北交所）
- **字段**:
  - `code`/`name`/`zxj`（最新价）/`zdf`（涨跌幅 %）/`zd`（涨跌额）
  - `zdf_d5`/`zdf_d10`/`zdf_d20`/`zdf_d60`/`zdf_w52`/`zdf_y`（5-60 日/52 周/年内涨跌幅）
  - `pe_ttm`/`pn`（市净率）/`zsz`（总市值）/`ltsz`（流通市值）
  - `hsl`（换手率 %）/`turnover`（成交额 万）/`volume`（成交量 手）
  - `zf`（振幅 %）/`lb`（量比）/`speed`（涨速）
  - `zljlr`（主力净流入）/`zllr`/`zllc`（主力流入/流出）
- **连通性**: 稳定（本项目已验证，腾讯域）
- **限制**: 涨跌幅排序（sort_type 名）未探明；不含北交所

### 东方财富 `push2 clist`（备选，首次可达但代理不稳定）

- **端点**: `https://push2.eastmoney.com/api/qt/clist/get`
- **参数**: `fs=m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23`（深沪 A），`fid=f3`（按涨跌幅排序），`po=1`（降序），`pn=N`（页码），`pz=N`（每页），`fields=...`
- **总标的**: 5554 只（含北交所）
- **字段**: 通过 `fields` 参数自由选择，支持涨跌幅/成交量/成交额/换手率/市盈率/流通市值等
- **连通性**: 当前代理下偶发失败（502/https 被拒），但首次探针成功可达
- **优势**: 支持任意字段排序，标的更全

### 推荐方案

**腾讯 `getBoardRankList` 作为主数据源**（稳定、同域、无需额外配置），原因：
1. 本项目已验证腾讯 API 稳定（`qt.gtimg.cn` 长期稳定）
2. 返回字段丰富（股价/PE/PB/市值/换手/涨跌幅/主力资金/多周期涨跌幅）
3. 无 token/配额限制
4. 4596 只覆盖沪深 A 股主流标的

**东方财富作为备选升级路径**，如需：
- 涨跌幅排序（若腾讯 sort_type 不支）
- 北交所覆盖
- 更高筛选灵活性

## 架构设计

### 后端：`data_source.py` 新增 `load_screener_v2()`

```python
SCREENER_URL = "https://proxy.finance.qq.com/cgi/cgi-bin/rank/hs/getBoardRankList"

def load_screener_v2(page: int = 1, page_size: int = 50, sort_by: str = "zdf",
                     sort_dir: str = "down", market: str = "全部") -> dict:
    """腾讯全市场排名接口，分页返回。"""
    params = {
        "board_code": "aStock",
        "sort_type": _map_sort_field(sort_by),  # "zdf"/"turnover"/"price" → 腾讯字段名
        "direct": "down" if sort_dir == "desc" else "up",
        "offset": str((page - 1) * page_size),
        "count": str(page_size),
    }
    try:
        resp = requests.get(SCREENER_URL, params=params, timeout=10)
        data = resp.json()["data"]
        rows = []
        for item in data.get("rank_list", []):
            rows.append(_normalize_rank_item(item))
        return {"total": data.get("total", 0), "page": page, "pageSize": page_size,
                "rows": rows, "provider": "Tencent rank API"}
    except Exception as exc:
        raise RuntimeError(f"全市场选股器请求失败: {exc}") from exc
```

### 字段映射

| 腾讯字段 | 标准化字段 | 含义 |
|----------|-----------|------|
| `code` | `code` | 代码（含前缀如 `sh600519`） |
| `name` | `name` | 名称 |
| `zxj` | `price` | 最新价 |
| `zdf` | `changePct` | 涨跌幅 % |
| `zd` | `change` | 涨跌额 |
| `zsz` | `totalMarketCap` | 总市值(亿) |
| `ltsz` | `circulatingMarketCap` | 流通市值(亿) |
| `pe_ttm` | `peTtm` | 市盈率 |
| `pn` | `pb` | 市净率 |
| `hsl` | `turnoverRate` | 换手率 % |
| `turnover` | `amount` | 成交额(万) |
| `volume` | `volume` | 成交量(手) |
| `zf` | `amplitude` | 振幅 % |
| `lb` | `volumeRatio` | 量比 |
| `zdf_d5`/`d10`/`d20`/`d60`/`w52`/`y` | `changePct5d`..`changePctYtd` | 多周期涨跌幅 |
| `zljlr` | `netMoneyFlow` | 主力净流入(万) |
| `speed` | `speed` | 涨速 % |

### 前端

- 现有选股器视图（`view === 'screener'`）升级为分页表格
- 表头支持点击排序（按涨跌幅/成交额/换手率/市值等）
- 分页器（`上一页 / 下一页 / 跳转`）
- 搜索框（按代码/名称实时过滤客户端侧）
- 保留现有 `REAL_UNIVERSE` 作为"精选"标签供切换

### 缓存策略

- 全市场列表缓存 60s（手动刷新时更新），避免高频轮询
- 单只股票详情仍走 `load_quotes` 实时（8s TTL）

## 待确认

- [ ] 腾讯 `getBoardRankList` 涨跌幅排序的 `sort_type` 值（需更多探针或文档查证）
- [ ] 是否保留 `REAL_UNIVERSE` 精选列表作为可选"精选"标签
- [ ] 排序字段优先级（默认按涨跌幅还是按成交额）

## 非目标

- 不改变现有 `load_screener()` 函数（保留兼容）
- 不作实时轮询（全市场列表手动刷新或 60s 缓存）
- 不引入新数据源依赖（以东财/腾讯免费接口为限）