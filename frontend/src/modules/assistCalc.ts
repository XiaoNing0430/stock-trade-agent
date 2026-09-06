/**
 * 草案调参纯函数——与 backend/assist/calculator.py 的 sizing() 逐字段镜像（FR-13）。
 * 调参仅在此重算，零 API 调用；数据不足（atr14/ma20 为 null）相应候选置 null，绝不造数。
 * 历史数据不足的 ATR/MA20 中文提示由调用方（store）负责，本模块仅产出 4 条仓位警示。
 */

/**
 * 四舍五入到 2 位小数——镜像 Python round(x, 2) 语义：
 * 最近值优先，恰好半程（.5）时舍入到偶数（银行家舍入）。
 * 恰好半程的双精度数（如 8.125 = k/8）×100 后仍精确，可正确判平；非平局由浮点真值主导，与 Python 一致。
 */
function round2(value: number): number {
  const scaled = value * 100;
  if (!Number.isFinite(scaled)) return value;
  const floor = Math.floor(scaled);
  const diff = scaled - floor;
  let rounded: number;
  if (diff > 0.5) rounded = floor + 1;
  else if (diff < 0.5) rounded = floor;
  else rounded = floor % 2 === 0 ? floor : floor + 1;
  const result = rounded / 100;
  return result === 0 ? 0 : result; // 归一 -0，避免 -0 !== 0 的比较问题
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
export function selectStop(entry: number, atr14: number | null, ma20: number | null, stopMode: 'atr' | 'ma20'): StopCandidate {
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
