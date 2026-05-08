import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector, label_registry as lr

_LOGGER = logging.getLogger(__name__)

# Le même nom de domaine que dans manifest.json
DOMAIN = "smart_area_lights"

class LumiereIntelligenteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère l'interface de configuration depuis l'UI."""
    
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Obtenir le gestionnaire d'options pour cette entrée."""
        return LumiereIntelligenteOptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Étape principale de configuration."""
        if user_input is not None:
            return self.async_create_entry(
                title="Configuration Lumières Intelligentes", 
                data=user_input
            )

        try:
            # Extraction des labels (étiquettes) existants
            label_reg = lr.async_get(self.hass)
            label_options = [{"value": "none", "label": "Aucun (Toutes les lumières)"}] + [
                {"value": label.label_id, "label": label.name}
                for label in label_reg.labels.values()
            ]
        except Exception as err:
            _LOGGER.error("Erreur lors de la récupération des labels : %s", err)
            label_options = []

        schema = vol.Schema({
            vol.Required("all_areas", default=False): selector.BooleanSelector(),
            vol.Optional("target_areas"): selector.AreaSelector(
                selector.AreaSelectorConfig(multiple=True)
            ),
            vol.Optional("label_filter"): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=label_options,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required("use_brightness", default=True): selector.BooleanSelector(),
            vol.Required("use_color_temp", default=True): selector.BooleanSelector(),
            vol.Required("use_rgb_color", default=True): selector.BooleanSelector(),
        })

        return self.async_show_form(step_id="user", data_schema=schema)

class LumiereIntelligenteOptionsFlowHandler(config_entries.OptionsFlow):
    """Gère les options de l'intégration."""

    def __init__(self, config_entry):
        """Initialiser le flux d'options."""
        # HA 2024+ : config_entry est une propriété read-only, HA s'en occupe
        pass

    async def async_step_init(self, user_input=None):
        """Gérer les options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        try:
            # Extraction des labels (étiquettes) existants
            label_reg = lr.async_get(self.hass)
            label_options = [{"value": "none", "label": "Aucun (Toutes les lumières)"}] + [
                {"value": label.label_id, "label": label.name}
                for label in label_reg.labels.values()
            ]
        except Exception as err:
            _LOGGER.error("Erreur lors de la récupération des labels (options) : %s", err)
            label_options = []

        # On récupère les valeurs actuelles (data + options)
        conf = {**self.config_entry.data, **self.config_entry.options}

        schema = vol.Schema({
            vol.Optional("label_filter", default=conf.get("label_filter")): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=label_options,
                    mode=selector.SelectSelectorMode.DROPDOWN
                )
            ),
            vol.Required("use_brightness", default=conf.get("use_brightness", True)): selector.BooleanSelector(),
            vol.Required("use_color_temp", default=conf.get("use_color_temp", True)): selector.BooleanSelector(),
            vol.Required("use_rgb_color", default=conf.get("use_rgb_color", True)): selector.BooleanSelector(),
        })

        return self.async_show_form(step_id="init", data_schema=schema)