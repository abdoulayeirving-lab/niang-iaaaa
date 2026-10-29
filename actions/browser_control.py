import asyncio
import threading
import concurrent.futures
import platform
import shutil
import subprocess
import asyncio
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from actions.browser_security import BrowserURLPolicyError, validate_browser_url

def _get_default_browser_id() -> str:
    """Returns raw default browser identifier string for current OS."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice"
                ) as key:
                    prog_id = winreg.QueryValueEx(key, "ProgId")[0].lower()
                return prog_id
            except Exception:
                pass

        elif system == "Darwin":
            result = subprocess.run(
                ["defaults", "read",
                 "com.apple.LaunchServices/com.apple.launchservices.secure",
                 "LSHandlers"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

        elif system == "Linux":
            result = subprocess.run(
                ["xdg-settings", "get", "default-web-browser"],
                capture_output=True, text=True, timeout=5
            )
            return result.stdout.lower()

    except Exception:
        pass

    return ""

_BROWSER_BINARIES = {
    "Windows": {
        "opera":   ["opera.exe"],
        "brave":   ["brave.exe"],
        "vivaldi": ["vivaldi.exe"],
        "chrome":  ["chrome.exe"],
        "firefox": ["firefox.exe"],
    },
    "Darwin": {
        "opera":   ["opera"],
        "brave":   ["brave browser", "brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["google chrome", "google-chrome"],
        "firefox": ["firefox"],
    },
    "Linux": {
        "opera":   ["opera", "opera-stable"],
        "brave":   ["brave-browser", "brave"],
        "vivaldi": ["vivaldi-stable", "vivaldi"],
        "chrome":  ["google-chrome", "google-chrome-stable", "chromium-browser", "chromium"],
        "firefox": ["firefox"],
    },
}


def _get_opera_executable() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
        candidate_keys = [
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\opera.exe",
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\launcher.exe",
            r"SOFTWARE\Clients\StartMenuInternet\OperaStable\shell\open\command",
            r"SOFTWARE\Clients\StartMenuInternet\OperaGXStable\shell\open\command",
        ]
        for key_path in candidate_keys:
            for hive in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
                try:
                    key  = winreg.OpenKey(hive, key_path)
                    val  = winreg.QueryValue(key, None)
                    winreg.CloseKey(key)
                    exe  = val.strip().strip('"').split('"')[0].split(" --")[0].strip()
                    if exe and Path(exe).exists():
                        print(f"[Browser] 🔍 Opera found via registry: {exe}")
                        return exe
                except Exception:
                    continue
    except Exception:
        pass
    return None


def _find_browser_executable(prog_id: str) -> tuple:
    system  = platform.system()
    os_bins = _BROWSER_BINARIES.get(system, {})

    if any(x in prog_id for x in ["firefox", "mozilla"]):
        return "firefox", None, None

    if "safari" in prog_id:
        return "webkit", None, None

    if "edge" in prog_id:
        return "chromium", None, "msedge"

    if "opera" in prog_id:
        exe = _get_opera_executable()
        if exe:
            return "chromium", exe, None
        for binary in os_bins.get("opera", []):
            path = shutil.which(binary)
            if path:
                return "chromium", path, None

    browser_patterns = {
        "brave":   ["brave"],
        "vivaldi": ["vivaldi"],
        "chrome":  ["chrome"],
    }
    for browser_name, patterns in browser_patterns.items():
        if not any(p in prog_id for p in patterns):
            continue
        binaries = os_bins.get(browser_name, [])
        for binary in binaries:
            path = shutil.which(binary)
            if path:
                print(f"[Browser] 🔍 Found {browser_name} at: {path}")
                return "chromium", path, None

    if "chrome" in prog_id or not prog_id:
        return "chromium", None, "chrome"

    return "chromium", None, None


class _BrowserThread:

    def __init__(self):
        self._loop          = None
        self._thread        = None
        self._ready         = threading.Event()
        self._playwright    = None
        self._browser       = None
        self._context       = None       # Normal context
        self._incog_context = None       # Incognito/private context
        self._page          = None       # Normal page
        self._incog_page    = None       # Incognito page
        self._incog_browser = None       # Separate incognito browser instance
        self._engine_name   = "chromium" # Bilgi için sakla
        self._exe_path      = None
        self._channel       = None
        self._tabs          = {}
        self._active_tabs   = {False: None, True: None}
        self._tab_sequence  = 0
        self._blocked_requests = []

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run_loop, daemon=True, name="BrowserThread"
        )
        self._thread.start()
        self._ready.wait(timeout=15)

    def _run_loop(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._init())
        self._ready.set()
        self._loop.run_forever()

    async def _init(self):
        self._playwright = await async_playwright().start()

    def run(self, coro, timeout: int = 30):
        if not self._loop:
            raise RuntimeError("BrowserThread not started.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    # ── Tarayıcı başlatma ────────────────────────────────────────────────────

    async def _launch_browser_if_needed(self):
        """Ana tarayıcıyı başlat (henüz başlatılmadıysa)."""
        if self._browser and self._browser.is_connected():
            return

        prog_id                              = _get_default_browser_id()
        self._engine_name, self._exe_path, self._channel = _find_browser_executable(prog_id)
        engine = getattr(self._playwright, self._engine_name)

        launch_kwargs = {"headless": False}
        if self._engine_name == "chromium":
            launch_kwargs["args"] = ["--start-maximized"]
        if self._exe_path:
            launch_kwargs["executable_path"] = self._exe_path
        elif self._channel:
            launch_kwargs["channel"] = self._channel

        try:
            self._browser = await engine.launch(**launch_kwargs)
            print(
                f"[Browser] ✅ Launched ({self._engine_name}"
                f"{' / ' + self._channel if self._channel else ''}"
                f"{' / ' + self._exe_path if self._exe_path else ''})"
            )
        except Exception as e:
            print(f"[Browser] ⚠️ Launch failed ({e}), falling back to built-in Chromium")
            self._browser = await self._playwright.chromium.launch(
                headless=False,
                args=["--start-maximized"]
            )

    async def _get_page(self, incognito: bool = False):
        """
        Sayfa döndürür.
        incognito=True → özel/gizli sekme
        incognito=False → normal sekme
        """
        await self._launch_browser_if_needed()

        if incognito:
            return await self._get_incognito_page()
        else:
            return await self._get_normal_page()

    def _register_page(self, page, incognito: bool = False) -> str:
        for tab_id, entry in self._tabs.items():
            if entry["page"] is page:
                self._active_tabs[incognito] = tab_id
                return tab_id

        self._tab_sequence += 1
        tab_id = f"tab-{self._tab_sequence}"
        self._tabs[tab_id] = {"page": page, "incognito": incognito}
        self._active_tabs[incognito] = tab_id
        page.on("close", lambda: self._forget_page(tab_id))
        return tab_id

    def _forget_page(self, tab_id: str) -> None:
        entry = self._tabs.pop(tab_id, None)
        if entry is None:
            return
        incognito = entry["incognito"]
        if self._active_tabs[incognito] == tab_id:
            self._active_tabs[incognito] = next(
                (
                    candidate
                    for candidate, data in reversed(list(self._tabs.items()))
                    if data["incognito"] == incognito
                ),
                None,
            )

    async def _protect_context(self, context, incognito: bool) -> None:
        context.on("page", lambda page: self._register_page(page, incognito))
        await context.route("**/*", self._guard_request)
        if hasattr(context, "route_web_socket"):
            await context.route_web_socket("**/*", self._guard_websocket)

    async def _guard_request(self, route) -> None:
        try:
            await asyncio.to_thread(validate_browser_url, route.request.url)
        except BrowserURLPolicyError as exc:
            self._blocked_requests.append((route.request.url, str(exc)))
            await route.abort()
            return
        await route.continue_()

    async def _guard_websocket(self, route) -> None:
        url = route.url
        parsed = urlsplit(url)
        scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme.lower())
        try:
            if not scheme:
                raise BrowserURLPolicyError("Only public HTTP(S) WebSocket hosts are allowed.")
            await asyncio.to_thread(
                validate_browser_url,
                parsed._replace(scheme=scheme).geturl(),
            )
        except BrowserURLPolicyError as exc:
            self._blocked_requests.append((url, str(exc)))
            await route.close(code=1008, reason="Blocked by browser network policy.")
            return
        await route.connect_to_server()

    async def _get_normal_page(self):
        active_id = self._active_tabs[False]
        if active_id and active_id in self._tabs:
            active_page = self._tabs[active_id]["page"]
            if not active_page.is_closed():
                self._page = active_page
                return active_page
            self._forget_page(active_id)

        if self._context is None:
            self._context = await self._browser.new_context(
                viewport=None,
                service_workers="block",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )
            await self._protect_context(self._context, False)
        self._page = await self._context.new_page()
        self._register_page(self._page, False)
        return self._page

    async def _get_incognito_page(self):
        """
        Gizli/özel sekme açar.
        Chromium → new_context(no_viewport, storage_state temiz)
        Firefox  → new_context(incognito)  [Playwright'ta firefox private]
        """
        active_id = self._active_tabs[True]
        if active_id and active_id in self._tabs:
            active_page = self._tabs[active_id]["page"]
            if not active_page.is_closed():
                self._incog_page = active_page
                return active_page
            self._forget_page(active_id)

        # Önceki gizli context'i kapat
        if self._incog_context:
            try:
                await self._incog_context.close()
            except Exception:
                pass

        print("[Browser] 🕵️  Opening private/incognito context...")

        if self._engine_name == "firefox":
            # Firefox: firefox_user_prefs ile private browsing
            self._incog_context = await self._browser.new_context(
                viewport=None,
                service_workers="block",
                firefox_user_prefs={
                    "browser.privatebrowsing.autostart": True
                }
            )
        else:
            # Chromium tabanlı: --incognito argümanı ile ayrı tarayıcı aç
            # (Playwright'ta context-level incognito için browser.new_context yeterli
            #  çünkü her context zaten izole storage'a sahip.
            #  Gerçek incognito görünümü için ayrı browser instance gerekir.)
            engine = getattr(self._playwright, self._engine_name)
            launch_kwargs = {
                "headless": False,
                "args": ["--incognito", "--start-maximized"],
            }
            if self._exe_path:
                launch_kwargs["executable_path"] = self._exe_path
            elif self._channel:
                launch_kwargs["channel"] = self._channel

            try:
                incog_browser = await engine.launch(**launch_kwargs)
            except Exception:
                incog_browser = await self._playwright.chromium.launch(
                    headless=False,
                    args=["--incognito", "--start-maximized"]
                )

            self._incog_browser = incog_browser
            self._incog_context = await incog_browser.new_context(
                viewport=None,
                service_workers="block",
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                )
            )

        await self._protect_context(self._incog_context, True)
        self._incog_page = await self._incog_context.new_page()
        self._register_page(self._incog_page, True)
        print("[Browser] ✅ Private/incognito page ready.")
        return self._incog_page

    # ── Eylemler ─────────────────────────────────────────────────────────────

    async def _go_to(self, url: str, incognito: bool = False) -> str:
        try:
            url = validate_browser_url(url)
        except BrowserURLPolicyError as exc:
            return f"Blocked navigation: {exc}"
        page = await self._get_page(incognito=incognito)
        self._blocked_requests.clear()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            mode = " [private]" if incognito else ""
            title = await page.title()
            blocked_count = len(self._blocked_requests)
            blocked_note = (
                f"; blocked {blocked_count} private/internal request(s)"
                if blocked_count else ""
            )
            return f"Opened{mode}: {page.url} (title: {title or 'untitled'}){blocked_note}"
        except PlaywrightTimeout:
            if self._blocked_requests:
                blocked_url, reason = self._blocked_requests[-1]
                return f"Navigation blocked: {reason} ({blocked_url})"
            return f"Timeout loading: {url}"
        except Exception as e:
            if self._blocked_requests:
                blocked_url, reason = self._blocked_requests[-1]
                return f"Navigation blocked: {reason} ({blocked_url})"
            return f"Navigation error: {e}"

    async def _search(self, query: str, engine: str = "google", incognito: bool = False) -> str:
        from urllib.parse import quote_plus
        q = quote_plus(query)
        engines = {
            "google":     f"https://www.google.com/search?q={q}",
            "bing":       f"https://www.bing.com/search?q={q}",
            "duckduckgo": f"https://duckduckgo.com/?q={q}",
        }
        page = await self._get_page(incognito=incognito)
        if urlsplit(page.url).hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            search_box = page.locator("input#search, input[name='search_query']")
            count = await search_box.count()
            if count != 1:
                return f"YouTube is open, but its search field is not unique (found {count})."
            try:
                await search_box.fill(query, timeout=8000)
                await search_box.press("Enter", timeout=8000)
                await page.wait_for_url("**/results?search_query=*", timeout=12000)
                if "search_query=" not in page.url:
                    return f"YouTube search did not complete; current URL: {page.url}"
                return f"YouTube search completed in the existing tab: {page.url}"
            except Exception as exc:
                return f"YouTube search failed in the existing tab: {exc}"
        url = engines.get(engine.lower(), engines["google"])
        return await self._go_to(url, incognito=incognito)

    async def _new_tab(self, url: str = "", incognito: bool = False) -> str:
        current = await self._get_page(incognito=incognito)
        page = await current.context.new_page()
        self._register_page(page, incognito)
        if url:
            return await self._go_to(url, incognito=incognito)
        return f"Opened {self._active_tabs[incognito]} (blank tab)."

    async def _list_tabs(self) -> str:
        tabs = []
        for tab_id, entry in list(self._tabs.items()):
            page = entry["page"]
            if page.is_closed():
                self._forget_page(tab_id)
                continue
            try:
                title = await page.title()
                url = page.url
                ready_state = await page.evaluate("document.readyState")
            except Exception as exc:
                title, url, ready_state = "", page.url, f"unavailable: {exc}"
            tabs.append({
                "id": tab_id,
                "active": self._active_tabs[entry["incognito"]] == tab_id,
                "private": entry["incognito"],
                "url": url,
                "title": title,
                "loading_state": ready_state,
            })
        return "[UNTRUSTED BROWSER TAB DATA]\n" + json.dumps(
            tabs, ensure_ascii=False, indent=2
        )

    async def _switch_tab(self, tab_id: str) -> str:
        entry = self._tabs.get(tab_id)
        if entry is None or entry["page"].is_closed():
            return f"Tab not found or closed: {tab_id}"
        self._active_tabs[entry["incognito"]] = tab_id
        page = entry["page"]
        if entry["incognito"]:
            self._incog_page = page
        else:
            self._page = page
        return f"Active tab {tab_id}: {page.url} (title: {await page.title() or 'untitled'})"

    async def _page_state(self, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            state = await page.evaluate(
                """() => ({
                    url: location.href,
                    title: document.title,
                    loading_state: document.readyState,
                    headings: [...document.querySelectorAll('h1,h2,h3')]
                        .filter(element => element.getClientRects().length > 0)
                        .slice(0, 20).map(element => element.innerText.trim())
                        .filter(Boolean),
                    human_verification_required: Boolean(
                        document.querySelector(
                            'iframe[src*="captcha" i], [class*="captcha" i], '
                            + '[id*="captcha" i], [data-sitekey]'
                        )
                    ),
                    one_time_code_field_present: Boolean(
                        document.querySelector(
                            'input[autocomplete="one-time-code"], '
                            + 'input[name*="otp" i], input[name*="mfa" i]'
                        )
                    )
                })"""
            )
            state["tab_id"] = self._active_tabs[incognito]
            state["blocked_private_requests"] = len(self._blocked_requests)
            return "[UNTRUSTED PAGE DATA]\n" + json.dumps(state, ensure_ascii=False, indent=2)
        except Exception as exc:
            return f"Could not read page state: {exc}"

    async def _history(self, direction: str, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            response = await (page.go_back() if direction == "back" else page.go_forward())
            if response is None:
                return f"No {direction} history entry is available."
            await page.wait_for_load_state("domcontentloaded", timeout=10000)
            return f"Navigated {direction}: {page.url} (title: {await page.title() or 'untitled'})"
        except Exception as exc:
            return f"Could not navigate {direction}: {exc}"

    async def _wait_for_element(
        self, selector: str, timeout_ms: int = 10000, incognito: bool = False
    ) -> str:
        if not selector:
            return "A selector is required."
        page = await self._get_page(incognito=incognito)
        timeout_ms = max(1000, min(int(timeout_ms), 30000))
        try:
            await page.locator(selector).wait_for(state="visible", timeout=timeout_ms)
            return f"Element became visible: {selector} (URL: {page.url})"
        except PlaywrightTimeout:
            return f"Timed out waiting for visible element: {selector}"
        except Exception as exc:
            return f"Could not wait for element: {exc}"

    async def _screenshot(self, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            destination = Path.home() / "Downloads" / (
                f"NIANG_IA_browser_{int(time.time())}_{uuid.uuid4().hex[:8]}.png"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(destination), full_page=True, timeout=15000)
            return f"Screenshot saved: {destination}"
        except Exception as exc:
            return f"Could not capture page: {exc}"

    async def _close_tab(self, tab_id: str = "", incognito: bool = False) -> str:
        target_id = tab_id or self._active_tabs[incognito]
        entry = self._tabs.get(target_id)
        if entry is None:
            return f"Tab not found: {target_id or '(none)'}"
        await entry["page"].close()
        self._forget_page(target_id)
        return f"Closed tab {target_id}."

    async def _click(self, selector=None, text=None, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            if text:
                matches = page.get_by_text(text, exact=False)
                count = await matches.count()
                if count != 1:
                    return f"Expected one text match for '{text}', found {count}; nothing was clicked."
                target = matches.first
                blocked = await self._submit_guard(target)
                if blocked:
                    return blocked
                await target.click(timeout=8000)
                return f"Clicked: '{text}'"
            elif selector:
                matches = page.locator(selector)
                count = await matches.count()
                if count != 1:
                    return f"Expected one element matching '{selector}', found {count}; nothing was clicked."
                target = matches.first
                blocked = await self._submit_guard(target)
                if blocked:
                    return blocked
                await target.click(timeout=8000)
                return f"Clicked: {selector}"
            return "No selector or text provided."
        except PlaywrightTimeout:
            return "Element not found or not clickable."
        except Exception as e:
            return f"Click error: {e}"

    async def _submit_guard(self, target) -> str | None:
        try:
            is_submit = await target.evaluate(
                """element => {
                    const control = element.closest(
                        'button, input[type="submit"], input[type="image"], '
                        + '[role="button"], a[href]'
                    );
                    if (!control) return false;
                    const label = [
                        control.getAttribute('aria-label'),
                        control.innerText,
                        control.value,
                        control.title
                    ].filter(Boolean).join(' ').toLowerCase();
                    const searchAction = /search|rechercher|recherche|chercher|find|filter|filtrer/.test(label);
                    if (searchAction) return false;
                    const sensitiveAction = /save|submit|send|publish|delete|remove|enregistrer|soumettre|envoyer|publier|supprimer|effacer|ajouter|modifier|confirmer|valider/.test(label);
                    const nativeSubmit = Boolean(control.form) && (
                        control.matches('input[type="submit"], input[type="image"]')
                        || (control.tagName === 'BUTTON' && control.type === 'submit')
                    );
                    return nativeSubmit || sensitiveAction;
                }"""
            )
        except Exception as e:
            return f"Could not verify the control safely; it was not clicked: {e}"
        if is_submit:
            return "This is a form submit button. Use submit_form, which requires your confirmation."
        return None

    async def _type(self, selector=None, text: str = "", clear_first: bool = True, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            element = page.locator(selector).first if selector else page.locator(":focus")
            if clear_first:
                await element.clear()
            await element.type(text, delay=50)
            return "Text typed."
        except Exception as e:
            return f"Type error: {e}"

    async def _scroll(self, direction: str = "down", amount: int = 500, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            y = amount if direction == "down" else -amount
            await page.mouse.wheel(0, y)
            return f"Scrolled {direction}."
        except Exception as e:
            return f"Scroll error: {e}"

    async def _press(self, key: str, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            if key.strip().lower() in ("enter", "return") and await page.evaluate(
                """() => {
                        const element = document.activeElement;
                        const form = element?.form || element?.closest('form');
                        if (!form) return false;
                        const submitter = form.querySelector(
                            'button[type="submit"], button:not([type]), '
                            + 'input[type="submit"], input[type="image"]'
                        );
                        const label = [
                            submitter?.getAttribute('aria-label'),
                            submitter?.innerText,
                            submitter?.value,
                            submitter?.title
                        ].filter(Boolean).join(' ').toLowerCase();
                        const searchAction = /search|rechercher|recherche|chercher|find|filter|filtrer/.test(label);
                        return form.method.toLowerCase() !== 'get' && !searchAction;
                    }"""
                ):
                return "Enter could submit this form. Use submit_form, which requires your confirmation."
            await page.keyboard.press(key)
            return f"Pressed: {key}"
        except Exception as e:
            return f"Key error: {e}"

    async def _get_text(self, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            text = await page.inner_text("body")
            text = text[:4000] if len(text) > 4000 else text
            return "[UNTRUSTED WEBPAGE TEXT]\n" + text
        except Exception as e:
            return f"Could not get page text: {e}"

    async def _inspect(self, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            details = await page.evaluate(
                """() => {
                    const visible = element => element.getClientRects().length > 0;
                    const cssQuote = value => value.replace(/\\\\/g, '\\\\\\\\')
                        .replace(/"/g, '\\\\"');
                    const selectorFor = element => {
                        if (element.id) return '#' + CSS.escape(element.id);
                        if (element.name) {
                            return element.tagName.toLowerCase()
                                + '[name="' + cssQuote(element.name) + '"]';
                        }
                        const peers = [...element.parentElement.children]
                            .filter(peer => peer.tagName === element.tagName);
                        return element.tagName.toLowerCase()
                            + ':nth-of-type(' + (peers.indexOf(element) + 1) + ')';
                    };
                    const labelFor = element =>
                        element.getAttribute('aria-label')
                        || element.labels?.[0]?.innerText?.trim()
                        || element.getAttribute('placeholder')
                        || element.getAttribute('name')
                        || element.innerText?.trim()
                        || (element.matches('input[type="submit"], input[type="button"]')
                            ? element.value : '')
                        || '';
                    const fields = [...document.querySelectorAll(
                        'input:not([type="password"]):not([type="hidden"]), '
                        + 'textarea, select, [role="combobox"], [contenteditable="true"]'
                    )].filter(visible).slice(0, 40).map(element => ({
                        label: labelFor(element),
                        type: element.getAttribute('type')
                            || element.tagName.toLowerCase(),
                        selector: selectorFor(element)
                    }));
                    const buttons = [...document.querySelectorAll(
                        'button, input[type="submit"], input[type="button"], [role="button"]'
                    )].filter(visible).slice(0, 40).map(element => ({
                        label: labelFor(element),
                        type: element.getAttribute('type') || element.tagName.toLowerCase(),
                        selector: selectorFor(element)
                    }));
                    const links = [...document.querySelectorAll('a[href]')]
                        .filter(visible).slice(0, 40).map(element => ({
                            label: labelFor(element),
                            selector: selectorFor(element)
                        }));
                    const headings = [...document.querySelectorAll('h1, h2, h3')]
                        .filter(visible).slice(0, 20)
                        .map(element => element.innerText.trim()).filter(Boolean);
                    return {
                        title: document.title,
                        url: location.href,
                        headings,
                        fields,
                        buttons,
                        links
                    };
                }"""
            )
            import json
            result = json.dumps(details, ensure_ascii=False, indent=2)
            result = result[:7000] if len(result) > 7000 else result
            return "[UNTRUSTED PAGE STRUCTURE]\n" + result
        except Exception as e:
            return f"Could not inspect page controls: {e}"

    async def _fill_form(self, fields: dict, incognito: bool = False) -> str:
        if not isinstance(fields, dict):
            return "Form fields must be provided as a selector-to-value object."
        page    = await self._get_page(incognito=incognito)
        results = []
        for selector, value in fields.items():
            try:
                matches = page.locator(selector)
                count = await matches.count()
                if count != 1:
                    results.append(
                        f"✗ {selector}: expected one matching field, found {count}"
                    )
                    continue
                el = matches.first
                await el.clear()
                await el.type(str(value), delay=40)
                actual = await el.evaluate(
                    "element => 'value' in element ? element.value : element.innerText"
                )
                if str(actual) != str(value):
                    results.append(f"✗ {selector}: verification did not match the requested value")
                    continue
                results.append(f"✓ {selector}")
            except Exception as e:
                results.append(f"✗ {selector}: {e}")
        return "Form filled: " + ", ".join(results)

    async def _select_option(self, selector: str, value: str, incognito: bool = False) -> str:
        if not selector or not isinstance(value, str):
            return "A selector and string option value are required."
        page = await self._get_page(incognito=incognito)
        try:
            matches = page.locator(selector)
            count = await matches.count()
            if count != 1:
                return f"Expected one option field matching '{selector}', found {count}."
            selected = await matches.select_option(value, timeout=8000)
            if value not in selected:
                return f"Option was not selected for '{selector}'."
            return f"Selected option '{value}' in {selector}."
        except Exception as exc:
            return f"Could not select option in {selector}: {exc}"

    async def _submit_form(self, selector=None, text=None, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)
        try:
            if text:
                matches = page.get_by_role("button", name=text, exact=False)
            elif selector:
                matches = page.locator(selector)
            else:
                return "Provide the submit button text or a CSS selector."
            count = await matches.count()
            if count != 1:
                return (
                    f"Expected one submit button matching '{text or selector}', "
                    f"found {count}; the form was not submitted."
                )
            target = matches.first
            await target.click(timeout=8000)
            return f"Form submitted using: {text or selector}"
        except PlaywrightTimeout:
            return "Submit button not found or not clickable; the form was not submitted."
        except Exception as e:
            return f"Form submission failed: {e}"

    async def _smart_click(self, description: str, incognito: bool = False) -> str:
        page       = await self._get_page(incognito=incognito)
        desc_lower = description.lower()

        role_hints = {
            "button":    ["button", "buton", "btn"],
            "link":      ["link", "bağlantı"],
            "searchbox": ["search", "arama"],
            "textbox":   ["input", "field", "alan"],
        }
        for role, keywords in role_hints.items():
            if any(k in desc_lower for k in keywords):
                try:
                    role_name = desc_lower
                    for keyword in keywords + ["box", "link", "button"]:
                        role_name = role_name.replace(keyword, "")
                    role_name = role_name.strip()
                    matches = (
                        page.get_by_role(role, name=role_name, exact=False)
                        if role_name else page.get_by_role(role)
                    )
                    count = await matches.count()
                    if count > 1:
                        return f"Multiple {role} controls match '{role_name}'; nothing was clicked."
                    if count == 0:
                        continue
                    target = matches.first
                    blocked = await self._submit_guard(target)
                    if blocked:
                        return blocked
                    await target.click(timeout=5000)
                    return f"Clicked ({role}): '{description}'"
                except Exception:
                    pass

        try:
            matches = page.get_by_text(description, exact=False)
            count = await matches.count()
            if count > 1:
                return f"Multiple text matches for '{description}'; nothing was clicked."
            if count == 0:
                raise ValueError("No matching text.")
            target = matches.first
            blocked = await self._submit_guard(target)
            if blocked:
                return blocked
            await target.click(timeout=5000)
            return f"Clicked (text): '{description}'"
        except Exception:
            pass

        try:
            matches = page.get_by_placeholder(description, exact=False)
            count = await matches.count()
            if count > 1:
                return f"Multiple fields match '{description}'; nothing was clicked."
            if count == 0:
                raise ValueError("No matching placeholder.")
            target = matches.first
            blocked = await self._submit_guard(target)
            if blocked:
                return blocked
            await target.click(timeout=5000)
            return f"Clicked (placeholder): '{description}'"
        except Exception:
            pass

        return f"Could not find: '{description}'"

    async def _smart_type(self, description: str, text: str, incognito: bool = False) -> str:
        page = await self._get_page(incognito=incognito)

        for method, locator in [
            ("placeholder", page.get_by_placeholder(description, exact=False)),
            ("label",       page.get_by_label(description, exact=False)),
        ]:
            try:
                count = await locator.count()
                if count > 1:
                    return f"Multiple fields match '{description}'; no text was entered."
                if count == 0:
                    continue
                el = locator.first
                await el.clear()
                await el.type(text, delay=50)
                return f"Typed into ({method}): '{description}'"
            except Exception as e:
                return f"Could not safely type into '{description}': {e}"

        return f"Could not find input: '{description}'"

    async def _close_browser(self) -> str:
        if self._incog_context:
            try:
                await self._incog_context.close()
            except Exception:
                pass
            self._incog_context = None
            self._incog_page    = None

        if self._incog_browser:
            try:
                await self._incog_browser.close()
            except Exception:
                pass
            self._incog_browser = None

        if self._browser:
            await self._browser.close()
            self._browser = None
            self._context = None
            self._page    = None
        self._tabs.clear()
        self._active_tabs = {False: None, True: None}
        self._incog_page = None
        self._blocked_requests.clear()

        return "Browser closed."


# ── Singleton browser thread ─────────────────────────────────────────────────

_bt         = _BrowserThread()
_bt_started = False
_bt_lock    = threading.Lock()


def _ensure_started():
    global _bt_started
    with _bt_lock:
        if not _bt_started:
            _bt.start()
            _bt_started = True


# ── Public API ───────────────────────────────────────────────────────────────

def browser_control(
    parameters:     dict,
    response=None,
    player=None,
    session_memory=None
) -> str:
    """
    Browser controller — auto-detects and uses system default browser.

    parameters:
        action      : go_to | search | new_tab | tabs | switch_tab | state | back |
                      forward | inspect | click | type | scroll | fill_form |
                      select_option | submit_form | smart_click | smart_type |
                      get_text | wait_for_element | screenshot | close_tab | press | close
        url         : URL for go_to
        query       : search query
        engine      : google | bing | duckduckgo (default: google)
        selector    : CSS selector for click/type
        text        : text to click or type
        description : element description for smart_click/smart_type
        direction   : up | down for scroll
        amount      : scroll amount in pixels (default: 500)
        key         : key name for press (e.g. Enter, Escape, Tab)
        fields      : {selector: value} dict for fill_form
        submit_form : selector or text for the submit button; requires explicit
                      user confirmation before this action is dispatched
        clear_first : bool, clear input before typing (default: True)
        incognito   : bool, open in private/incognito mode (default: False)
    """
    _ensure_started()

    action   = (parameters or {}).get("action", "").lower().strip()
    incognito = bool(parameters.get("incognito", False))
    result   = "Unknown action."

    try:
        if action == "go_to":
            result = _bt.run(_bt._go_to(parameters.get("url", ""), incognito=incognito))

        elif action == "new_tab":
            result = _bt.run(_bt._new_tab(
                parameters.get("url", ""),
                incognito=incognito,
            ))

        elif action == "tabs":
            result = _bt.run(_bt._list_tabs())

        elif action == "switch_tab":
            result = _bt.run(_bt._switch_tab(str(parameters.get("tab_id", ""))))

        elif action == "state":
            result = _bt.run(_bt._page_state(incognito=incognito))

        elif action in {"back", "forward"}:
            result = _bt.run(_bt._history(action, incognito=incognito))

        elif action == "search":
            result = _bt.run(_bt._search(
                parameters.get("query", ""),
                parameters.get("engine", "google"),
                incognito=incognito
            ))

        elif action == "click":
            result = _bt.run(_bt._click(
                selector=parameters.get("selector"),
                text=parameters.get("text"),
                incognito=incognito
            ))

        elif action == "type":
            result = _bt.run(_bt._type(
                selector=parameters.get("selector"),
                text=parameters.get("text", ""),
                clear_first=parameters.get("clear_first", True),
                incognito=incognito
            ))

        elif action == "scroll":
            result = _bt.run(_bt._scroll(
                direction=parameters.get("direction", "down"),
                amount=parameters.get("amount", 500),
                incognito=incognito
            ))

        elif action == "fill_form":
            result = _bt.run(_bt._fill_form(
                parameters.get("fields", {}),
                incognito=incognito
            ))

        elif action == "select_option":
            result = _bt.run(_bt._select_option(
                parameters.get("selector", ""),
                parameters.get("value", ""),
                incognito=incognito,
            ))

        elif action == "submit_form":
            result = _bt.run(_bt._submit_form(
                selector=parameters.get("selector"),
                text=parameters.get("text"),
                incognito=incognito
            ))

        elif action == "smart_click":
            result = _bt.run(_bt._smart_click(
                parameters.get("description", ""),
                incognito=incognito
            ))

        elif action == "smart_type":
            result = _bt.run(_bt._smart_type(
                parameters.get("description", ""),
                parameters.get("text", ""),
                incognito=incognito
            ))

        elif action == "get_text":
            result = _bt.run(_bt._get_text(incognito=incognito))

        elif action == "inspect":
            result = _bt.run(_bt._inspect(incognito=incognito))

        elif action == "wait_for_element":
            result = _bt.run(_bt._wait_for_element(
                parameters.get("selector", ""),
                parameters.get("timeout_ms", 10000),
                incognito=incognito,
            ))

        elif action == "screenshot":
            result = _bt.run(_bt._screenshot(incognito=incognito))

        elif action == "close_tab":
            result = _bt.run(_bt._close_tab(
                str(parameters.get("tab_id", "")),
                incognito=incognito,
            ))

        elif action == "press":
            result = _bt.run(_bt._press(
                parameters.get("key", "Enter"),
                incognito=incognito
            ))

        elif action == "close":
            result = _bt.run(_bt._close_browser())

        else:
            result = f"Unknown action: {action}"

    except concurrent.futures.TimeoutError:
        result = "Browser action timed out."
    except Exception as e:
        result = f"Browser error: {e}"

    failed = result.startswith((
        "Browser error:", "Browser action timed out.", "Navigation error:",
        "Blocked navigation:", "Navigation blocked:", "Timeout loading:",
        "Click error:", "Type error:", "Form submission failed:",
        "Could not ", "Unknown action:", "YouTube search failed",
        "YouTube is open, but", "Timed out waiting", "No back history",
        "No forward history", "Tab not found", "Expected one",
        "Multiple fields", "Form fields must",
    ))
    status = "failed" if failed else "completed"
    summary = f"[Browser] {action}: {status}"
    print(summary)
    if player:
        player.write_log(summary[:60])

    return result