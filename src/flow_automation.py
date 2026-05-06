from __future__ import annotations

import json
import os
import random
import re
import shutil
import subprocess
import zipfile
import time
from pathlib import Path
from urllib import request

FLOW_URL = "https://labs.google/fx/tools/flow"
UNUSUAL_ACTIVITY_TEXT = "We noticed some unusual activity"
UNUSUAL_ACTIVITY_PATTERNS = [
    "We noticed some unusual activity",
    "Мы заметили необычную активность",
    "Мы зафиксировали необычную активность",
    "обнаружили необычную активность",
]
DEFAULT_CDP_PORT = int(os.environ.get("FLOW_CHROME_CDP_PORT", "9223"))
DEFAULT_CDP_HOST = os.environ.get("FLOW_CHROME_CDP_HOST", "127.0.0.1")
FLOW_CHROME_USER_DATA_DIR = os.environ.get("FLOW_CHROME_USER_DATA_DIR", "").strip()
FLOW_CHROME_PROFILE_DIRECTORY = os.environ.get("FLOW_CHROME_PROFILE_DIRECTORY", "").strip()
LEGACY_PROFILE_NAME = "flow_browser_profile"


class FlowAutomation:
    def __init__(self, root: Path):
        self.root = root
        self.legacy_profile_dir = root / "projects" / LEGACY_PROFILE_NAME
        if FLOW_CHROME_USER_DATA_DIR:
            self.chrome_user_data_dir = Path(FLOW_CHROME_USER_DATA_DIR)
        else:
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                self.chrome_user_data_dir = Path(local_appdata) / "FlowVeoStudio" / "ChromeUserData"
            else:
                self.chrome_user_data_dir = root / "projects" / "flow_chrome_user_data"
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.last_error = None
        self.opened_url = None
        self.browser_label = None
        self.chrome_process = None
        self.cdp_port = None

    @property
    def is_open(self) -> bool:
        try:
            return self.page is not None and not self.page.is_closed()
        except Exception:
            return False

    def current_url(self):
        try:
            if self.page is not None and not self.page.is_closed():
                return self.page.url
        except Exception:
            return None
        return None

    def goto(self, url: str, wait_ms: int = 5000):
        if not self.is_open and not self.try_recover_page():
            raise RuntimeError("Flow browser is not open")
        self.page.bring_to_front()
        self._navigate_best_effort(url, wait_ms=wait_ms)
        return self.status()

    def _is_closed_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        return (
            "target page" in text
            or "target closed" in text
            or "browser has been closed" in text
            or "context or browser has been closed" in text
            or "cannot switch to a different thread" in text
        )

    def _reset_connection(self):
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.browser_label = None
        self.cdp_port = None

    def _navigate_best_effort(self, url: str, wait_ms: int = 3000):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        try:
            self.page.bring_to_front()
        except Exception as exc:
            if self._is_closed_error(exc):
                raise
        try:
            self.page.goto(url, wait_until="commit", timeout=15000)
        except Exception as exc:
            if self._is_closed_error(exc):
                raise
            try:
                self.page.evaluate("(targetUrl) => { window.location.href = targetUrl; }", url)
            except Exception as eval_exc:
                if self._is_closed_error(eval_exc):
                    raise
        if wait_ms:
            try:
                self.page.wait_for_timeout(wait_ms)
            except Exception as exc:
                if self._is_closed_error(exc):
                    raise
        try:
            self.opened_url = self.page.url
        except Exception:
            pass

    def try_recover_page(self) -> bool:
        if self.is_open:
            return True
        if self.context is None:
            return False
        try:
            for candidate in list(self.context.pages):
                try:
                    if not candidate.is_closed():
                        self.page = candidate
                        try:
                            self.opened_url = candidate.url
                        except Exception:
                            pass
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False

    def _context_pages(self):
        if self.context is None:
            return None
        try:
            return self.context.pages
        except Exception:
            self._reset_connection()
            return None

    def status(self):
        return {
            "open": self.is_open,
            "url": self.opened_url,
            "last_error": self.last_error,
            "profile_dir": str(self.chrome_user_data_dir),
            "browser": self.browser_label,
            "cdp_port": self.cdp_port,
            "cdp_host": DEFAULT_CDP_HOST,
            "connect_mode": "external_chrome_cdp",
        }

    def _find_chrome_executable(self):
        candidates = [
            shutil.which("chrome"),
            shutil.which("chrome.exe"),
            os.environ.get("CHROME_PATH"),
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        ]
        for candidate in candidates:
            if candidate and Path(candidate).exists():
                return candidate
        raise RuntimeError("Google Chrome executable was not found")

    def _is_cdp_available(self, port: int):
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            with request.urlopen(url, timeout=1) as response:
                return response.status == 200
        except Exception:
            return False

    def _wait_for_cdp(self, port: int, timeout_seconds: float = 15.0):
        deadline = time.time() + timeout_seconds
        last_error = None
        while time.time() < deadline:
            try:
                if self._is_cdp_available(port):
                    return
            except Exception as exc:
                last_error = exc
            time.sleep(0.25)
        raise RuntimeError(f"Chrome remote debugging did not start on port {port}: {last_error}")

    def _cdp_owner_pid(self, port: int):
        try:
            completed = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return None
        if completed.returncode != 0:
            return None
        suffix = f":{port}"
        for line in completed.stdout.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[0].upper() != "TCP":
                continue
            local_address = parts[1]
            state = parts[3].upper()
            if state == "LISTENING" and local_address.endswith(suffix):
                try:
                    return int(parts[4])
                except ValueError:
                    return None
        return None

    def _process_command_line(self, pid: int):
        try:
            completed = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-CimInstance Win32_Process -Filter \"ProcessId = {pid}\").CommandLine",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            return ""
        if completed.returncode != 0:
            return ""
        return (completed.stdout or "").strip()

    def _ensure_cdp_target_is_acceptable(self, port: int):
        pid = self._cdp_owner_pid(port)
        command_line = self._process_command_line(pid) if pid else ""
        normalized = command_line.lower().replace("/", "\\")
        legacy_profile = str(self.legacy_profile_dir).lower().replace("/", "\\")
        if LEGACY_PROFILE_NAME.lower() in normalized or legacy_profile in normalized:
            raise RuntimeError(
                "Chrome CDP port is owned by the old isolated Flow profile. "
                "Close that Chrome window/process first, then start Chrome with start-flow-chrome.bat."
            )
        return {"pid": pid, "command_line": command_line}

    def _ensure_connected_profile_is_acceptable(self):
        if self.context is None:
            return
        page = None
        text = ""
        try:
            page = self.context.new_page()
            page.goto("chrome://version", wait_until="domcontentloaded", timeout=10000)
            text = page.locator("body").inner_text(timeout=5000)
        except Exception:
            return
        finally:
            if page is not None:
                try:
                    page.close()
                except Exception:
                    pass
        normalized = text.lower().replace("/", "\\")
        legacy_profile = str(self.legacy_profile_dir).lower().replace("/", "\\")
        if LEGACY_PROFILE_NAME.lower() in normalized or legacy_profile in normalized:
            self.browser = None
            self.context = None
            self.page = None
            raise RuntimeError(
                "Connected Chrome is using the old isolated Flow profile. "
                "Close that Chrome window/process first, then start Chrome with start-flow-chrome.bat."
            )

    def _launch_regular_chrome_cdp(self, url: str | None = None):
        chrome_path = self._find_chrome_executable()
        self.cdp_port = DEFAULT_CDP_PORT
        self.chrome_user_data_dir.mkdir(parents=True, exist_ok=True)
        args = [
            chrome_path,
            f"--remote-debugging-port={self.cdp_port}",
            f"--user-data-dir={self.chrome_user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--window-size=1400,900",
        ]
        if FLOW_CHROME_PROFILE_DIRECTORY:
            args.append(f"--profile-directory={FLOW_CHROME_PROFILE_DIRECTORY}")
        args.append(url or FLOW_URL)
        self.chrome_process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self._wait_for_cdp(self.cdp_port)
        except Exception as exc:
            raise RuntimeError(
                "Could not start regular Chrome with remote debugging. "
                "Close all Chrome windows and run start-flow-chrome.bat, then try again. "
                f"Original error: {exc}"
            ) from exc

    def _connect_external_chrome_cdp(self, url: str | None = None):
        self.cdp_port = DEFAULT_CDP_PORT
        if not self._is_cdp_available(self.cdp_port):
            self._launch_regular_chrome_cdp(url)
        self._ensure_cdp_target_is_acceptable(self.cdp_port)
        self.browser = self.playwright.chromium.connect_over_cdp(f"http://{DEFAULT_CDP_HOST}:{self.cdp_port}")
        self.context = self.browser.contexts[0] if self.browser.contexts else self.browser.new_context()
        self._ensure_connected_profile_is_acceptable()
        self.browser_label = "Google Chrome (external regular profile via CDP)"
        return self.context.pages

    def open(self, downloads_dir: Path, url: str | None = None):
        try:
            if self.is_open:
                if url:
                    self.opened_url = url
                    try:
                        self._navigate_best_effort(self.opened_url, wait_ms=3000)
                    except Exception as exc:
                        if self._is_closed_error(exc):
                            self._reset_connection()
                            return self.open(downloads_dir, url)
                        raise
                else:
                    try:
                        self.opened_url = self.page.url
                    except Exception:
                        pass
                self.page.bring_to_front()
                return self.status()

            downloads_dir.mkdir(parents=True, exist_ok=True)

            pages = self._context_pages()
            if pages is None:
                from playwright.sync_api import sync_playwright

                self.playwright = sync_playwright().start()
                pages = self._connect_external_chrome_cdp(url or FLOW_URL)
            open_pages = []
            for page in pages:
                try:
                    if not page.is_closed():
                        open_pages.append(page)
                except Exception:
                    continue

            flow_pages = []
            for page in open_pages:
                try:
                    page_url = page.url or ""
                except Exception:
                    page_url = ""
                if "labs.google/fx" in page_url and "tools/flow" in page_url:
                    flow_pages.append((page, page_url))

            target_url = url or FLOW_URL
            chosen = None
            if flow_pages and url:
                for page, page_url in flow_pages:
                    if page_url.rstrip("/") == url.rstrip("/"):
                        chosen = page
                        break
            if chosen is None and flow_pages:
                chosen = flow_pages[0][0]
            if chosen is None:
                chosen = open_pages[0] if open_pages else self.context.new_page()

            self.page = chosen
            self.opened_url = target_url
            current = ""
            try:
                current = self.page.url or ""
            except Exception:
                current = ""
            if current.rstrip("/") != target_url.rstrip("/"):
                try:
                    self._navigate_best_effort(target_url, wait_ms=3000)
                except Exception as exc:
                    if self._is_closed_error(exc):
                        self._reset_connection()
                        return self.open(downloads_dir, url)
                    raise
            self.page.bring_to_front()
            self.last_error = None
            return self.status()
        except Exception as exc:
            self.last_error = str(exc)
            raise

    def close(self, close_browser: bool = True):
        if close_browser and self.context:
            try:
                self.context.close()
            except Exception:
                pass
        if close_browser and self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.playwright:
            try:
                self.playwright.stop()
            except Exception:
                pass
        if close_browser and self.chrome_process:
            try:
                self.chrome_process.terminate()
            except Exception:
                pass
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.browser_label = None
        self.chrome_process = None
        self.cdp_port = None
        return self.status()

    def reload(self, wait_ms: int = 30000):
        if not self.is_open and not self.try_recover_page():
            raise RuntimeError("Flow browser is not open")
        try:
            self.page.bring_to_front()
            self.page.reload(wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(wait_ms)
        except Exception:
            if not self.try_recover_page():
                raise
        try:
            self.opened_url = self.page.url
        except Exception:
            pass
        return self.status()

    def _first_visible(self, selectors: list[str]):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        for selector in selectors:
            loc = self.page.locator(selector)
            count = loc.count()
            for index in range(count - 1, -1, -1):
                item = loc.nth(index)
                try:
                    if item.is_visible(timeout=500) and item.is_enabled(timeout=500):
                        return item
                except Exception:
                    continue
        return None

    def _find_prompt_input(self):
        token = self.page.evaluate(
            """() => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const isEnabled = (el) =>
                    !el.disabled &&
                    el.getAttribute('aria-disabled') !== 'true' &&
                    el.getAttribute('disabled') === null;
                const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const labelFor = (el) => clean([
                    el.getAttribute('placeholder'),
                    el.getAttribute('aria-label'),
                    el.getAttribute('title'),
                    el.innerText,
                    el.textContent,
                ].join(' '));

                const candidates = [...document.querySelectorAll(
                    "textarea, input[type='text'], [role='textbox'], [contenteditable='true']"
                )]
                    .filter((el) => isVisible(el) && isEnabled(el))
                    .map((el) => {
                        const rect = el.getBoundingClientRect();
                        const label = labelFor(el);
                        const looksLikeFlowComposer = /что вы хотите создать|what do you want to create|prompt/i.test(label);
                        const bottomComposerPosition = rect.top > window.innerHeight * 0.45;
                        const usableSize = rect.width >= 120 && rect.height >= 18;
                        let score = 0;
                        if (looksLikeFlowComposer) score += 10000;
                        if (bottomComposerPosition) score += 2000;
                        if (usableSize) score += 500;
                        score += rect.bottom;
                        return { el, rect, score };
                    })
                    .filter((item) => item.score >= 2500)
                    .sort((a, b) => b.score - a.score);

                document.querySelectorAll('[data-flow-veo-prompt-input]').forEach((el) => {
                    el.removeAttribute('data-flow-veo-prompt-input');
                });
                const best = candidates[0]?.el;
                if (!best) return '';
                const token = `flow-veo-prompt-${Date.now()}-${Math.random().toString(16).slice(2)}`;
                best.setAttribute('data-flow-veo-prompt-input', token);
                return token;
            }"""
        )
        if not token:
            raise RuntimeError("Could not find Flow prompt input. Click the prompt box in Flow and try again.")
        return self.page.locator(f"[data-flow-veo-prompt-input='{token}']")

    def _human_pause(self, min_ms: int = 120, max_ms: int = 420):
        if not self.is_open:
            return
        low = max(0, int(min_ms))
        high = max(low, int(max_ms))
        self.page.wait_for_timeout(random.randint(low, high))

    def _clipboard_paste(self, text: str) -> bool:
        try:
            origin = self.page.evaluate("() => window.location.origin")
            if self.context is not None and origin:
                try:
                    self.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=origin)
                except Exception:
                    pass
            self.page.evaluate("(value) => navigator.clipboard.writeText(value)", text)
            self._human_pause(100, 300)
            self.page.keyboard.press("Control+V")
            return True
        except Exception:
            return False

    def _prompt_input_text(self, prompt_input) -> str:
        try:
            return prompt_input.evaluate(
                """(el) => {
                    if ('value' in el) return el.value || '';
                    if (el.isContentEditable) return el.innerText || el.textContent || '';
                    return el.innerText || el.textContent || '';
                }"""
            )
        except Exception:
            return ""

    def _insert_prompt_human_like(self, prompt_input, prompt: str):
        prompt_input.click(timeout=5000)
        self._human_pause(150, 500)
        self.page.keyboard.press("Control+A")
        self._human_pause(100, 300)

        if not self._clipboard_paste(prompt):
            self.page.keyboard.insert_text(prompt)
        self._human_pause(180, 520)

        if self._prompt_input_text(prompt_input).strip() == prompt.strip():
            return

        self.page.keyboard.press("Control+A")
        self._human_pause(100, 260)
        self.page.keyboard.insert_text(prompt)
        self._human_pause(180, 520)
        if self._prompt_input_text(prompt_input).strip() == prompt.strip():
            return

        # Last-resort recovery only; normal submissions should use keyboard/clipboard events.
        prompt_input.fill(prompt, timeout=5000)
        self._human_pause(180, 520)
        if self._prompt_input_text(prompt_input).strip() != prompt.strip():
            raise RuntimeError("Flow prompt input did not accept the prompt text")

    def _submit_from_prompt_enter(self, prompt_input):
        self._human_pause(150, 450)
        prompt_input.click(timeout=5000)
        self._human_pause(80, 220)
        self.page.keyboard.press("Enter")
        self._human_pause(900, 1500)

    def submit_prompt(self, prompt: str, delay_seconds: float = 2.5):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        self.page.bring_to_front()
        prompt_input = self._find_prompt_input()
        self._insert_prompt_human_like(prompt_input, prompt)
        self._submit_from_prompt_enter(prompt_input)
        if self._prompt_input_text(prompt_input).strip() == prompt.strip():
            raise RuntimeError(
                "Flow did not accept Enter submit from the bottom composer: the prompt text stayed in the input. "
                "Stopped before marking it as submitted."
            )
        base_delay = max(1.2, min(float(delay_seconds), 4.5))
        effective_delay = random.uniform(max(1.2, base_delay - 1.3), min(4.5, base_delay + 2.0))
        time.sleep(effective_delay)

    def visible_flow_errors(self):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        return self.page.evaluate(
            """(unusualPatterns) => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const matchesUnusual = (text) => unusualPatterns.some((p) => text.includes(p));
                const seen = new Set();
                const results = [];
                const errorNodes = [...document.querySelectorAll('body *')]
                    .filter(isVisible)
                    .filter((el) => matchesUnusual(clean(el.innerText || el.textContent || '')))
                    .filter((el) => ![...el.children].some((child) =>
                        isVisible(child) && matchesUnusual(clean(child.innerText || child.textContent || ''))
                    ));

                for (const errorNode of errorNodes) {
                    let node = errorNode;
                    let cardText = clean(errorNode.innerText || errorNode.textContent || '');
                    let index = null;
                    for (let depth = 0; node && depth < 16; depth += 1) {
                        const text = clean(node.innerText || node.textContent || '');
                        if (matchesUnusual(text)) {
                            cardText = text;
                            const match = text.match(/#(\\d{3})/);
                            if (match) {
                                index = Number(match[1]);
                                break;
                            }
                        }
                        node = node.parentElement;
                    }
                    const key = index === null ? `unknown:${cardText.slice(0, 120)}` : `index:${index}`;
                    if (seen.has(key)) continue;
                    seen.add(key);
                    results.push({
                        index,
                        type: 'unusual_activity',
                        message: unusualPatterns[0],
                        card_text: cardText.slice(0, 1000),
                    });
                }
                const pageText = clean(document.body ? document.body.innerText : '');
                const url = window.location.href;
                const blockers = [
                    {
                        type: 'unsupported_country',
                        message: 'Flow is not available in this country',
                        patterns: [
                            'unsupported-country',
                            'Flow ещё не работает в вашей стране',
                            'Flow is not available in your country',
                            'not available in your country',
                        ],
                    },
                    {
                        type: 'recaptcha_unavailable',
                        message: 'Flow reCAPTCHA connectivity problem',
                        patterns: [
                            'Не удается связаться с сервисом reCAPTCHA',
                            'reCAPTCHA',
                        ],
                    },
                ];
                for (const blocker of blockers) {
                    if (blocker.patterns.some((pattern) => pageText.includes(pattern) || url.includes(pattern))) {
                        const key = `page:${blocker.type}`;
                        if (!seen.has(key)) {
                            seen.add(key);
                            results.push({
                                index: null,
                                type: blocker.type,
                                message: blocker.message,
                                card_text: pageText.slice(0, 1000),
                            });
                        }
                    }
                }
                return results;
            }""",
            UNUSUAL_ACTIVITY_PATTERNS,
        )

    def _visible_media_candidates(self):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        return self.page.evaluate(
            """() => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const downloadEls = [...document.querySelectorAll('button, a[href]')]
                    .filter(isVisible)
                    .filter((el) => /download|save|export|скач|загруз/i.test([
                        el.innerText,
                        el.textContent,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                        el.getAttribute('href'),
                    ].join(' ')));
                const normalizeMediaUrl = (value) => {
                    if (!value || !/media\\.getMediaUrlRedirect/.test(value)) return '';
                    const url = new URL(value, location.href);
                    url.searchParams.delete('mediaUrlType');
                    return url.href;
                };
                const mediaUrls = [];
                for (const el of [...document.querySelectorAll('video, source, img')]) {
                    const url = normalizeMediaUrl(el.currentSrc || el.src || el.getAttribute('src') || '');
                    if (url && !mediaUrls.includes(url)) mediaUrls.push(url);
                }
                return downloadEls.map((button, ordinal) => {
                    let node = button;
                    let cardText = '';
                    for (let depth = 0; node && depth < 14; depth += 1) {
                        cardText = clean(node.innerText || node.textContent || '');
                        if (/#\\d{3}/.test(cardText)) {
                            break;
                        }
                        node = node.parentElement;
                    }
                    const indexMatch = cardText.match(/#(\\d{3})/);
                    return {
                        ordinal,
                        index: indexMatch ? Number(indexMatch[1]) : null,
                        video_src: mediaUrls[ordinal] || '',
                        text: clean(button.innerText || button.textContent || button.getAttribute('aria-label') || ''),
                        card_text: cardText.slice(0, 900),
                    };
                }).filter((item) => item.index !== null && item.video_src);
            }"""
        )

    def _click_download_for_index(self, index: int):
        clicked = self.page.evaluate(
            """(targetIndex) => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const marker = `#${String(targetIndex).padStart(3, '0')}`;
                const isDownload = (el) => /download|save|export|скач|загруз/i.test([
                        el.innerText,
                        el.textContent,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                        el.getAttribute('href'),
                    ].join(' '));

                const buttons = [...document.querySelectorAll('button, a[href]')]
                    .filter(isVisible)
                    .filter(isDownload);

                for (const button of buttons) {
                    let node = button;
                    for (let depth = 0; node && depth < 12; depth += 1) {
                        const text = clean(node.innerText || node.textContent || '');
                        if (text.includes(marker)) {
                            button.scrollIntoView({ block: 'center', inline: 'nearest' });
                            button.click();
                            return true;
                        }
                        node = node.parentElement;
                    }
                }
                return false;
            }""",
            index,
        )
        if not clicked:
            raise RuntimeError(f"Download button for #{index:03d} disappeared before click")

    def _visible_retry_candidates(self):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        return self.page.evaluate(
            """() => {
                const isVisible = (el) => {
                    const style = window.getComputedStyle(el);
                    const rect = el.getBoundingClientRect();
                    return style &&
                        style.visibility !== 'hidden' &&
                        style.display !== 'none' &&
                        rect.width > 0 &&
                        rect.height > 0;
                };
                const clean = (value) => (value || '').replace(/\\s+/g, ' ').trim();
                const retryEls = [...document.querySelectorAll('button, [role="button"]')]
                    .filter(isVisible)
                    .filter((el) => /refresh|retry|повтор/i.test([
                        el.innerText,
                        el.textContent,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                    ].join(' ')))
                    .filter((el) => !/undo|regenerate|сгенер/i.test([
                        el.innerText,
                        el.textContent,
                        el.getAttribute('aria-label'),
                        el.getAttribute('title'),
                    ].join(' ')));

                return retryEls.map((el, ordinal) => {
                    let node = el;
                    let cardText = '';
                    for (let depth = 0; node && depth < 14; depth += 1) {
                        cardText = clean(node.innerText || node.textContent || '');
                        if (/#\\d{3}/.test(cardText)) break;
                        node = node.parentElement;
                    }
                    const indexMatch = cardText.match(/#(\\d{3})/);
                    return {
                        ordinal,
                        index: indexMatch ? Number(indexMatch[1]) : null,
                        text: clean(el.innerText || el.textContent || el.getAttribute('aria-label') || ''),
                        card_text: cardText.slice(0, 900),
                    };
                });
            }"""
        )

    def retry_visible_failed(self, known_indexes: set[int] | None = None, max_count: int = 10):
        candidates = self._visible_retry_candidates()
        if known_indexes is not None:
            candidates = [
                item for item in candidates
                if item.get("index") is not None and int(item["index"]) in known_indexes
            ]
        candidates = candidates[:max_count]
        results = []
        for candidate in candidates:
            index = candidate.get("index")
            current = self._visible_retry_candidates()
            matching = [
                item for item in current
                if item.get("index") == index or (index is None and item.get("ordinal") == candidate.get("ordinal"))
            ]
            if not matching:
                continue
            ordinal = int(matching[0]["ordinal"])
            try:
                clicked = self.page.evaluate(
                    """(ordinal) => {
                        const isVisible = (el) => {
                            const style = window.getComputedStyle(el);
                            const rect = el.getBoundingClientRect();
                            return style &&
                                style.visibility !== 'hidden' &&
                                style.display !== 'none' &&
                                rect.width > 0 &&
                                rect.height > 0;
                        };
                        const retryEls = [...document.querySelectorAll('button, [role="button"]')]
                            .filter(isVisible)
                            .filter((el) => /refresh|retry|повтор/i.test([
                                el.innerText,
                                el.textContent,
                                el.getAttribute('aria-label'),
                                el.getAttribute('title'),
                            ].join(' ')))
                            .filter((el) => !/undo|regenerate|сгенер/i.test([
                                el.innerText,
                                el.textContent,
                                el.getAttribute('aria-label'),
                                el.getAttribute('title'),
                            ].join(' ')));
                        const el = retryEls[ordinal];
                        if (!el) return false;
                        el.click();
                        return true;
                    }""",
                    ordinal,
                )
                if not clicked:
                    raise RuntimeError("Retry button disappeared before click")
                self.page.wait_for_timeout(1200)
                results.append(
                    {
                        "index": index,
                        "status": "retried",
                        "message": "Clicked Flow retry button.",
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "index": index,
                        "status": "retry_error",
                        "error": str(exc),
                    }
                )
        return results

    def _save_download_as_video(self, download, target: Path, work_dir: Path):
        work_dir.mkdir(parents=True, exist_ok=True)
        raw_path = work_dir / download.suggested_filename
        if raw_path.exists():
            stem = raw_path.stem or "download"
            raw_path = work_dir / f"{stem}_{int(time.time())}{raw_path.suffix}"
        download.save_as(str(raw_path))

        with raw_path.open("rb") as file:
            signature = file.read(8)

        if signature.startswith(b"\x00\x00") and b"ftyp" in signature:
            target.write_bytes(raw_path.read_bytes())
            return {"raw_path": str(raw_path), "container": "mp4"}

        if signature.startswith(b"PK"):
            with zipfile.ZipFile(raw_path) as archive:
                video_names = [
                    name for name in archive.namelist()
                    if name.lower().endswith((".mp4", ".mov", ".webm"))
                ]
                if not video_names:
                    raise RuntimeError(f"Downloaded ZIP did not contain a video file: {raw_path}")
                with archive.open(video_names[0]) as source, target.open("wb") as dest:
                    dest.write(source.read())
            return {"raw_path": str(raw_path), "container": "zip", "inner_name": video_names[0]}

        raise RuntimeError(f"Downloaded file is not an MP4 or ZIP video package: {raw_path}")

    def _save_response_as_video(self, response, target: Path, raw_path: Path):
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_bytes(response.body())

        with raw_path.open("rb") as file:
            signature = file.read(8)

        if signature.startswith(b"\x00\x00") and b"ftyp" in signature:
            target.write_bytes(raw_path.read_bytes())
            return {"raw_path": str(raw_path), "container": "mp4_src"}

        if signature.startswith(b"PK"):
            with zipfile.ZipFile(raw_path) as archive:
                video_names = [
                    name for name in archive.namelist()
                    if name.lower().endswith((".mp4", ".mov", ".webm"))
                ]
                if not video_names:
                    raise RuntimeError(f"Downloaded ZIP did not contain a video file: {raw_path}")
                with archive.open(video_names[0]) as source, target.open("wb") as dest:
                    dest.write(source.read())
            return {"raw_path": str(raw_path), "container": "zip_src", "inner_name": video_names[0]}

        raise RuntimeError(f"Media URL did not return an MP4 or ZIP video package: {raw_path}")

    def _is_mp4_file(self, path: Path):
        if not path.exists() or path.stat().st_size < 16:
            return False
        with path.open("rb") as file:
            header = file.read(16)
        return b"ftyp" in header[:12]

    def collect_visible_indexes(self, max_scrolls: int = 30):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        self.page.bring_to_front()
        try:
            self.page.evaluate(
                """() => {
                    const candidates = [...document.querySelectorAll('*')]
                        .filter((el) => {
                            const style = window.getComputedStyle(el);
                            return /(auto|scroll)/.test(style.overflowY) &&
                                el.scrollHeight > el.clientHeight + 50;
                        })
                        .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                    const target = candidates[0] || document.scrollingElement || document.documentElement;
                    target.scrollTop = 0;
                }"""
            )
        except Exception:
            pass
        self.page.wait_for_timeout(700)
        found = set()
        stable_rounds = 0
        for _ in range(max_scrolls):
            try:
                indexes = self.page.evaluate(
                    """() => {
                        const text = (document.body.innerText || '').replace(/\\s+/g, ' ');
                        return [...new Set((text.match(/#\\d{3}/g) || []))];
                    }"""
                )
            except Exception:
                break
            for token in indexes or []:
                try:
                    found.add(int(str(token).lstrip('#')))
                except Exception:
                    continue
            try:
                scroll = self._scroll_results()
            except Exception:
                break
            self.page.wait_for_timeout(800)
            if scroll.get("after") == scroll.get("before") or scroll.get("after") >= scroll.get("max"):
                stable_rounds += 1
                if stable_rounds >= 2:
                    break
            else:
                stable_rounds = 0
        return sorted(found)

    def _scroll_results(self):
        return self.page.evaluate(
            """() => {
                const scrollables = [...document.querySelectorAll('*')]
                    .filter((el) => {
                        const style = window.getComputedStyle(el);
                        return /(auto|scroll)/.test(style.overflowY) &&
                            el.scrollHeight > el.clientHeight + 50;
                    })
                    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
                const target = scrollables[0] || document.scrollingElement || document.documentElement;
                const before = target.scrollTop;
                target.scrollBy(0, Math.max(500, Math.floor(window.innerHeight * 0.8)));
                return {
                    before,
                    after: target.scrollTop,
                    max: target.scrollHeight - target.clientHeight,
                };
            }"""
        )

    def download_visible_from_media_src(
        self,
        output_dir: Path,
        work_dir: Path,
        names_by_index: dict[int, str],
        max_count: int = 10,
    ):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")
        self.page.bring_to_front()
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        candidates = [
            item for item in self._visible_media_candidates()
            if item.get("index") is not None and int(item["index"]) in names_by_index
        ][:max_count]
        results = []

        for candidate in candidates:
            index = int(candidate["index"])
            filename = names_by_index.get(index) or f"clip_{index:04d}"
            filename = re.sub(r"[^a-zA-Z0-9_.-]+", "_", filename).strip("._") or f"clip_{index:04d}"
            if not filename.lower().endswith(".mp4"):
                filename = f"{filename}.mp4"
            target = output_dir / filename
            if target.exists() and self._is_mp4_file(target):
                results.append(
                    {
                        "index": index,
                        "status": "skipped_existing",
                        "path": str(target),
                        "flow_title": filename[:-4],
                    }
                )
                continue
            if target.exists():
                bad_target = work_dir / f"bad_{target.name}_{int(time.time())}"
                target.replace(bad_target)

            media_url = candidate["video_src"]
            raw_path = work_dir / f"media_{index:03d}_{int(time.time())}"
            try:
                response = self.context.request.get(media_url, timeout=120000)
                if not response.ok:
                    raise RuntimeError(f"Media request failed: HTTP {response.status}")
                saved = self._save_response_as_video(response, target, raw_path)
                results.append(
                    {
                        "index": index,
                        "status": "downloaded",
                        "path": str(target),
                        "flow_title": filename[:-4],
                        "media_url": media_url,
                        **saved,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "index": index,
                        "status": "error",
                        "error": str(exc),
                        "path": str(target),
                        "flow_title": filename[:-4],
                        "media_url": media_url,
                    }
                )
        return results

    def download_all_visible_with_scroll(
        self,
        output_dir: Path,
        work_dir: Path,
        names_by_index: dict[int, str],
        max_count: int = 80,
    ):
        if not self.is_open:
            raise RuntimeError("Flow browser is not open")

        all_results = []
        seen_indexes = set()
        retried_indexes = set()
        stuck_rounds = 0

        def download_attempt_count():
            return sum(1 for item in all_results if item.get("status") != "retried")

        while download_attempt_count() < max_count and stuck_rounds < 4:
            flow_errors = [
                item for item in self.visible_flow_errors()
                if item.get("index") is not None and int(item["index"]) in names_by_index
            ]
            for item in flow_errors:
                index = int(item["index"])
                if index in seen_indexes:
                    continue
                seen_indexes.add(index)
                all_results.append(
                    {
                        "index": index,
                        "status": "flow_error",
                        "error": item.get("message") or "Flow error",
                        "card_text": item.get("card_text", ""),
                    }
                )

            visible = self._visible_media_candidates()
            visible_indexes = [
                int(item["index"]) for item in visible
                if item.get("index") is not None and int(item["index"]) in names_by_index
            ]
            visible_indexes = [idx for idx in visible_indexes if idx not in seen_indexes]

            if visible_indexes:
                batch_names = {idx: names_by_index[idx] for idx in visible_indexes}
                remaining = max_count - download_attempt_count()
                results = self.download_visible_from_media_src(output_dir, work_dir, batch_names, max_count=remaining)
                all_results.extend(results)
                for item in results:
                    if "index" in item:
                        seen_indexes.add(int(item["index"]))
                stuck_rounds = 0
            else:
                retryable = set(names_by_index) - retried_indexes - seen_indexes
                retry_results = self.retry_visible_failed(retryable, max_count=5)
                for item in retry_results:
                    if item.get("index") is not None:
                        retried_indexes.add(int(item["index"]))
                    all_results.append(item)
                if retry_results:
                    stuck_rounds = 0
                    self.page.wait_for_timeout(6000)
                    continue
                stuck_rounds += 1

            scroll = self._scroll_results()
            try:
                self.page.keyboard.press("PageDown")
            except Exception:
                pass
            self.page.wait_for_timeout(900)
            if scroll.get("after") == scroll.get("before") or scroll.get("after") >= scroll.get("max"):
                stuck_rounds += 1

        return all_results
