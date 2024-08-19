"""
::

     ____    ____    _____   ______     ___              __     
    /\  _`\ /\  _`\ /\  __`\/\__  _\__ /\_ \            /\ \    
    \ \ \L\_\ \ \L\_\ \ \/\ \/_/\ \/\_\\//\ \      __   \_\ \   
     \ \ \L_L\ \  _\L\ \ \ \ \ \ \ \/\ \ \ \ \   /'__`\ /'_` \  
      \ \ \/, \ \ \L\ \ \ \_\ \ \ \ \ \ \ \_\ \_/\  __//\ \L\ \ 
       \ \____/\ \____/\ \_____\ \ \_\ \_\/\____\ \____\ \___,_\ 
        \/___/  \/___/  \/_____/  \/_/\/_/\/____/\/____/\/__,_ /


GEOtiled: A Scalable Workflow for Generating Large Datasets of
High-Resolution Terrain Parameters

Refactored library. Compiled by Jay Ashworth
v0.0.1
GCLab 2023

Derived from original work by: Camila Roa (@CamilaR20), Eric Vaughan (@VaughanEric), Andrew Mueller (@Andym1098), Sam Baumann (@sam-baumann), David Huang (@dhuang0212), Ben Klein (@robobenklein)

`Read the paper here <https://dl.acm.org/doi/pdf/10.1145/3588195.3595941>`_

Terrain parameters such as slope, aspect, and hillshading are essential in various applications, including agriculture, forestry, and
hydrology. However, generating high-resolution terrain parameters is computationally intensive, making it challenging to provide
these value-added products to communities in need. We present a
scalable workflow called GEOtiled that leverages data partitioning
to accelerate the computation of terrain parameters from digital elevation models, while preserving accuracy. We assess our workflow
in terms of its accuracy and wall time by comparing it to SAGA,
which is highly accurate but slow to generate results, and to GDAL,
which supports memory optimizations but not data parallelism. We
obtain a coefficient of determination (𝑅2) between GEOtiled and
SAGA of 0.794, ensuring accuracy in our terrain parameters. We
achieve an X6 speedup compared to GDAL when generating the
terrain parameters at a high-resolution (10 m) for the Contiguous
United States (CONUS).
"""

import os
import math
import subprocess
import requests
import pandas as pd
from osgeo import gdal
from osgeo import osr
from osgeo import ogr
import numpy as np
import matplotlib.pyplot as plt
import concurrent.futures
from tqdm import tqdm
import geopandas as gpd

# In Ubuntu: sudo apt-get install grass grass-doc
# pip install grass-session
# from grass_session import Session
# import grass.script as gscript
# import tempfile

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def bash(argv):
    """
    Execute bash commands using Popen.
    ----------------------------------

    This function acts as a wrapper to execute bash commands using the subprocess Popen method. Commands are executed synchronously,
    and errors are caught and raised.

    Required Parameters
    -------------------
    argv : List
        List of arguments for a bash command. They should be in the order that you would arrange them in the command line (e.g., ["ls", "-lh", "~/"]).

    Outputs
    -------
    None
        The function does not return any value.

    Error States
    ------------
    RuntimeError
        Raises a RuntimeError if Popen returns with an error, detailing the error code, stdout, and stderr.

    Notes
    -----
    - It's essential to ensure that the arguments in the 'argv' list are correctly ordered and formatted for the desired bash command.
    """
    arg_seq = [str(arg) for arg in argv]
    proc = subprocess.Popen(
        arg_seq, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )  # , shell=True)
    proc.wait()  # ... unless intentionally asynchronous
    stdout, stderr = proc.communicate()

    # Error catching: https://stackoverflow.com/questions/5826427/can-a-python-script-execute-a-function-inside-a-bash-script
    if proc.returncode != 0:
        raise RuntimeError(
            "'%s' failed, error code: '%s', stdout: '%s', stderr: '%s'"
            % (" ".join(arg_seq), proc.returncode, stdout.rstrip(), stderr.rstrip())
        )


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def build_mosaic(input_files, output_file, description="Elevation"):
    """
    Build a mosaic of geo-tiles using the GDAL library.
    ---------------------------------------------------

    This function creates a mosaic from a list of geo-tiles.
    It is an integral part of the GEOTILED workflow and is frequently used for merging tiles into a single mosaic file.

    Required Parameters
    -------------------
    input_files : list of str
        List of strings containing paths to the geo-tiles that are to be merged.
    output_file : str
        String representing the desired location and filename for the output mosaic.

    Optional Parameters
    -------------------
    description : str
        Description to attach to the output raster band. Default is "Elevation".

    Outputs
    -------
    None
        The function does not return any value.
        Generates a .tif file representing the created mosaic. This file will be placed at the location specified by 'output_file'.

    Notes
    -----
    - Ensure the input geo-tiles are compatible for merging.
    - The function utilizes the GDAL library's capabilities to achieve the desired mosaic effect.
    """
    # input_files: list of .tif files to merge
    vrt = gdal.BuildVRT("Materials/merged.vrt", input_files)
    translate_options = gdal.TranslateOptions(
        creationOptions=[
            "COMPRESS=LZW",
            "TILED=YES",
            "BIGTIFF=YES",
            "NUM_THREADS=ALL_CPUS",
        ]
    )  # ,callback=gdal.TermProgress_nocb)
    gdal.Translate(output_file, vrt, options=translate_options)
    vrt = None  # closes file
    dataset = gdal.Open(output_file)
    band = dataset.GetRasterBand(1)
    band.SetDescription(description)
    dataset = None


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def build_mosaic_filtered(input_files, output_file):
    """
    Build a mosaic of geo-tiles using the GDAL library with added logic to handle overlapping regions.
    ---------------------------------------------------------------------------------------------------

    This function creates a mosaic from a list of geo-tiles and introduces extra logic to handle averaging when regions overlap.
    The function is similar to `build_mosaic` but provides additional capabilities to ensure the integrity of data in overlapping regions.

    Required Parameters
    -------------------
    input_files : list of str
        List of strings containing paths to the geo-tiles to be merged.
    output_file : str
        String representing the desired location and filename for the output mosaic.

    Outputs
    -------
    None
        The function does not return any value.
        Generates a .tif file representing the created mosaic. This file is placed at the location specified by 'output_file'.

    Notes
    -----
    - The function makes use of the GDAL library's capabilities and introduces Python-based pixel functions to achieve the desired averaging effect.
    - The function is particularly useful when there are multiple sources of geo-data with possible overlapping regions,
      ensuring a smooth transition between tiles.
    - Overlapping regions in the mosaic are handled by averaging pixel values.
    """
    vrt = gdal.BuildVRT("Materials/merged.vrt", input_files) ## TODO:
    vrt = None  # closes file

    with open("Materials/merged.vrt", "r") as f:
        contents = f.read()

    if "<NoDataValue>" in contents:
        nodata_value = contents[
            contents.index("<NoDataValue>") + len("<NoDataValue>") : contents.index(
                "</NoDataValue>"
            )
        ]  # To add averaging function
    else:
        nodata_value = 0

    code = """band="1" subClass="VRTDerivedRasterBand">
  <PixelFunctionType>average</PixelFunctionType>
  <PixelFunctionLanguage>Python</PixelFunctionLanguage>
  <PixelFunctionCode><![CDATA[
import numpy as np

def average(in_ar, out_ar, xoff, yoff, xsize, ysize, raster_xsize,raster_ysize, buf_radius, gt, **kwargs):
    data = np.ma.array(in_ar, mask=np.equal(in_ar, {}))
    np.mean(data, axis=0, out=out_ar, dtype="float32")
    mask = np.all(data.mask,axis = 0)
    out_ar[mask] = {}
]]>
  </PixelFunctionCode>""".format(nodata_value, nodata_value)

    sub1, sub2 = contents.split('band="1">', 1)
    contents = sub1 + code + sub2

    with open("Materials/merged.vrt", "w") as f:
        f.write(contents)

    cmd = [
        "gdal_translate",
        "-co",
        "COMPRESS=LZW",
        "-co",
        "TILED=YES",
        "-co",
        "BIGTIFF=YES",
        "--config",
        "GDAL_VRT_ENABLE_PYTHON",
        "YES",
        "Materials/merged.vrt",
        output_file,
    ]
    bash(cmd)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def build_stack(input_files, output_file):
    """
    Stack a list of .tif files into a single .tif file with multiple bands.
    ------------------------------------------------------------------------

    This function takes multiple .tif files and combines them into a single .tif file where each input file represents a separate band.
    This operation is useful when multiple datasets, each represented by a separate .tif file, need to be combined into a single multi-band raster.

    Required Parameters
    -------------------
    input_files : list of str
        List of strings containing paths to the .tif files to be stacked.
    output_file : str
        String representing the desired location and filename for the output stacked raster.

    Outputs
    -------
    None
        The function does not return any value.
        A multi-band .tif file is generated at the location specified by 'output_file'.

    Notes
    -----
    - The function makes use of the GDAL library's capabilities to achieve the stacking operation.
    - Each input .tif file becomes a separate band in the output .tif file, retaining the order of the `input_files` list.
    """
    # input_files: list of .tif files to stack
    vrt_options = gdal.BuildVRTOptions(separate=True)
    vrt = gdal.BuildVRT("stack.vrt", input_files, options=vrt_options)
    translate_options = gdal.TranslateOptions(
        creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=YES"]
    )  # ,callback=gdal.TermProgress_nocb)
    gdal.Translate(output_file, vrt, options=translate_options)
    vrt = None  # closes file


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def change_raster_format(input_file, output_file, raster_format):
    """
    Convert the format of a given raster file.
    -------------------------------------------

    This function leverages the GDAL library to facilitate raster format conversion.
    It allows users to convert the format of their .tif raster files to several supported formats,
    specifically highlighting the GTiff and NC4C formats.

    Required Parameters
    -------------------
    input_file : str
        String containing the path to the input .tif file.
    output_file : str
        String representing the desired location and filename for the output raster.
    raster_format : str
        String indicating the desired output format for the raster conversion.
        Supported formats can be found at `GDAL Raster Formats <https://gdal.org/drivers/raster/index.html>`.
        This function explicitly supports GTiff and NC4C.

    Outputs
    -------
    None
        The function does not return any value.
        A raster file in the desired format is generated at the location specified by 'output_file'.

    Notes
    -----
    - While GTiff and NC4C formats have been explicitly mentioned,
      the function supports several other formats as listed in the GDAL documentation.
    - The function sets specific creation options for certain formats.
      For example, the GTiff format will use LZW compression, tiling, and support for large files.
    """

    # Supported formats: https://gdal.org/drivers/raster/index.html
    # SAGA, GTiff
    if raster_format == "GTiff":
        translate_options = gdal.TranslateOptions(
            format=raster_format,
            creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=YES"],
        )  # ,callback=gdal.TermProgress_nocb)
    elif raster_format == "NC4C":
        translate_options = gdal.TranslateOptions(
            format=raster_format, creationOptions=["COMPRESS=DEFLATE"]
        )  # ,callback=gdal.TermProgress_nocb)
    else:
        translate_options = gdal.TranslateOptions(
            format=raster_format
        )  # ,callback=gdal.TermProgress_nocb)

    gdal.Translate(output_file, input_file, options=translate_options)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def compute_geotiled(input_file):
    """
    Generate terrain parameters for an elevation model.
    ---------------------------------------------------

    This function uses the GDAL library to compute terrain parameters like slope, aspect, and hillshading
    from a provided elevation model in .tif format.

    Required Parameters
    --------------------
    input_file : str
        String containing the path to the input elevation model .tif.

    Returns
    -------
    None
        The function does not return any value.
        Generates terrain parameter files at the specified paths for slope, aspect, and hillshading.

    Notes
    -----
    - The function currently supports the following terrain parameters:
      - Slope
      - Aspect
      - Hillshading
    - The generated parameter files adopt the following GDAL creation options: 'COMPRESS=LZW', 'TILED=YES', and 'BIGTIFF=YES'.
    - The hillshading file undergoes an additional step to change its datatype to match that of the other parameters and
      also sets its nodata value. The intermediate file used for this process is removed after the conversion.
    """

    out_folder = os.path.dirname(os.path.dirname(input_file))
    out_file = os.path.join(out_folder,'slope_tiles', os.path.basename(input_file))
    # Slope
    dem_options = gdal.DEMProcessingOptions(format='GTiff', creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES'])
    gdal.DEMProcessing(out_file, input_file, processing='slope', options=dem_options)

    #Adding 'Slope' name to band description
    dataset = gdal.Open(out_file)
    band = dataset.GetRasterBand(1)
    band.SetDescription("Slope")
    dataset = None

    # Aspect
    out_file = os.path.join(out_folder,'aspect_tiles', os.path.basename(input_file))
    dem_options = gdal.DEMProcessingOptions(zeroForFlat=False, format='GTiff', creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES'])
    gdal.DEMProcessing(out_file, input_file, processing='aspect', options=dem_options)

    #Adding 'Aspect' name to band description
    dataset = gdal.Open(out_file)
    band = dataset.GetRasterBand(1)
    band.SetDescription("Aspect")
    dataset = None

    # Hillshading
    out_file = os.path.join(
        out_folder, "hillshading_tiles", os.path.basename(input_file)
    )
    dem_options = gdal.DEMProcessingOptions(
        format="GTiff", creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=YES"]
    )
    gdal.DEMProcessing(
        out_file, input_file, processing="hillshade", options=dem_options
    )

    # Adding 'Hillshading' name to band description
    dataset = gdal.Open(out_file)
    band = dataset.GetRasterBand(1)
    band.SetDescription("Hillshading")
    dataset = None


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# def compute_params(input_prefix, parameters):
#     """
#     Compute various topographic parameters using GDAL and GRASS GIS.
#     ----------------------------------------------------------------

#     This function computes a range of topographic parameters such as slope, aspect, and hillshading for a given Digital Elevation Model (DEM) using GDAL and GRASS GIS libraries.

#     Required Parameters
#     -------------------
#     input_prefix : str
#         Prefix path for the input DEM (elevation.tif) and the resulting parameter files.
#         For instance, if input_prefix is "/path/to/dem/", then the elevation file should be
#         "/path/to/dem/elevation.tif" and the resulting slope will be at "/path/to/dem/slope.tif", etc.
#     parameters : list of str
#         List of strings specifying which topographic parameters to compute. Possible values are:
#         'slope', 'aspect', 'hillshading', 'twi', 'plan_curvature', 'profile_curvature',
#         'convergence_index', 'valley_depth', 'ls_factor'.

#     Outputs
#     -------
#     None
#         Files are written to the `input_prefix` directory based on the requested parameters.

#     Notes
#     -----
#     - GDAL is used for slope, aspect, and hillshading computations.
#     - GRASS GIS is used for other parameters including 'twi', 'plan_curvature', 'profile_curvature', and so on.
#     - The function creates a temporary GRASS GIS session for processing.
#     - Assumes the input DEM is named 'elevation.tif' prefixed by `input_prefix`.

#     Error states
#     ------------
#     - If an unsupported parameter is provided in the 'parameters' list, it will be ignored.
#     """

#     # Slope
#     if 'slope' in parameters:
#         dem_options = gdal.DEMProcessingOptions(format='GTiff', creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES'], callback=gdal.TermProgress_nocb)
#         gdal.DEMProcessing(input_prefix + 'slope.tif', input_prefix + 'elevation.tif', processing='slope', options=dem_options)
#     # Aspect
#     if 'aspect' in parameters:
#         dem_options = gdal.DEMProcessingOptions(zeroForFlat=True, format='GTiff', creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES'], callback=gdal.TermProgress_nocb)
#         gdal.DEMProcessing(input_prefix + 'aspect.tif', input_prefix + 'elevation.tif', processing='aspect', options=dem_options)
#     # Hillshading
#     if 'hillshading' in parameters:
#         dem_options = gdal.DEMProcessingOptions(format='GTiff', creationOptions=['COMPRESS=LZW', 'TILED=YES', 'BIGTIFF=YES'], callback=gdal.TermProgress_nocb)
#         gdal.DEMProcessing(input_prefix + 'hillshading.tif', input_prefix + 'elevation.tif', processing='hillshade', options=dem_options)

#     # Other parameters with GRASS GIS
#     if any(param in parameters for param in ['twi', 'plan_curvature', 'profile_curvature']):
#         # define where to process the data in the temporary grass-session
#         tmpdir = tempfile.TemporaryDirectory()

#         s = Session()
#         s.open(gisdb=tmpdir.name, location='PERMANENT', create_opts=input_prefix + 'elevation.tif')
#         creation_options = 'BIGTIFF=YES,COMPRESS=LZW,TILED=YES' # For GeoTIFF files

#         # Load raster into GRASS without loading it into memory (else use r.import or r.in.gdal)
#         gscript.run_command('r.external', input=input_prefix + 'elevation.tif', output='elevation', overwrite=True)
#         # Set output folder for computed parameters
#         gscript.run_command('r.external.out', directory=os.path.dirname(input_prefix), format="GTiff", option=creation_options)

#         if 'twi' in parameters:
#             gscript.run_command('r.topidx', input='elevation', output='twi.tif', overwrite=True)

#         if 'plan_curvature' in parameters:
#             gscript.run_command('r.slope.aspect', elevation='elevation', tcurvature='plan_curvature.tif', overwrite=True)

#         if 'profile_curvature' in parameters:
#             gscript.run_command('r.slope.aspect', elevation='elevation', pcurvature='profile_curvature.tif', overwrite=True)

#         if 'convergence_index' in parameters:
#             gscript.run_command('r.convergence', input='elevation', output='convergence_index.tif', overwrite=True)

#         if 'valley_depth' in parameters:
#             gscript.run_command('r.valley.bottom', input='elevation', mrvbf='valley_depth.tif', overwrite=True)

#         if 'ls_factor' in parameters:
#             gscript.run_command('r.watershed', input='elevation', length_slope='ls_factor.tif', overwrite=True)


#         tmpdir.cleanup()
#         s.close()

#         # Slope and aspect with GRASS GIS (uses underlying GDAL implementation)
#         #vgscript.run_command('r.slope.aspect', elevation='elevation', aspect='aspect.tif', slope='slope.tif', overwrite=True)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

# def compute_params_concurrently(input_prefix, parameters):
#     """
#     Compute various topographic parameters concurrently using multiple processes.
#     ------------------------------------------------------------------------------

#     This function optimizes the performance of the `compute_params` function by concurrently computing
#     various topographic parameters. It utilizes Python's concurrent futures for parallel processing.

#     Required Parameters
#     -------------------
#     input_prefix : str
#         Prefix path for the input DEM (elevation.tif) and the resulting parameter files.
#         E.g., if `input_prefix` is "/path/to/dem/", the elevation file is expected at
#         "/path/to/dem/elevation.tif", and the resulting slope at "/path/to/dem/slope.tif", etc.
#     parameters : list of str
#         List of strings specifying which topographic parameters to compute. Possible values include:
#         'slope', 'aspect', 'hillshading', 'twi', 'plan_curvature', 'profile_curvature',
#         'convergence_index', 'valley_depth', 'ls_factor'.

#     Outputs
#     -------
#     None
#         Files are written to the `input_prefix` directory based on the requested parameters.

#     Notes
#     -----
#     - Utilizes a process pool executor with up to 20 workers for parallel computations.
#     - Invokes the `compute_params` function for each parameter in the list concurrently.

#     Error states
#     ------------
#     - Unsupported parameters are ignored in the `compute_params` function.
#     - Potential for resource contention: possible if multiple processes attempt simultaneous disk writes or read shared input files.
#     """
#     with concurrent.futures.ProcessPoolExecutor(max_workers=20) as executor:
#         for param in parameters:
#             executor.submit(compute_params, input_prefix, param)

# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def crop_coord(input_file, output_file, upper_left, lower_right):
    """
    Crop a raster file to a specific region using upper-left and lower-right coordinates.
    --------------------------------------------------------------------------------------

    This function uses the GDAL library to crop a raster file based on specified coordinates.

    Required Parameters
    -------------------
    input_file : str
        Path to the input raster file intended for cropping.
    output_file : str
        Destination path where the cropped raster file will be saved.
    upper_left : tuple of float
        (x, y) coordinates specifying the upper-left corner of the cropping window.
        Must be in the same projection as the input raster.
    lower_right : tuple of float
        (x, y) coordinates specifying the lower-right corner of the cropping window.
        Must be in the same projection as the input raster.

    Outputs
    -------
    None
        Generates a cropped raster file saved at the designated `output_file` location.

    Notes
    -----
    - The `upper_left` and `lower_right` coordinates define the bounding box for cropping.
    - Employs GDAL's Translate method with specific creation options for cropping.
    - For shapefiles, ensure they are unzipped. Using zipped files can lead to GDAL errors.

    Error states
    ------------
    - GDAL might raise an error if provided coordinates fall outside the input raster's bounds.
    """

    # upper_left = (x, y), lower_right = (x, y)
    # Coordinates must be in the same projection as the raster
    window = upper_left + lower_right
    translate_options = gdal.TranslateOptions(
        projWin=window, creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=YES"]
    )  # ,callback=gdal.TermProgress_nocb)
    gdal.Translate(output_file, input_file, options=translate_options)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def crop_into_tiles(mosaic, out_folder, n_tiles, buffer=10):
    """
    Splits a mosaic image into smaller, equally-sized tiles and saves them to a specified folder.
    ----------------------------------------------------------------------------------------------

    The function divides the mosaic into a specified number of tiles (n_tiles), taking care
    to adjust the dimensions of edge tiles and add a buffer to each tile.

    Required Parameters
    --------------------
        mosaic : str
            The file path of the mosaic image.
        out_folder : str
            The directory path where the tile images will be saved.
        n_tiles : int
            The total number of tiles to produce. Must be a perfect square number.

    Optional Parameters
    --------------------
        buffer : int
            Specifies the size of the buffer region between tiles in pixels. Default is 10.

    Returns:
    ---------
        None: Tiles are saved to the specified directory and no value is returned.

    Notes
    ------
        - The function will automatically create a buffer of overlapping pixels that is included in the borders between two tiles. This is customizable with the "buffer" kwarg.
    """
    n_tiles = math.sqrt(n_tiles)

    ds = gdal.Open(mosaic, 0)
    cols = ds.RasterXSize
    rows = ds.RasterYSize
    x_win_size = int(math.ceil(cols / n_tiles))
    y_win_size = int(math.ceil(rows / n_tiles))

    tile_count = 0

    for i in range(0, rows, y_win_size):
        if i + y_win_size < rows:
            nrows = y_win_size
        else:
            nrows = rows - i

        for j in range(0, cols, x_win_size):
            if j + x_win_size < cols:
                ncols = x_win_size
            else:
                ncols = cols - j

            tile_file = out_folder + "/tile_" + "{0:04d}".format(tile_count) + ".tif"
            win = [j, i, ncols, nrows]

            # Upper left corner
            win[0] = max(0, win[0] - buffer)
            win[1] = max(0, win[1] - buffer)

            w = win[2] + 2 * buffer
            win[2] = w if win[0] + w < cols else cols - win[0]

            h = win[3] + 2 * buffer
            win[3] = h if win[1] + h < rows else rows - win[1]

            crop_pixels(mosaic, tile_file, win)
            tile_count += 1


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def crop_region(input_file, shp_file, output_file):
    """
    Crop a raster file based on a region defined by a shapefile.
    ------------------------------------------------------------------

    This function uses the GDAL library to crop a raster file according to the boundaries
    specified in a shapefile.

    Required Parameters
    -------------------
    input_file : str
        Path to the input raster file intended for cropping.
    shp_file : str
        Path to the shapefile that outlines the cropping region.
    output_file : str
        Destination path where the cropped raster file will be saved.

    Outputs
    -------
    None
        Produces a cropped raster file at the designated `output_file` location using boundaries
        from the `shp_file`.

    Notes
    -----
    - Utilizes GDAL's Warp method, setting the `cutlineDSName` option and enabling `cropToCutline`
      for shapefile-based cropping.

    Error states
    ------------
    - GDAL may generate an error if the shapefile's boundaries exceed the input raster's limits.
    - GDAL can also report errors if the provided shapefile is invalid or devoid of geometries.
    """
    warp_options = gdal.WarpOptions(
        cutlineDSName=shp_file,
        cropToCutline=True,
        creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=YES"],
    )  # ,callback=gdal.TermProgress_nocb)
    warp = gdal.Warp(output_file, input_file, options=warp_options)
    warp = None


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def crop_to_valid_data(input_file, output_file, block_size=512):
    """
    Crops a border region of NaN values from a GeoTIFF file.
    -----------------------------------------------------------

    Using a blocking method, the function will scan through the GeoTIFF file to determine the extent of valid data in order to crop of excess border NaN values.

    Required Parameters
    --------------------
        input_file : str
            Path to the input GeoTIFF file.
        output_file : str
            Desired path for the output cropped GeoTIFF file.

    Optional Parameters
    --------------------
        block_size : int
            Specifies the size of blocks used in computing the extent. Default is 512. This means that a max 512x512 pixel area will be loaded into memory at any time.

    Returns:
    ---------
        None: Saves a cropped GeoTIFF file to the specified output path.

    Notes
    ------
        - block_size is used to minimize RAM usage with a blocking technique. Adjust to fit your performance needs.
    """
    src_ds = gdal.Open(input_file, gdal.GA_ReadOnly)
    src_band = src_ds.GetRasterBand(1)

    no_data_value = src_band.GetNoDataValue()

    gt = src_ds.GetGeoTransform()

    # Initialize bounding box variables to None
    x_min, x_max, y_min, y_max = None, None, None, None

    for i in range(0, src_band.YSize, block_size):
        # Calculate block height to handle boundary conditions
        if i + block_size < src_band.YSize:
            actual_block_height = block_size
        else:
            actual_block_height = src_band.YSize - i

        for j in range(0, src_band.XSize, block_size):
            # Calculate block width to handle boundary conditions
            if j + block_size < src_band.XSize:
                actual_block_width = block_size
            else:
                actual_block_width = src_band.XSize - j

            block_data = src_band.ReadAsArray(
                j, i, actual_block_width, actual_block_height
            )

            rows, cols = np.where(block_data != no_data_value)

            if rows.size > 0 and cols.size > 0:
                if x_min is None or j + cols.min() < x_min:
                    x_min = j + cols.min()
                if x_max is None or j + cols.max() > x_max:
                    x_max = j + cols.max()
                if y_min is None or i + rows.min() < y_min:
                    y_min = i + rows.min()
                if y_max is None or i + rows.max() > y_max:
                    y_max = i + rows.max()

    # Convert pixel coordinates to georeferenced coordinates
    min_x = gt[0] + x_min * gt[1]
    max_x = gt[0] + (x_max + 1) * gt[1]
    min_y = gt[3] + (y_max + 1) * gt[5]
    max_y = gt[3] + y_min * gt[5]

    out_ds = gdal.Translate(
        output_file,
        src_ds,
        projWin=[min_x, max_y, max_x, min_y],
        projWinSRS="EPSG:4326",
    )

    out_ds = None
    src_ds = None


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def crop_pixels(input_file, output_file, window):
    """
    Crop a raster file to a specific region using provided pixel window.
    ---------------------------------------------------------------------

    This function uses the GDAL library to perform the cropping operation based on pixel coordinates
    rather than geospatial coordinates.

    Required Parameters
    -------------------
    input_file : str
        String representing the path to the input raster file to be cropped.
    output_file : str
        String representing the path where the cropped raster file should be saved.
    window : list or tuple
        List or tuple specifying the window to crop by in the format [left_x, top_y, width, height].
        Here, left_x and top_y are the pixel coordinates of the upper-left corner of the cropping window,
        while width and height specify the dimensions of the cropping window in pixels.

    Outputs
    -------
    None
        A cropped raster file saved at the specified output_file path.

    Notes
    -----
    - The function uses GDAL's Translate method with the `srcWin` option to perform the pixel-based cropping.
    - Must ensure that GDAL is properly installed to utilize this function.

    Error States
    ------------
    - If the specified pixel window is outside the bounds of the input raster, an error might be raised by GDAL.
    """

    # Window to crop by [left_x, top_y, width, height]
    translate_options = gdal.TranslateOptions(
        srcWin=window, creationOptions=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=YES"]
    )  # ,callback=gdal.TermProgress_nocb)
    gdal.Translate(output_file, input_file, options=translate_options)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def download_file(url, folder, pbar):
    """
    Download a single file given its URL and store it in a specified path.
    -----------------------------------------------------------------------

    This is a utility function that facilitates the downloading of files, especially within iterative download operations.

    Required Parameters
    -------------------
    url : str
        String containing the URL of the file intended for downloading.
    folder : str
        String specifying the path where the downloaded file will be stored.
    pbar : tqdm object
        Reference to the tqdm progress bar, typically used in a parent function to indicate download progress.

    Outputs
    -------
    int
        Returns an integer representing the number of bytes downloaded.
    None
        Creates a file in the designated 'folder' upon successful download.

    Notes
    -----
    - This function is meant to be used inside of `download_files()`. If you use it outside of that, YMMV.
    - If the file already exists in the specified folder, no download occurs, and the function returns 0.
    - Utilizes the requests library for file retrieval and tqdm for progress visualization.
    """
    local_filename = os.path.join(folder, url.split("/")[-1])
    if os.path.exists(local_filename):
        return 0

    response = requests.get(url, stream=True)
    downloaded_size = 0
    with open(local_filename, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
            downloaded_size += len(chunk)
            pbar.update(len(chunk))
    return downloaded_size


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def download_files(input, folder="./"):
    """
    Download one or multiple files from provided URLs.
    ---------------------------------------------------

    This function allows for the simultaneous downloading of files using threading, and showcases download progress via a tqdm progress bar.

    Required Parameters
    -------------------
    input : str or list of str
        Can either be:
        1. A string specifying the path to a .txt file. This file should contain URLs separated by newlines.
        2. A list of strings where each string is a URL.

    Optional Parameters
    -------------------
    folder : str
        String denoting the directory where the downloaded files will be stored. Default is the current directory.

    Outputs
    -------
    None
        Downloads files and stores them in the specified 'folder'.

    Notes
    -----
    - The function uses `ThreadPoolExecutor` from the `concurrent.futures` library to achieve multi-threaded downloads for efficiency.
    - The tqdm progress bar displays the download progress.
    - If the 'input' argument is a string, it's assumed to be the path to a .txt file containing URLs.
    - Will not download files if the file already exists, but the progress bar will not reflect it.
    """
    if isinstance(input, str):
        with open(input, "r", encoding="utf8") as dsvfile:
            urls = [url.strip().replace("'$", "") for url in dsvfile.readlines()]
    else:
        urls = input
    print(input)
    total_size = sum(get_file_size(url.strip()) for url in urls)
    downloaded_size = 0

    with tqdm(
        total=total_size,
        unit="B",
        unit_scale=True,
        ncols=1000,
        desc="Downloading",
        colour="green",
    ) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(download_file, url, folder, pbar) for url in urls
            ]
            for future in concurrent.futures.as_completed(futures):
                size = future.result()
                downloaded_size += size


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def extract_raster(csv_file, raster_file, band_names):
    """
    Extract raster values corresponding to the coordinates specified in the CSV file.
    --------------------------------------------------------------------------------------------

    This function reads the x and y coordinates from a CSV file and extracts the raster values
    corresponding to those coordinates. The extracted values are added to the CSV file as new columns.

    Required Parameters
    -------------------
    csv_file : str
        String representing the path to the CSV file containing 'x' and 'y' columns with coordinates.
    raster_file : str
        String representing the path to the raster file to extract values from.
    band_names : list of str
        List of strings specifying the column names for each band's extracted values.

    Outputs
    -------
    None
        Modifies the provided CSV file to include new columns with extracted raster values based on band_names.

    Notes
    -----
    - The CSV file must contain columns named 'x' and 'y' specifying the coordinates.
    - The order of band_names should correspond to the order of bands in the raster_file.
    - Ensure that GDAL and pandas are properly installed to utilize this function.

    Error States
    ------------
    - If the CSV file does not have 'x' and 'y' columns, a KeyError will occur.
    - If the specified coordinates in the CSV file are outside the bounds of the raster, incorrect or no values may be extracted.
    """
    # Extract values from raster corresponding to
    df = pd.read_csv(csv_file)

    ds = gdal.Open(raster_file, 0)
    gt = ds.GetGeoTransform()

    n_bands = ds.RasterCount
    bands = np.zeros((df.shape[0], n_bands))

    for i in range(df.shape[0]):
        px = int((df["x"][i] - gt[0]) / gt[1])
        py = int((df["y"][i] - gt[3]) / gt[5])

        for j in range(n_bands):
            band = ds.GetRasterBand(j + 1)
            val = band.ReadAsArray(px, py, 1, 1)
            bands[i, j] = val[0]
    ds = None

    for j in range(n_bands):
        df[band_names[j]] = bands[:, j]

    df.to_csv(csv_file, index=None)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def fetch_dem(
    bbox={"xmin": -84.0387, "ymin": 35.86, "xmax": -83.815, "ymax": 36.04},
    dataset="National Elevation Dataset (NED) 1/3 arc-second Current",
    prod_format="GeoTIFF",
    download=False,
    txtPath="download_urls.txt",
    saveToTxt=True,
    downloadFolder="./",
    shapeFile=None,
):
    """
    Queries the USGS API for DEM data given specified parameters and optionally extracts download URLs.
    ----------------------------------------------------------------------------------------------------

    The function targets the USGS National Map API, fetching Digital Elevation Model (DEM) data based on provided parameters. It can automatically download these files or save their URLs to a .txt file.

    Optional Parameters
    -------------------
    bbox : dict
        Dictionary containing bounding box coordinates to query. Consists of xmin, ymin, xmax, ymax. Default is {"xmin": -84.0387, "ymin": 35.86, "xmax": -83.815, "ymax": 36.04}.
    dataset : str
        Specifies the USGS dataset to target. Default is "National Elevation Dataset (NED) 1/3 arc-second Current".
    prod_format : str
        Desired file format for the downloads. Default is "GeoTIFF".
    download : bool
        If set to True, triggers automatic file downloads. Default is False.
    txtPath : str
        Designated path to save the .txt file containing URLs. Default is "download_urls.txt".
    saveToTxt : bool
        Flag to determine if URLs should be saved to a .txt file. Default is True.
    downloadFolder : str
        Destination folder for downloads (used if `download` is True). Default is the current directory.
    shapeFile : str
        Path to a shapefile with which a bounding box will be generated. Overrides the 'bbox' parameter if set.

    Outputs
    -------
    None
        Depending on configurations, either saves URLs to a .txt file or initiates downloads using the `download_files` function.

    Notes
    -----
    - If both `bbox` and `shapefile` are provided, `bbox` will take precedence.
    - Uses the USGS National Map API for data fetching. Ensure the chosen dataset and product format are valid.
    """
    if shapeFile is not None:
        coords = get_extent(shapeFile)
        bbox["xmin"] = coords[0][0]
        bbox["ymax"] = coords[0][1]
        bbox["xmax"] = coords[1][0]
        bbox["ymin"] = coords[1][1]

    base_url = "https://tnmaccess.nationalmap.gov/api/v1/products"

    # Construct the query parameters
    params = {
        "bbox": f"{bbox['xmin']},{bbox['ymin']},{bbox['xmax']},{bbox['ymax']}",
        "datasets": dataset,
        "prodFormats": prod_format,
    }

    # Make a GET request
    response = requests.get(base_url, params=params)

    # Check for a successful request
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data. Status code: {response.status_code}")

    # Convert JSON response to Python dict
    data = response.json()

    # Extract download URLs
    download_urls = [item["downloadURL"] for item in data["items"]]

    if saveToTxt is True:
        with open(txtPath, "w") as file:
            for url in download_urls:
                file.write(f"{url}\n")

    if download is True:
        download_files(download_urls, folder=downloadFolder)


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def generate_img(
    tif,
    cmap="inferno",
    dpi=150,
    downsample=1,
    verbose=False,
    clean=False,
    title=None,
    nancolor="green",
    ztype="Z",
    zunit=None,
    xyunit=None,
    reproject_gcs=False,
    shp_files=None,
    crop_shp=False,
    bordercolor="black",
    borderlinewidth=1.5,
    saveDir=None,
):
    """
    Plot a GeoTIFF image using matplotlib.
    --------------------------------------

    This function is a powerful plotting tool for GEOTiff files that uses GDAL, OSR, numpy, matplotlib, and geopandas.
    We have tried to create a simple interface for the end user where you can input a tif file and an informational image will be generated.
    If the default image is not suited for your needs or if any of the information is incorrect, there are a series of keyword arguments that allow for user customizability.

    Several major features that are not enabled by default include:

    - Automatic PCS to GCS conversion using the ``reproject_gcs`` flag.
    - Automated cropping with a shapefile using the ``shp_file`` parameter in addition to the ``crop_shp``.
    - Downsampling in order to reduce computation time using the ``downsample`` flag.
    - A verbose mode that will print additional spatial information about the geotiff file using the ``verbose`` flag.
    - A clean mode that will print an image of the geotiff with no other information using the ``clean`` flag.

    Required Parameters
    --------------------
    tif : str
        Path to the GeoTIFF file.

    Optional Parameters
    -------------------
    cmap : str
        Colormap used for visualization. Default is 'inferno'.
    dpi : int
        Resolution in dots per inch for the figure. Default is 150.
    downsample : int
        Factor to downsample the image by. Default is 10.
    verbose : bool
        If True, print geotransform and spatial reference details. Default is False.
    clean : bool
        If True, no extra data will be shown besides the plot image. Default is False.
    title : str
        Title for the plot. Default will display the projection name.
    nancolor : str
        Color to use for NaN values. Default is 'green'.
    ztype : str
        Data that is represented by the z-axis. Default is 'Z'.
    zunit : str
        Units for the data values (z-axis). Default is None and inferred from spatial reference.
    xyunit : str
        Units for the x and y axes. Default is None and inferred from spatial reference.
    reproject_gcs : bool
        Reproject a given raster from a projected coordinate system (PCS) into a geographic coordinate system (GCS).
    shp_file : str
        Path to the shapefile used for cropping. Default is None.
    crop_shp : bool
        Flag to indicate if the shapefile should be used for cropping. Default is False.
    bordercolor : str
        Color for the shapefile boundary. Default is "black".
    borderlinewidth : float
        Line width for the shapefile boundary. Default is 1.5.

    Returns
    -------
    raster_array: np.ndarray
        Returns the raster array that was used for visualization.

    Notes
    -----
    - Alternative colormaps can be found in the `matplotlib documentation <https://matplotlib.org/stable/users/explain/colors/colormaps.html>`_.
    - Shapemap cannot be in a .zip form. GDAL will throw an error if you use a .zip. We recommend using .shp. It can also cause issues if you don't have the accompanying files with the .shp file. (.dbf, .prj, .shx).
    - Must be used with Jupyter Notebooks to display results properly. Will Implement a feature to save output to dir eventually.
    - Using ``shp_file`` without setting ``crop_shp`` will allow you to plot the outline of the shapefile without actually cropping anything.
    """

    # Initial setup
    tif_dir_changed = False

    # Reproject raster into geographic coordinate system if needed
    if reproject_gcs:
        print("Reprojecting..")
        base_dir = os.path.dirname(tif)
        new_path = os.path.join(base_dir, "vis.tif")
        reproject(tif, new_path, "EPSG:4326")
        if crop_shp is False:
            new_path_crop = os.path.join(base_dir, "vis_trim_crop.tif")
            print("Cropping NaN values...")
            crop_to_valid_data(new_path, new_path_crop)
            print("Done.")
            os.remove(new_path)
            tif = new_path_crop
        else:
            tif = new_path
        tif_dir_changed = True

    # Crop using shapefiles if needed
    if crop_shp and shp_files:
        # Check if the list is not empty
        if not shp_files:
            print("Shapefile list is empty. Skipping shapefile cropping.")
        else:
            # Read each shapefile, clean any invalid geometries, and union them
            gdfs = [gpd.read_file(shp_file).buffer(0) for shp_file in shp_files]
            combined_geom = gdfs[0].unary_union
            for gdf in gdfs[1:]:
                combined_geom = combined_geom.union(gdf.unary_union)

            combined_gdf = gpd.GeoDataFrame(geometry=[combined_geom], crs=gdfs[0].crs)

            # Save the combined shapefile temporarily for cropping
            temp_combined_shp = os.path.join(os.path.dirname(tif), "temp_combined.shp")
            combined_gdf.to_file(temp_combined_shp)

            print("Cropping with combined shapefiles...")
            base_dir = os.path.dirname(tif)
            new_path = os.path.join(base_dir, "crop.tif")
            crop_region(tif, temp_combined_shp, new_path)
            if tif_dir_changed:
                os.remove(tif)
            tif = new_path
            tif_dir_changed = True
            print("Done.")

            # Remove the temporary combined shapefile
            os.remove(temp_combined_shp)

    print("Reading in tif for visualization...")
    dataset = gdal.Open(tif)
    band = dataset.GetRasterBand(1)

    geotransform = dataset.GetGeoTransform()
    spatial_ref = osr.SpatialReference(wkt=dataset.GetProjection())

    # Extract spatial information about raster
    proj_name = spatial_ref.GetAttrValue("PROJECTION")
    proj_name = proj_name if proj_name else "GCS, No Projection"
    data_unit = zunit or spatial_ref.GetLinearUnitsName()
    coord_unit = xyunit or spatial_ref.GetAngularUnitsName()
    z_type = ztype if band.GetDescription() == "" else band.GetDescription()

    if verbose:
        print(
            f"Geotransform:\n{geotransform}\n\nSpatial Reference:\n{spatial_ref}\n\nDocumentation on spatial reference format: https://docs.ogc.org/is/18-010r11/18-010r11.pdf\n"
        )

    raster_array = gdal.Warp(
        "",
        tif,
        format="MEM",
        width=int(dataset.RasterXSize / downsample),
        height=int(dataset.RasterYSize / downsample),
    ).ReadAsArray()

    # Mask nodata values
    raster_array = np.ma.array(
        raster_array, mask=np.equal(raster_array, band.GetNoDataValue())
    )

    print("Done.\nPlotting data...")

    # Set up plotting environment
    cmap_instance = plt.get_cmap(cmap)
    cmap_instance.set_bad(color=nancolor)

    # Determine extent
    ulx, xres, _, uly, _, yres = geotransform
    lrx = ulx + (dataset.RasterXSize * xres)
    lry = uly + (dataset.RasterYSize * yres)

    # Plot
    fig, ax = plt.subplots(dpi=dpi)
    sm = ax.imshow(
        raster_array,
        cmap=cmap_instance,
        vmin=np.nanmin(raster_array),
        vmax=np.nanmax(raster_array),
        extent=[ulx, lrx, lry, uly],
    )
    if clean:
        ax.axis("off")
    else:
        # Adjust colorbar and title
        cbar = fig.colorbar(
            sm, fraction=0.046 * raster_array.shape[0] / raster_array.shape[1], pad=0.04
        )
        cbar_ticks = np.linspace(np.nanmin(raster_array), np.nanmax(raster_array), 8)
        cbar.set_ticks(cbar_ticks)
        cbar.set_label(f"{z_type} ({data_unit}s)")

        ax.set_title(
            title if title else f"Visualization of GEOTiff data using {proj_name}.",
            fontweight="bold",
        )
        ax.tick_params(
            axis="both",
            which="both",
            bottom=True,
            top=False,
            left=True,
            right=False,
            color="black",
            length=5,
            width=1,
        )

        ax.set_title(
            title or f"Visualization of GEOTiff data using {proj_name}.",
            fontweight="bold",
        )

    # Set up the ticks for x and y axis
    x_ticks = np.linspace(ulx, lrx, 5)
    y_ticks = np.linspace(lry, uly, 5)

    # Format the tick labels to two decimal places
    x_tick_labels = [f"{tick:.2f}" for tick in x_ticks]
    y_tick_labels = [f"{tick:.2f}" for tick in y_ticks]

    ax.set_xticks(x_ticks)
    ax.set_yticks(y_ticks)
    ax.set_xticklabels(x_tick_labels)
    ax.set_yticklabels(y_tick_labels)

    # Determine x and y labels based on whether data is lat-long or projected
    y_label = (
        f"Latitude ({coord_unit}s)"
        if spatial_ref.EPSGTreatsAsLatLong()
        else f"Northing ({coord_unit}s)"
    )
    x_label = (
        f"Longitude ({coord_unit}s)"
        if spatial_ref.EPSGTreatsAsLatLong()
        else f"Easting ({coord_unit}s)"
    )
    ax.set_ylabel(y_label)
    ax.set_xlabel(x_label)

    # ax.ticklabel_format(style='plain', axis='both')  # Prevent scientific notation on tick labels
    ax.set_aspect("equal")

    if shp_files:
        for shp_file in shp_files:
            overlay = gpd.read_file(shp_file)
            overlay.boundary.plot(color=bordercolor, linewidth=borderlinewidth, ax=ax)

    print("Done. (image should appear soon...)")

    if saveDir is not None:
        fig.savefig(saveDir)

    if tif_dir_changed:
        os.remove(tif)

    return raster_array


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def get_extent(shp_file):
    """
    Get the bounding box (extent) of a shapefile.
    ----------------------------------------------

    This function extracts the extent or bounding box of a shapefile. The extent is returned as
    the upper left and lower right coordinates.

    Required Parameters
    -------------------
    shp_file : str
        String representing the path to the shapefile.

    Outputs
    -------
    tuple of tuple
        Returns two tuples, the first representing the upper left (x, y) coordinate and the second
        representing the lower right (x, y) coordinate.

    Notes
    -----
    - Ensure that OGR is properly installed to utilize this function.

    Error States
    ------------
    - If the provided file is not a valid shapefile or cannot be read, OGR may raise an error.
    """
    ds = ogr.Open(shp_file)
    layer = ds.GetLayer()
    ext = layer.GetExtent()
    upper_left = (ext[0], ext[3])
    lower_right = (ext[1], ext[2])

    return upper_left, lower_right


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def get_file_size(url):
    """
    Retrieve the size of a file at a given URL in bytes.
    ----------------------------------------------------

    This function sends a HEAD request to the provided URL and reads the 'Content-Length' header to determine the size of the file.
    It's primarily designed to support the `download_files` function to calculate download sizes beforehand.

    Required Parameters
    -------------------
    url : str
        String representing the URL from which the file size needs to be determined.

    Outputs
    -------
    int
        Size of the file at the specified URL in bytes. Returns 0 if the size cannot be determined.

    Notes
    -----
    - This function relies on the server's response headers to determine the file size.
    - If the server doesn't provide a 'Content-Length' header or there's an error in the request, the function will return 0.
    - This function's primary use is with `download_files()`.
    """
    try:
        response = requests.head(url)
        return int(response.headers.get("Content-Length", 0))
    except:
        return 0


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def reproject(input_file, output_file, projection):
    """
    Reproject a geospatial raster dataset (GeoTIFF) using the GDAL library.
    -------------------------------------------------------------------------

    This function reprojects a given GeoTIFF raster dataset from its original coordinate system to a new specified projection. The result is saved as a new raster file. The projection can be provided in multiple formats, including standard EPSG codes or WKT format.

    Required Parameters
    -------------------
    input_file : str
        String representing the file location of the GeoTIFF to be reprojected.
    output_file : str
        String representing the desired location and filename for the output reprojected raster.
    projection : str
        String indicating the desired target projection. This can be a standard GDAL format code (e.g., EPSG:4326) or the path to a .wkt file.

    Outputs
    -------
    None
        Generates a reprojected GeoTIFF file at the specified 'output_file' location.

    Notes
    -----
    - The function supports multi-threading for improved performance on multi-core machines.
    - The source raster data remains unchanged; only a new reprojected output file is generated.
    """
    # Projection can be EPSG:4326, .... or the path to a wkt file
    warp_options = gdal.WarpOptions(
        dstSRS=projection,
        creationOptions=[
            "COMPRESS=LZW",
            "TILED=YES",
            "BIGTIFF=YES",
            "NUM_THREADS=ALL_CPUS",
        ],
        multithread=True,
        warpOptions=["NUM_THREADS=ALL_CPUS"],
    )  # ,callback=gdal.TermProgress_nocb)
    warp = gdal.Warp(output_file, input_file, options=warp_options)
    warp = None  # Closes the files


# ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------


def tif2csv(raster_file, band_names=["elevation"], output_file="params.csv"):
    """
    Convert raster values from a TIF file into CSV format.
    ------------------------------------------------------

    This function reads raster values from a specified raster TIF file and exports them into a CSV format.
    The resulting CSV file will contain columns representing the x and y coordinates, followed by columns
    for each band of data in the raster.

    Required Parameters
    -------------------
    raster_file : str
        Path to the input raster TIF file to be converted.

    Optional Parameters
    -------------------
    band_names : list
        Names for each band in the raster. The order should correspond to the bands in the raster file.
        Default is ['elevation'].
    output_file : str
        Path where the resultant CSV file will be saved. Default is 'params.csv'.

    Outputs
    -------
    None
        The function will generate a CSV file saved at the specified `output_file` path, containing the raster values
        and their corresponding x and y coordinates.

    Notes
    -----
    - The x and y coordinates in the output CSV correspond to the center of each pixel.
    - NaN values in the CSV indicate that there's no data or missing values for a particular pixel.

    Error States
    ------------
    - If the provided raster file is not present, invalid, or cannot be read, GDAL may raise an error.
    - If the number of provided `band_names` does not match the number of bands in the raster, the resulting CSV
      might contain columns without headers or may be missing some data.
    """
    ds = gdal.Open(raster_file, 0)
    xmin, res, _, ymax, _, _ = ds.GetGeoTransform()
    xsize = ds.RasterXSize
    ysize = ds.RasterYSize
    xstart = xmin + res / 2
    ystart = ymax - res / 2

    x = np.arange(xstart, xstart + xsize * res, res)
    y = np.arange(ystart, ystart - ysize * res, -res)
    x = np.tile(x[:xsize], ysize)
    y = np.repeat(y[:ysize], xsize)

    n_bands = ds.RasterCount
    bands = np.zeros((x.shape[0], n_bands))
    for k in range(1, n_bands + 1):
        band = ds.GetRasterBand(k)
        data = band.ReadAsArray()
        data = np.ma.array(data, mask=np.equal(data, band.GetNoDataValue()))
        data = data.filled(np.nan)
        bands[:, k - 1] = data.flatten()

    column_names = ["x", "y"] + band_names
    stack = np.column_stack((x, y, bands))
    df = pd.DataFrame(stack, columns=column_names)
    df.dropna(inplace=True)
    df.to_csv(output_file, index=None)
