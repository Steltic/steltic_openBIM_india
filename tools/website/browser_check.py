"""Open every staged example on loopback and exercise the viewer, report and companion links.

Optional release check: install Playwright and Pillow, then supply a Chromium-family browser.
The website runs with every external browser request blocked during this check.
"""

import argparse
import asyncio
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
from pathlib import Path
import threading

from PIL import Image
from playwright.async_api import async_playwright


class Handler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


async def exercise(context, base, row, args):
    page = await context.new_page()
    errors = []
    local = []
    external = []
    record = {
        "id": row["id"],
        "unit": row["unit"],
        "errors": errors,
        "local_failures": local,
        "external_requests": external,
    }

    def response(r):
        if r.status >= 400:
            local.append([r.status, r.url])

    page.on("response", response)
    page.on("pageerror", lambda error: errors.append(str(error)[:220]))
    page.on(
        "requestfailed",
        lambda r: (local if r.url.startswith(base) else external).append([r.failure, r.url]),
    )

    async def go(url):
        response = await page.goto(base + "/" + url, wait_until="load", timeout=90000)
        assert response and response.ok, url

    try:
        await go(row["viewer"])
        canvas = page.locator("#model")
        await page.wait_for_selector('#model[data-ready="true"]', timeout=60000)
        record["mode"] = await canvas.get_attribute("data-mode")
        record["summary"] = await page.locator("#summary").inner_text()
        rendered = Image.open(BytesIO(await canvas.screenshot(timeout=60000))).convert("RGB")
        img = rendered.copy()
        img.thumbnail((350, 350))
        ink = sum(
            n
            for n, color in img.getcolors(img.width * img.height)
            if min(color) < 160 and max(color) - min(color) > 13
        )
        record["model_pixels"] = ink
        assert ink > 35, ("Empty model view", ink)
        if args.screens and row["id"] in ("IN_Ex5", "IN_Ex11", "IN_CFS_Ex3", "IN_CFS_Ex14"):
            args.screens.mkdir(exist_ok=True, parents=True)
            await page.screenshot(path=str(args.screens / f"{row['id']}-{row['unit']}.png"))
        # Select a visible steel surface, just as a visitor would. Antialiased
        # edge pixels can touch the background in the single-sample pick buffer.
        pixels = rendered.load()
        candidates = [
            (x, y)
            for y in range(20, rendered.height - 24, 3)
            for x in range(12, rendered.width - 12, 3)
            if max(pixels[x, y]) < 180 and max(pixels[x, y]) - min(pixels[x, y]) > 24
        ]
        candidates.sort(
            key=lambda xy: (xy[0] - rendered.width / 2) ** 2 + (xy[1] - rendered.height / 2) ** 2
        )
        for x, y in candidates[:12]:
            await canvas.click(position={"x": x, "y": y})
            if await page.locator("#properties dd").count():
                break
        assert await page.locator(
            "#properties dd"
        ).count(), "Canvas object picking did not select a visible member"
        record["picked_member"] = await page.locator("#properties h3").inner_text()
        await page.locator("#objects").select_option(index=1)
        assert await page.locator("#properties dd").count() >= 4
        record["first_object"] = await page.locator("#properties h3").inner_text()
        await page.locator("#search").fill(record["first_object"])
        assert await page.locator("#objects option").count() > 1
        await page.locator("#search").fill("")
        await page.locator("#panels").check()
        await page.locator("#layer").select_option("Panels")
        await page.locator("#objects").select_option(index=1)
        assert "Panel thickness" in await page.locator("#properties").inner_text()
        await page.locator("#camera").select_option("Plan")
        await page.locator("#fit").click()
        await page.keyboard.press("Tab")
        await go(row["report"])
        header = page.locator("#coordination")
        record["decision"] = await header.locator("h2").inner_text()
        assert ("fails" in record["decision"]) == (row["id"] == "IN_Ex5")
        assert await header.locator("a[href]").count() >= 5
        await header.locator("summary").click()
        assert await header.locator("li").count() > 0
        if await page.locator('script[src*="mathjax"]').count():
            await page.evaluate("() => MathJax.startup.promise.then(() => true)")
            record["typeset_equations"] = await page.locator("mjx-container svg").count()
            assert await page.evaluate(
                'async () => !!(await MathJax.tex2svgPromise("x^2")).querySelector("svg")'
            )
        assert await page.locator("img").evaluate_all(
            "(imgs)=>imgs.every(i=>i.complete && i.naturalWidth>0)"
        )
        if not args.pages_only:
            await go(row["public_folder"] + "/analysis.html")
            if row["id"] == "IN_CFS_Ex3":
                assert await page.locator("svg line,svg path,svg polygon").count() > 20
                assert "IS 801" in await page.locator("body").inner_text()
                record["analytical_display"] = "portal elevation"
            else:
                await page.wait_for_function(
                    'typeof renderer!=="undefined" && renderer.info.render.calls>0', timeout=60000
                )
                assert await page.locator("canvas").count() > 0
                record["analytical_display"] = "3D frame"
            if row.get("fresh_lateral_folder"):
                for n in ("report.html", "viewer_3d.html"):
                    await go(row["existing_lateral_folder"] + "/" + n)
                    await page.wait_for_url("**/" + row["fresh_lateral_folder"] + "/" + n, timeout=30000)
                    if n == "report.html":
                        assert "companion report" in await page.locator("#coordination").inner_text()
                    else:
                        await page.wait_for_function(
                            'typeof renderer!=="undefined" && renderer.info.render.calls>0', timeout=60000
                        )
                record["companion_routes"] = 2
    except Exception as ex:
        errors.append(repr(ex)[:420])
    finally:
        await page.close()
    print(
        row["id"],
        row["unit"],
        record.get("mode"),
        "OK" if not (errors or local or external) else str([errors, local, external])[:400],
        flush=True,
    )
    return record


async def run(args, base):
    rows = json.loads(args.routes.read_bytes())
    rows = [r for r in rows if not args.case or r["id"] in args.case]
    async with async_playwright() as p:
        flags = (
            ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
            if not args.line
            else ["--disable-webgl"]
        )
        browser = await p.chromium.launch(executable_path=str(args.browser), headless=True, args=flags)
        context = await browser.new_context(
            viewport={"width": 393 if args.mobile else 1320, "height": 852}, device_scale_factor=1
        )

        async def local_only(route):
            if route.request.url.startswith(base + "/"):
                await route.continue_()
            else:
                await route.abort()

        await context.route("**/*", local_only)
        sem = asyncio.Semaphore(args.workers)

        async def one(row):
            async with sem:
                return await exercise(context, base, row, args)

        records = await asyncio.gather(*(one(r) for r in rows))
        await browser.close()
    args.out.write_text(json.dumps(records, indent=2) + "\n", encoding="utf8")
    return not any(r["errors"] or r["local_failures"] or r["external_requests"] for r in records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("browser", "root", "routes", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--screens", type=Path)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--case", action="append")
    for flag in ("mobile", "line", "pages-only"):
        parser.add_argument("--" + flag, action="store_true")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), partial(Handler, directory=str(args.root.resolve())))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ok = asyncio.run(run(args, f"http://127.0.0.1:{server.server_port}"))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    raise SystemExit(0 if ok else 1)
