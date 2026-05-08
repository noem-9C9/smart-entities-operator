import logging
import asyncio
from homeassistant.components.light import (
    LightEntity, ATTR_BRIGHTNESS, ATTR_COLOR_MODE, ATTR_SUPPORTED_COLOR_MODES, 
    ColorMode, ATTR_RGB_COLOR, ATTR_COLOR_TEMP_KELVIN, ATTR_HS_COLOR, ATTR_XY_COLOR
)
from homeassistant.core import HomeAssistant, callback, EVENT_HOMEASSISTANT_STARTED
from homeassistant.helpers import (
    entity_registry as er, area_registry as ar, device_registry as dr, 
    label_registry as lr
)
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Configure les lumières depuis les données saisies dans l'UI."""
    tag_filter = config_entry.data.get("label_filter", "")
    target_areas = config_entry.data.get("target_areas", [])
    all_areas = config_entry.data.get("all_areas", False)
    
    area_reg = ar.async_get(hass)
    
    if all_areas:
        # Si "Toutes les pièces" est coché, on récupère tous les IDs de zones
        target_areas = [area_id for area_id in area_reg.areas]
        
    entities = []

    for area_id in target_areas:
        area = area_reg.async_get_area(area_id)
        name = f"Lumières {area.name}" if area else f"Lumières {area_id}"
        entities.append(SmartAreaLight(hass, name, area_id, config_entry))

    async_add_entities(entities)

class SmartAreaLight(LightEntity):
    def __init__(self, hass, name, area_id, config_entry):
        self.hass = hass
        self._name = name
        self._area_id = area_id.lower()
        self.config_entry = config_entry
        
        self._state = False
        self._brightness = 255
        self._color_temp_kelvin = None
        self._rgb_color = None
        self._total_lights = 0
        self._on_lights = 0
        
        self._tracked_entities = []
        self._unsub_track_state = None
        
        # Initialiser avec des valeurs par défaut pour éviter l'erreur lors de l'ajout
        self._attr_supported_color_modes = {ColorMode.ONOFF}
        self._attr_color_mode = ColorMode.ONOFF
        
        # L'ID unique basé sur l'aire
        initial_label = config_entry.data.get("label_filter")
        if not initial_label or initial_label == "none":
            initial_label = "all"
        self._attr_unique_id = f"group_auto_{self._area_id}_{initial_label}".strip('_')
        # Force l'ID d'entité technique
        self.entity_id = f"light.group_auto_{self._area_id}_{initial_label}".strip('_')
        self._attr_available = True

    @property
    def should_poll(self):
        return False

    @property
    def name(self):
        return self._name

    @property
    def is_on(self):
        return self._state

    @property
    def brightness(self):
        return self._brightness

    @property
    def color_temp_kelvin(self):
        return self._color_temp_kelvin

    @property
    def rgb_color(self):
        return self._rgb_color

    @property
    def color_mode(self):
        return self._attr_color_mode

    @property
    def supported_color_modes(self):
        return self._attr_supported_color_modes

    @property
    def extra_state_attributes(self):
        """Attributs supplémentaires pour l'entité."""
        conf = {**self.config_entry.data, **self.config_entry.options}
        label_id = conf.get("label_filter")
        return {
            "area_id": self._area_id,
            "label_filter": label_id if label_id and label_id != "none" else "Aucun (Toutes les lumières)",
            "total_lights": self._total_lights,
            "on_lights": self._on_lights,
            "tracked_entities": self._tracked_entities
        }

    async def async_added_to_hass(self):
        """Appelé quand l'entité est ajoutée à Home Assistant."""
        self._update_internal_state()
        self._setup_listeners()
        
        # Écouter les mises à jour de configuration (OptionsFlow)
        self.async_on_remove(
            self.config_entry.add_update_listener(self._async_entry_updated)
        )
        
        # Écouter l'ajout ou la modification d'appareils (pour MQTT/Zigbee Discovery)
        self.async_on_remove(
            self.hass.bus.async_listen("entity_registry_updated", self._async_registry_updated)
        )
        self.async_on_remove(
            self.hass.bus.async_listen("device_registry_updated", self._async_registry_updated)
        )
        
        # Si HA n'a pas encore fini de démarrer, on attend le signal pour recalculer l'état final
        if self.hass.state != "RUNNING":
            self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STARTED, self._async_ha_started
            )

    def _setup_listeners(self):
        if self._unsub_track_state:
            self._unsub_track_state()
            self._unsub_track_state = None

        if self._tracked_entities:
            self._unsub_track_state = async_track_state_change_event(
                self.hass, self._tracked_entities, self._async_state_changed
            )

    async def async_will_remove_from_hass(self):
        """Appelé quand l'entité est supprimée."""
        if self._unsub_track_state:
            self._unsub_track_state()

    async def _async_entry_updated(self, hass, entry):
        """Appelé quand les options de configuration sont modifiées."""
        _LOGGER.debug("Mise à jour des options pour %s", self.name)
        self._update_internal_state()
        self.async_write_ha_state()

    @callback
    def _async_ha_started(self, _event):
        """Recalculer l'état quand Home Assistant a fini de démarrer."""
        _LOGGER.debug("Home Assistant démarré, mise à jour finale pour %s", self.name)
        self._update_internal_state()
        self.async_write_ha_state()

    @callback
    def _async_state_changed(self, event):
        self._update_internal_state()
        self.async_write_ha_state()
        
    @callback
    def _async_registry_updated(self, event):
        """Recalculer si une entité est ajoutée ou modifiée dans le registre."""
        # On relance simplement la mise à jour interne
        self._update_internal_state()
        self.async_write_ha_state()

    def _update_internal_state(self):
        """Met à jour la liste des entités suivies et l'état global."""
        try:
            # Récupérer les derniers réglages (data + options)
            conf = {**self.config_entry.data, **self.config_entry.options}
            label_id_filter = conf.get("label_filter")
            if label_id_filter == "none":
                label_id_filter = None
            use_brightness = conf.get("use_brightness", True)
            use_color_temp = conf.get("use_color_temp", True)
            use_rgb_color = conf.get("use_rgb_color", True)

            _LOGGER.debug("Mise à jour de %s (label: %s, b:%s, ct:%s, rgb:%s)", 
                         self.name, label_id_filter, use_brightness, use_color_temp, use_rgb_color)
            
            entity_reg = er.async_get(self.hass)
            device_reg = dr.async_get(self.hass)
            
            new_tracked = []
            for entity_id, entry in entity_reg.entities.items():
                if entity_id == self.entity_id:
                    continue
                if not entity_id.startswith("light."):
                    continue
                    
                ent_area = entry.area_id
                ent_labels = entry.labels or set()
                
                # Vérifier si l'appareil a le label
                if entry.device_id:
                    device = device_reg.async_get(entry.device_id)
                    if device:
                        if not ent_area:
                            ent_area = device.area_id
                        if device.labels:
                            ent_labels = ent_labels.union(device.labels)
                        
                if ent_area and ent_area.lower() == self._area_id:
                    if label_id_filter:
                        if label_id_filter not in ent_labels:
                            continue
                    new_tracked.append(entity_id)
            
            if set(new_tracked) != set(self._tracked_entities):
                self._tracked_entities = new_tracked
                self._setup_listeners()
            
            self._total_lights = len(self._tracked_entities)
            on_lights = []
            total_brightness = 0
            total_kelvin = 0
            total_rgb = [0, 0, 0]
            supported_modes = set()
            
            count_brightness = 0
            count_kelvin = 0
            count_rgb = 0

            for entity_id in self._tracked_entities:
                state_obj = self.hass.states.get(entity_id)
                if not state_obj:
                    continue

                modes = state_obj.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or []
                
                # Convertir les modes pour vérifier les capacités réelles de l'ampoule
                str_modes = [str(m).split('.')[-1].lower() for m in modes]
                supports_color = any(m in ("hs", "rgb", "rgbw", "rgbww", "xy") for m in str_modes)
                supports_temp = "color_temp" in str_modes
                
                # Filtrer les modes selon les réglages
                if use_brightness:
                    # Ne pas supprimer ONOFF ici, on le gère de façon globale plus bas
                    supported_modes.update(modes)
                
                if state_obj.state == "on":
                    on_lights.append(entity_id)
                    
                    if use_brightness:
                        b_val = state_obj.attributes.get(ATTR_BRIGHTNESS)
                        if b_val is not None:
                            total_brightness += int(b_val)
                            count_brightness += 1
                        
                        if use_color_temp and supports_temp:
                            k_val = state_obj.attributes.get(ATTR_COLOR_TEMP_KELVIN)
                            if k_val is not None:
                                total_kelvin += int(k_val)
                                count_kelvin += 1
                            
                        if use_rgb_color and supports_color:
                            rgb_val = state_obj.attributes.get(ATTR_RGB_COLOR)
                            if rgb_val is not None and len(rgb_val) == 3:
                                total_rgb[0] += rgb_val[0]
                                total_rgb[1] += rgb_val[1]
                                total_rgb[2] += rgb_val[2]
                                count_rgb += 1

            self._on_lights = len(on_lights)
            self._state = self._on_lights > 0
            
            # 1. Normalisation stricte : convertir tout en Enum pour éviter les conflits avec les chaînes
            standard_modes = set()
            for m in supported_modes:
                val = m.value if hasattr(m, "value") else str(m)
                val = str(val).split('.')[-1].lower()
                try:
                    standard_modes.add(ColorMode(val))
                except ValueError:
                    pass

            # 2. Application des filtres de configuration de l'utilisateur
            if not use_brightness:
                standard_modes = {ColorMode.ONOFF}
            else:
                if not standard_modes:
                    standard_modes = {ColorMode.BRIGHTNESS}
                if not use_rgb_color:
                    standard_modes = {m for m in standard_modes if m not in (ColorMode.RGB, ColorMode.HS, ColorMode.XY)}
                if not use_color_temp:
                    standard_modes.discard(ColorMode.COLOR_TEMP)

            if not standard_modes:
                standard_modes = {ColorMode.ONOFF}

            # 3. Application des RÈGLES STRICTES DE HOME ASSISTANT
            # S'il y a des couleurs/températures, ONOFF et BRIGHTNESS sont interdits.
            has_advanced_color = any(m not in (ColorMode.BRIGHTNESS, ColorMode.ONOFF, ColorMode.UNKNOWN) for m in standard_modes)
            
            if has_advanced_color:
                standard_modes.discard(ColorMode.BRIGHTNESS)
                standard_modes.discard(ColorMode.ONOFF)
            elif ColorMode.BRIGHTNESS in standard_modes and ColorMode.ONOFF in standard_modes:
                standard_modes.discard(ColorMode.ONOFF)

            final_modes = standard_modes
                
            # Choix du mode courant
            if not self._state:
                self._attr_color_mode = ColorMode.UNKNOWN
            else:
                if ColorMode.RGB in final_modes and count_rgb > 0:
                    self._attr_color_mode = ColorMode.RGB
                elif ColorMode.COLOR_TEMP in final_modes and count_kelvin > 0:
                    self._attr_color_mode = ColorMode.COLOR_TEMP
                elif ColorMode.BRIGHTNESS in final_modes and count_brightness > 0:
                    self._attr_color_mode = ColorMode.BRIGHTNESS
                elif final_modes:
                    self._attr_color_mode = list(final_modes)[0]
                else:
                    self._attr_color_mode = ColorMode.ONOFF
            
            self._attr_supported_color_modes = final_modes

            # Moyennes
            self._brightness = int(total_brightness / count_brightness) if count_brightness > 0 else 255
            self._color_temp_kelvin = int(total_kelvin / count_kelvin) if count_kelvin > 0 else None
            self._rgb_color = (int(total_rgb[0]/count_rgb), int(total_rgb[1]/count_rgb), int(total_rgb[2]/count_rgb)) if count_rgb > 0 else None
                
        except Exception as err:
            _LOGGER.exception("Erreur critique lors de la mise à jour de %s : %s", self.name, err)

    async def async_turn_on(self, **kwargs):
        """Allume les lumières de la zone."""
        _LOGGER.debug("Appel de turn_on pour %s avec %s", self.name, kwargs)
        self._update_internal_state()
        
        if not self._tracked_entities:
            _LOGGER.warning("Aucune lumière trouvée pour %s", self.name)
            return

        is_simple_turn_on = not kwargs
        tasks = []
        
        for entity_id in self._tracked_entities:
            state_obj = self.hass.states.get(entity_id)
            
            # Si on ajuste un réglage (luminosité/couleur) alors que le groupe est déjà partiellement allumé,
            # on l'applique UNIQUEMENT aux ampoules qui sont DÉJÀ allumées.
            if not is_simple_turn_on and self._state:
                if not state_obj or state_obj.state != "on":
                    continue
                    
            modes = state_obj.attributes.get(ATTR_SUPPORTED_COLOR_MODES) or [] if state_obj else []
            str_modes = [str(m).split('.')[-1].lower() for m in modes]
            
            supports_brightness = any(m not in ("onoff", "unknown") for m in str_modes)
            supports_color = any(m in ("hs", "rgb", "rgbw", "rgbww", "xy") for m in str_modes)
            supports_temp = "color_temp" in str_modes

            valid_kwargs = {"entity_id": entity_id}
            
            if ATTR_BRIGHTNESS in kwargs and supports_brightness:
                valid_kwargs[ATTR_BRIGHTNESS] = kwargs[ATTR_BRIGHTNESS]
            
            if ATTR_COLOR_TEMP_KELVIN in kwargs and supports_temp:
                valid_kwargs[ATTR_COLOR_TEMP_KELVIN] = kwargs[ATTR_COLOR_TEMP_KELVIN]
                
            for attr in [ATTR_RGB_COLOR, ATTR_XY_COLOR, ATTR_HS_COLOR]:
                if attr in kwargs and supports_color:
                    valid_kwargs[attr] = kwargs[attr]

            tasks.append(
                self.hass.services.async_call("light", "turn_on", valid_kwargs, False)
            )

        if tasks:
            await asyncio.gather(*tasks)

    async def async_turn_off(self, **kwargs):
        """Éteint les lumières de la zone."""
        _LOGGER.debug("Appel de turn_off pour %s", self.name)
        if self._tracked_entities:
            await self.hass.services.async_call(
                "light", "turn_off", {"entity_id": self._tracked_entities}, False
            )