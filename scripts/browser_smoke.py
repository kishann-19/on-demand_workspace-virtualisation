"""Exercise the real UI against a running server; remove created workspaces afterwards.

pip install playwright && playwright install chromium
python scripts/browser_smoke.py --url http://localhost:8000
An optional --browser /usr/bin/chromium uses an existing browser installation.
"""

import argparse
import secrets
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://localhost:8000")
parser.add_argument("--browser", default=None)
args = parser.parse_args()
artifacts = Path("test-results")
artifacts.mkdir(exist_ok=True)
errors = []

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path=args.browser, args=["--no-sandbox"])
    page = browser.new_page(viewport={"width": 1440, "height": 1050})
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(args.url)
    page.get_by_role("button", name="Create an account", exact=True).click()
    page.get_by_label("Your name", exact=True).fill("Kishan")
    page.get_by_label("Email address", exact=True).fill(f"browser-{uuid.uuid4().hex}@example.com")
    page.get_by_label("Password", exact=True).fill(secrets.token_urlsafe(24))
    page.get_by_role("button", name="Create account", exact=False).click()
    page.get_by_role("heading", name="Welcome to your space, Kishan.").wait_for()
    csrf = page.request.get(f"{args.url}/api/auth/me").json()["csrf"]
    created = []

    def create(name, template):
        page.get_by_role("button", name="New workspace", exact=False).click()
        page.get_by_label("Workspace name").fill(name)
        page.get_by_label("Environment template").select_option(template)
        with page.expect_response(
            lambda response: response.url.endswith("/api/workspaces") and response.request.method == "POST",
            timeout=60000,
        ) as response:
            page.get_by_role("button", name="Launch workspace", exact=False).click()
        assert response.value.status == 201, response.value.text()
        key = response.value.json()["id"]
        created.append(key)
        page.locator(f'[data-workspace="{key}"]').wait_for()
        return key

    try:
        python_id = create("Python experiment", "python")
        page.locator(f'[data-action="open"][data-id="{python_id}"]').click()
        expect(page.locator("#terminal-status")).to_have_text("Connected", timeout=15000)
        expect(page.locator("#current-file")).to_have_text("main.py")
        page.locator("#code-editor").fill('print("Hello from my cloud workspace!")\n')
        page.get_by_role("button", name="Save file", exact=True).click()
        expect(page.locator("#save-status")).to_have_text("Saved")
        page.get_by_role("button", name="Run", exact=False).click()
        expect(page.locator("#terminal")).to_contain_text("Hello from my cloud workspace!", timeout=15000)
        page.screenshot(path=str(artifacts / "editor.png"))
        page.locator("#close-editor").click()
        page.locator(f'[data-action="stop"][data-id="{python_id}"]').click()
        page.locator(f'[data-action="start"][data-id="{python_id}"]').wait_for(timeout=15000)
        page.locator(f'[data-action="backups"][data-id="{python_id}"]').click()
        page.get_by_role("button", name="Create backup", exact=True).click()
        page.get_by_role("link", name="Download", exact=True).wait_for(timeout=15000)
        page.on("dialog", lambda dialog: dialog.accept())
        with page.expect_response(
            lambda response: response.url.endswith("/restore"), timeout=15000
        ) as response:
            page.get_by_role("button", name="Restore", exact=True).click()
        assert response.value.status == 200
        page.locator("#backups-dialog [data-close]").click()
        page.locator(f'[data-action="start"][data-id="{python_id}"]').click()
        page.locator(f'[data-action="open"][data-id="{python_id}"]').wait_for(timeout=15000)
        web_id = create("My first website", "web")
        page.screenshot(path=str(artifacts / "dashboard.png"), full_page=True)
        page.locator(f'[data-action="open"][data-id="{web_id}"]').click()
        page.get_by_role("button", name="Preview", exact=False).click()
        frame = page.frame_locator("#preview-frame")
        expect(frame.get_by_role("heading", name="Hello, world.")).to_be_visible()
        frame.get_by_role("button", name="Say hello").click()
        expect(frame.get_by_text("You just made your page interactive!")).to_be_visible()
        page.screenshot(path=str(artifacts / "preview.png"))
        page.locator("#preview-dialog [data-close]").click()
        page.locator("#close-editor").click()
        page.set_viewport_size({"width": 390, "height": 844})
        assert not page.evaluate("document.documentElement.scrollWidth > innerWidth")
        page.screenshot(path=str(artifacts / "mobile.png"), full_page=True)
        assert not errors, errors
        print(
            "PASS: registration, create, editor, terminal, stop/resume, backup/restore, web preview, mobile layout; no JavaScript errors."
        )
    finally:
        for key in created:
            response = page.request.delete(f"{args.url}/api/workspaces/{key}", headers={"X-CSRF-Token": csrf})
            assert response.status == 200, response.text()
        browser.close()
