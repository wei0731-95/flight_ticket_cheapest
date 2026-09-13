"""JavaScript snippets evaluated inside the trip.com page."""

# Hides the most obvious headless tells before any page script runs.
STEALTH_INIT = """
() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  Object.defineProperty(navigator, 'languages', { get: () => ['zh-TW', 'zh', 'en-US', 'en'] });
  Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
  Object.defineProperty(navigator, 'hardwareConcurrency', { get: () => 8 });
  Object.defineProperty(navigator, 'deviceMemory', { get: () => 8 });
  window.chrome = window.chrome || { runtime: {}, app: {}, csi: () => {}, loadTimes: () => {} };
  const query = window.navigator.permissions && window.navigator.permissions.query;
  if (query) {
    window.navigator.permissions.query = (params) =>
      params && params.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : query(params);
  }
  const getParameter = WebGLRenderingContext.prototype.getParameter;
  WebGLRenderingContext.prototype.getParameter = function (param) {
    if (param === 37445) return 'Intel Inc.';
    if (param === 37446) return 'Intel Iris OpenGL Engine';
    return getParameter.apply(this, arguments);
  };
}
"""

# True once the page is showing enough currency amounts to look like results.
HAS_PRICES = """
(minCount) => {
  const text = document.body ? document.body.innerText : '';
  const matches = text.match(/(?:NT\\$|TWD|NTD|US\\$|\\$)\\s*\\d[\\d,]{2,}/g) || [];
  return matches.length >= minCount;
}
"""

# Scrape result cards without depending on trip.com's class names: a card is the
# *smallest* element that holds a price and at least two clock times.
COLLECT_CARDS = """
(options) => {
  const { selectors, limit } = options;
  const PRICE = /(?:NT\\$|TWD|NTD|US\\$|\\$)\\s*\\d[\\d,]{2,}/;
  const TIME = /\\b\\d{1,2}:\\d{2}\\b/g;

  const describe = (el) => {
    const link = el.querySelector('a[href]');
    return {
      text: (el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 1500),
      href: link ? link.href : '',
    };
  };

  for (const selector of selectors || []) {
    let matched = [];
    try { matched = Array.from(document.querySelectorAll(selector)); } catch (e) { continue; }
    const usable = matched.filter((el) => PRICE.test(el.innerText || ''));
    if (usable.length) return usable.slice(0, limit).map(describe);
  }

  const candidates = Array.from(document.querySelectorAll('li, div, article, section')).filter((el) => {
    const text = el.innerText || '';
    if (!text || text.length > 2000 || !PRICE.test(text)) return false;
    return (text.match(TIME) || []).length >= 2;
  });
  // Keep only the innermost candidates so each card maps to one itinerary.
  const minimal = candidates.filter((el) => !candidates.some((other) => other !== el && el.contains(other)));
  return minimal.slice(0, limit).map(describe);
}
"""

# Signals that we got a bot wall instead of search results.
BLOCK_MARKERS = (
    "captcha",
    "recaptcha",
    "unusual traffic",
    "access denied",
    "verify you are human",
    "are you a robot",
    "請驗證",
    "请验证",
    "安全驗證",
    "安全验证",
    "驗證碼",
    "验证码",
)


# trip.com's Search control is not a <button> or <a>, so it cannot be found by
# tag. Locate the innermost visible element whose text is exactly "Search" and
# hand back its centre point: clicking it through Playwright's mouse produces a
# trusted event, which a JS .click() does not.
FIND_SEARCH_TARGET = """
() => {
  const WANT = /^(search|搜尋|搜索|查詢|検索)$/i;
  const nodes = Array.from(document.querySelectorAll(
    'button, a, span, div, li, input[type="submit"], input[type="button"], [role="button"]'
  ));
  const matches = nodes.filter((el) => {
    const label = el.tagName === 'INPUT' ? (el.value || '') : (el.textContent || '');
    if (!WANT.test(label.trim())) return false;
    const rect = el.getBoundingClientRect();
    return rect.width > 8 && rect.height > 8;
  });
  if (!matches.length) {
    // Nothing matched: report what clickable labels the page does have, so a
    // failure still says why.
    const sample = nodes
      .map((el) => (el.textContent || '').trim())
      .filter((t) => t && t.length < 24)
      .slice(0, 40);
    return { found: false, sample: Array.from(new Set(sample)).slice(0, 25) };
  }
  // Innermost wins: an ancestor can contain the word without being the control.
  matches.sort((a, b) => (a.textContent || '').length - (b.textContent || '').length
                      || (a.getBoundingClientRect().width * a.getBoundingClientRect().height)
                       - (b.getBoundingClientRect().width * b.getBoundingClientRect().height));
  const target = matches[0];
  target.scrollIntoView({ block: 'center', inline: 'center' });
  const rect = target.getBoundingClientRect();
  return {
    found: true,
    x: rect.left + rect.width / 2,
    y: rect.top + rect.height / 2,
    tag: target.tagName,
    cls: String(target.className || '').slice(0, 120),
    text: (target.textContent || '').trim().slice(0, 40),
  };
}
"""
