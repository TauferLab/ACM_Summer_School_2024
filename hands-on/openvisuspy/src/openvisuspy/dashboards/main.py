import os, sys
import argparse,json
import panel as pn
import logging
import base64,json
sys.path.append('/app/openvisuspy/src')
from openvisuspy import SetupLogger, Slice, ProbeTool, GetQueryParams

# //////////////////////////////////////////////////////////////////////////////////////
if __name__.startswith('bokeh'):

	# https://github.com/holoviz/panel/issues/3404
	# https://panel.holoviz.org/api/config.html
	pn.extension(
		"ipywidgets",
		"floatpanel",
		log_level ="DEBUG",
		notifications=True, 
		sizing_mode="stretch_width",
		# template="fast",
		#theme="default",
	)

	log_filename=os.environ.get("OPENVISUSPY_DASHBOARDS_LOG_FILENAME","/tmp/openvisuspy-dashboards.log")
	logger=SetupLogger(log_filename=log_filename,logging_level=logging.DEBUG)

	
	slice = Slice()
	slice.load(sys.argv[1])
	
	query_params=GetQueryParams()
	if "load" in query_params:
		body=json.loads(base64.b64decode(query_params['load']).decode("utf-8"))
		slice.setSceneBody(body)
	elif "dataset" in query_params:
		scene_name=query_params["dataset"]
		slice.scene.value=scene_name

	if False:
		app = ProbeTool(slice).getMainLayout()
	else:
		app = slice.getMainLayout()

	app.servable()

