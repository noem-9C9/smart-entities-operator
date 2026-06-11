import logging
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector, label_registry as lr

from .const import (
    DOMAIN, ENTRY_TYPE_COVER, ENTRY_TYPE_LIGHT, ENTRY_TYPE_SENSOR, ENTRY_TYPE_SWITCH
)

_LOGGER = logging.getLogger(__name__)

# (step_id, entry_type, titre de l'entrée créée)
GROUP_STEPS = {
    "lights": (ENTRY_TYPE_LIGHT, "Lumières intelligentes"),
    "covers": (ENTRY_TYPE_COVER, "Volets intelligents"),
    "switches": (ENTRY_TYPE_SWITCH, "Switchs intelligents"),
}

LIGHT_OPTION_KEYS = ("use_brightness", "use_color_temp", "use_rgb_color")


def _get_label_options(hass, none_label="Aucun (Pas de filtre)"):
    """Liste des labels existants pour le sélecteur (avec une option 'aucun')."""
    try:
        label_reg = lr.async_get(hass)
        return [{"value": "none", "label": none_label}] + [
            {"value": label.label_id, "label": label.name}
            for label in label_reg.labels.values()
        ]
    except Exception as err:
        _LOGGER.error("Erreur lors de la récupération des labels : %s", err)
        return []


def _group_schema(hass, conf, entry_type):
    """Schéma commun des groupes : pièces ciblées et/ou entité globale Maison."""
    schema = {
        vol.Required("all_areas", default=conf.get("all_areas", False)): selector.BooleanSelector(),
        vol.Optional("target_areas", default=conf.get("target_areas", [])): selector.AreaSelector(
            selector.AreaSelectorConfig(multiple=True)
        ),
        vol.Required("create_global", default=conf.get("create_global", False)): selector.BooleanSelector(),
        vol.Optional("label_filter", default=conf.get("label_filter", "none")): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_get_label_options(hass),
                mode=selector.SelectSelectorMode.DROPDOWN
            )
        ),
    }
    if entry_type == ENTRY_TYPE_LIGHT:
        for key in LIGHT_OPTION_KEYS:
            schema[vol.Required(key, default=conf.get(key, True))] = selector.BooleanSelector()
    return vol.Schema(schema)


def _sensor_schema(hass, conf, with_offsets=False):
    """Schéma des capteurs globaux (moyennes maison)."""
    schema = {
        vol.Required("keywords", default=conf.get("keywords", "temperature, humidite")): selector.TextSelector(),
        vol.Optional("label_filter", default=conf.get("label_filter", "none")): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=_get_label_options(hass),
                mode=selector.SelectSelectorMode.DROPDOWN
            )
        ),
    }
    if with_offsets:
        schema[vol.Optional("offsets", default=conf.get("offsets", ""))] = selector.TextSelector(
            selector.TextSelectorConfig(multiline=True)
        )
    return vol.Schema(schema)


class SmartAreaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Gère l'interface de configuration depuis l'UI."""

    VERSION = 2

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Obtenir le gestionnaire d'options pour cette entrée."""
        return SmartAreaOptionsFlowHandler()

    async def async_step_user(self, user_input=None):
        """Étape principale : choisir le type de groupement à créer."""
        return self.async_show_menu(
            step_id="user",
            menu_options=["lights", "covers", "switches", "sensors"],
        )

    async def _async_step_group(self, step_id, user_input):
        """Étape commune de création d'un groupe (lumières, volets, switchs)."""
        entry_type, title = GROUP_STEPS[step_id]
        if user_input is not None:
            user_input["entry_type"] = entry_type
            return self.async_create_entry(title=title, data=user_input)

        return self.async_show_form(
            step_id=step_id,
            data_schema=_group_schema(self.hass, {}, entry_type),
        )

    async def async_step_lights(self, user_input=None):
        """Configuration d'un groupe de lumières."""
        return await self._async_step_group("lights", user_input)

    async def async_step_covers(self, user_input=None):
        """Configuration d'un groupe de volets."""
        return await self._async_step_group("covers", user_input)

    async def async_step_switches(self, user_input=None):
        """Configuration d'un groupe de switchs."""
        return await self._async_step_group("switches", user_input)

    async def async_step_sensors(self, user_input=None):
        """Configuration des capteurs globaux (moyennes maison)."""
        if user_input is not None:
            user_input["entry_type"] = ENTRY_TYPE_SENSOR
            return self.async_create_entry(title="Capteurs globaux", data=user_input)

        return self.async_show_form(
            step_id="sensors",
            data_schema=_sensor_schema(self.hass, {}),
        )


class SmartAreaOptionsFlowHandler(config_entries.OptionsFlow):
    """Gère les options de l'intégration (l'entrée est rechargée à la validation)."""

    @property
    def _conf(self):
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input=None):
        """Aiguiller vers les options du bon type d'entrée."""
        entry_type = self.config_entry.data.get("entry_type", ENTRY_TYPE_LIGHT)
        if entry_type == ENTRY_TYPE_SENSOR:
            return await self.async_step_sensors(user_input)
        step_id = next(s for s, (t, _) in GROUP_STEPS.items() if t == entry_type)
        return await self._async_step_group(step_id, user_input)

    async def _async_step_group(self, step_id, user_input):
        """Options communes des groupes."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        entry_type, _ = GROUP_STEPS[step_id]
        return self.async_show_form(
            step_id=step_id,
            data_schema=_group_schema(self.hass, self._conf, entry_type),
        )

    async def async_step_lights(self, user_input=None):
        """Options d'un groupe de lumières."""
        return await self._async_step_group("lights", user_input)

    async def async_step_covers(self, user_input=None):
        """Options d'un groupe de volets."""
        return await self._async_step_group("covers", user_input)

    async def async_step_switches(self, user_input=None):
        """Options d'un groupe de switchs."""
        return await self._async_step_group("switches", user_input)

    async def async_step_sensors(self, user_input=None):
        """Options des capteurs globaux (mots-clés, label, offsets par capteur)."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="sensors",
            data_schema=_sensor_schema(self.hass, self._conf, with_offsets=True),
        )
