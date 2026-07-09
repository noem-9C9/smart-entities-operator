# Smart Entities Operator

![Smart Entities Operator](https://github.com/noem-9C9/smart-entities-operator/raw/main/custom_components/smart_entities_operator/brand/logo.png)

Intégration Home Assistant (config par UI) qui **opère automatiquement sur des ensembles d'entités**, découverts par *label*/mot-clé ou choisis explicitement.

> Anciennement `smart_area`. Le domaine technique est désormais `smart_entities_operator` (renommage complet).

## Fonctionnalités

### Groupes (par pièce ou pour toute la maison)
- **Lumières** — expose un jeu de modes canonique (on/off, luminosité, température, RGB) ; `light.turn_on` convertit vers le mode natif de chaque ampoule.
- **Volets** — ouvert si au moins un membre est ouvert, position moyenne.
- **Switchs** — allumé si au moins un membre est allumé.

Sélection des membres par **pièce** et/ou **label**, découverte dynamique (les nouvelles entités MQTT/Zigbee sont prises en compte automatiquement).

### Capteurs opérateurs
- **Agrégat** — combine plusieurs capteurs avec l'opération de votre choix : moyenne, médiane, min, max, somme, amplitude (max − min), écart-type, nombre de valeurs. Sources par mots-clés (id/nom/classe) filtrés par label **et/ou** par sélection d'entités précises.
- **Différence** — `A − B` (ou `|A − B|`) entre deux entités précises.
- **Dérivée** — variation d'une entité par seconde / minute / heure / jour, avec fenêtre de lissage optionnelle.
- **Moyenne glissante** — moyenne d'une entité sur une fenêtre de temps glissante, pondérée par la durée.

### Robustesse
- Les entités **indisponibles** sont exclues des calculs et listées dans l'attribut `unavailable_members`.
- **Filtrage des valeurs aberrantes** :
  - bornes absolues `min_valid` / `max_valid` (agrégat, moyenne glissante) ;
  - rejet statistique par **écart absolu médian** (MAD) sur l'agrégat (`outlier_mad`) ;
  - filtre **anti-pic** `max_step` sur la moyenne glissante.
  - Les valeurs écartées sont listées dans l'attribut `excluded_members`.
- **Offsets** de correction par capteur (agrégat).
- Les sources sont exposées dans l'attribut `entity_id` (convention HA, lisible par les cartes).

## Installation
Copier `custom_components/smart_entities_operator/` dans le dossier `config/custom_components/` de Home Assistant, puis redémarrer. Ajouter l'intégration via *Paramètres → Appareils et services → Ajouter*.

## Note sur l'onglet « Liées »
L'onglet *Liées* de Home Assistant (composant `search`) ne déplie les entités membres que pour le domaine `group`. Ici les sources sont exposées dans l'attribut `entity_id` et dans les attributs `unavailable_members` / `excluded_members`, visibles dans la fiche de l'entité et exploitables par les cartes de dashboard.
