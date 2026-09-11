"""Vendor map icons from EarthRanger's open source server (PADAS/er-server, Apache 2.0).

Downloads the files listed in ICONS at the pinned commit, normalises each SVG to the registry's
shape (one square viewBox, `currentColor`, no styles, classes, titles or halos) and rewrites the
matching entries of `services/frontend/src/assets/icons/icon-registry.json`. Entries the table
does not name (our own drawings) are kept as they are. Decision D165.

    uv run scripts/import_earthranger_icons.py            # download, normalise, write
    uv run scripts/import_earthranger_icons.py --check    # only report what would change

The licence text of the source repository is written next to the icons as `LICENSE-EarthRanger`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

REPO = "PADAS/er-server"
COMMIT = "c9f1255b866b3c1df4088b2cc5c2f4a5808e4f70"  # develop on 2026-02-15
RAW = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/"
SOURCE_LABEL = "EarthRanger (PADAS/er-server)"
LICENSE = "Apache-2.0"

ROOT = Path(__file__).resolve().parent.parent
ICONS_DIR = ROOT / "services" / "frontend" / "src" / "assets" / "icons"
REGISTRY = ICONS_DIR / "icon-registry.json"

OBS = "das/observations/static/"
MAP = "das/mapping/static/"
SPRITE = "das/activity/static/sprite-src/"

FOLDERS = {
    "wildlife": "wildlife",
    "person": "people",
    "vehicle": "vehicles",
    "infrastructure": "infrastructure",
    "device": "devices",
    "event": "events",
}

SVG_NS = "http://www.w3.org/2000/svg"
PAINTED = {"path", "circle", "rect", "polygon", "ellipse", "polyline", "line"}
WHITE = {"#fff", "#ffffff", "white", "rgb(255,255,255)"}
DROP_ELEMENTS = {"title", "desc", "metadata", "style"}
DROP_ATTRIBUTES = {
    "class",
    "style",
    "id",
    "data-name",
    "opacity",
    "fill-opacity",
    "enable-background",
    "version",
    "x",
    "y",
    "width",
    "height",
    "{http://www.w3.org/XML/1998/namespace}space",
}


@dataclass(frozen=True)
class Icon:
    key: str
    label: str
    source: str  # path in the EarthRanger repository
    fallback: str | None = None
    aliases: tuple[str, ...] = ()
    mapping: str | None = (
        None  # the EarthRanger name our key corresponds to; the file's base by default
    )

    @property
    def category(self) -> str:
        return self.key.split(".")[0]

    @property
    def asset(self) -> str:
        return f"{FOLDERS[self.category]}/{self.key.split('.', 1)[1]}.svg"

    @property
    def earthranger_mapping(self) -> str:
        if self.mapping:
            return self.mapping
        base = self.source.rsplit("/", 1)[1][:-4]
        return re.sub(r"(-black)?(-male|-female)?(_rep|-event|-icon|-black|-smart-rep)?$", "", base)


def W(key: str, label: str, file: str, fallback: str = "wildlife.generic", *aliases: str) -> Icon:
    return Icon(key, label, OBS + file, fallback, aliases)


def S(key: str, label: str, file: str, fallback: str | None, *aliases: str) -> Icon:
    return Icon(key, label, SPRITE + file, fallback, aliases)


def M(
    key: str, label: str, file: str, fallback: str = "infrastructure.site", *aliases: str
) -> Icon:
    return Icon(key, label, MAP + file, fallback, aliases)


ICONS: list[Icon] = [
    # Wildlife groups: the fallback of a species is its group, the group's fallback the generic icon.
    Icon("wildlife.generic", "Wildlife", OBS + "paws-black.svg", None, ("animal",), "wildlife"),
    W("wildlife.canid", "Canid", "gray_wolf-male.svg", "wildlife.generic", "Canidae"),
    W("wildlife.feline", "Feline", "lion-black-male.svg", "wildlife.generic", "Felidae", "cat"),
    W(
        "wildlife.antelope",
        "Antelope",
        "antelope-black-male.svg",
        "wildlife.generic",
        "Bovidae",
        "gazelle",
    ),
    W("wildlife.bovid", "Bovid", "buffalo-male.svg", "wildlife.generic", "cattle"),
    W("wildlife.deer", "Deer", "red_deer-male.svg", "wildlife.generic", "Cervidae"),
    W("wildlife.bear", "Bear", "brown_bear-male.svg", "wildlife.generic", "Ursidae"),
    W("wildlife.primate", "Primate", "monkey-male.svg", "wildlife.generic", "ape"),
    W("wildlife.raptor", "Bird of prey", "bird-of-prey-male.svg", "wildlife.bird", "eagle"),
    W("wildlife.vulture", "Vulture", "cape_vulture-male.svg", "wildlife.raptor"),
    W("wildlife.reptile", "Reptile", "tortoise-male.svg", "wildlife.generic"),
    W(
        "wildlife.marine",
        "Marine mammal",
        "dugong-male.svg",
        "wildlife.generic",
        "whale",
        "dolphin",
    ),
    W("wildlife.shark", "Shark", "great_white_shark.svg", "wildlife.fish"),
    S("wildlife.bird", "Bird", "birds_rep.svg", "wildlife.generic", "Aves"),
    S("wildlife.fish", "Fish", "grouper_rep.svg", "wildlife.generic"),
    S("wildlife.livestock", "Livestock", "cow_rep.svg", "wildlife.generic", "cattle", "cow"),
    # Species and named groups from the subject icons.
    W("wildlife.aardvark", "Aardvark", "aardvark-male.svg"),
    W("wildlife.addax", "Addax", "addax-male.svg", "wildlife.antelope"),
    W("wildlife.albatross", "Albatross", "albatross_antipodean.svg", "wildlife.bird"),
    W(
        "wildlife.asian_elephant",
        "Asian elephant",
        "asian_elephant-black-male.svg",
        "wildlife.elephant",
        "Elephas maximus",
    ),
    W("wildlife.baboon", "Baboon", "baboon-male.svg", "wildlife.primate"),
    W("wildlife.badger", "Badger", "badger-male.svg"),
    W("wildlife.barbary_sheep", "Barbary sheep", "barbary_sheep-male.svg", "wildlife.bovid"),
    W(
        "wildlife.bearded_vulture",
        "Bearded vulture",
        "bearded_vulture-male.svg",
        "wildlife.vulture",
    ),
    W("wildlife.bighorn_sheep", "Bighorn sheep", "bighorn_sheep_desert-male.svg", "wildlife.bovid"),
    W("wildlife.bison", "Bison", "bison-male.svg", "wildlife.bovid"),
    W("wildlife.black_bear", "Black bear", "black_bear-male.svg", "wildlife.bear"),
    W("wildlife.black_vulture", "Black vulture", "black_vulture-male.svg", "wildlife.vulture"),
    W("wildlife.bobcat", "Bobcat", "bobcat-male.svg", "wildlife.feline"),
    W("wildlife.brown_bear", "Brown bear", "brown_bear-male.svg", "wildlife.bear", "grizzly"),
    W("wildlife.brown_hyena", "Brown hyena", "brownhyena-male.svg", "wildlife.hyena"),
    W("wildlife.buffalo", "Buffalo", "buffalo-male.svg", "wildlife.bovid", "Syncerus caffer"),
    W("wildlife.camel", "Camel", "camel-male.svg"),
    W("wildlife.cape_vulture", "Cape vulture", "cape_vulture-male.svg", "wildlife.vulture"),
    W("wildlife.chamois", "Chamois", "chamois-male.svg", "wildlife.bovid"),
    W(
        "wildlife.cheetah",
        "Cheetah",
        "cheetah-black-male.svg",
        "wildlife.feline",
        "Acinonyx jubatus",
    ),
    W("wildlife.chimpanzee", "Chimpanzee", "chimpanzee-male.svg", "wildlife.primate"),
    W(
        "wildlife.cinereous_vulture",
        "Cinereous vulture",
        "cinereous_vulture-male.svg",
        "wildlife.vulture",
    ),
    W("wildlife.cougar", "Cougar", "cougar-male.svg", "wildlife.feline", "puma", "mountain lion"),
    W("wildlife.cow", "Cow", "cow-black.svg", "wildlife.livestock"),
    W("wildlife.crocodile", "Crocodile", "crocodile-male.svg", "wildlife.reptile"),
    W(
        "wildlife.demoiselle_crane",
        "Demoiselle crane",
        "demoiselle_crane-male.svg",
        "wildlife.bird",
    ),
    W("wildlife.donkey", "Donkey", "donkey-male.svg", "wildlife.livestock"),
    W("wildlife.dugong", "Dugong", "dugong-male.svg", "wildlife.marine"),
    W("wildlife.duiker", "Duiker", "duiker.svg", "wildlife.antelope"),
    W("wildlife.eagle_owl", "Eagle owl", "eagle_owl-male.svg", "wildlife.raptor", "owl"),
    W("wildlife.eland", "Eland", "eland.svg", "wildlife.antelope"),
    W(
        "wildlife.elephant",
        "Elephant",
        "elephant-black-male.svg",
        "wildlife.generic",
        "Loxodonta africana",
    ),
    W("wildlife.elk", "Elk", "elk-male.svg", "wildlife.deer"),
    W("wildlife.eurasian_lynx", "Eurasian lynx", "eurasian_lynx-male.svg", "wildlife.feline"),
    W("wildlife.european_roller", "European roller", "european_roller-male.svg", "wildlife.bird"),
    W("wildlife.fallow_deer", "Fallow deer", "fallow_deer-male.svg", "wildlife.deer"),
    W(
        "wildlife.forest_elephant",
        "Forest elephant",
        "forest_elephant-black-male.svg",
        "wildlife.elephant",
        "Loxodonta cyclotis",
    ),
    W("wildlife.frog", "Frog", "frog.svg", "wildlife.generic", "amphibian"),
    W("wildlife.giraffe", "Giraffe", "giraffe-male.svg"),
    W("wildlife.gorilla", "Gorilla", "gorilla.svg", "wildlife.primate"),
    W("wildlife.wolf", "Wolf", "gray_wolf-male.svg", "wildlife.canid", "Canis lupus", "grey wolf"),
    W("wildlife.great_white_shark", "Great white shark", "great_white_shark.svg", "wildlife.shark"),
    W("wildlife.grevys_zebra", "Grevy's zebra", "grevys_zebra-black-male.svg", "wildlife.zebra"),
    W(
        "wildlife.griffon_vulture",
        "Griffon vulture",
        "griffon_vulture-male.svg",
        "wildlife.vulture",
    ),
    W("wildlife.hare", "Hare", "hare-male.svg"),
    W("wildlife.hartebeest", "Hartebeest", "hartebeest-male.svg", "wildlife.antelope"),
    W("wildlife.hirola", "Hirola", "hirola-male.svg", "wildlife.antelope"),
    W("wildlife.hooded_vulture", "Hooded vulture", "hooded_vulture-male.svg", "wildlife.vulture"),
    W("wildlife.horse", "Horse", "horse-male.svg", "wildlife.livestock"),
    W("wildlife.ibex", "Ibex", "ibex-male.svg", "wildlife.bovid"),
    W("wildlife.jaguar", "Jaguar", "jaguar-male.svg", "wildlife.feline"),
    W("wildlife.koala", "Koala", "koala-black-male.svg"),
    W("wildlife.kulan", "Kulan", "kulan-male.svg", "wildlife.wild_horse", "onager"),
    W(
        "wildlife.lappet_faced_vulture",
        "Lappet-faced vulture",
        "lappet_faced_vulture-male.svg",
        "wildlife.vulture",
    ),
    W("wildlife.leopard", "Leopard", "leopard-male.svg", "wildlife.feline", "Panthera pardus"),
    W("wildlife.lesser_kudu", "Lesser kudu", "lesser_kudu-male.svg", "wildlife.antelope"),
    W("wildlife.lion", "Lion", "lion-black-male.svg", "wildlife.feline", "Panthera leo"),
    W("wildlife.lynx", "Lynx", "lynx-male.svg", "wildlife.feline"),
    W("wildlife.lyrebird", "Lyrebird", "lyrebird-male.svg", "wildlife.bird"),
    W("wildlife.macaw", "Macaw", "macaw-male.svg", "wildlife.bird", "parrot"),
    W("wildlife.manta_ray", "Manta ray", "mantaray.svg", "wildlife.fish"),
    W("wildlife.martial_eagle", "Martial eagle", "martial_eagle-male.svg", "wildlife.raptor"),
    W("wildlife.meerkat", "Meerkat", "meerkat-male.svg"),
    W("wildlife.monkey", "Monkey", "monkey-male.svg", "wildlife.primate"),
    W("wildlife.moose", "Moose", "moose-male.svg", "wildlife.deer"),
    W("wildlife.mule", "Mule", "mule-male.svg", "wildlife.livestock"),
    W("wildlife.mule_deer", "Mule deer", "mule_deer-male.svg", "wildlife.deer"),
    W("wildlife.ocelot", "Ocelot", "ocelot-male.svg", "wildlife.feline"),
    W("wildlife.opossum", "Opossum", "opossum-male.svg"),
    W("wildlife.orangutan", "Orangutan", "orangutan.svg", "wildlife.primate"),
    W("wildlife.ostrich", "Ostrich", "ostrich-male.svg", "wildlife.bird"),
    W("wildlife.pangolin", "Pangolin", "pangolin-male.svg"),
    W("wildlife.peccary", "Peccary", "peccary-male.svg"),
    W("wildlife.pelican", "Pelican", "pelican-male.svg", "wildlife.bird"),
    W("wildlife.petrel", "Petrel", "petrel_northern_giant.svg", "wildlife.bird"),
    W("wildlife.pronghorn", "Pronghorn", "pronghorn-male.svg", "wildlife.antelope"),
    W("wildlife.rabbit", "Rabbit", "rabbit-male.svg"),
    W("wildlife.raccoon", "Raccoon", "raccoon-male.svg"),
    W("wildlife.red_deer", "Red deer", "red_deer-male.svg", "wildlife.deer"),
    W(
        "wildlife.rhino",
        "Rhino",
        "rhino-black-male.svg",
        "wildlife.generic",
        "rhinoceros",
        "black rhino",
        "Diceros bicornis",
    ),
    W("wildlife.roan", "Roan antelope", "roan-male.svg", "wildlife.antelope"),
    W("wildlife.sable", "Sable antelope", "sable-black-male.svg", "wildlife.antelope"),
    W(
        "wildlife.scimitar_oryx",
        "Scimitar oryx",
        "scimitar_oryx-black-male.svg",
        "wildlife.antelope",
        "oryx",
    ),
    W("wildlife.secretary_bird", "Secretary bird", "secretary_bird-male.svg", "wildlife.bird"),
    W("wildlife.serval", "Serval", "serval-male.svg", "wildlife.feline"),
    W("wildlife.sheep", "Sheep", "sheep-male.svg", "wildlife.livestock"),
    W("wildlife.shoebill", "Shoebill", "shoebill-male.svg", "wildlife.bird"),
    W("wildlife.sloth", "Sloth", "sloth.svg"),
    W(
        "wildlife.spotted_hyena",
        "Spotted hyena",
        "spotted_hyena-male.svg",
        "wildlife.hyena",
        "Crocuta crocuta",
    ),
    W("wildlife.swift_fox", "Swift fox", "swift_fox-male.svg", "wildlife.canid", "fox"),
    W("wildlife.tapir", "Tapir", "tapir-male.svg"),
    W("wildlife.tauros", "Tauros", "tauros-male.svg", "wildlife.bovid", "aurochs"),
    W("wildlife.tiang", "Tiang", "tiang-male.svg", "wildlife.antelope"),
    W("wildlife.topi", "Topi", "topi-male.svg", "wildlife.antelope"),
    W("wildlife.tortoise", "Tortoise", "tortoise-male.svg", "wildlife.reptile"),
    W("wildlife.tree_kangaroo", "Tree kangaroo", "tree-kangaroo-male.svg"),
    W("wildlife.turtle", "Turtle", "turtle-male.svg", "wildlife.reptile", "sea turtle"),
    W("wildlife.vicuna", "Vicuña", "vicuna-male.svg", "wildlife.camel"),
    W("wildlife.whale_shark", "Whale shark", "whale-shark-male.svg", "wildlife.shark"),
    W(
        "wildlife.white_backed_vulture",
        "White-backed vulture",
        "white_backed_vulture-male.svg",
        "wildlife.vulture",
    ),
    W(
        "wildlife.white_rhino",
        "White rhino",
        "white_rhino.svg",
        "wildlife.rhino",
        "Ceratotherium simum",
    ),
    W("wildlife.wild_boar", "Wild boar", "wild_boar-male.svg", "wildlife.generic", "boar"),
    W(
        "wildlife.wild_dog",
        "Wild dog",
        "wild_dog-male.svg",
        "wildlife.canid",
        "Lycaon pictus",
        "painted dog",
    ),
    W("wildlife.wild_horse", "Wild horse", "wild_horse-male.svg", "wildlife.horse", "Przewalski"),
    W("wildlife.wildebeest", "Wildebeest", "wildebeest-male.svg", "wildlife.antelope", "gnu"),
    W("wildlife.zebra", "Zebra", "zebra-black-male.svg", "wildlife.generic", "Equus quagga"),
    # Species that only the event library draws.
    S("wildlife.hippo", "Hippo", "hippo_rep.svg", "wildlife.generic", "hippopotamus"),
    S("wildlife.warthog", "Warthog", "warthog_rep.svg", "wildlife.generic"),
    S("wildlife.jackal", "Jackal", "jackal_rep.svg", "wildlife.canid"),
    S("wildlife.impala", "Impala", "impala_rep.svg", "wildlife.antelope"),
    S("wildlife.greater_kudu", "Greater kudu", "greater_kudu.svg", "wildlife.antelope", "kudu"),
    S("wildlife.waterbuck", "Waterbuck", "waterbuck.svg", "wildlife.antelope"),
    S("wildlife.gerenuk", "Gerenuk", "gerenuk-male-smart-rep.svg", "wildlife.antelope"),
    S("wildlife.grants_gazelle", "Grant's gazelle", "grants_gazelle_rep.svg", "wildlife.antelope"),
    S("wildlife.goat", "Goat", "goat_rep.svg", "wildlife.livestock"),
    S("wildlife.bull", "Bull", "bull_rep.svg", "wildlife.livestock"),
    S(
        "wildlife.hyena",
        "Hyena",
        "striped_hyena-male-smart-rep.svg",
        "wildlife.generic",
        "Hyaenidae",
    ),
    S("wildlife.hawk", "Hawk", "hawk_rep.svg", "wildlife.raptor"),
    S("wildlife.falcon", "Falcon", "falcon_rep.svg", "wildlife.raptor"),
    S("wildlife.raven", "Raven", "raven_rep.svg", "wildlife.bird", "crow"),
    S("wildlife.gull", "Gull", "gull_rep.svg", "wildlife.bird"),
    S("wildlife.passerine", "Passerine", "passerine_rep.svg", "wildlife.bird", "songbird"),
    S("wildlife.snowy_owl", "Snowy owl", "snowy_owl_rep.svg", "wildlife.raptor"),
    S("wildlife.hornbill", "Hornbill", "hornbillsighting_rep.svg", "wildlife.bird"),
    S(
        "wildlife.flamingo",
        "Flamingo",
        "flamingo_phoenicoparrus_andinus-event.svg",
        "wildlife.bird",
    ),
    S("wildlife.crane", "Crane", "sandhill_crane_rep.svg", "wildlife.bird"),
    S("wildlife.goose", "Goose", "cackling_goose_rep.svg", "wildlife.bird"),
    S("wildlife.mammal", "Mammal", "mammal_rep.svg", "wildlife.generic"),
    S(
        "wildlife.reptiles_amphibians",
        "Reptiles and amphibians",
        "reptiles_amphibians_rep.svg",
        "wildlife.reptile",
    ),
    S("wildlife.sea_lion", "Sea lion", "sealion_rep.svg", "wildlife.marine", "seal"),
    S("wildlife.whale", "Whale", "blue_whale_rep.svg", "wildlife.marine"),
    S("wildlife.orca", "Orca", "killer_whale_orca_rep.svg", "wildlife.marine", "killer whale"),
    S("wildlife.manatee", "Manatee", "manatee_rep.svg", "wildlife.marine"),
    S("wildlife.arctic_fox", "Arctic fox", "arctic_fox_rep.svg", "wildlife.canid"),
    S("wildlife.polar_bear", "Polar bear", "polar_bear-event.svg", "wildlife.bear"),
    S("wildlife.red_panda", "Red panda", "red_panda-event.svg", "wildlife.generic"),
    S("wildlife.gibbon", "Gibbon", "gibbon-event.svg", "wildlife.primate"),
    S("wildlife.muskox", "Muskox", "muskox-event.svg", "wildlife.bovid"),
    S("wildlife.dog", "Dog", "pet-dog_rep.svg", "wildlife.canid", "domestic dog"),
    # People.
    Icon("person.ranger", "Ranger", OBS + "ranger.svg", None, ("person", "staff", "field staff")),
    W("person.ranger_team", "Ranger team", "ranger_team.svg", "person.ranger", "patrol"),
    W("person.patrol_team", "Patrol team", "patrol_team-black.svg", "person.ranger_team"),
    W("person.manager", "Manager", "manager.svg", "person.ranger"),
    W("person.scout", "Scout", "scout.svg", "person.ranger", "community scout"),
    W(
        "person.researcher",
        "Researcher",
        "expedition-black.svg",
        "person.ranger",
        "scientist",
        "expedition",
    ),
    W(
        "person.dog_team",
        "Dog team",
        "dog_team-black.svg",
        "person.ranger_team",
        "canine unit",
        "K9",
    ),
    W("person.fence_attendant", "Fence attendant", "fence_attendant.svg", "person.ranger"),
    # Vehicles.
    Icon("vehicle.4x4", "4x4", OBS + "suv.svg", None, ("car", "vehicle", "suv"), "vehicle"),
    W("vehicle.car", "Car", "car.svg", "vehicle.4x4"),
    W("vehicle.truck", "Truck", "truck.svg", "vehicle.4x4", "lorry"),
    W("vehicle.van", "Van", "van.svg", "vehicle.4x4", "minibus"),
    W("vehicle.motorcycle", "Motorcycle", "motorcycle.svg", "vehicle.4x4", "motorbike"),
    S("vehicle.bicycle", "Bicycle", "bicycle-patrol-icon.svg", "vehicle.motorcycle", "bike"),
    S("vehicle.quad", "Quad bike", "quadbike_patrol.svg", "vehicle.motorcycle", "ATV"),
    W("vehicle.security", "Security vehicle", "security_vehicle-black.svg", "vehicle.4x4"),
    W("vehicle.tourist", "Tourist vehicle", "tourist_vehicle.svg", "vehicle.4x4", "safari vehicle"),
    W("vehicle.boat", "Boat", "boat.svg", "vehicle.4x4"),
    W("vehicle.ranger_boat", "Ranger boat", "ranger_boat-black.svg", "vehicle.boat", "patrol boat"),
    W("vehicle.plane", "Aircraft", "plane.svg", "vehicle.4x4", "aircraft", "airplane"),
    W("vehicle.helicopter", "Helicopter", "helicopter.svg", "vehicle.plane"),
    W("vehicle.drone", "Drone", "drone.svg", "vehicle.plane", "UAV"),
    W("vehicle.quadcopter", "Quadcopter", "drone_quadcopter.svg", "vehicle.drone"),
    W("vehicle.balloon", "Hot air balloon", "hot_air_balloon.svg", "vehicle.plane"),
    W("vehicle.excavator", "Excavator", "excavator.svg", "vehicle.truck", "digger"),
    W("vehicle.tractor", "Tractor", "maintenance_tractor.svg", "vehicle.truck"),
    W("vehicle.dump_truck", "Dump truck", "maintenance_dump_truck.svg", "vehicle.truck"),
    # Infrastructure: static assets and map features.
    M(
        "infrastructure.site",
        "Site",
        "feature-POI-star_flag.svg",
        "infrastructure.gate",
        "point of interest",
        "flag",
    ),
    Icon("infrastructure.gate", "Gate", OBS + "static-gate.svg", None, (), "gate"),
    M(
        "infrastructure.park_gate",
        "Park gate",
        "park_gate-black.svg",
        "infrastructure.gate",
        "entrance",
    ),
    M("infrastructure.barrier", "Barrier", "Barrier.svg", "infrastructure.gate", "boom"),
    W("infrastructure.door", "Door", "static-door.svg", "infrastructure.gate"),
    W("infrastructure.fence", "Fence", "static-fence.svg", "infrastructure.gate"),
    Icon(
        "infrastructure.electric_fence",
        "Electric fence",
        OBS + "static_fence_energizer.svg",
        "infrastructure.fence",
        ("fence energizer", "energizer"),
        "fence",
    ),
    W(
        "infrastructure.fence_sensor",
        "Fence sensor",
        "static_fence_sensor.svg",
        "infrastructure.fence",
    ),
    M(
        "infrastructure.beehive_fence",
        "Beehive fence",
        "beehive_fence.svg",
        "infrastructure.fence",
        "apiary",
    ),
    Icon(
        "infrastructure.water_point",
        "Water point",
        MAP + "feature-water_hole.svg",
        None,
        ("waterhole", "water hole"),
        "waterhole",
    ),
    W(
        "infrastructure.water_tank",
        "Water tank",
        "static-water-tank.svg",
        "infrastructure.water_point",
    ),
    W(
        "infrastructure.water_gauge",
        "Water gauge",
        "static-water-gauge.svg",
        "infrastructure.water_point",
        "water level",
    ),
    M(
        "infrastructure.water_pump",
        "Water pump",
        "water_pump.svg",
        "infrastructure.water_point",
        "pump",
    ),
    W(
        "infrastructure.pump_station",
        "Pump station",
        "static_pump_station.svg",
        "infrastructure.water_pump",
    ),
    M("infrastructure.dam", "Dam", "dam-black.svg", "infrastructure.water_point"),
    M("infrastructure.windmill", "Windmill", "windmill.svg", "infrastructure.water_pump"),
    M("infrastructure.wind_turbine", "Wind turbine", "wind_turbine.svg", "infrastructure.site"),
    M(
        "infrastructure.solar_station",
        "Solar station",
        "solar_station_stand.svg",
        "infrastructure.site",
        "solar panel",
    ),
    W("infrastructure.gas_tank", "Gas tank", "static-gas-tank.svg", "infrastructure.site", "fuel"),
    M("infrastructure.building", "Building", "building-black.svg", "infrastructure.site"),
    M("infrastructure.house", "House", "House-Black.svg", "infrastructure.building"),
    M(
        "infrastructure.fence_attendant_house",
        "Fence attendant house",
        "fence_attendant_house.svg",
        "infrastructure.house",
    ),
    M("infrastructure.lodge", "Lodge", "Lodge-Black.svg", "infrastructure.building", "hotel"),
    M("infrastructure.lodging", "Lodging", "lodging-black.svg", "infrastructure.lodge"),
    M("infrastructure.campsite", "Campsite", "campsite-black.svg", "infrastructure.site", "camp"),
    M(
        "infrastructure.safari_camp",
        "Safari camp",
        "safari_camp-black.svg",
        "infrastructure.campsite",
    ),
    M("infrastructure.village", "Village", "village-black.svg", "infrastructure.building"),
    M("infrastructure.settlement", "Settlement", "settlement-black.svg", "infrastructure.village"),
    M(
        "infrastructure.headquarters",
        "Park headquarters",
        "park_HQ-black.svg",
        "infrastructure.building",
        "HQ",
        "office",
    ),
    M(
        "infrastructure.ranger_post",
        "Ranger post",
        "ranger_post-black.svg",
        "infrastructure.building",
        "outpost",
    ),
    M(
        "infrastructure.ranger_station",
        "Ranger station",
        "ranger_station-brown.svg",
        "infrastructure.ranger_post",
    ),
    M(
        "infrastructure.police_station",
        "Police station",
        "police_station.svg",
        "infrastructure.building",
    ),
    M("infrastructure.clinic", "Clinic", "clinic.svg", "infrastructure.building"),
    M("infrastructure.hospital", "Hospital", "hospital.svg", "infrastructure.clinic"),
    M(
        "infrastructure.tourism_center",
        "Tourism centre",
        "tourism_center-black.svg",
        "infrastructure.building",
        "visitor centre",
    ),
    M(
        "infrastructure.viewpoint",
        "Viewpoint",
        "viewpoint-black.svg",
        "infrastructure.site",
        "lookout",
    ),
    M("infrastructure.picnic_spot", "Picnic spot", "picnic_spot-black.svg", "infrastructure.site"),
    M("infrastructure.hide", "Hide", "Hide.svg", "infrastructure.site", "blind"),
    M("infrastructure.feeding_site", "Feeding site", "Feeding.svg", "infrastructure.site"),
    M("infrastructure.den", "Den", "den.svg", "infrastructure.site", "burrow"),
    M("infrastructure.nest", "Nest", "bird_nest2.svg", "infrastructure.site"),
    M("infrastructure.roost", "Roost", "bird_roost.svg", "infrastructure.nest"),
    M("infrastructure.bai", "Bai", "bai-black.svg", "infrastructure.site", "forest clearing"),
    M("infrastructure.helipad", "Helipad", "helipad.svg", "infrastructure.site"),
    M(
        "infrastructure.airstrip",
        "Airstrip",
        "feature-airstrip.svg",
        "infrastructure.site",
        "runway",
    ),
    M("infrastructure.jetty", "Jetty", "jetty-black.svg", "infrastructure.site", "pier", "harbour"),
    M("infrastructure.mine", "Mine", "mine.svg", "infrastructure.site"),
    M(
        "infrastructure.spray_race",
        "Cattle spray race",
        "feature-cattle_spray_race.svg",
        "infrastructure.site",
        "dip",
    ),
    M(
        "infrastructure.shooting_range",
        "Shooting range",
        "shooting_range-olive.svg",
        "infrastructure.site",
    ),
    M("infrastructure.evacuation", "Evacuation point", "evacuation.svg", "infrastructure.site"),
    M(
        "infrastructure.repeater",
        "Radio repeater",
        "repeaters-black.svg",
        "infrastructure.site",
        "mast",
        "antenna",
    ),
    # Devices.
    Icon("device.sensor", "Sensor", OBS + "static-sensor.svg", None, ("device",), "static sensor"),
    W("device.camera_trap", "Camera trap", "camera_trap.svg", "device.sensor", "camera"),
    M("device.cctv", "CCTV camera", "cctv.svg", "device.camera_trap", "security camera"),
    M("device.video_camera", "Video camera", "video_camera.svg", "device.camera_trap"),
    W(
        "device.lora_gateway",
        "LoRaWAN gateway",
        "static_lora_gateway.svg",
        "device.sensor",
        "gateway",
    ),
    W("device.weather_station", "Weather station", "static-weather.svg", "device.sensor"),
    W(
        "device.radio",
        "Stationary radio",
        "stationary-radio-black.svg",
        "device.sensor",
        "base station",
    ),
    W("device.radio_repeater", "Radio repeater", "static_radio_repeater.svg", "device.radio"),
    S(
        "device.acoustic_sensor",
        "Acoustic sensor",
        "acoustic_sensor_rep.svg",
        "device.sensor",
        "microphone",
    ),
    S("device.gps", "GPS tracker", "GPS_point_rep.svg", "device.sensor", "tracker"),
    S(
        "device.satellite",
        "Satellite device",
        "skylight-detection-satellite_rep.svg",
        "device.sensor",
        "Iridium",
    ),
    W("device.pin", "Pin", "pin.svg", "device.sensor", "marker"),
    # Events.
    S(
        "event.detection",
        "Detection",
        "sighting_rep.svg",
        "event.alert",
        "species detection",
        "sighting",
    ),
    S(
        "event.wildlife_sighting",
        "Wildlife sighting",
        "wildlife_sighting_rep.svg",
        "event.detection",
    ),
    S(
        "event.elephant_sighting",
        "Elephant sighting",
        "elephant_sighting_rep.svg",
        "event.wildlife_sighting",
    ),
    S(
        "event.rhino_sighting",
        "Rhino sighting",
        "rhino_sighting_rep.svg",
        "event.wildlife_sighting",
    ),
    S("event.lion_sighting", "Lion sighting", "lion_sighting_rep.svg", "event.wildlife_sighting"),
    S(
        "event.leopard_sighting",
        "Leopard sighting",
        "leopard_sighting_rep.svg",
        "event.wildlife_sighting",
    ),
    S(
        "event.cheetah_sighting",
        "Cheetah sighting",
        "cheetah_sighting_rep.svg",
        "event.wildlife_sighting",
    ),
    S("event.geofence", "Geofence", "geofence_break_rep.svg", "event.alert", "geofence break"),
    S("event.geofence_enter", "Geofence entered", "ew_geofence_entered.svg", "event.geofence"),
    S("event.geofence_exit", "Geofence exited", "ew_geofence_exited.svg", "event.geofence"),
    S(
        "event.device_offline",
        "Device offline",
        "silent_source_rep.svg",
        "event.alert",
        "offline",
        "no data",
        "silent source",
    ),
    S(
        "event.source_offline",
        "Data source offline",
        "silent_source_provider_rep.svg",
        "event.device_offline",
    ),
    S("event.low_battery", "Low battery", "low_battery_rep.svg", "event.alert", "battery"),
    S("event.immobility", "Immobility", "immobility_rep.svg", "event.alert", "no movement"),
    S(
        "event.immobility_all_clear",
        "Immobility all clear",
        "immobility_all_clear_rep.svg",
        "event.immobility",
    ),
    S("event.speeding", "Speeding", "vehicleoverspeed_rep.svg", "event.alert", "speed limit"),
    S("event.vehicle_movement", "Vehicle movement", "vehiclemovement_rep.svg", "event.alert"),
    S("event.proximity", "Proximity", "proximity.svg", "event.alert", "near"),
    S(
        "event.subject_proximity",
        "Subjects close together",
        "subject_proximity.svg",
        "event.proximity",
    ),
    S("event.entry", "Entry", "entry_alert_rep.svg", "event.alert"),
    S("event.open_gate", "Gate open", "open_gate_rep.svg", "event.alert"),
    S("event.open_door", "Door open", "open_door_rep.svg", "event.alert"),
    S("event.fence_breakage", "Fence breakage", "fence_breakage_rep.svg", "event.alert"),
    S("event.fence_voltage", "Fence voltage", "fence_voltage_rep.svg", "event.alert"),
    S("event.fire", "Fire", "fire_rep.svg", "event.alert"),
    S("event.burn", "Burn", "burn_rep.svg", "event.fire"),
    S("event.rainfall", "Rainfall", "rainfall_rep.svg", "event.alert", "rain"),
    S("event.water_level", "Water level", "water_level_rep.svg", "event.alert", "flood"),
    S("event.water", "Water", "water_rep.svg", "event.water_level"),
    S("event.natural", "Natural event", "natural_event_rep.svg", "event.alert", "weather"),
    S("event.carcass", "Carcass", "carcass_rep.svg", "event.alert"),
    S(
        "event.mortality",
        "Wildlife mortality",
        "wildlife_mortality_rep.svg",
        "event.carcass",
        "death",
    ),
    S(
        "event.elephant_mortality",
        "Elephant mortality",
        "elephant_mortality_rep.svg",
        "event.mortality",
    ),
    S("event.injured_animal", "Injured animal", "injured_animal_rep.svg", "event.alert"),
    S("event.health_check", "Health check", "health_check_rep.svg", "event.alert", "veterinary"),
    S("event.rhino_birth", "Rhino birth", "rhino_birth_rep.svg", "event.alert", "birth"),
    S("event.boma", "Boma", "rhino_boma_rep.svg", "event.alert", "enclosure"),
    S("event.migration", "Migration", "migration_rep.svg", "event.alert"),
    S(
        "event.wildlife_gap_movement",
        "Wildlife gap movement",
        "wildlife_gap_movement_rep.svg",
        "event.migration",
        "corridor",
    ),
    S("event.spoor", "Spoor", "spoor_rep.svg", "event.detection", "tracks", "footprints"),
    S("event.snare", "Snare", "snare_rep.svg", "event.alert"),
    S("event.snared_animal", "Snared animal", "snare_animal_rep.svg", "event.snare"),
    S("event.trap", "Trap", "steel_jaw_trap_rep.svg", "event.snare"),
    S("event.poison", "Poison", "poison_rep.svg", "event.alert"),
    S("event.poaching", "Poaching", "poaching_rep.svg", "event.alert"),
    S("event.poacher_camp", "Poacher camp", "poacher_camp_rep.svg", "event.poaching"),
    S("event.poacher_sighting", "Poacher sighting", "poacher_sighting_rep.svg", "event.poaching"),
    S("event.gunshot", "Gunshot", "shot_rep.svg", "event.alert", "shot"),
    S("event.arrest", "Arrest", "arrest_rep.svg", "event.alert"),
    S("event.suspicious_person", "Suspicious person", "suspicious_person_rep.svg", "event.alert"),
    S("event.trafficker", "Trafficker", "trafficker_rep.svg", "event.alert"),
    S("event.illegal_activity", "Illegal activity", "illegal_activity_rep.svg", "event.alert"),
    S(
        "event.deforestation",
        "Deforestation",
        "deforestation_rep.svg",
        "event.illegal_activity",
        "logging",
    ),
    S("event.mining", "Mining", "mining_rep.svg", "event.illegal_activity"),
    S("event.fishing", "Fishing", "fishing_rep.svg", "event.illegal_activity"),
    S(
        "event.illegal_dumping",
        "Illegal dumping",
        "illegal_dumping_rep.svg",
        "event.illegal_activity",
    ),
    S("event.litter", "Litter", "litter_rep.svg", "event.alert"),
    S("event.vandalism", "Vandalism", "vandalism_rep.svg", "event.alert"),
    S("event.confiscation", "Confiscation", "confiscation_rep.svg", "event.alert"),
    S(
        "event.recovered_firearms",
        "Recovered firearms",
        "recovered_firearms_rep.svg",
        "event.confiscation",
    ),
    S(
        "event.recovered_trophies",
        "Recovered trophies",
        "recovered_trophies_rep.svg",
        "event.confiscation",
    ),
    S("event.ivory_found", "Ivory or horn found", "ivory_horn_found_rep.svg", "event.confiscation"),
    S(
        "event.human_wildlife_conflict",
        "Human wildlife conflict",
        "hwc_rep.svg",
        "event.alert",
        "HWC",
    ),
    S(
        "event.hwc_alert",
        "Human wildlife conflict alert",
        "hwc_alert_rep.svg",
        "event.human_wildlife_conflict",
    ),
    S("event.predation", "Predation", "hwc_predation_rep.svg", "event.human_wildlife_conflict"),
    S("event.conflict", "Conflict", "conflict_rep.svg", "event.alert"),
    S(
        "event.livestock_movement",
        "Livestock movement",
        "livestock_movement_rep.svg",
        "event.alert",
    ),
    S(
        "event.lost_livestock",
        "Lost livestock",
        "lost-livestock_rep.svg",
        "event.livestock_movement",
    ),
    S("event.livestock_death", "Livestock death", "livestock-death_rep.svg", "event.carcass"),
    S("event.stock_theft", "Stock theft", "stock_theft_rep.svg", "event.alert"),
    S("event.medevac", "Medevac", "medevac_rep.svg", "event.alert", "medical"),
    S("event.missing_person", "Missing person", "missing_person_rep.svg", "event.alert"),
    S("event.accident", "Accident", "accident_rep.svg", "event.alert"),
    S("event.sos", "SOS", "SOS_rep.svg", "event.alert", "emergency"),
    S("event.check_in_ok", "Check-in OK", "ew_check_in_im_ok.svg", "event.alert"),
    S("event.check_in_not_ok", "Check-in not OK", "ew_check_in_not_ok.svg", "event.alert"),
    S("event.missed_check_in", "Missed check-in", "ew_missed_check_in.svg", "event.alert"),
    S("event.sit_rep", "Situation report", "sit_rep.svg", "event.alert", "sitrep"),
    S("event.patrol", "Patrol", "patrol_rep.svg", "event.alert"),
    S("event.contact", "Contact", "contact_rep.svg", "event.alert"),
    S("event.radio", "Radio", "radio_rep.svg", "event.alert"),
    S("event.sensor", "Sensor", "sensor_rep.svg", "event.alert"),
    S("event.collar", "Collar", "collar.svg", "event.alert", "drop-off"),
    S("event.light", "Light", "light_rep.svg", "event.alert"),
    S(
        "event.magnetic_field",
        "Magnetic field change",
        "magnetic_field_change_rep.svg",
        "event.sensor",
    ),
    S("event.pump_station", "Pump station", "pump_station_rep.svg", "event.sensor"),
    S("event.maintenance", "Maintenance", "maintenance-event.svg", "event.alert"),
    S("event.road_status", "Road status", "road_status_rep.svg", "event.alert"),
    S("event.vehicle_response", "Vehicle response", "vehicle_response_rep.svg", "event.alert"),
    S("event.drone_sighting", "Drone sighting", "drone_sighting_rep.svg", "event.detection"),
    S("event.plane_sighting", "Aircraft sighting", "plane_sighting_rep.svg", "event.detection"),
    S(
        "event.helicopter_sighting",
        "Helicopter sighting",
        "helicopter_sighting_rep.svg",
        "event.detection",
    ),
    S("event.boat_sighting", "Boat sighting", "boat_sighting_rep.svg", "event.detection"),
    S("event.photo", "Photo taken", "photo_taken_rep.svg", "event.alert"),
    S("event.blood_sample", "Blood sample", "blood_sample_rep.svg", "event.health_check"),
    S("event.fecal_sample", "Fecal sample", "fecal_sample_rep.svg", "event.health_check"),
    S("event.feeding", "Feeding", "feeding_rep.svg", "event.alert"),
    S("event.nest", "Nest", "nest_rep.svg", "event.detection"),
    S("event.turtle_nest", "Turtle nest", "turtle_nest_rep.svg", "event.nest"),
    S("event.vulture_alert", "Vulture alert", "vulture_alert_rep.svg", "event.alert"),
    S("event.unknown", "Unknown", "unknown_rep.svg", "event.alert"),
    S("event.generic", "Generic report", "generic_rep.svg", "event.alert"),
]


class Normalised:
    """The cleaned SVG text and what was done to it."""

    def __init__(self, text: str, dropped_halo: bool) -> None:
        self.text = text
        self.dropped_halo = dropped_halo


def _style_fills(root: ET.Element) -> dict[str, str]:
    """`.a{fill:#fff;}` rules from the document's style blocks, class name to fill."""
    fills: dict[str, str] = {}
    for style in root.iter(f"{{{SVG_NS}}}style"):
        for match in re.finditer(r"\.([\w-]+)\s*\{([^}]*)\}", style.text or ""):
            classes, body = match.group(1), match.group(2)
            fill = re.search(r"(?<![-\w])fill\s*:\s*([^;]+)", body)
            if fill:
                fills[classes] = fill.group(1).strip().lower()
    for style in root.iter(f"{{{SVG_NS}}}style"):
        # `.b,.c{fill:#fff}` lists several classes
        for match in re.finditer(r"((?:\.[\w-]+\s*,\s*)+\.[\w-]+)\s*\{([^}]*)\}", style.text or ""):
            fill = re.search(r"(?<![-\w])fill\s*:\s*([^;]+)", match.group(2))
            if fill:
                for name in re.findall(r"\.([\w-]+)", match.group(1)):
                    fills[name] = fill.group(1).strip().lower()
    return fills


def _own_fill(element: ET.Element, style_fills: dict[str, str]) -> str | None:
    style = element.get("style") or ""
    inline = re.search(r"(?<![-\w])fill\s*:\s*([^;]+)", style)
    if inline:
        return inline.group(1).strip().lower()
    if element.get("fill"):
        return element.get("fill", "").strip().lower()
    for name in (element.get("class") or "").split():
        if name in style_fills:
            return style_fills[name]
    return None


def _tag(element: ET.Element) -> str:
    return element.tag.split("}")[-1]


def _painted(
    root: ET.Element, style_fills: dict[str, str]
) -> list[tuple[ET.Element, ET.Element | None, str]]:
    """Every painted element with its parent and its effective fill (inherited, black by default)."""
    result: list[tuple[ET.Element, ET.Element | None, str]] = []

    def walk(element: ET.Element, parent: ET.Element | None, inherited: str) -> None:
        own = _own_fill(element, style_fills)
        fill = own or inherited
        if _tag(element) in PAINTED:
            result.append((element, parent, fill))
        for child in list(element):
            walk(child, element, fill)

    walk(root, None, "black")
    return result


def _parents(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def normalise(text: str) -> Normalised:
    ET.register_namespace("", SVG_NS)
    root = ET.fromstring(text)
    if root.tag != f"{{{SVG_NS}}}svg":
        raise ValueError("not an SVG document")
    style_fills = _style_fills(root)

    # A white shape next to a dark one is EarthRanger's halo: drop it. All-white icons are drawn
    # for dark backgrounds and keep their shapes (they become currentColor like the rest).
    painted = _painted(root, style_fills)
    whites = [(e, p) for e, p, fill in painted if fill in WHITE]
    dropped_halo = 0 < len(whites) < len(painted)
    if dropped_halo:
        for element, parent in whites:
            if parent is not None:
                parent.remove(element)

    parents = _parents(root)
    for element in list(root.iter()):
        if _tag(element) in DROP_ELEMENTS and element in parents:
            parents[element].remove(element)
    parents = _parents(root)
    for defs in list(root.iter(f"{{{SVG_NS}}}defs")):
        if len(defs) == 0 and defs in parents:
            parents[defs].remove(defs)

    for element in root.iter():
        for attribute in list(element.attrib):
            if attribute in DROP_ATTRIBUTES:
                del element.attrib[attribute]
        fill = element.get("fill")
        if fill is not None and fill.strip().lower() != "none":
            del element.attrib["fill"]
        stroke = element.get("stroke")
        if stroke is not None and stroke.strip().lower() != "none":
            element.set("stroke", "currentColor")

    # Empty groups left behind by the pruning.
    changed = True
    while changed:
        changed = False
        parents = _parents(root)
        for element in list(root.iter(f"{{{SVG_NS}}}g")):
            if len(element) == 0 and element in parents:
                parents[element].remove(element)
                changed = True

    root.set("viewBox", _square_viewbox(root, text))
    root.set("fill", "currentColor")
    for element in root.iter():
        for attribute in (
            "d",
            "points",
            "cx",
            "cy",
            "r",
            "rx",
            "ry",
            "x1",
            "y1",
            "x2",
            "y2",
            "transform",
        ):
            value = element.get(attribute)
            if value is not None:
                element.set(attribute, _round_numbers(value))
    for element in root.iter():
        element.text = (element.text or "").strip() or None
        element.tail = (element.tail or "").strip() or None
    serialised = ET.tostring(root, encoding="unicode")
    serialised = (
        re.sub(r"\s+xmlns:xlink=\"[^\"]*\"", "", serialised)
        if "xlink:" not in serialised
        else serialised
    )
    return Normalised(serialised + "\n", dropped_halo)


_NUMBER = re.compile(r"-?\d*\.?\d+(?:e-?\d+)?")


def _round_numbers(value: str) -> str:
    """Two decimals are far below a pixel at any size the icons are drawn (viewBoxes of 15 to 60
    units); Illustrator exports carry four or five and the bundle inlines every file. Path data
    may write two numbers without a separator (`.0342.001`); a rounded number that lost its dot
    would swallow the next one, so a space is put between numbers that touched."""
    out: list[str] = []
    end = 0
    for match in _NUMBER.finditer(value):
        rounded = _number(float(match.group(0)))
        out.append(value[end : match.start()])
        if match.start() == end and end > 0 and not rounded.startswith("-"):
            out.append(" ")
        out.append(rounded)
        end = match.end()
    out.append(value[end:])
    return "".join(out)


def _number(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def _square_viewbox(root: ET.Element, original: str) -> str:
    box = root.get("viewBox")
    if box:
        min_x, min_y, width, height = (float(v) for v in re.split(r"[\s,]+", box.strip()))
    else:
        width_attr = re.search(r'\swidth="([\d.]+)', original)
        height_attr = re.search(r'\sheight="([\d.]+)', original)
        if not width_attr or not height_attr:
            raise ValueError("no viewBox and no width and height")
        min_x, min_y, width, height = (
            0.0,
            0.0,
            float(width_attr.group(1)),
            float(height_attr.group(1)),
        )
    side = max(width, height)
    min_x -= (side - width) / 2
    min_y -= (side - height) / 2
    return " ".join(_number(v) for v in (min_x, min_y, side, side))


def fetch(path: str) -> str:
    with urllib.request.urlopen(RAW + path.replace(" ", "%20"), timeout=60) as response:
        body: bytes = response.read()
    return body.decode("utf-8")


def entry_for(icon: Icon) -> dict[str, object]:
    return {
        "asset": icon.asset,
        "category": icon.category,
        "label": icon.label,
        "source": SOURCE_LABEL,
        "license": LICENSE,
        "fallback": icon.fallback,
        "earthranger_mapping": icon.earthranger_mapping,
        "aliases": list(icon.aliases),
    }


CATEGORY_ORDER = list(FOLDERS)


def write_registry(entries: dict[str, dict[str, object]]) -> None:
    """One entry per line, grouped by category, so a diff reads per icon."""
    ordered = sorted(
        entries.items(), key=lambda item: (CATEGORY_ORDER.index(str(item[1]["category"])), item[0])
    )
    lines = [
        f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}" for key, value in ordered
    ]
    REGISTRY.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="report without writing")
    args = parser.parse_args()

    keys = [icon.key for icon in ICONS]
    duplicates = {key for key in keys if keys.count(key) > 1}
    if duplicates:
        print(f"duplicate keys in ICONS: {sorted(duplicates)}", file=sys.stderr)
        return 1
    entries: dict[str, dict[str, object]] = json.loads(REGISTRY.read_text(encoding="utf-8"))
    known = set(entries) | set(keys)
    for icon in ICONS:
        if icon.fallback and icon.fallback not in known:
            print(f"{icon.key}: fallback {icon.fallback} is not a key", file=sys.stderr)
            return 1

    changed = 0
    halos = 0
    for icon in ICONS:
        target = ICONS_DIR / icon.asset
        result = normalise(fetch(icon.source))
        halos += result.dropped_halo
        before = target.read_text(encoding="utf-8") if target.exists() else None
        entry = entry_for(icon)
        if before != result.text or entries.get(icon.key) != entry:
            changed += 1
            if args.check:
                print(f"would write {icon.key} ({icon.asset}, {len(result.text)} bytes)")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(result.text, encoding="utf-8")
        entries[icon.key] = entry

    if not args.check:
        write_registry(entries)
        (ICONS_DIR / "LICENSE-EarthRanger").write_text(fetch("LICENSE"), encoding="utf-8")
    referenced = {str(value["asset"]) for value in entries.values()}
    stray = sorted(
        str(path.relative_to(ICONS_DIR))
        for path in ICONS_DIR.glob("*/*.svg")
        if str(path.relative_to(ICONS_DIR)) not in referenced
    )
    print(
        f"{len(ICONS)} EarthRanger icons, {changed} written, {halos} halos removed, {len(entries)} registry entries"
    )
    if stray:
        print(f"unreferenced files (delete by hand): {stray}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
