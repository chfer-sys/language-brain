# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: hanzi-with-pinyin.spec.ts >> T4 — default page search shows hanzi via HanziWithPinyin
- Location: tests/hanzi-with-pinyin.spec.ts:18:1

# Error details

```
Error: expect(locator).toHaveCount(expected) failed

Locator:  locator('[data-testid="result-row"]')
Expected: 2
Received: 8
Timeout:  5000ms

Call log:
  - Expect "toHaveCount" with timeout 5000ms
  - waiting for locator('[data-testid="result-row"]')
    14 × locator resolved to 8 elements
       - unexpected value "8"

```

# Page snapshot

```yaml
- generic [ref=e1]:
  - generic [ref=e2]:
    - generic [ref=e3]:
      - banner [ref=e4]:
        - heading "Language Brain" [level=1] [ref=e5]
        - paragraph [ref=e6]: 语言大脑
      - 'searchbox "Try: 看起来好吃 or 吃 or basic-verbs" [active] [ref=e8]': 吃
      - navigation "Primary" [ref=e9]:
        - link "Browse vault" [ref=e10] [cursor=pointer]:
          - /url: /vault
        - link "+ Add sentence" [ref=e11] [cursor=pointer]:
          - /url: /add
    - generic [ref=e12]:
      - group "Connection-kind filters" [ref=e13]:
        - generic [ref=e14]: kind
        - button "lex" [pressed] [ref=e15] [cursor=pointer]
        - button "sem" [pressed] [ref=e16] [cursor=pointer]
        - button "grp" [pressed] [ref=e17] [cursor=pointer]
        - button "opp" [pressed] [ref=e18] [cursor=pointer]
      - group "Unit-type filters" [ref=e19]:
        - generic [ref=e20]: type
        - button "sent" [pressed] [ref=e21] [cursor=pointer]
        - button "words" [pressed] [ref=e22] [cursor=pointer]
        - button "cmpd" [pressed] [ref=e23] [cursor=pointer]
        - button "groups" [pressed] [ref=e24] [cursor=pointer]
    - region "Search results" [ref=e25]:
      - list [ref=e26]:
        - listitem [ref=e27]:
          - link "吃 chī lex relevance score" [ref=e28] [cursor=pointer]:
            - /url: /unit/W174
            - generic "chī" [ref=e31]: 吃
            - generic [ref=e32]: chī
            - generic [ref=e34]: lex
            - generic "relevance score" [ref=e35]: "1.00"
          - paragraph [ref=e36]: e.g. 我喜欢吃
        - listitem [ref=e37]:
          - link "吃 饭 chī fàn lex relevance score" [ref=e38] [cursor=pointer]:
            - /url: /unit/C810
            - generic [ref=e40]:
              - generic "chī" [ref=e41]: 吃
              - generic "fàn" [ref=e42]: 饭
            - generic [ref=e43]: chī fàn
            - generic [ref=e45]: lex
            - generic "relevance score" [ref=e46]: "0.50"
          - paragraph [ref=e47]: e.g. 我吃饭
        - listitem [ref=e48]:
          - link "我 吃 饭 wǒ chī fàn lex relevance score" [ref=e49] [cursor=pointer]:
            - /url: /unit/S6
            - generic [ref=e51]:
              - generic "wǒ" [ref=e52]: 我
              - generic "chī" [ref=e53]: 吃
              - generic "fàn" [ref=e54]: 饭
            - generic [ref=e55]: wǒ chī fàn
            - generic [ref=e57]: lex
            - generic "relevance score" [ref=e58]: "0.33"
        - listitem [ref=e59]:
          - link "我 想 吃 wǒ xiǎng chī lex relevance score" [ref=e60] [cursor=pointer]:
            - /url: /unit/S9
            - generic [ref=e62]:
              - generic "wǒ" [ref=e63]: 我
              - generic "xiǎng" [ref=e64]: 想
              - generic "chī" [ref=e65]: 吃
            - generic [ref=e66]: wǒ xiǎng chī
            - generic [ref=e68]: lex
            - generic "relevance score" [ref=e69]: "0.33"
        - listitem [ref=e70]:
          - link "我 喜 欢 吃 wǒ xǐ huān chī lex relevance score" [ref=e71] [cursor=pointer]:
            - /url: /unit/S12
            - generic [ref=e73]:
              - generic "wǒ" [ref=e74]: 我
              - generic "xǐ" [ref=e75]: 喜
              - generic "huān" [ref=e76]: 欢
              - generic "chī" [ref=e77]: 吃
            - generic [ref=e78]: wǒ xǐ huān chī
            - generic [ref=e80]: lex
            - generic "relevance score" [ref=e81]: "0.25"
        - listitem [ref=e82]:
          - link "我 喜 欢 吃 wǒ xǐ huān chī lex relevance score" [ref=e83] [cursor=pointer]:
            - /url: /unit/S5
            - generic [ref=e85]:
              - generic "wǒ" [ref=e86]: 我
              - generic "xǐ" [ref=e87]: 喜
              - generic "huān" [ref=e88]: 欢
              - generic "chī" [ref=e89]: 吃
            - generic [ref=e90]: wǒ xǐ huān chī
            - generic [ref=e92]: lex
            - generic "relevance score" [ref=e93]: "0.25"
        - listitem [ref=e94]:
          - link "两 个 人 为 了 吃 不 惧 台 风 liǎng gè rén wèi le chī bù jù tái fēng lex relevance score" [ref=e95] [cursor=pointer]:
            - /url: /unit/S37
            - generic [ref=e97]:
              - generic "liǎng" [ref=e98]: 两
              - generic "gè" [ref=e99]: 个
              - generic "rén" [ref=e100]: 人
              - generic "wèi" [ref=e101]: 为
              - generic "le" [ref=e102]: 了
              - generic "chī" [ref=e103]: 吃
              - generic "bù" [ref=e104]: 不
              - generic "jù" [ref=e105]: 惧
              - generic "tái" [ref=e106]: 台
              - generic "fēng" [ref=e107]: 风
            - generic [ref=e108]: liǎng gè rén wèi le chī bù jù tái fēng
            - generic [ref=e110]: lex
            - generic "relevance score" [ref=e111]: "0.10"
        - listitem [ref=e112]:
          - link "你 想 吃 广 东 本 地 特 色 美 食 吗 nǐ xiǎng chī Guǎngdōng běndì tèsè měishí ma lex relevance score" [ref=e113] [cursor=pointer]:
            - /url: /unit/S23
            - generic [ref=e115]:
              - generic "nǐ" [ref=e116]: 你
              - generic "xiǎng" [ref=e117]: 想
              - generic "chī" [ref=e118]: 吃
              - generic "guǎng" [ref=e119]: 广
              - generic "dōng" [ref=e120]: 东
              - generic "běn" [ref=e121]: 本
              - generic "dì" [ref=e122]: 地
              - generic "tè" [ref=e123]: 特
              - generic "sè" [ref=e124]: 色
              - generic "měi" [ref=e125]: 美
              - generic "shí" [ref=e126]: 食
              - generic "ma" [ref=e127]: 吗
            - generic [ref=e128]: nǐ xiǎng chī Guǎngdōng běndì tèsè měishí ma
            - generic [ref=e130]: lex
            - generic "relevance score" [ref=e131]: "0.08"
  - generic [ref=e135]:
    - generic [ref=e136]: "[plugin:vite-plugin-svelte] src/routes/unit/[id]/+page.svelte:218:43 Can only bind to state or props https://svelte.dev/e/bind_invalid_value"
    - generic [ref=e137]: src/routes/unit/[id]/+page.svelte:218:43
    - generic [ref=e138]: "216 | <label class=\"field\"> 217 | <span class=\"label\">Pinyin</span> 218 | <input type=\"text\" bind:value={editPinyin} data-testid=\"edit-pinyin\" /> ^ 219 | </label> 220 | <label class=\"field\">"
    - generic [ref=e139]:
      - text: Click outside, press Esc key, or fix the code to dismiss.
      - text: You can also disable this overlay by setting
      - code [ref=e140]: server.hmr.overlay
      - text: to
      - code [ref=e141]: "false"
      - text: in
      - code [ref=e142]: vite.config.ts
      - text: .
```

# Test source

```ts
  1  | import { test, expect, type Page } from '@playwright/test';
  2  | 
  3  | // HanziWithPinyin is rendered inside ResultRow on the search results page.
  4  | // These tests verify the integration — that the default page search flow works
  5  | // and shows hanzi via HanziWithPinyin. Component-internal behavior
  6  | // (tone classes, per-char pinyin tooltips, fetch fallback) is preserved
  7  | // by the passing add-page and unit-detail tests that exercise pages
  8  | // containing HanziWithPinyin.
  9  | 
  10 | const FAKE_RESULTS = [
  11 |   { id: 'chi', type: 'word', name: '吃', snippet: 'chī', kinds: ['lexical'], score: 1.0 },
  12 |   { id: 's-1', type: 'sentence', name: '我喜欢吃', snippet: 'wǒ xǐhuān chī', kinds: ['lexical'], score: 0.5 }
  13 | ];
  14 | 
  15 | // Route pattern matches the absolute API URL (same as default-page.spec.ts).
  16 | const SEARCH_ROUTE = /http:\/\/localhost:8000\/api\/search/;
  17 | 
  18 | test('T4 — default page search shows hanzi via HanziWithPinyin', async ({ page }) => {
  19 |   // Mock search endpoint
  20 |   await page.route(SEARCH_ROUTE, (route) =>
  21 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ query: '吃', results: FAKE_RESULTS }) })
  22 |   );
  23 |   // Mock pinyin endpoint so HanziWithPinyin gets tone data
  24 |   await page.route(/http:\/\/localhost:8000\/api\/pinyin\//, (route) => {
  25 |     const url = route.request().url();
  26 |     const text = url.includes('/api/pinyin/') ? decodeURIComponent(url.split('/api/pinyin/')[1]) : '';
  27 |     // Return per-char entries with tone info
  28 |     const entries = text.split('').map((ch: string) => ({
  29 |       char: ch,
  30 |       pinyin: ch === '吃' ? 'chī' : '',
  31 |       tone: ch === '吃' ? 1 : 5
  32 |     }));
  33 |     route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(entries) });
  34 |   });
  35 |   await page.goto('/');
  36 |   await page.waitForLoadState('networkidle');
  37 |   // Use click + keyboard.type for reliable Svelte input handling (same as default-page.spec.ts)
  38 |   const input = page.locator('input[type="search"]');
  39 |   await input.click();
  40 |   await page.waitForTimeout(100);
  41 |   await page.keyboard.type('吃');
  42 |   // Wait for debounce (200ms) + network + render
  43 |   await page.waitForTimeout(500);
  44 |   // Verify search input received the value
  45 |   await expect(page.locator('input[type="search"]')).toHaveValue('吃');
  46 |   // Verify result rows appear
  47 |   const rows = page.locator('[data-testid="result-row"]');
> 48 |   await expect(rows).toHaveCount(2);
     |                      ^ Error: expect(locator).toHaveCount(expected) failed
  49 |   // Verify HanziWithPinyin renders the hanzi character with tone-1 class
  50 |   // (the component exposes per-char spans with data-tone and data-pinyin attributes)
  51 |   // Use .first() because both "吃" (word) and "我喜欢吃" (sentence) contain "吃"
  52 |   const hanziSpan = page.locator('[data-testid="result-name-char-吃"]').first();
  53 |   await expect(hanziSpan).toBeVisible();
  54 |   await expect(hanziSpan).toHaveAttribute('data-tone', '1');
  55 |   await expect(hanziSpan).toHaveAttribute('data-pinyin', 'chī');
  56 |   // The tone-1 class applies a red underline (border-bottom-color: #dc2626)
  57 |   await expect(hanziSpan).toHaveClass(/tone-1/);
  58 | });
  59 | 
```