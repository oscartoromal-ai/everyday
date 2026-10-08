"""The page telling the desktop app its title bar and a nudge dismissed, in a
real browser with a stand-in for pywebview's bridge: through pywebview's
state, which goes one way, never its js_api, whose answer can land in the
next page (error:413a7f47bf31). The `live` and `page` fixtures are conftest.py's."""

import pytest

pytest.importorskip("playwright.sync_api")

# pywebview's bridge as it comes in once the page has loaded: a js_api
# whose calls are counted, and a state whose settings are recorded.
BRIDGE = """() => {
  window.calls = [];
  window.reports = [];
  window.pywebview = {
    api: {
      title_bar: () => window.calls.push("title_bar"),
      nudges_changed: () => window.calls.push("nudges_changed"),
    },
    state: new Proxy({}, {
      set(target, key, value) {
        target[key] = value;
        window.reports.push([key, value]);
        return true;
      },
    }),
  };
  window.dispatchEvent(new CustomEvent("pywebviewready"));
}"""


def test_the_page_tells_the_desktop_app_through_its_state_only(page, live) -> None:
    page.goto(f"{live}/calendar")
    page.evaluate(BRIDGE)
    reports = page.evaluate("window.reports")
    assert len(reports) == 1
    key, bar = reports[0]
    assert key == "titleBar"
    assert bar["paper"].startswith("#") and bar["ink"].startswith("#")
    assert bar["title"] == page.title()
    dark = bar["dark"]

    page.locator(".theme-toggle").click()
    key, bar = page.evaluate("window.reports.at(-1)")
    assert key == "titleBar"
    assert bar["dark"] is not dark

    page.evaluate(
        """() => document.body.dispatchEvent(new CustomEvent("htmx:afterRequest", {
          bubbles: true,
          detail: {
            elt: document.body, successful: true, pathInfo: {requestPath: "/ui/nudges/3/dismiss"},
          },
        }))"""
    )
    key, when = page.evaluate("window.reports.at(-1)")
    assert key == "nudgeDismissed"
    assert isinstance(when, int)

    assert page.evaluate("window.calls") == []
