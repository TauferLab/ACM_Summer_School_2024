PORT=8989
git clone --single-branch -b test_region_extraction https://github.com/sci-visus/openvisuspy.git
cd openvisuspy
git checkout b2c63396ea3c7f2ab32efa3bbe464dd2918543d6
python -m venv .venv
source .venv/bin/activate
python -m pip install --verbose --no-cache --no-warn-script-location boto3 colorcet fsspec numpy imageio pympler==1.0.1 urllib3 pillow xarray xmltodict  plotly requests scikit-image scipy seaborn tifffile pandas tqdm matplotlib  zarr altair cartopy dash fastparquet folium geodatasets geopandas geoviews lxml numexpr scikit-learn sqlalchemy statsmodels vega_datasets xlrd yfinance pyarrow pydeck h5py hdf5plugin netcdf4 nexpy nexusformat nbgitpuller intake ipysheet ipywidgets bokeh ipywidgets-bokeh panel holoviews hvplot datashader vtk pyvista trame trame-vtk trame-vuetify notebook "jupyterlab==3.6.6" jupyter_bokeh jupyter-server-proxy  jupyterlab-system-monitor "pyviz_comms>=2.0.0,<3.0.0" "jupyterlab-pygments>=0.2.0,<0.3.0" 
python -m pip install OpenVisus
export VISUS_CACHE="/tmp/visus-cache/nasa3"
export BOKEH_ALLOW_WS_ORIGIN="*"
export BOKEH_RESOURCES="cdn"
export PYTHONPATH=$PWD/src

panel serve ./src/openvisuspy/dashboards   --allow-websocket-origin='*' --address=0.0.0.0 --port $PORT --args config.json
