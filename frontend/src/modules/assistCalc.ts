/**
 * 草案调参纯函数——与 backend/assist/calculator.py 的 sizing() 逐字段镜像（FR-13）。
 * 调参仅在此重算，零 API 调用；数据不足（atr14/ma20 为 null）相应候选置 null，绝不造数。
 * 历史数据不足的 ATR/MA20 中文提示由调用方（store）负责，本模块仅产出 4 条仓位警示。
 */

/** Python round(x, 2) 的精确等价：按 double 精确二进制值做十进制半程偶舍（BigInt 分解，勿用浮点缩放）。 */
function round2(value: number): number {
  if (!Number.isFinite(value)) return value;
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, value);
  const bits = view.getBigUint64(0);
  const exp = Number((bits >> 52n) & 0x7ffn);
  const frac = bits & 0xfffffffffffffn;
  const sign = value < 0 ? -1n : 1n;
  let m: bigint;
  let e: number;
  if (exp === 0) {
    m = frac;
    e = -1074;
  } else {
    m = frac | (1n << 52n);
    e = exp - 1075;
  }
  let q: bigint;
  if (e >= 0) {
    q = (m << BigInt(e)) * 100n; // 整数值，×100 后无需舍入
  } else {
    const num = m * 100n;
    const den = 1n << BigInt(-e);
    q = num / den;
    const twice = (num % den) * 2n;
    if (twice > den || (twice === den && q % 2n === 1n)) q += 1n;
  }
  return Number(sign * q) / 100;
}

export interface StopCandidate {
  stop: number | null;
  warnings: string[];
}

export interface SizingInput {
  entry: number;
  stopMode: 'atr' | 'ma20';
  atr14: number | null;
  ma20: number | null;
  equity: number;
  riskPct: number;
  rrRatio: number;
  capPct: number;
  limitRatio: number;
}

export interface SizingOutput {
  stop: number | null;
  target: number | null;
  stopDistance: number | null;
  suggestedShares: number;
  positionPct: number;
  warnings: string[];
}

/** 按模式选首选候选，无效（null 或 ≥ 入场价）回退备选；均无效则置空并提示手动设定。 */
export function selectStop(
  entry: number,
  atr14: number | null,
  ma20: number | null,
  stopMode: 'atr' | 'ma20'
): StopCandidate {
  const stopAtr = atr14 !== null ? round2(entry - 2 * atr14) : null;
  const stopMa20 = ma20 !== null ? round2(ma20) : null;
  const preferred = stopMode === 'atr' ? stopAtr : stopMa20;
  const alternate = stopMode === 'atr' ? stopMa20 : stopAtr;
  const stop = [preferred, alternate].find((c) => c !== null && c < entry) ?? null;
  const warnings: string[] = [];
  if (stop === null && (preferred !== null || alternate !== null)) {
    warnings.push('候选止损价均不低于入场价，已置空止损（强趋势 / 数据不足），请手动设定');
  }
  return { stop, warnings };
}

/** 单日涨跌幅上限（镜像 backend/data_source.py price_limit_ratio：主板 10% / 创业板·科创板 20% / 北交所 30%）。 */
export function priceLimitRatio(code: string): 0.1 | 0.2 | 0.3 {
  const trimmed = code.trim();
  if (trimmed.startsWith('4') || trimmed.startsWith('8')) return 0.3;
  if (trimmed.startsWith('68')) return 0.2;
  if (trimmed.startsWith('30')) return 0.2;
  return 0.1;
}

export interface SizingAtStopInput {
  entry: number;
  stop: number | null;
  equity: number;
  riskPct: number;
  rrRatio: number;
  capPct: number;
  limitRatio: number;
}

/**
 * 以调用方已定的止损现算目标 / 风险仓位（手动止损也走同一口径，与 backend sizing() 的
 * stop 之后分支逐字段一致）；警示不含 selectStop 的候选价警示，由调用方按顺序合并。
 */
export function sizePositionAtStop(input: SizingAtStopInput): SizingOutput {
  const { entry, stop, equity, riskPct, rrRatio, capPct, limitRatio } = input;
  const warnings: string[] = [];
  let target: number | null = null;
  let stopDistance: number | null = null;
  let shares = 0;
  let positionPct = 0;
  if (stop !== null) {
    const safeDistance = round2(entry - stop);
    if (safeDistance > 0) {
      stopDistance = safeDistance;
      const riskAmount = round2((equity * riskPct) / 100.0);
      shares = Math.floor(riskAmount / stopDistance / 100.0) * 100;
      const capShares = Math.floor((equity * capPct) / 100.0 / entry / 100.0) * 100;
      if (shares <= 0) {
        warnings.push('权益不足一手，无法按该风险比例建仓');
      } else if (shares > capShares) {
        shares = Math.max(capShares, 0);
        warnings.push('建议仓位已按单票市值上限截断');
      }
      target = round2(entry + stopDistance * rrRatio);
      if ((target - entry) / entry > limitRatio) {
        warnings.push('目标位距入场价超单日涨幅上限，需多日达成');
      }
      if (shares > 0) {
        positionPct = round2(((shares * entry) / equity) * 100.0);
      }
    }
  }
  return {
    stop,
    target,
    stopDistance,
    suggestedShares: Math.max(shares, 0),
    positionPct,
    warnings,
  };
}

export function sizePosition(input: SizingInput): SizingOutput {
  const { entry, stopMode, atr14, ma20, equity, riskPct, rrRatio, capPct, limitRatio } = input;
  const { stop, warnings } = selectStop(entry, atr14, ma20, stopMode);
  let target: number | null = null;
  let stopDistance: number | null = null;
  let shares = 0;
  let positionPct = 0;
  if (stop !== null) {
    stopDistance = round2(entry - stop);
    const riskAmount = round2((equity * riskPct) / 100.0);
    shares = Math.floor(riskAmount / stopDistance / 100.0) * 100;
    const capShares = Math.floor((equity * capPct) / 100.0 / entry / 100.0) * 100;
    if (shares <= 0) {
      warnings.push('权益不足一手，无法按该风险比例建仓');
    } else if (shares > capShares) {
      shares = Math.max(capShares, 0);
      warnings.push('建议仓位已按单票市值上限截断');
    }
    target = round2(entry + stopDistance * rrRatio);
    if ((target - entry) / entry > limitRatio) {
      warnings.push('目标位距入场价超单日涨幅上限，需多日达成');
    }
    if (shares > 0) {
      positionPct = round2(((shares * entry) / equity) * 100.0);
    }
  }
  return {
    stop,
    target,
    stopDistance,
    suggestedShares: Math.max(shares, 0),
    positionPct,
    warnings,
  };
}
