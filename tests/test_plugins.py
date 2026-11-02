"""Tests for the plugins package public API."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestPluginsPublicAPI:
    def test_base_plugin_importable_from_plugins(self):
        from plugins import BasePlugin
        from plugins.template.plugin import BasePlugin as TemplateBasePlugin

        assert BasePlugin is TemplateBasePlugin

    def test_plugin_context_importable_from_plugins(self):
        from plugins import PluginContext
        from plugins.template.plugin import PluginContext as TemplatePluginContext

        assert PluginContext is TemplatePluginContext
