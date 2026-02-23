const { chromium } = require('playwright');

(async () => {
    const browser = await chromium.launch();
    const page = await browser.newPage();

    page.on('console', msg => {
        console.log(`BROWSER CONSOLE: ${msg.type().toUpperCase()} ${msg.text()}`);
    });

    page.on('pageerror', err => {
        console.log(`BROWSER ERROR: ${err.message}`);
    });

    try {
        console.log('Navigating to http://127.0.0.1:8000 ...');
        await page.goto('http://127.0.0.1:8000', { waitUntil: 'networkidle', timeout: 30000 });
        console.log('Page loaded. Waiting for model to load...');
        await page.waitForTimeout(5000); // 这里的等待时间假设模型加载需要一点时间
        console.log('Wait finished.');
    } catch (e) {
        console.error('Wait failed or navigation error:', e.message);
    }

    await browser.close();
})();
