"""Server-side smoke checks for the responsive dashboard.

Run with a copy of a representative SQLite database:
    DB_PATH=/path/to/qa.db python -m unittest discover -s tests

Browser layout and touch behavior still require the device checks in
RESPONSIVE_DESIGN_PLAN.md.
"""

import os
import unittest
from datetime import timedelta
from unittest.mock import patch

import pandas as pd
from dash.development.base_component import Component

import dashboard


def walk(node):
    if isinstance(node, Component):
        yield node
        yield from walk(getattr(node, "children", None))
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from walk(child)


class ResponsiveDashboardSmoke(unittest.TestCase):
    def test_app_shell_and_assets(self):
        ids = [node.id for node in walk(dashboard.app.layout)
               if getattr(node, "id", None)]
        self.assertEqual(len(ids), len(set(ids)), "Duplicate IDs in app shell")
        self.assertIn("mobile-filter-toggle", ids)
        self.assertIn("filter-selected-count", ids)
        client = dashboard.server.test_client()
        index = client.get("/")
        self.assertEqual(index.status_code, 200)
        self.assertIn(b'name="viewport" content="width=device-width, initial-scale=1"',
                      index.data)
        css = client.get("/assets/responsive.css")
        self.assertEqual(css.status_code, 200)
        self.assertIn(b"dashboard-filter-body", css.data)
        css.close()
        self.assertEqual(client.get("/_dash-layout").status_code, 200)
        self.assertEqual(client.get("/_dash-dependencies").status_code, 200)
        count = client.post("/_dash-update-component", json={
            "output": "filter-selected-count.children",
            "outputs": {"id": "filter-selected-count", "property": "children"},
            "inputs": [{"id": "selected-tickers", "property": "data",
                        "value": ["NVDA", "AMD"]}],
            "state": [], "changedPropIds": ["selected-tickers.data"],
        })
        self.assertEqual(count.status_code, 200)
        self.assertEqual(count.get_json()["response"]["filter-selected-count"]["children"],
                         "2 tickers selected")
        selection = client.post("/_dash-update-component", json={
            "output": "selected-tickers.data",
            "outputs": {"id": "selected-tickers", "property": "data"},
            "inputs": [
                {"id": "chk-semi-companies", "property": "value", "value": ["NVDA"]},
                {"id": "chk-semi-etfs", "property": "value", "value": ["SOXX"]},
                {"id": "chk-macro--other", "property": "value", "value": []},
                {"id": "chk-tech--mixed", "property": "value", "value": []},
            ],
            "state": [], "changedPropIds": ["chk-semi-companies.value"],
        })
        self.assertEqual(selection.status_code, 200)
        self.assertEqual(selection.get_json()["response"]["selected-tickers"]["data"],
                         ["NVDA", "SOXX"])

    @unittest.skipUnless(os.environ.get("DB_PATH"),
                         "Set DB_PATH to a representative QA database")
    def test_all_tabs_render_without_server_error(self):
        start = (dashboard._now_hkt() - timedelta(days=365)).strftime("%Y-%m-%d")
        end = dashboard._now_hkt().strftime("%Y-%m-%d")
        for tab in ("tab-overview", "tab-financials", "tab-sentiment",
                    "tab-cycles", "tab-compare", "tab-supplychain"):
            with self.subTest(tab=tab):
                result = dashboard.render_tab(tab, ["NVDA", "AMD"], start, end, None)
                nodes = list(walk(result))
                strings = [node.children for node in nodes
                           if isinstance(getattr(node, "children", None), str)]
                self.assertFalse(any("Tab Error" in value for value in strings), strings)
                self.assertFalse(any("Error loading Enterprise" in value for value in strings), strings)
                graphs = [node for node in nodes if node.__class__.__name__ == "Graph"]
                self.assertTrue(all(graph.responsive is True for graph in graphs))
                body = {
                    "output": "tab-content.children",
                    "outputs": {"id": "tab-content", "property": "children"},
                    "inputs": [
                        {"id": "main-tabs", "property": "active_tab", "value": tab},
                        {"id": "selected-tickers", "property": "data", "value": ["NVDA", "AMD"]},
                        {"id": "date-range", "property": "start_date", "value": start},
                        {"id": "date-range", "property": "end_date", "value": end},
                        {"id": "btn-refresh", "property": "n_clicks", "value": None},
                    ],
                    "state": [],
                    "changedPropIds": ["main-tabs.active_tab"],
                }
                response = dashboard.server.test_client().post(
                    "/_dash-update-component", json=body)
                self.assertEqual(response.status_code, 200, response.data[:400])
                self.assertIn("response", response.get_json())

        comparison = dashboard.run_comparison(1, start, end, start, end,
                                              ["NVDA", "AMD"])
        comparison_text = [node.children for node in walk(comparison)
                           if isinstance(getattr(node, "children", None), str)]
        self.assertFalse(any("Tab Error" in value for value in comparison_text))
        self.assertTrue(all(node.responsive is True for node in walk(comparison)
                            if node.__class__.__name__ == "Graph"))
        self.assertGreater(len(dashboard.update_cycle_price_chart("NVDA").data), 0)

    def test_status_details_support_tap_and_keyboard(self):
        for status in (dashboard.update_crawl_badge(0),
                       dashboard.update_freshness_badge(0),
                       dashboard.update_ibkr_badge(0)):
            self.assertEqual(status.__class__.__name__, "Details")
            self.assertEqual(status.children[0].__class__.__name__, "Summary")
            self.assertTrue(status.children[1].children)
        client = dashboard.server.test_client()
        for target in ("crawl-status-badge", "data-freshness-badge",
                       "ibkr-status-badge"):
            with self.subTest(target=target):
                response = client.post("/_dash-update-component", json={
                    "output": f"{target}.children",
                    "outputs": {"id": target, "property": "children"},
                    "inputs": [{"id": "status-interval", "property": "n_intervals",
                                "value": 0}],
                    "state": [], "changedPropIds": ["status-interval.n_intervals"],
                })
                self.assertEqual(response.status_code, 200)

    def test_empty_enterprise_memory_is_an_explained_state(self):
        with patch.object(dashboard, "sc_dram_query", return_value=pd.DataFrame()):
            result = dashboard._sc_enterprise_ram_section()
        text = [node.children for node in walk(result)
                if isinstance(getattr(node, "children", None), str)]
        self.assertTrue(any("No enterprise memory price data" in value
                            for value in text))


if __name__ == "__main__":
    unittest.main()
