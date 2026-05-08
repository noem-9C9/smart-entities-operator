"""L'intégration Lumière Intelligente UI."""
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry

DOMAIN = "smart_area_lights"
PLATFORMS = ["light"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configure l'intégration à partir de l'interface UI."""
    # Transfère les données vers le fichier light.py
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Désinstalle l'intégration si on la supprime de l'UI."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)