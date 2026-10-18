import { describe, expect, it, vi, afterEach } from 'vitest';
import {
  buildCompareCurvesCsv,
  buildCompareMetricsCsv,
  buildCompareTradesCsv,
  buildCsv,
  csvCell,
  downloadCsv,
  summarizeConfig,
} from '@/modules/csv';

describe('csvCell 公式注入防护', () => {
  it.each([
    ['=cmd', "'=cmd"],
    ['+1+1', "'+1+1"],
    ['-1;drop', "'-1;drop"],
    ['@sum', "'@sum"],
    ['\tx', "'\tx"],
  ])('危险前缀 %s 加撇号', (input, expected) => {
    expect(csvCell(input)).toBe(expected);
  });

  it('\\r 前缀单元格按 RFC4180 包裹（\\r 属包裹集合，裸 CR 不包裹会裂行），撇号留在包裹内部', () => {
    expect(csvCell('\rx')).toBe('"\'\rx"');
  });

  it('正常文本 / 数字 / 布尔 / null 不加撇号', () => {
    expect(csvCell('贵州茅台')).toBe('贵州茅台');
    expect(csvCell(-12.5)).toBe('-12.5');
    expect(csvCell(true)).toBe('true');
    expect(csvCell(null)).toBe('');
    expect(csvCell(undefined)).toBe('');
  });

  it.each([
    ['a,b', '"a,b"'],
    ['say "hi"', '"say ""hi"""'],
    ['gridCount=8, mode=classic', '"gridCount=8, mode=classic"'],
  ])('含逗号/引号按 RFC4180 加引号包裹（%s）', (input, expected) => {
    expect(csvCell(input)).toBe(expected);
  });

  it('危险前缀撇号在 RFC4180 包裹内部（包裹语义不覆盖注入防护）', () => {
    expect(csvCell('=a,b')).toBe('"\'=a,b"');
  });
});

describe('buildCsv', () => {
  it('表头与行按逗号/换行拼接', () => {
    expect(
      buildCsv(
        ['a', 'b'],
        [
          [1, 'x'],
          [null, 'y,z'],
        ]
      )
    ).toBe('a,b\n1,x\n,"y,z"');
  });
});

describe('summarizeConfig', () => {
  it('按插入序拼 key=value，空配置给占位', () => {
    expect(summarizeConfig({ fastPeriod: 5, slowPeriod: 20 })).toBe('fastPeriod=5, slowPeriod=20');
    expect(summarizeConfig({ gridCount: 8, mode: 'classic', lower: 90 })).toBe('gridCount=8, mode=classic, lower=90');
    expect(summarizeConfig(null)).toBe('');
  });
});

describe('buildCompareMetricsCsv', () => {
  it('行=策略，列=中文表头全集，null 落空单元格', () => {
    const csv = buildCompareMetricsCsv([
      { label: '网格', type: 'grid', params: 'gridCount=8', metrics: { returnPct: 5.2, winRatePct: null } },
      { label: 'MACD', type: 'macd', params: '', metrics: null },
    ]);
    const lines = csv.split('\n');
    expect(lines[0]).toContain('区间收益%');
    expect(lines[0]).toContain('夏普比率');
    expect(lines[1]).toContain('网格');
    expect(lines[1]).toContain('5.2');
    expect(lines[2]).toContain('MACD');
  });
});

describe('buildCompareCurvesCsv 宽表', () => {
  it('日期 + 每策略一列 + 基准列；error 策略整列省略', () => {
    const csv = buildCompareCurvesCsv({
      benchmarkCurve: [
        { date: '2026-01-01', equity: 1 },
        { date: '2026-01-02', equity: 1.01 },
      ],
      results: [
        {
          label: '网格',
          equityCurve: [
            { date: '2026-01-01', equity: 1 },
            { date: '2026-01-02', equity: 1.05 },
          ],
        },
        { label: 'MACD', equityCurve: null },
      ],
    });
    const lines = csv.split('\n');
    expect(lines[0]).toBe('日期,网格 净值,基准净值');
    expect(lines[1]).toBe('2026-01-01,1,1');
    expect(lines[2]).toBe('2026-01-02,1.05,1.01');
  });
});

describe('buildCompareTradesCsv 长表', () => {
  it('每笔成交一行；triggerPrice/module 为 null 落空', () => {
    const csv = buildCompareTradesCsv([
      {
        label: '网格',
        trades: [{ date: '2026-01-05', side: 'buy', triggerPrice: 90.5, price: 90.6, shares: 100, fee: 5 }],
      },
      {
        label: '双均线',
        trades: [
          { date: '2026-01-06', side: 'sell', triggerPrice: null, price: 100, shares: 200, fee: 5, module: 'range' },
        ],
      },
    ]);
    const lines = csv.split('\n');
    expect(lines[0]).toBe('策略,日期,方向,触发价,成交价,股数,费用,模块');
    expect(lines[1]).toBe('网格,2026-01-05,buy,90.5,90.6,100,5,');
    expect(lines[2]).toBe('双均线,2026-01-06,sell,,100,200,5,range');
  });
});

describe('downloadCsv', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    // 清理挂在 URL 上的 mock（jsdom 本就不实现 createObjectURL）
    Object.assign(URL, { createObjectURL: undefined, revokeObjectURL: undefined });
  });

  it('BOM + Blob + 文件名下载', () => {
    const createObjectURL = vi.fn((_blob: Blob) => 'blob:mock');
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.fn();
    const append = vi.fn();
    const link: Record<string, unknown> = {};
    vi.spyOn(document, 'createElement').mockImplementation((tag: string): HTMLElement => {
      if (tag === 'a') {
        return { ...link, click, style: {} } as unknown as HTMLElement;
      }
      return document.createElementNS('', tag) as unknown as HTMLElement;
    });
    vi.spyOn(document.body, 'appendChild').mockImplementation(append as never);
    downloadCsv('atlas-compare-metrics-1.csv', 'a,b');
    const blob = createObjectURL.mock.calls[0][0];
    expect(blob).toBeInstanceOf(Blob);
    expect(blob.type).toBe('text/csv;charset=utf-8;');
    // jsdom Blob.text() 按 spec 以 UTF-8 decode without BOM 解码，BOM 被剥离，
    // 无法经 text() 断言首字符；改以字节数验证：BOM(\ufeff→3 字节) + 'a,b'(3 字节) = 6。
    expect(blob.size).toBe(6);
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:mock');
  });
});
