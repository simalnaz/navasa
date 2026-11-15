"""Measured temperatures from Perseverance MEDA for the sols named in the mission file.

Source (named in the mission file, site.meda): Mars 2020 MEDA calibrated environmental data,
NASA PDS Atmospheres Node (PDS4 bundle mars2020_meda, collection data_calibrated_env).
The archive's readme: use the derived level when it exists, otherwise the calibrated level;
the derived TIRS product has no temperatures, so the calibrated files are used.

Per sol, from two files (about one row per second, each row with LMST):
    air      ATS_LOCAL_TEMP1..3 (CAL_ATS): the three air temperature sensors on the remote sensing
             mast; a row counts when all three have a value; value = their mean
    ground   GROUND_TEMP (CAL_TIRS): ground brightness temperature; a row is left out when a quality
             flag says 0 for ROVER_STILL (rover moving), ROVER_LOW_TILT (tilt >= 20 deg),
             TIRS_GROUND_FOOTPRINT_NOT_IN_SHADOW (rover shadow on the spot) or
             WHEEL_OUTSIDE_TIRS_DOWNWARD_LOOKING_FOV (wheel in view). An empty flag is not a 0.

Reduction (DEFAULT_MEDA): median per Mars minute (removes single-second spikes), then
    hourly    mean of the minute medians in each LMST hour (hours without minutes are left out)
    min, max  lowest and highest minute median and its LMST
Kelvin to Celsius: minus 273.15.

Output: data/work/<pack>/meda.json

Usage:
    python -m pipeline.meda [data/missions/<mission>.json]
"""

import csv
import datetime
import json
import os
import statistics
import sys

from pipeline.mars_time import unix_ms_at_m20_local_time
from pipeline.mission import RAW_DIR, MissionPaths, load_mission, mission_path_from_arguments

KELVIN_TO_CELSIUS = 273.15
DEFAULT_MEDA = {"minutes_per_hour": 60}
GROUND_QUALITY_FLAGS = (
    "ROVER_STILL",
    "ROVER_LOW_TILT",
    "TIRS_GROUND_FOOTPRINT_NOT_IN_SHADOW",
    "WHEEL_OUTSIDE_TIRS_DOWNWARD_LOOKING_FOV",
)
AIR_COLUMNS = ("ATS_LOCAL_TEMP1", "ATS_LOCAL_TEMP2", "ATS_LOCAL_TEMP3")


class MedaFileError(Exception):
    pass


def parse_lmst(text):
    """'01859M13:05:22.123' -> (sol, hours as a float)."""
    sol_text, clock = text.strip().split("M")
    hours, minutes, seconds = clock.split(":")
    return int(sol_text), int(hours) + int(minutes) / 60.0 + float(seconds) / 3600.0


def read_rows(path, required_columns):
    with open(path, "r", encoding="utf-8", newline="") as table_file:
        reader = csv.DictReader(table_file)
        missing = []
        for column in required_columns:
            if reader.fieldnames is None or column not in reader.fieldnames:
                missing.append(column)
        if len(missing) > 0:
            raise MedaFileError(f"{path}: missing columns {missing}")
        for row in reader:
            yield row


def air_samples(path, sol):
    """(hours, kelvin) for every row of this sol with all three mast sensors."""
    samples = []
    for row in read_rows(path, ("LMST",) + AIR_COLUMNS):
        row_sol, hours = parse_lmst(row["LMST"])
        if row_sol != sol:
            continue
        values = []
        for column in AIR_COLUMNS:
            if row[column].strip() != "":
                values.append(float(row[column]))
        if len(values) == len(AIR_COLUMNS):
            samples.append((hours, sum(values) / len(values)))
    return samples


def ground_samples(path, sol):
    """(hours, kelvin) for rows of this sol with a ground temperature and no flag saying 0; and the count left out."""
    samples = []
    left_out = 0
    for row in read_rows(path, ("LMST", "GROUND_TEMP") + GROUND_QUALITY_FLAGS):
        row_sol, hours = parse_lmst(row["LMST"])
        if row_sol != sol or row["GROUND_TEMP"].strip() == "":
            continue
        flagged = False
        for flag in GROUND_QUALITY_FLAGS:
            if row[flag].strip() == "0":
                flagged = True
        if flagged:
            left_out += 1
            continue
        samples.append((hours, float(row["GROUND_TEMP"])))
    return samples, left_out


def summarise(samples):
    """Minute medians -> hourly means, min and max (Celsius, LMST hours). None if there are no samples."""
    if len(samples) == 0:
        return None
    by_minute = {}
    for hours, kelvin in samples:
        minute = int(hours * DEFAULT_MEDA["minutes_per_hour"])
        by_minute.setdefault(minute, []).append(kelvin)
    minute_medians = []
    for minute in sorted(by_minute):
        minute_medians.append((minute, statistics.median(by_minute[minute]) - KELVIN_TO_CELSIUS))
    by_hour = {}
    for minute, celsius in minute_medians:
        by_hour.setdefault(minute // DEFAULT_MEDA["minutes_per_hour"], []).append(celsius)
    hourly = []
    for hour in sorted(by_hour):
        values = by_hour[hour]
        hourly.append({"hour": hour, "mean_c": round(sum(values) / len(values), 1), "minutes": len(values)})
    lowest = min(minute_medians, key=lambda item: item[1])
    highest = max(minute_medians, key=lambda item: item[1])
    return {
        "hourly": hourly,
        "min": {"c": round(lowest[1], 1), "lmst_hours": round(lowest[0] / 60.0, 3)},
        "max": {"c": round(highest[1], 1), "lmst_hours": round(highest[0] / 60.0, 3)},
        "minutes": len(minute_medians),
    }


def utc_text(unix_ms):
    return datetime.datetime.fromtimestamp(unix_ms / 1000.0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")


def main(mission_path):
    mission = load_mission(mission_path)
    meda = mission["site"].get("meda")
    paths = MissionPaths(mission)
    output_path = os.path.join(paths.work_dir, "meda.json")
    if meda is None:
        print("Mission has no MEDA data (site.meda): skipped")
        if os.path.isfile(output_path):
            os.remove(output_path)
        return 0
    sols = []
    for entry in meda["sols"]:
        sol = entry["sol"]
        air = summarise(air_samples(os.path.join(RAW_DIR, entry["ats_file"]), sol))
        ground_rows, left_out = ground_samples(os.path.join(RAW_DIR, entry["tirs_file"]), sol)
        ground = summarise(ground_rows)
        sols.append(
            {
                "sol": sol,
                "stop_id": entry.get("stop_id"),
                "note": entry.get("note"),
                "utc_start": utc_text(unix_ms_at_m20_local_time(sol, 0.0)),
                "utc_end": utc_text(unix_ms_at_m20_local_time(sol + 1, 0.0)),
                "air": air,
                "ground": ground,
                "ground_rows_left_out": left_out,
            }
        )
        air_text = "no data" if air is None else f"{air['min']['c']} to {air['max']['c']} C, {len(air['hourly'])} h"
        ground_text = "no data" if ground is None else f"{ground['min']['c']} to {ground['max']['c']} C, {len(ground['hourly'])} h"
        print(f"MEDA sol {sol}: air {air_text}; ground {ground_text} ({left_out} rows left out by flags)")
    with open(output_path, "w", encoding="utf-8") as output:
        json.dump({"sols": sols}, output, indent=1)
    print(f"MEDA summary written to {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(mission_path_from_arguments()))
