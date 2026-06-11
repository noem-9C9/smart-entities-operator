# TASK — Smart Area v3.1 (fichier temporaire)

- [x] 1. `const.py` : types d'entrées cover/switch — *vérif : py_compile OK*
- [x] 2. `entity.py` : base commune `SmartAreaGroupEntity` (découverte membres, listeners, scope pièce/maison) — *vérif : py_compile OK*
- [x] 3. `light.py` : réécriture propre des modes couleur (modes canoniques ONOFF/BRIGHTNESS/COLOR_TEMP/RGB) — *vérif : py_compile OK + relecture logique*
- [x] 4. `cover.py` : groupes de volets (open/close/stop/position moyenne) — *vérif : py_compile OK*
- [x] 5. `switch.py` : groupes de switchs — *vérif : py_compile OK*
- [x] 6. `sensor.py` : offsets par capteur via options + exclusion des entités de l'intégration — *vérif : py_compile OK + test unitaire du parsing offsets passé*
- [x] 7. `__init__.py` : rechargement sur changement d'options pour tous les types — *vérif : py_compile OK*
- [x] 8. `config_flow.py` : menu 4 choix, schéma groupe commun (pièces et/ou global), options éditables — *vérif : py_compile OK*
- [x] 9. Traductions fr/en — *vérif : JSON valide*
- [x] 10. Nouveau `logo.svg` + PNG (+ assets brands pour l'affichage dans HA) — *vérif : rendu PNG inspecté visuellement (cairosvg)*
- [x] 11. README + version manifest 3.1.0 — *vérif : relecture*

## Notes / décisions
- Les groupes lumière n'exposent plus les modes hétéroclites des membres mais un jeu canonique
  (ONOFF/BRIGHTNESS/COLOR_TEMP/RGB) ; `light.turn_on` de HA convertit les couleurs par ampoule.
- Changement d'options ⇒ rechargement de l'entrée (entités recréées) ; pièces/global/mots-clés
  éditables après coup. Les entités orphelines (pièce ou mot-clé retiré) restent dans le registre
  et peuvent être supprimées à la main.
- Offsets capteurs : champ multiligne `sensor.xxx = -0.5` dans les options des capteurs globaux.
- L'affichage du logo dans la page Intégrations de HA nécessite une PR sur home-assistant/brands
  (assets prêts dans `brands/smart_area/`).
