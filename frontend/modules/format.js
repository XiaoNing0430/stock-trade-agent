// Pure formatting, escaping and time helpers. No dependencies, no Vue.
export function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return `${value >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
}

export function formatTime(timestamp) {
  if (!timestamp) return '--:--:--';
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatDateLabel(timestamp) {
  if (!timestamp) return '尚未更新';
  return `更新于 ${formatTime(timestamp)}`;
}

export function formatAmount(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  const amount = Number(value);
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(2)} 亿`;
  if (amount >= 10000) return `${(amount / 10000).toFixed(2)} 万`;
  return `${Math.round(amount).toLocaleString()} 元`;
}

export function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '¥0';
  return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
}

export function formatNullable(value, digits = 2) {
  return formatNumber(value, digits);
}

export function formatPctNullable(value) {
  return formatPct(value);
}

export function trendClass(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'trend-flat';
  return Number(value) >= 0 ? 'trend-up' : 'trend-down';
}

export function escapeHtml(value) {
  return String(value ?? '').replace(
    /[&<>"']/g,
    (char) =>
      ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;',
      })[char]
  );
}

export function validityExpiry(createdAtMs, validity) {
  if (!createdAtMs) return null;
  const base = new Date(createdAtMs);
  const year = base.getFullYear();
  const month = base.getMonth();
  const date = base.getDate();
  let end;
  if (validity === '本月内') {
    end = new Date(year, month + 1, 0, 23, 59, 59, 999);
  } else if (validity === '本周内') {
    // ISO week ends on Sunday; Monday is the first day of the week.
    const dayOfWeek = base.getDay();
    const daysUntilSunday = dayOfWeek === 0 ? 0 : 7 - dayOfWeek;
    end = new Date(year, month, date + daysUntilSunday, 23, 59, 59, 999);
  } else {
    // Default (今日) and any unknown validity: end of the creation day.
    end = new Date(year, month, date, 23, 59, 59, 999);
  }
  return end.getTime();
}
