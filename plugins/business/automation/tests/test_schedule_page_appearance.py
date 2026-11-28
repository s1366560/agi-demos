"""Render the packaged schedule page on light and dark host canvases."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import expect, sync_playwright

UI = Path(__file__).resolve().parents[1] / "ui"


def _rgb(value: str) -> list[float]:
    return [float(number) for number in re.findall(r"[\d.]+", value)]


def _luminance(rgb: list[float]) -> float:
    def linear(channel: float) -> float:
        value = channel / 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    return sum(
        weight * linear(channel)
        for weight, channel in zip((0.2126, 0.7152, 0.0722), rgb, strict=True)
    )


@pytest.mark.integration
@pytest.mark.parametrize(
    ("host_theme", "locale", "placeholder", "empty"),
    [("dark", "zh-CN", "按名称搜索", "暂无数据"), ("light", "en-US", "Search by name", "No data")],
)
def test_signed_schedule_canvas_is_readable(host_theme, locale, placeholder, empty):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(color_scheme=host_theme)
        page.set_content(
            f'<body style="background:{"#101014" if host_theme == "dark" else "#fff"}"><iframe></iframe>'
        )
        frame = page.frames[1]
        frame.set_content('<div id="root"></div>')
        frame.evaluate(
            """locale => {window.memstack = {
                getContext: async () => ({locale, projectId:"project",commands:[],pathname:"/cron-jobs"}),
                invoke: async (_, data) => data.view === "capabilities" ?
                    Object.fromEntries(["create","edit","toggle","run_now","delete"].map(action =>
                        [action,{allowed:true}])) : {items:[], total:0}
            };}""",
            locale,
        )
        frame.add_style_tag(path=UI / "cron-jobs.css")
        frame.add_script_tag(path=UI / "cron-jobs.js")
        expect(frame.get_by_placeholder(placeholder)).to_be_visible()
        expect(frame.locator(".ant-empty-description")).to_have_text(empty)
        rgb = _rgb(frame.locator("body").evaluate("el => getComputedStyle(el).backgroundColor"))
        assert len(rgb) == 3, "the iframe must paint an opaque document canvas"
        for selector in ("h2", ".ant-typography-secondary", ".ant-empty-description", "input"):
            foreground = frame.locator(selector).first.evaluate(
                "(el, pseudo) => getComputedStyle(el,pseudo).color",
                "::placeholder" if selector == "input" else None,
            )
            channels = _rgb(foreground)
            alpha = channels[3] if len(channels) == 4 else 1
            ink = [
                alpha * channel + (1 - alpha) * bg
                for channel, bg in zip(channels[:3], rgb, strict=True)
            ]
            bright, dark = sorted((_luminance(ink), _luminance(rgb)), reverse=True)
            assert (bright + 0.05) / (dark + 0.05) >= 4.5, (selector, foreground)
        browser.close()
