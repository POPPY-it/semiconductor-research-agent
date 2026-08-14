"""前端 E2E（真实浏览器）：打开工作台 → 创建任务 → 等待完成 → 验证研报渲染。"""
import asyncio
import json
import time
from pathlib import Path

from playwright.async_api import async_playwright

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PROFILE = r"D:\qwen3.6\publish-scripts\e2e-profile"
BASE = "http://127.0.0.1:8000"
OUT = Path(r"D:\qwen3.6\semiconductor-agent\spikes\results")


async def main() -> None:
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=PROFILE,
            executable_path=CHROME,
            headless=False,
            args=["--no-first-run", "--no-default-browser-check"],
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto(BASE, wait_until="domcontentloaded", timeout=60000)
        await page.wait_for_timeout(5000)

        print("TITLE:", await page.title())
        body = (await page.locator("body").inner_text())[:300]
        print("PAGE_TEXT:", body.replace("\n", " | "))
        assert "新建研报任务" in body, "工作台首页未渲染"

        # 填选题并提交
        await page.locator("textarea").first.fill("半导体行业日报：E2E 浏览器全链路验证")
        await page.locator("button:has-text('生成研报')").first.click()
        await page.wait_for_timeout(6000)

        body2 = (await page.locator("body").inner_text())[:400]
        print("AFTER_SUBMIT:", body2.replace("\n", " | "))

        # 等待完成（最多 12 分钟）
        deadline = time.time() + 720
        while time.time() < deadline:
            body3 = await page.locator("body").inner_text()
            if "研报正文" in body3 or "任务失败" in body3:
                break
            await page.wait_for_timeout(15000)

        body4 = await page.locator("body").inner_text()
        print("FINAL_STATUS:", body4[:200].replace("\n", " | "))
        ok = "研报正文" in body4
        print("E2E_RESULT:", "PASS" if ok else "FAIL")

        OUT.mkdir(parents=True, exist_ok=True)
        await page.screenshot(path=str(OUT / "e2e_report.png"), full_page=True)
        print("SCREENSHOT:", OUT / "e2e_report.png")
        await ctx.close()


asyncio.run(main())
