# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: vault_browse.spec.ts >> T6 — prev/next visible when total > 50, hidden when total <= 50
- Location: tests/vault_browse.spec.ts:173:1

# Error details

```
Test timeout of 30000ms exceeded.
```

```
Error: locator.click: Test timeout of 30000ms exceeded.
Call log:
  - waiting for locator('[data-testid="pagination"] button:last-child')
    - locator resolved to <button type="button" aria-label="Next page" class="page-btn s-NKwX_-hddHxy">Next →</button>
  - attempting click action
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <vite-error-overlay></vite-error-overlay> intercepts pointer events
    - retrying click action
    - waiting 20ms
    2 × waiting for element to be visible, enabled and stable
      - element is visible, enabled and stable
      - scrolling into view if needed
      - done scrolling
      - <vite-error-overlay></vite-error-overlay> intercepts pointer events
    - retrying click action
      - waiting 100ms
    56 × waiting for element to be visible, enabled and stable
       - element is visible, enabled and stable
       - scrolling into view if needed
       - done scrolling
       - <vite-error-overlay></vite-error-overlay> intercepts pointer events
     - retrying click action
       - waiting 500ms

```

# Page snapshot

```yaml
- generic [active] [ref=e1]:
  - main [ref=e3]:
    - generic [ref=e4]:
      - link "← Back" [ref=e5] [cursor=pointer]:
        - /url: /
      - heading "Browse vault" [level=1] [ref=e6]
    - generic [ref=e7]:
      - tablist "Unit type" [ref=e8]:
        - tab "Word" [ref=e9] [cursor=pointer]
        - tab "Compound" [ref=e10] [cursor=pointer]
        - tab "Sentence" [selected] [ref=e11] [cursor=pointer]
      - generic [ref=e12]:
        - text: sort
        - combobox "Sort order" [ref=e13] [cursor=pointer]:
          - option "id" [selected]
          - option "pinyin"
    - list [ref=e14]:
      - listitem [ref=e15]:
        - link "S1 我流口水了 wǒ liú kǒu shuǐ le" [ref=e16] [cursor=pointer]:
          - /url: /unit/S1
          - generic [ref=e17]: S1
          - generic [ref=e18]: 我流口水了
          - generic [ref=e19]: wǒ liú kǒu shuǐ le
      - listitem [ref=e20]:
        - link "S10 我准考 wǒ zhǔn kǎo" [ref=e21] [cursor=pointer]:
          - /url: /unit/S10
          - generic [ref=e22]: S10
          - generic [ref=e23]: 我准考
          - generic [ref=e24]: wǒ zhǔn kǎo
      - listitem [ref=e25]:
        - link "S11 我受不了这个 wǒ shòu bù liǎo zhè ge" [ref=e26] [cursor=pointer]:
          - /url: /unit/S11
          - generic [ref=e27]: S11
          - generic [ref=e28]: 我受不了这个
          - generic [ref=e29]: wǒ shòu bù liǎo zhè ge
      - listitem [ref=e30]:
        - link "S12 我喜欢吃 wǒ xǐ huān chī" [ref=e31] [cursor=pointer]:
          - /url: /unit/S12
          - generic [ref=e32]: S12
          - generic [ref=e33]: 我喜欢吃
          - generic [ref=e34]: wǒ xǐ huān chī
      - listitem [ref=e35]:
        - link "S13 需要静下来 xū yào jìng xià lái" [ref=e36] [cursor=pointer]:
          - /url: /unit/S13
          - generic [ref=e37]: S13
          - generic [ref=e38]: 需要静下来
          - generic [ref=e39]: xū yào jìng xià lái
      - listitem [ref=e40]:
        - link "S14 客气什么 kèqi shénme" [ref=e41] [cursor=pointer]:
          - /url: /unit/S14
          - generic [ref=e42]: S14
          - generic [ref=e43]: 客气什么
          - generic [ref=e44]: kèqi shénme
      - listitem [ref=e45]:
        - link "S15 测试 cè shì" [ref=e46] [cursor=pointer]:
          - /url: /unit/S15
          - generic [ref=e47]: S15
          - generic [ref=e48]: 测试
          - generic [ref=e49]: cè shì
      - listitem [ref=e50]:
        - link "S16 我也刚到 wǒ yě gāng dào" [ref=e51] [cursor=pointer]:
          - /url: /unit/S16
          - generic [ref=e52]: S16
          - generic [ref=e53]: 我也刚到
          - generic [ref=e54]: wǒ yě gāng dào
      - listitem [ref=e55]:
        - link "S17 早点休息吧 晚安啦 zǎodiǎn xiūxi ba wǎn'ān la" [ref=e56] [cursor=pointer]:
          - /url: /unit/S17
          - generic [ref=e57]: S17
          - generic [ref=e58]: 早点休息吧 晚安啦
          - generic [ref=e59]: zǎodiǎn xiūxi ba wǎn'ān la
      - listitem [ref=e60]:
        - link "S18 我找不到你 wǒ zhǎo bù dào nǐ" [ref=e61] [cursor=pointer]:
          - /url: /unit/S18
          - generic [ref=e62]: S18
          - generic [ref=e63]: 我找不到你
          - generic [ref=e64]: wǒ zhǎo bù dào nǐ
      - listitem [ref=e65]:
        - link "S19 尊重彼此的界限 zūnzhòng bǐcǐ de jièxiàn" [ref=e66] [cursor=pointer]:
          - /url: /unit/S19
          - generic [ref=e67]: S19
          - generic [ref=e68]: 尊重彼此的界限
          - generic [ref=e69]: zūnzhòng bǐcǐ de jièxiàn
      - listitem [ref=e70]:
        - link "S2 但我也不能静太久 dàn wǒ yě bù néng jìng tài jiǔ" [ref=e71] [cursor=pointer]:
          - /url: /unit/S2
          - generic [ref=e72]: S2
          - generic [ref=e73]: 但我也不能静太久
          - generic [ref=e74]: dàn wǒ yě bù néng jìng tài jiǔ
      - listitem [ref=e75]:
        - link "S20 但就是一包量很少 dàn jiù shì yì bāo liàng hěn shǎo" [ref=e76] [cursor=pointer]:
          - /url: /unit/S20
          - generic [ref=e77]: S20
          - generic [ref=e78]: 但就是一包量很少
          - generic [ref=e79]: dàn jiù shì yì bāo liàng hěn shǎo
      - listitem [ref=e80]:
        - link "S21 这是你想看的夜景吗 zhè shì nǐ xiǎng kàn de yèjǐng ma" [ref=e81] [cursor=pointer]:
          - /url: /unit/S21
          - generic [ref=e82]: S21
          - generic [ref=e83]: 这是你想看的夜景吗
          - generic [ref=e84]: zhè shì nǐ xiǎng kàn de yèjǐng ma
      - listitem [ref=e85]:
        - link "S22 还是你有哪些喜欢的食物 háishi nǐ yǒu nǎxiē xǐhuan de shíwù" [ref=e86] [cursor=pointer]:
          - /url: /unit/S22
          - generic [ref=e87]: S22
          - generic [ref=e88]: 还是你有哪些喜欢的食物
          - generic [ref=e89]: háishi nǐ yǒu nǎxiē xǐhuan de shíwù
      - listitem [ref=e90]:
        - link "S23 你想吃广东本地特色美食吗 nǐ xiǎng chī Guǎngdōng běndì tèsè měishí ma" [ref=e91] [cursor=pointer]:
          - /url: /unit/S23
          - generic [ref=e92]: S23
          - generic [ref=e93]: 你想吃广东本地特色美食吗
          - generic [ref=e94]: nǐ xiǎng chī Guǎngdōng běndì tèsè měishí ma
      - listitem [ref=e95]:
        - link "S24 3分钟后到达 3 fēn zhōng hòu dào dá" [ref=e96] [cursor=pointer]:
          - /url: /unit/S24
          - generic [ref=e97]: S24
          - generic [ref=e98]: 3分钟后到达
          - generic [ref=e99]: 3 fēn zhōng hòu dào dá
      - listitem [ref=e100]:
        - link "S25 我到大堂了 wǒ dào dàtáng le" [ref=e101] [cursor=pointer]:
          - /url: /unit/S25
          - generic [ref=e102]: S25
          - generic [ref=e103]: 我到大堂了
          - generic [ref=e104]: wǒ dào dàtáng le
      - listitem [ref=e105]:
        - link "S26 真的假的 zhēn de jiǎ de" [ref=e106] [cursor=pointer]:
          - /url: /unit/S26
          - generic [ref=e107]: S26
          - generic [ref=e108]: 真的假的
          - generic [ref=e109]: zhēn de jiǎ de
      - listitem [ref=e110]:
        - link "S27 只是我这个人会有一点搞笑 zhǐshì wǒ zhège rén huì yǒu yìdiǎn gǎoxiào" [ref=e111] [cursor=pointer]:
          - /url: /unit/S27
          - generic [ref=e112]: S27
          - generic [ref=e113]: 只是我这个人会有一点搞笑
          - generic [ref=e114]: zhǐshì wǒ zhège rén huì yǒu yìdiǎn gǎoxiào
      - listitem [ref=e115]:
        - link "S28 你不介意我这个点就行 nǐ bù jièyi wǒ zhège diǎn jiù xíng" [ref=e116] [cursor=pointer]:
          - /url: /unit/S28
          - generic [ref=e117]: S28
          - generic [ref=e118]: 你不介意我这个点就行
          - generic [ref=e119]: nǐ bù jièyi wǒ zhège diǎn jiù xíng
      - listitem [ref=e120]:
        - link "S29 那你是什么专业啊 nà nǐ shì shénme zhuānyè a" [ref=e121] [cursor=pointer]:
          - /url: /unit/S29
          - generic [ref=e122]: S29
          - generic [ref=e123]: 那你是什么专业啊
          - generic [ref=e124]: nà nǐ shì shénme zhuānyè a
      - listitem [ref=e125]:
        - link "S3 给自己充电吗 gěi zì jǐ chōng diàn ma" [ref=e126] [cursor=pointer]:
          - /url: /unit/S3
          - generic [ref=e127]: S3
          - generic [ref=e128]: 给自己充电吗
          - generic [ref=e129]: gěi zì jǐ chōng diàn ma
      - listitem [ref=e130]:
        - link "S30 这两个字比较亲密 zhè liǎng ge zì bǐjiào qīnmì" [ref=e131] [cursor=pointer]:
          - /url: /unit/S30
          - generic [ref=e132]: S30
          - generic [ref=e133]: 这两个字比较亲密
          - generic [ref=e134]: zhè liǎng ge zì bǐjiào qīnmì
      - listitem [ref=e135]:
        - link "S31 我流口水了 wǒ liú kǒu shuǐ le" [ref=e136] [cursor=pointer]:
          - /url: /unit/S31
          - generic [ref=e137]: S31
          - generic [ref=e138]: 我流口水了
          - generic [ref=e139]: wǒ liú kǒu shuǐ le
      - listitem [ref=e140]:
        - link "S32 三年拿过奖学金的 sān nián ná guò jiǎng xué jǐn de" [ref=e141] [cursor=pointer]:
          - /url: /unit/S32
          - generic [ref=e142]: S32
          - generic [ref=e143]: 三年拿过奖学金的
          - generic [ref=e144]: sān nián ná guò jiǎng xué jǐn de
      - listitem [ref=e145]:
        - link "S33 你小瞧现在的中国人了 nǐ xiǎo qìng xiàn zài de zhōng guó rén le" [ref=e146] [cursor=pointer]:
          - /url: /unit/S33
          - generic [ref=e147]: S33
          - generic [ref=e148]: 你小瞧现在的中国人了
          - generic [ref=e149]: nǐ xiǎo qìng xiàn zài de zhōng guó rén le
      - listitem [ref=e150]:
        - link "S34 每个选择都有困难的地方 měi gè xuǎn zé dōu yǒu kùn nan de dì fang" [ref=e151] [cursor=pointer]:
          - /url: /unit/S34
          - generic [ref=e152]: S34
          - generic [ref=e153]: 每个选择都有困难的地方
          - generic [ref=e154]: měi gè xuǎn zé dōu yǒu kùn nan de dì fang
      - listitem [ref=e155]:
        - link "S35 平时一般一个人哈哈哈 píngshí yìbān yíge rén hā hā hā" [ref=e156] [cursor=pointer]:
          - /url: /unit/S35
          - generic [ref=e157]: S35
          - generic [ref=e158]: 平时一般一个人哈哈哈
          - generic [ref=e159]: píngshí yìbān yíge rén hā hā hā
      - listitem [ref=e160]:
        - link "S36 昨晚为啥挠我痒痒? zuó wǎn wèi shá náo wǒ yǎng yang?" [ref=e161] [cursor=pointer]:
          - /url: /unit/S36
          - generic [ref=e162]: S36
          - generic [ref=e163]: 昨晚为啥挠我痒痒?
          - generic [ref=e164]: zuó wǎn wèi shá náo wǒ yǎng yang?
      - listitem [ref=e165]:
        - link "S37 两个人为了吃不惧台风 liǎng gè rén wèi le chī bù jù tái fēng" [ref=e166] [cursor=pointer]:
          - /url: /unit/S37
          - generic [ref=e167]: S37
          - generic [ref=e168]: 两个人为了吃不惧台风
          - generic [ref=e169]: liǎng gè rén wèi le chī bù jù tái fēng
      - listitem [ref=e170]:
        - link "S38 你对员工也太差了吧 nǐ duì yuángōng yě tài chà le ba" [ref=e171] [cursor=pointer]:
          - /url: /unit/S38
          - generic [ref=e172]: S38
          - generic [ref=e173]: 你对员工也太差了吧
          - generic [ref=e174]: nǐ duì yuángōng yě tài chà le ba
      - listitem [ref=e175]:
        - link "S39 下班很迟吗 xià bān hěn chí ma" [ref=e176] [cursor=pointer]:
          - /url: /unit/S39
          - generic [ref=e177]: S39
          - generic [ref=e178]: 下班很迟吗
          - generic [ref=e179]: xià bān hěn chí ma
      - listitem [ref=e180]:
        - link "S4 你渴了吗 nǐ kě le ma" [ref=e181] [cursor=pointer]:
          - /url: /unit/S4
          - generic [ref=e182]: S4
          - generic [ref=e183]: 你渴了吗
          - generic [ref=e184]: nǐ kě le ma
      - listitem [ref=e185]:
        - link "S40 收藏了 shōu cáng le" [ref=e186] [cursor=pointer]:
          - /url: /unit/S40
          - generic [ref=e187]: S40
          - generic [ref=e188]: 收藏了
          - generic [ref=e189]: shōu cáng le
      - listitem [ref=e190]:
        - link "S41 难不成你也才睡醒 nán bù chéng nǐ yě cái shuì xǐng" [ref=e191] [cursor=pointer]:
          - /url: /unit/S41
          - generic [ref=e192]: S41
          - generic [ref=e193]: 难不成你也才睡醒
          - generic [ref=e194]: nán bù chéng nǐ yě cái shuì xǐng
      - listitem [ref=e195]:
        - link "S42 今天睡这么早 值得表扬啊 jīn tiān shuì zhè me zǎo zhí de biǎo yáng a" [ref=e196] [cursor=pointer]:
          - /url: /unit/S42
          - generic [ref=e197]: S42
          - generic [ref=e198]: 今天睡这么早 值得表扬啊
          - generic [ref=e199]: jīn tiān shuì zhè me zǎo zhí de biǎo yáng a
      - listitem [ref=e200]:
        - link "S43 你指熬夜方面还是别的 nǐ zhǐ áoyè fāngmiàn háishi bié de" [ref=e201] [cursor=pointer]:
          - /url: /unit/S43
          - generic [ref=e202]: S43
          - generic [ref=e203]: 你指熬夜方面还是别的
          - generic [ref=e204]: nǐ zhǐ áoyè fāngmiàn háishi bié de
      - listitem [ref=e205]:
        - link "S44 熬夜伤身体 áoyè shāng shēntǐ" [ref=e206] [cursor=pointer]:
          - /url: /unit/S44
          - generic [ref=e207]: S44
          - generic [ref=e208]: 熬夜伤身体
          - generic [ref=e209]: áoyè shāng shēntǐ
      - listitem [ref=e210]:
        - link "S45 我流口水了 我流口水了" [ref=e211] [cursor=pointer]:
          - /url: /unit/S45
          - generic [ref=e212]: S45
          - generic [ref=e213]: 我流口水了
          - generic [ref=e214]: 我流口水了
      - listitem [ref=e215]:
        - link "S46 我流口水了 我流口水了" [ref=e216] [cursor=pointer]:
          - /url: /unit/S46
          - generic [ref=e217]: S46
          - generic [ref=e218]: 我流口水了
          - generic [ref=e219]: 我流口水了
      - listitem [ref=e220]:
        - link "S47 我流口水了 我流口水了" [ref=e221] [cursor=pointer]:
          - /url: /unit/S47
          - generic [ref=e222]: S47
          - generic [ref=e223]: 我流口水了
          - generic [ref=e224]: 我流口水了
      - listitem [ref=e225]:
        - link "S48 我流口水了 我流口水了" [ref=e226] [cursor=pointer]:
          - /url: /unit/S48
          - generic [ref=e227]: S48
          - generic [ref=e228]: 我流口水了
          - generic [ref=e229]: 我流口水了
      - listitem [ref=e230]:
        - link "S49 两个女孩子可危险了 Liǎng gè nǚháizi kě wēixiǎn le" [ref=e231] [cursor=pointer]:
          - /url: /unit/S49
          - generic [ref=e232]: S49
          - generic [ref=e233]: 两个女孩子可危险了
          - generic [ref=e234]: Liǎng gè nǚháizi kě wēixiǎn le
      - listitem [ref=e235]:
        - link "S5 我喜欢吃 wǒ xǐ huān chī" [ref=e236] [cursor=pointer]:
          - /url: /unit/S5
          - generic [ref=e237]: S5
          - generic [ref=e238]: 我喜欢吃
          - generic [ref=e239]: wǒ xǐ huān chī
      - listitem [ref=e240]:
        - link "S50 那我允许你也问我 nà wǒ yǔnxǔ nǐ yě wèn wǒ" [ref=e241] [cursor=pointer]:
          - /url: /unit/S50
          - generic [ref=e242]: S50
          - generic [ref=e243]: 那我允许你也问我
          - generic [ref=e244]: nà wǒ yǔnxǔ nǐ yě wèn wǒ
      - listitem [ref=e245]:
        - link "S51 明明仅学长一个人 míngmíng jǐn xuézhǎng yí gè rén" [ref=e246] [cursor=pointer]:
          - /url: /unit/S51
          - generic [ref=e247]: S51
          - generic [ref=e248]: 明明仅学长一个人
          - generic [ref=e249]: míngmíng jǐn xuézhǎng yí gè rén
      - listitem [ref=e250]:
        - link "S52 那俺跟你同一时间睡吧 nà ǎn gēn nǐ tóng yī shí jiān shuì ba" [ref=e251] [cursor=pointer]:
          - /url: /unit/S52
          - generic [ref=e252]: S52
          - generic [ref=e253]: 那俺跟你同一时间睡吧
          - generic [ref=e254]: nà ǎn gēn nǐ tóng yī shí jiān shuì ba
      - listitem [ref=e255]:
        - link "S53 其实这是一个小借口 qíshí zhè shì yí gè xiǎo jièkǒu" [ref=e256] [cursor=pointer]:
          - /url: /unit/S53
          - generic [ref=e257]: S53
          - generic [ref=e258]: 其实这是一个小借口
          - generic [ref=e259]: qíshí zhè shì yí gè xiǎo jièkǒu
      - listitem [ref=e260]:
        - link "S54 那我撤回这句话 nà wǒ chè huí zhè jù huà" [ref=e261] [cursor=pointer]:
          - /url: /unit/S54
          - generic [ref=e262]: S54
          - generic [ref=e263]: 那我撤回这句话
          - generic [ref=e264]: nà wǒ chè huí zhè jù huà
    - generic [ref=e265]:
      - button "Previous page" [disabled] [ref=e266]: ← Prev
      - generic [ref=e267]: 1–50 of 87
      - button "Next page" [ref=e268] [cursor=pointer]: Next →
  - generic [ref=e272]:
    - generic [ref=e273]: "[plugin:vite-plugin-svelte] src/routes/unit/[id]/+page.svelte:218:43 Can only bind to state or props https://svelte.dev/e/bind_invalid_value"
    - generic [ref=e274]: src/routes/unit/[id]/+page.svelte:218:43
    - generic [ref=e275]: "216 | <label class=\"field\"> 217 | <span class=\"label\">Pinyin</span> 218 | <input type=\"text\" bind:value={editPinyin} data-testid=\"edit-pinyin\" /> ^ 219 | </label> 220 | <label class=\"field\">"
    - generic [ref=e276]:
      - text: Click outside, press Esc key, or fix the code to dismiss.
      - text: You can also disable this overlay by setting
      - code [ref=e277]: server.hmr.overlay
      - text: to
      - code [ref=e278]: "false"
      - text: in
      - code [ref=e279]: vite.config.ts
      - text: .
```

# Test source

```ts
  92  |   await page.locator('[role="tab"][data-type="word"]').click();
  93  |   await page.waitForLoadState('networkidle');
  94  | 
  95  |   expect(capturedType).toBe('word');
  96  |   const rows = page.locator('[data-testid="vault-list"] .row');
  97  |   await expect(rows).toHaveCount(2);
  98  |   await expect(rows.nth(0)).toContainText('W1');
  99  | });
  100 | 
  101 | // ─── Test 3: Compound tab ────────────────────────────────────────────────────
  102 | 
  103 | test('T3 — click Compound tab → renders compound items', async ({ page }) => {
  104 |   let capturedType: string | null = null;
  105 |   page.route(VAULT_ROUTE, (route) => {
  106 |     const url = new URL(route.request().url());
  107 |     capturedType = url.searchParams.get('type');
  108 |     if (capturedType === 'compound') {
  109 |       route.fulfill({
  110 |         status: 200,
  111 |         contentType: 'application/json',
  112 |         body: JSON.stringify(makeVaultResponse('compound', FAKE_COMPOUND_ITEMS))
  113 |       });
  114 |     } else {
  115 |       route.fulfill({
  116 |         status: 200,
  117 |         contentType: 'application/json',
  118 |         body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS))
  119 |       });
  120 |     }
  121 |   });
  122 | 
  123 |   await page.goto('/vault');
  124 |   await page.waitForLoadState('networkidle');
  125 | 
  126 |   await page.locator('[role="tab"][data-type="compound"]').click();
  127 |   await page.waitForLoadState('networkidle');
  128 | 
  129 |   expect(capturedType).toBe('compound');
  130 |   const rows = page.locator('[data-testid="vault-list"] .row');
  131 |   await expect(rows).toHaveCount(2);
  132 |   await expect(rows.nth(0)).toContainText('C1');
  133 | });
  134 | 
  135 | // ─── Test 4: Sort by pinyin ──────────────────────────────────────────────────
  136 | 
  137 | test('T4 — change sort to pinyin → second request has sort=pinyin', async ({ page }) => {
  138 |   let capturedSort: string | null = null;
  139 |   page.route(VAULT_ROUTE, (route) => {
  140 |     const url = new URL(route.request().url());
  141 |     capturedSort = url.searchParams.get('sort');
  142 |     route.fulfill({
  143 |       status: 200,
  144 |       contentType: 'application/json',
  145 |       body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 2, capturedSort ?? 'id'))
  146 |     });
  147 |   });
  148 | 
  149 |   await page.goto('/vault');
  150 |   await page.waitForLoadState('networkidle');
  151 |   // First call — default sort=id.
  152 |   expect(capturedSort).toBe('id');
  153 | 
  154 |   // Change sort to pinyin.
  155 |   await page.locator('.sort-select').selectOption('pinyin');
  156 |   await page.waitForLoadState('networkidle');
  157 |   expect(capturedSort).toBe('pinyin');
  158 | });
  159 | 
  160 | // ─── Test 5: Click row navigates to /unit/{id} ───────────────────────────────
  161 | 
  162 | test('T5 — click a row → navigates to /unit/{id}', async ({ page }) => {
  163 |   setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS));
  164 |   await page.goto('/vault');
  165 |   await page.waitForLoadState('networkidle');
  166 | 
  167 |   await page.locator('[data-testid="vault-list"] .row').first().click();
  168 |   await expect(page).toHaveURL(/\/unit\/S1/);
  169 | });
  170 | 
  171 | // ─── Test 6: Pagination prev/next visibility ────────────────────────────────
  172 | 
  173 | test('T6 — prev/next visible when total > 50, hidden when total <= 50', async ({ page }) => {
  174 |   // total > 50 → pagination visible.
  175 |   setupVaultRoute(page, makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 100));
  176 |   await page.goto('/vault');
  177 |   await page.waitForLoadState('networkidle');
  178 |   await expect(page.locator('[data-testid="pagination"]')).toBeVisible();
  179 | 
  180 |   // Simulate prev/next click updates offset.
  181 |   let capturedOffset: number | null = null;
  182 |   page.route(VAULT_ROUTE, (route) => {
  183 |     const url = new URL(route.request().url());
  184 |     capturedOffset = Number(url.searchParams.get('offset') ?? 0);
  185 |     route.fulfill({
  186 |       status: 200,
  187 |       contentType: 'application/json',
  188 |       body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 100))
  189 |     });
  190 |   });
  191 | 
> 192 |   await page.locator('[data-testid="pagination"] button:last-child').click(); // Next
      |                                                                      ^ Error: locator.click: Test timeout of 30000ms exceeded.
  193 |   await page.waitForLoadState('networkidle');
  194 |   expect(capturedOffset).toBe(50);
  195 | 
  196 |   // total <= 50 → pagination hidden.
  197 |   await page.goto('/vault');
  198 |   await page.waitForLoadState('networkidle');
  199 |   // Override mock for this page visit.
  200 |   page.route(VAULT_ROUTE, (route) =>
  201 |     route.fulfill({
  202 |       status: 200,
  203 |       contentType: 'application/json',
  204 |       body: JSON.stringify(makeVaultResponse('sentence', FAKE_SENTENCE_ITEMS, 2))
  205 |     })
  206 |   );
  207 |   // Reload to re-trigger load().
  208 |   await page.reload();
  209 |   await page.waitForLoadState('networkidle');
  210 |   await expect(page.locator('[data-testid="pagination"]')).not.toBeVisible();
  211 | });
  212 | 
  213 | // ─── Test 7: Browse vault link on / navigates to /vault ─────────────────────
  214 | 
  215 | test('T7 — "Browse vault" link on / navigates to /vault', async ({ page }) => {
  216 |   // Mock the search endpoint so the page loads cleanly.
  217 |   page.route(/http:\/\/localhost:8000\/api\/search/, (route) =>
  218 |     route.fulfill({
  219 |       status: 200,
  220 |       contentType: 'application/json',
  221 |       body: JSON.stringify({ query: '', results: [] })
  222 |     })
  223 |   );
  224 |   await page.goto('/');
  225 |   await page.waitForLoadState('networkidle');
  226 | 
  227 |   const link = page.locator('a.add-link[href="/vault"]', { hasText: 'Browse vault' });
  228 |   await expect(link).toBeVisible();
  229 |   await link.click();
  230 |   await expect(page).toHaveURL('/vault');
  231 | });
  232 | 
```