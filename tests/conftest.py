from unittest.mock import AsyncMock, patch

import pytest

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def fake_frontend(hass):
    """Il pacchetto hass_frontend non è installato nei test: simuliamo frontend e http."""
    with patch("custom_components.scorte_scadenze._async_register_card", AsyncMock()) as mocked:
        yield mocked
