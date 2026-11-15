"""Make the small global Mars image for the app's orbit view.

Source: Mars Viking MDIM 2.1 Colorized Global Mosaic, 232 m/pixel, USGS Astrogeology
Science Center (NASA Viking Orbiter images), simple cylindrical (longitude/latitude)
projection, 92160 x 46080 pixels, 12.7 GB. Only every n-th row and column is read
over the network (nearest pixel), so the whole file is never downloaded.

Output: web/data/globe/mars_viking_colour.jpg  (DEFAULT_GLOBE["width_px"] x half that,
        longitude -180..180 left to right, latitude 90..-90 top to bottom)

Usage:
    python -m pipeline.make_globe
"""

import os
import sys

import numpy
import rasterio
from PIL import Image
from rasterio.enums import Resampling

from pipeline.stops import PROJECT_ROOT

SOURCE_URL = "https://planetarymaps.usgs.gov/mosaic/Mars_Viking_MDIM21_ClrMosaic_global_232m.tif"
OUTPUT_PATH = os.path.join(PROJECT_ROOT, "web", "data", "globe", "mars_viking_colour.jpg")
DEFAULT_GLOBE = {"width_px": 2048, "jpeg_quality": 85}


def main():
    width = DEFAULT_GLOBE["width_px"]
    height = width // 2
    print(f"Reading {SOURCE_URL} at {width} x {height} ...")
    with rasterio.open("/vsicurl/" + SOURCE_URL) as source:
        if source.count < 3:
            raise ValueError("expected a 3-band colour mosaic")
        if abs(source.width / source.height - 2.0) > 1e-6:
            raise ValueError("expected a global 2:1 longitude/latitude mosaic")
        bounds = source.bounds
        colour = source.read(
            (1, 2, 3), out_shape=(3, height, width), resampling=Resampling.nearest
        )
    print(f"Source bounds (map metres): {tuple(round(value) for value in bounds)}")
    image = numpy.transpose(colour, (1, 2, 0))
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    Image.fromarray(image, mode="RGB").save(OUTPUT_PATH, "JPEG", quality=DEFAULT_GLOBE["jpeg_quality"])
    print(f"Written {OUTPUT_PATH}: {os.path.getsize(OUTPUT_PATH) / 1e6:.2f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
