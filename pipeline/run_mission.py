"""Build a mission's data pack from its mission file, every step in order.

    python -m pipeline.run_mission data/missions/<mission>.json

Steps: check the mission file, crop the layers, slope, routes, geology, thermal,
terrain horizon, coverage, Mars context, build
and check the pack. Stops at the first step that fails.
"""

import sys

from pipeline import build_pack, context_maps, coverage_check, crop_layers, geology, horizon, routes, terrain, thermal
from pipeline.mission import MissionFileError, load_mission, mission_path_from_arguments

STEPS = (
    ("crop layers and make image tiles", crop_layers.main),
    ("slope", terrain.main),
    ("routes", routes.main),
    ("geology", geology.main),
    ("thermal (THEMIS)", thermal.main),
    ("terrain horizon for sun and shadow", horizon.main),
    ("coverage check", coverage_check.main),
    ("Mars context layers (planet, region, crater)", context_maps.main),
    ("build and check the data pack", build_pack.main),
)


def main(mission_path):
    try:
        mission = load_mission(mission_path)
    except MissionFileError as error:
        print(f"Mission file {mission_path} has problems:")
        for problem in error.problems:
            print(f"  - {problem}")
        return 1
    print(f"Mission {mission['id']}: {mission['name']} ({len(mission['stops'])} stops)")
    for step_name, step in STEPS:
        print(f"\n== {step_name}")
        result = step(mission_path)
        if result != 0:
            print(f"Stopped: step '{step_name}' failed.")
            return result
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
