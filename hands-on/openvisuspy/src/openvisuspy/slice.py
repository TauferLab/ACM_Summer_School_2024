
import os,sys,logging,copy,traceback,colorcet
import base64
import types
import logging
import copy
import traceback
import io 
import threading
import time
from urllib.parse import urlparse, urlencode

import numpy as np


import bokeh
import bokeh.models
import bokeh.events
import bokeh.plotting
import bokeh.models.callbacks
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, ColorBar, LinearColorMapper
from bokeh.transform import transform

import param 

import panel as pn
from panel.layout import FloatPanel
from panel import Column,Row,GridBox,Card
from panel.pane import HTML,JSON,Bokeh

from .utils   import *
from .backend import Aborted,LoadDataset,ExecuteBoxQuery,QueryNode


logger = logging.getLogger(__name__)

SLICE_ID=0
EPSILON = 0.001

DEFAULT_SHOW_OPTIONS={
	"top": [
		["open_button","save_button","info_button","copy_url_button",  "scene", "timestep", "timestep_delta", "palette",  "color_mapper_type", "resolution", "view_dependent", "num_refinements"],
		["field","direction", "offset", "range_mode", "range_min",  "range_max"]
	],
	"bottom": [
		["request","response"]
	]
}

class ViewportUpdate: 
	pass

# ////////////////////////////////////////////////////////////////////////////////////
class Canvas:
  
	# constructor
	def __init__(self, id):
		self.id=id
		self.fig=None
		self.pdim=2

		# events
		self.events={
			bokeh.events.Tap: [],
			bokeh.events.DoubleTap: [],
			bokeh.events.SelectionGeometry: [],
			ViewportUpdate: []
		}

		self.fig_layout=Row(sizing_mode="stretch_both")	
		self.createFigure() 

		# since I cannot track consistently inner_width,inner_height (particularly on Jupyter) I am using a timer
		self.last_W=0
		self.last_H=0
		self.last_viewport=None
		self.setViewport([0,0,256,256])
		
	# onIdle
	def onIdle(self):
		
		# I need to wait until I get a decent size
		W,H=self.getWidth(),self.getHeight()
		if W==0 or H==0:  
			return

		# some zoom in/out or panning happened (handled by bokeh) 
		# note: no need to fix the aspect ratio in this case
		x=self.fig.x_range.start
		w=self.fig.x_range.end-x

		y=self.fig.y_range.start
		h=self.fig.y_range.end-y

		# nothing todo
		if [x,y,w,h]==self.last_viewport and [self.last_W,self.last_H]==[W,H]:
			return

		# I need to fix the aspect ratio 
		if self.pdim==2 and [self.last_W,self.last_H]!=[W,H]:
			x+=0.5*w
			y+=0.5*h
			if (w/W) > (h/H): 
				h=w*(H/W) 
			else: 
				w=h*(W/H)
			x-=0.5*w
			y-=0.5*h

		self.last_W=W
		self.last_H=H
		self.last_viewport=[x,y,w,h]

		if not all([
			self.fig.x_range.start==x, self.fig.x_range.end==x+w,
			self.fig.y_range.start==y, self.fig.y_range.end==y+h
		]):
			self.fig.x_range.start, self.fig.x_range.end = x,x+w
			self.fig.y_range.start, self.fig.y_range.end = y,y+h

		[fn(None) for fn in self.events[ViewportUpdate]]

	# on_event
	def on_event(self, evt, callback):
		self.events[evt].append(callback)

	# createFigure
	def createFigure(self):
		old=self.fig

		self.pan_tool               = bokeh.models.PanTool()
		self.wheel_zoom_tool        = bokeh.models.WheelZoomTool()
		self.box_select_tool        = bokeh.models.BoxSelectTool()
		self.box_select_tool_helper = bokeh.models.TextInput()

		self.fig=bokeh.plotting.figure(tools=[self.pan_tool,self.wheel_zoom_tool,self.box_select_tool]) 
		self.fig.toolbar_location="right" 
		self.fig.toolbar.active_scroll = self.wheel_zoom_tool
		self.fig.toolbar.active_drag    = self.pan_tool
		self.fig.toolbar.active_inspect = None
		self.fig.toolbar.active_tap     = None

		# try to preserve the old status
		self.fig.x_range = bokeh.models.Range1d(0,512) if old is None else old.x_range
		self.fig.y_range = bokeh.models.Range1d(0,512) if old is None else old.y_range
		self.fig.sizing_mode = 'stretch_both'          if old is None else old.sizing_mode
		self.fig.yaxis.axis_label  = "Latitude"               if old is None else old.xaxis.axis_label
		self.fig.xaxis.axis_label  = "Longitude"               if old is None else old.yaxis.axis_label
		self.fig.on_event(bokeh.events.Tap      , lambda evt: [fn(evt) for fn in self.events[bokeh.events.Tap      ]])
		self.fig.on_event(bokeh.events.DoubleTap, lambda evt: [fn(evt) for fn in self.events[bokeh.events.DoubleTap]])

		# replace the figure from the fig_layout (so that later on I can replace it)
		self.fig_layout[:]=[]
		self.fig_layout.append(Bokeh(self.fig))
		
		self.enableSelection()

		self.last_renderer={}

	# enableSelection
	def enableSelection(self,use_python_events=False):
		if use_python_events:
			# python event DOES NOT work
			self.fig.on_event(bokeh.events.SelectionGeometry, lambda s: print("JHERE"))
		else:
			def handleSelectionGeometry(attr,old,new):
				j=json.loads(new)
				x,y=float(j["x0"]),float(j["y0"])
				w,h=float(j["x1"])-x,float(j["y1"])-y
				evt=types.SimpleNamespace()
				evt.new=[x,y,w,h]
				[fn(evt) for fn in self.events[bokeh.events.SelectionGeometry]]
				logger.info(f"HandleSeletionGeometry {evt}")

			self.box_select_tool_helper.on_change('value', handleSelectionGeometry)

			self.fig.js_on_event(bokeh.events.SelectionGeometry, bokeh.models.callbacks.CustomJS(
				args=dict(widget=self.box_select_tool_helper), 
				code="""
					console.log("Setting widget value for selection...");
					widget.value=JSON.stringify(cb_obj.geometry, undefined, 2);
					console.log("Setting widget value for selection DONE");
					"""
			))	

	# setAxisLabels
	def setAxisLabels(self,x,y):
		self.fig.xaxis.axis_label  = 'Longitude'
		self.fig.yaxis.axis_label  = 'Latitude'		

	# getWidth (this is number of pixels along X for the canvas)
	def getWidth(self):
		try:
			return self.fig.inner_width
		except:
			return 0

	# getHeight (this is number of pixels along Y  for the canvas)
	def getHeight(self):
		try:
			return self.fig.inner_height
		except:
			return 0

	# getViewport [(x1,x2),(y1,y2)]
	def getViewport(self):
		x=self.fig.x_range.start
		y=self.fig.y_range.start
		w=self.fig.x_range.end-x
		h=self.fig.y_range.end-y
		return [x,y,w,h]

	  # setViewport
	def setViewport(self,value):
		x,y,w,h=value
		self.last_W,self.last_H=0,0 # force a fix viewport
		self.fig.x_range.start, self.fig.x_range.end = x, x+w
		self.fig.y_range.start, self.fig.y_range.end = y, y+h
		# NOTE: the event will be fired inside onIdle

	# setImage
	def showData(self, data, viewport,color_bar=None):

		x,y,w,h=viewport

		# 1D signal
		if len(data.shape)==1:
			self.pdim=1
			self.wheel_zoom_tool.dimensions="width"
			vmin,vmax=np.min(data),np.max(data)
			self.fig.y_range.start=0.5*(vmin+vmax)-1.2*0.5*(vmax-vmin)
			self.fig.y_range.end  =0.5*(vmin+vmax)+1.2*0.5*(vmax-vmin)
			self.fig.renderers.clear()
			xs=np.arange(x,x+w,w/data.shape[0])
			ys=data
			self.fig.line(xs,ys)
			
		# 2d image (eventually multichannel)
		else:	
			assert(len(data.shape) in [2,3])
			self.pdim=2
			self.wheel_zoom_tool.dimensions="both"
			img=ConvertDataForRendering(data)
			dtype=img.dtype
			
			# compatible with last rendered image?
			if all([
				self.last_renderer.get("source",None) is not None,
				self.last_renderer.get("dtype",None)==dtype,
				self.last_renderer.get("color_bar",None)==color_bar
			]):
				self.last_renderer["source"].data={"image":[img], "Longitude":[x], "Latitude":[y], "dw":[w], "dh":[h]}
			else:
				self.createFigure()
				source = bokeh.models.ColumnDataSource(data={"image":[img], "Longitude":[x], "Latitude":[y], "dw":[w], "dh":[h]})
				if img.dtype==np.uint32:	
					self.fig.image_rgba("image", source=source, x="Longitude", y="Latitude", dw="dw", dh="dh") 
				else:
					self.fig.image("image", source=source, x="Longitude", y="Latitude", dw="dw", dh="dh", color_mapper=color_bar.color_mapper) 
				self.fig.add_layout(color_bar, 'right')
				self.last_renderer={
					"source": source,
					"dtype":img.dtype,
					"color_bar":color_bar
				}
    


# ////////////////////////////////////////////////////////////////////////////////////
class Slice(param.Parameterized):
	def __init__(self):
		super().__init__()  

		# whenever some new result is available
		self.render_id              = pn.widgets.IntSlider          (name="RenderId", value=0)
	
			# current scene as JSON
		self.scene_body             = pn.widgets.TextAreaInput(name='Current',sizing_mode="stretch_width",height=520,)
	
		# core query
		self.scene                  = pn.widgets.Select             (name="Scene", options=[], width=120)
		self.timestep               = pn.widgets.IntSlider          (name="Time", value=0, start=0, end=1, step=1, sizing_mode="stretch_width")
		self.timestep_delta         = pn.widgets.Select             (name="Speed", options=[1, 2, 4, 8, 1, 32, 64, 128], value=1, width=50)
		self.field                  = pn.widgets.Select             (name='Field', options=[], value='data', width=80)
		self.resolution             = pn.widgets.IntSlider          (name='Res', value=21, start=20, end=99,  sizing_mode="stretch_width")
		self.view_dependent         = pn.widgets.Select             (name="ViewDep",options={"Yes":True,"No":False}, value=True,width=80)
		self.num_refinements        = pn.widgets.IntSlider          (name='#Ref', value=0, start=0, end=4, width=80)
		self.direction              = pn.widgets.Select             (name='Direction', options={'X':0, 'Y':1, 'Z':2}, value=2, width=80)
		self.offset                 = pn.widgets.EditableFloatSlider(name="Offset", start=0.0, end=1024.0, step=1.0, value=0.0,  sizing_mode="stretch_width", format=bokeh.models.formatters.NumeralTickFormatter(format="0.01"))
		self.viewport               = pn.widgets.TextInput          (name="Viewport",value="")
	
		# palette thingy
		self.range_mode             = pn.widgets.Select             (name="Range", options=["metadata", "user", "dynamic", "dynamic-acc"], value="user", width=120)
		self.range_min              = pn.widgets.FloatInput         (name="Min", width=80,value=0)
		self.range_max              = pn.widgets.FloatInput         (name="Max", width=80,value=300)
	
		self.palette                = pn.widgets.ColorMap           (name="Palette", options=GetPalettes(), value_name=DEFAULT_PALETTE, ncols=5,  width=180)
		self.color_mapper_type      = pn.widgets.Select             (name="Mapper", options=["linear", "log", ],width=60)
		
		# play thingy
		self.play_button            = pn.widgets.Button             (name="Play", width=8)
		self.play_sec               = pn.widgets.Select             (name="Frame delay", options=["0.00", "0.01", "0.1", "0.2", "0.1", "1", "2"], value="0.01")
	
		# bottom status bar
		self.request                = pn.widgets.TextInput          (name="", sizing_mode='stretch_width', disabled=False)
		self.response               = pn.widgets.TextInput          (name="", sizing_mode='stretch_width', disabled=False)
	
		# toolbar thingy
		self.info_button            = pn.widgets.Button   (icon="info-circle",width=20)
		self.open_button            = pn.widgets.Button   (icon="file-upload",width=20)
		self.save_button            = pn.widgets.Button   (icon="file-download",width=20)
		self.copy_url_button        = pn.widgets.Button   (icon="copy",width=20)
		self.logout_button          = pn.widgets.Button   (icon="logout",width=20)
	
		# internal use only
		self.save_button_helper = pn.widgets.TextInput(visible=False)
		self.copy_url_button_helper = pn.widgets.TextInput(visible=False)
		self.file_name_input=  pn.widgets.TextInput(name="Numpy_File", placeholder='Numpy File Name')
	
	
		# constructor


		self.on_change_callbacks={}

		self.num_hold=0
		global SLICE_ID
		self.id=SLICE_ID
		SLICE_ID += 1
		
		self.db = None
		self.access = None
		self.detailed_data=None
		self.selected_physic_box=None
		self.selected_logic_box=None

		# translate and scale for each dimension
		self.logic_to_physic        = [(0.0, 1.0)] * 3
		self.metadata_range         = [0.0, 255.0]
		self.scenes                 = {}

		self.scene_body.stylesheets=[""".bk-input {background-color: rgb(48, 48, 64);color: white;font-size: small;}"""]

		self.createGui()

		def onSceneChange(evt): 
			logger.info(f"onSceneChange {evt}")
			body=self.scenes[evt.new]
			self.setSceneBody(body)
		self.scene.param.watch(SafeCallback(onSceneChange),"value", onlychanged=True,queued=True)

		def onTimestepChange(evt):
			self.refresh()
		self.timestep.param.watch(SafeCallback(onTimestepChange), "value", onlychanged=True,queued=True)

		def onTimestepDeltaChange(evt):
			if bool(getattr(self,"setting_timestep_delta",False)): return
			setattr("setting_timestep_delta",True)
			value=int(evt.new)
			A = self.timestep.start
			B = self.timestep.end
			T = self.getTimestep()
			T = A + value * int((T - A) / value)
			T = min(B, max(A, T))
			self.timestep.step = value
			self.setTimestep(T)
			setattr("setting_timestep_delta",False)
		self.timestep_delta.param.watch(SafeCallback(onTimestepDeltaChange),"value", onlychanged=True,queued=True)

		def onFieldChange(evt):
			self.refresh()
		self.field.param.watch(SafeCallback(onFieldChange),"value", onlychanged=True,queued=True)

		def onPaletteChange(evt):
			self.color_bar=None
			self.refresh()
		self.palette.param.watch(SafeCallback(onPaletteChange),"value_name", onlychanged=True,queued=True)

		def onRangeModeChange(evt):
			mode=evt.new
			self.color_map=None

			if mode == "metadata":   
				self.range_min.value = self.metadata_range[0]
				self.range_max.value = self.metadata_range[1]

			if mode == "dynamic-acc":
				self.range_min.value = 0.0
				self.range_max.value = 0.0
			
			self.range_min.disabled = False if mode == "user" else True
			self.range_max.disabled = False if mode == "user" else True
			self.refresh()
		self.range_mode.param.watch(SafeCallback(onRangeModeChange),"value", onlychanged=True,queued=True)

		def onRangeChange(evt):
			self.color_map=None
			self.color_bar=None
			self.refresh()
		self.range_min.param.watch(SafeCallback(onRangeChange),"value", onlychanged=True,queued=True)
		self.range_max.param.watch(SafeCallback(onRangeChange),"value", onlychanged=True,queued=True)

		def onColorMapperTypeChange(evt):
			self.color_bar=None 
			self.refresh()
		self.color_mapper_type.param.watch(SafeCallback(onColorMapperTypeChange),"value", onlychanged=True,queued=True)
		
		self.resolution.param.watch(SafeCallback(lambda evt: self.refresh()),"value", onlychanged=True,queued=True)
		self.view_dependent.param.watch(SafeCallback(lambda evt: self.refresh()),"value", onlychanged=True,queued=True)

		self.num_refinements.param.watch(SafeCallback(lambda evt: self.refresh()),"value", onlychanged=True,queued=True)

		def onDirectionChange(evt):
			value=evt.new
			logger.debug(f"id={self.id} value={value}")
			pdim = self.getPointDim()
			if pdim in (1,2): value = 2 # direction value does not make sense in 1D and 2D
			dims = [int(it) for it in self.db.getLogicSize()]

			# default behaviour is to guess the offset
			offset_value,offset_range=self.guessOffset(value)
			self.offset.start=offset_range[0]
			self.offset.end  =offset_range[1]
			self.offset.step=1e-16 if self.offset.editable and offset_range[2]==0.0 else offset_range[2] #  problem with editable slider and step==0
			self.offset.value=offset_value
			self.setQueryLogicBox(([0]*pdim,dims))
			self.refresh()
		self.direction.param.watch(SafeCallback(onDirectionChange),"value", onlychanged=True,queued=True)

		self.offset.param.watch(SafeCallback(lambda evt: self.refresh()),"value", onlychanged=True,queued=True)

		self.info_button.on_click(SafeCallback(lambda evt: self.showInfo()))
		self.open_button.on_click(SafeCallback(lambda evt: self.showOpen()))
		self.save_button.on_click(SafeCallback(lambda evt: self.save()))
		self.copy_url_button.on_click(SafeCallback(lambda evt: self.copyUrl()))
		self.play_button.on_click(SafeCallback(lambda evt: self.togglePlay()))

		self.setShowOptions(DEFAULT_SHOW_OPTIONS)

		self.canvas.on_event(bokeh.events.SelectionGeometry, SafeCallback(self.showDetails))

		self.start()


	# showDetails
	def showDetails(self,evt=None):
		from matplotlib.figure import Figure
		import openvisuspy as ovy
		import panel as pn
		import numpy as np
		from matplotlib.colors import LinearSegmentedColormap

		x,y,w,h=evt.new
		logic_box=self.toLogic([x,y,w,h])
		data=list(ovy.ExecuteBoxQuery(self.db, access=self.db.createAccess(), field=self.field.value,logic_box=logic_box,num_refinements=1))[0]["data"]
		print('Selected logic box here...')
		print(logic_box)
		self.selected_logic_box=logic_box
		self.selected_physic_box=[[x,x+w],[y,y+h]]
		print('Physical box here')
		print(f'{x} {y} {x+w} {y+h}')
		self.detailed_data=data
		save_numpy_button = pn.widgets.Button(name='Save Data as Numpy', button_type='primary')
		save_numpy_button.on_click(self.save_data)
		if self.range_mode.value=="dynamic-acc":
			vmin,vmax=np.min(data),np.max(data)
			self.range_min.value = min(self.range_min.value, vmin)
			self.range_max.value = max(self.range_max.value, vmax)
			logger.info(f"Updating range with selected area vmin={vmin} vmax={vmax}")
		p = figure(x_range=(self.selected_physic_box[0][0], self.selected_physic_box[0][1]), y_range=(self.selected_physic_box[1][0], self.selected_physic_box[1][1]))
		palette_name = self.palette.value_name 
		mapper = LinearColorMapper(palette=palette_name, low=self.range_min.value, high=self.range_max.value)
        
		data_flipped = data # Flip data to match imshow orientation
		source = ColumnDataSource(data=dict(image=[data_flipped]))
		dw = abs(self.selected_physic_box[0][1] -self.selected_physic_box[0][0])
		dh = abs(self.selected_physic_box[1][1] - self.selected_physic_box[1][0])
		p.image(image='image', x=self.selected_physic_box[0][0], y=self.selected_physic_box[1][0], dw=dw, dh=dh, color_mapper=mapper, source=source)  
		color_bar = ColorBar(color_mapper=mapper, label_standoff=12, location=(0,0))
		p.add_layout(color_bar, 'right')
		p.xaxis.axis_label = "Longitude"
		p.yaxis.axis_label = "Latitude"


        # Display using Panel
		self.showDialog(
            pn.Column(
                self.file_name_input,  # Assuming this is defined elsewhere in your class
                save_numpy_button,
                pn.pane.Bokeh(p),
                sizing_mode="stretch_both"
            ), 
            width=1024, height=768, name="Details"
        )

  

	def save_data(self, event):
		if self.detailed_data is not None:
			file_name = f"{self.file_name_input.value}.npz"
			print(file_name)
			np.savez(file_name, data=self.detailed_data, lon_lat=self.selected_physic_box)
			ShowInfoNotification('Data Saved successfully to current directory!')
			print("Data saved successfully.") 
		else:
			print("No data to save.")
	# open
	def showOpen(self):

		def onLoadClick(evt):
			body=value.decode('ascii')
			self.scene_body.value=body
			ShowInfoNotification('Load done. Press `Eval`')
		file_input = pn.widgets.FileInput(description="Load", accept=".json")
		file_input.param.watch(SafeCallback(onLoadClick),"value", onlychanged=True,queued=True)

		def onEvalClick(evt):
			self.setSceneBody(json.loads(self.scene_body.value))
			ShowInfoNotification('Eval done')
		eval_button = pn.widgets.Button(name="Eval", align='end')
		eval_button.on_click(SafeCallback(onEvalClick))

		self.showDialog(
			Column(
				self.scene_body,
				Row(file_input, eval_button, align='end'),
				sizing_mode="stretch_both",align="end"
			), 
			width=600, height=700, name="Open")
	

	# save
	def save(self):
		body=json.dumps(self.getSceneBody(),indent=2)
		self.save_button_helper.value=body
		ShowInfoNotification('Save done')
		print(body)

	# copy url
	def copyUrl(self):
		self.copy_url_button_helper.value=self.getShareableUrl()
		ShowInfoNotification('Copy url done')

	
	# createGui
	def createGui(self):

		self.save_button.js_on_click(args={"source":self.save_button_helper}, code="""
			function jsSave() {
				console.log('Test scene values');
				console.log(source.value);
				const link = document.createElement("a");
				const file = new Blob([source.value], { type: 'text/plain' });
				link.href = URL.createObjectURL(file);
				link.download = "save_scene.json";
				link.click();
				URL.revokeObjectURL(link.href);
			}
			setTimeout(jsSave,300);
		""")


		self.copy_url_button.js_on_click(args={"source": self.copy_url_button_helper}, code="""
			function jsCopyUrl() {
				console.log(source);
				navigator.clipboard.writeText(source.value);
			} 
			setTimeout(jsCopyUrl,300);
		""")

		self.logout_button = pn.widgets.Button(icon="logout",width=20)
		self.logout_button.js_on_click(args={"source": self.logout_button}, code="""
			console.log("logging out...")
			window.location=window.location.href + "/logout";
		""")

		# for icons see https://tabler.io/icons

		# play time
		self.play = types.SimpleNamespace()
		self.play.is_playing = False

		self.idle_callback = None
		self.color_bar     = None
		self.query_node    = None

		self.t1=time.time()
		self.aborted       = Aborted()
		self.new_job       = False
		self.current_img   = None
		self.last_job_pushed =time.time()
		self.query_node=QueryNode()

		self.canvas = Canvas(self.id)
		self.canvas.on_event(ViewportUpdate,              SafeCallback(self.onCanvasViewportChange))
		self.canvas.on_event(bokeh.events.Tap           , SafeCallback(self.onCanvasSingleTap))
		self.canvas.on_event(bokeh.events.DoubleTap     , SafeCallback(self.onCanvasDoubleTap))

		self.top_layout=Column(sizing_mode="stretch_width")

		self.middle_layout=Column(
			Row(self.canvas.fig_layout, sizing_mode='stretch_both'),
			sizing_mode='stretch_both'
		)

		self.bottom_layout=Column(sizing_mode="stretch_width")

		self.dialogs=Column()
		self.dialogs.visible=False

		self.main_layout=Column(
			self.top_layout,
			self.middle_layout,
			self.bottom_layout, 

			self.dialogs,
			self.copy_url_button_helper,
			self.save_button_helper,

			sizing_mode="stretch_both"
		)

	# onCanvasViewportChange
	def onCanvasViewportChange(self, evt):
		x,y,w,h=self.canvas.getViewport()
		self.viewport.value=f"{x} {y} {w} {h}" # this way someone from the outside can watch for changes
		self.refresh()

	# onCanvasSingleTap
	def onCanvasSingleTap(self, evt):
		logger.info(f"Single tap {evt}")
		pass

	# onCanvasDoubleTap
	def onCanvasDoubleTap(self, evt):
		logger.info(f"Double tap {evt}")

	# getShowOptions
	def getShowOptions(self):
		return self.show_options

	# setShowOptions
	def setShowOptions(self, value):
		self.show_options=value
		for layout, position in ((self.top_layout,"top"),(self.bottom_layout,"bottom")):
			layout.clear()
			for row in value.get(position,[[]]):
				v=[]
				for widget in row:
					if isinstance(widget,str):
						widget=getattr(self, widget.replace("-","_"),None)
					if widget:
						v.append(widget)
				if v: layout.append(Row(*v,sizing_mode="stretch_width"))

		# bottom

	# getShareableUrl
	def getShareableUrl(self):
		body=self.getSceneBody()
		load_s=base64.b64encode(json.dumps(body).encode('utf-8')).decode('ascii')
		current_url=GetCurrentUrl()
		o=urlparse(current_url)
		return o.scheme + "://" + o.netloc + o.path + '?' + urlencode({'load': load_s})		

	# stop
	def stop(self):
		self.aborted.setTrue()
		self.query_node.stop()

	# start
	def start(self):
		self.query_node.start()
		if not self.idle_callback:
			self.idle_callback = AddPeriodicCallback(self.onIdle, 1000 // 30)
		self.refresh()

	# getMainLayout
	def getMainLayout(self):
		return self.main_layout

	# getLogicToPhysic
	def getLogicToPhysic(self):
		return self.logic_to_physic

	# setLogicToPhysic
	def setLogicToPhysic(self, value):
		logger.debug(f"id={self.id} value={value}")
		self.logic_to_physic = value
		self.refresh()

	# getPhysicBox
	def getPhysicBox(self):
		dims = self.db.getLogicSize()
		vt = [it[0] for it in self.logic_to_physic]
		vs = [it[1] for it in self.logic_to_physic]
		return [[
			0 * vs[I] + vt[I],
			dims[I] * vs[I] + vt[I]
		] for I in range(len(dims))]

	# setPhysicBox
	def setPhysicBox(self, value):
		dims = self.db.getLogicSize()
		def LinearMapping(a, b, A, B):
			vs = (B - A) / (b - a)
			vt = A - a * vs
			return vt, vs
		T = [LinearMapping(0, dims[I], *value[I]) for I in range(len(dims))]
		self.setLogicToPhysic(T)
		
	# getSceneBody
	def getSceneBody(self):
		return {
			"scene" : {
				"name": self.scene.value, 
				
				# NOT needed.. they should come automatically from the dataset?
				#   "timesteps": self.db.getTimesteps(),
				#   "physic_box": self.getPhysicBox(),
				#   "fields": self.field.options,
				#   "directions" : self.direction.options,
				# "metadata-range": self.metadata_range,

				"timestep-delta": self.timestep_delta.value,
				"timestep": self.timestep.value,
				"direction": self.direction.value,
				"offset": self.offset.value, 
				"field": self.field.value,
				"view-dependent": self.view_dependent.value,
				"resolution": self.resolution.value,
				"num-refinements": self.num_refinements.value,
				"play-sec":self.play_sec.value,
				"palette": self.palette.value_name,
				"color-mapper-type": self.color_mapper_type.value,
				"range-mode": self.range_mode.value,
				"range-min": cdouble(self.range_min.value), # Object of type float32 is not JSON serializable
				"range-max": cdouble(self.range_max.value),
				"viewport": self.canvas.getViewport()
			}
		}

	# hold
	def hold(self):
		self.num_hold=getattr(self,"num_hold",0) + 1
		# if self.num_hold==1: self.doc.hold()

	# unhold
	def unhold(self):
		self.num_hold-=1
		# if self.num_hold==0: self.doc.unhold()

	# load
	def load(self, value):

		if isinstance(value,str):
			ext=os.path.splitext(value)[1].split("?")[0]
			if ext==".json":
				value=LoadJSON(value)
			else:
				value={"scenes": [{"name": os.path.basename(value), "url":value}]}

		# from dictionary
		elif isinstance(value,dict):
			pass
		else:
			raise Exception(f"{value} not supported")

		assert(isinstance(value,dict))
		assert(len(value)==1)
		root=list(value.keys())[0]

		self.scenes={}
		for it in value[root]:
			if "name" in it:
				self.scenes[it["name"]]={"scene": it}

		self.scene.options = list(self.scenes)

		if self.scenes:
			first_scene_name=list(self.scenes)[0]
			# I am not getting the event since it didn't change
			if False:
				self.scene.value=first_scene_name
			else:
				self.setSceneBody(self.scenes[first_scene_name])

	# setSceneBody
	def setSceneBody(self, scene):

		logger.info(f"# //////////////////////////////////////////#")
		logger.info(f"id={self.id} {scene} START")

		# TODO!
		# self.stop()

		assert(isinstance(scene,dict))
		assert(len(scene)==1 and list(scene.keys())==["scene"])

		# go one level inside
		scene=scene["scene"]

		# the url should come from first load (for security reasons)
		name=scene["name"]

		assert(name in self.scenes)
		default_scene=self.scenes[name]["scene"]
		url =default_scene["url"]
		urls=default_scene.get("urls",{})

		# special case, I want to force the dataset to be local (case when I have a local dashboards and remove dashboards)
		if "urls" in scene:

			if "--prefer" in sys.argv:
				prefer = sys.argv[sys.argv.index("--prefer") + 1]
				prefers = [it for it in urls if it['id']==prefer]
				if prefers:
					logger.info(f"id={self.id} Overriding url from {prefers[0]['url']} since selected from --select command line")
					url = prefers[0]['url']
					
			else:
				locals=[it for it in urls if it['id']=="local"]
				if locals and os.path.isfile(locals[0]["url"]):
					logger.info(f"id={self.id} Overriding url from {locals[0]['url']} since it exists and is a local path")
					url = locals[0]["url"]

		logger.info(f"id={self.id} LoadDataset url={url}...")
		db=LoadDataset(url=url) 

		# update the GUI too
		self.db    =db
		self.access=db.createAccess()
		self.scene.value=name

		timesteps=self.db.getTimesteps()
		self.timestep.start = timesteps[ 0]
		self.timestep.end   = timesteps[-1]
		self.timestep.step  = 1

		self.field.options=list(self.db.getFields())

		pdim = self.getPointDim()

		if "logic-to-physic" in scene:
			logic_to_physic=scene["logic-to-physic"]
			self.setLogicToPhysic(logic_to_physic)
		else:
			physic_box = self.db.inner.idxfile.bounds.toAxisAlignedBox().toString().strip().split()
			physic_box = [(float(physic_box[I]), float(physic_box[I + 1])) for I in range(0, pdim * 2, 2)]
			self.setPhysicBox(physic_box)

		if "directions" in scene:
			directions=scene["directions"]
		else:
			directions = self.db.inner.idxfile.axis.strip().split()
			directions = {it: I for I, it in enumerate(directions)} if directions else  {'X':0,'Y':1,'Z':2}
		self.direction.options=directions

		self.timestep_delta.value=int(scene.get("timestep-delta", 1))
		self.timestep.value=int(scene.get("timestep", self.db.getTimesteps()[0]))
		self.view_dependent.value = bool(scene.get('view-dependent', True))

		resolution=int(scene.get("resolution", -6))
		if resolution<0: resolution=self.db.getMaxResolution()+resolution
		self.resolution.end = self.db.getMaxResolution()
		self.resolution.value = resolution

		self.field.value=scene.get("field", self.db.getField().name)
		self.num_refinements.value=int(scene.get("num-refinements", 1 if pdim==1 else 2))

		self.direction.value = int(scene.get("direction", 2))

		default_offset_value,offset_range=self.guessOffset(self.direction.value)
		self.offset.start=offset_range[0]
		self.offset.end  =offset_range[1]
		self.offset.step=1e-16 if self.offset.editable and offset_range[2]==0.0 else offset_range[2] #  problem with editable slider and step==0
		self.offset.value=self.offset.value=float(scene.get("offset",default_offset_value))
		self.setQueryLogicBox(([0]*self.getPointDim(),[int(it) for it in self.db.getLogicSize()]))

		self.play_sec.value=float(scene.get("play-sec",0.01))
		self.palette.value_name=scene.get("palette",DEFAULT_PALETTE)

		db_field = self.db.getField(self.field.value)
		self.metadata_range = list(scene.get("metadata-range",[db_field.getDTypeRange().From, db_field.getDTypeRange().To]))
		assert(len(self.metadata_range))==2
		self.color_map=None

		self.range_mode.value=scene.get("range-mode","user")

		self.color_mapper_type.value = scene.get("color-mapper-type","linear")	

		viewport=scene.get("viewport",None)
		if viewport is not None:
			self.canvas.setViewport(viewport)

		show_options=scene.get("show-options",DEFAULT_SHOW_OPTIONS)
		self.setShowOptions(show_options)

		self.start()

		logger.info(f"id={self.id} END\n")


	# showInfo
	def showInfo(self):

		logger.debug(f"Show info")
		body=self.scenes[self.scene.value]
		metadata=body["scene"].get("metadata", [])

		cards=[]
		for I, item in enumerate(metadata):

			type = item["type"]
			filename = item.get("filename",f"metadata_{I:02d}.bin")

			if type == "b64encode":
				# binary encoded in string
				body = base64.b64decode(item["encoded"]).decode("utf-8")
				body = io.StringIO(body)
				body.seek(0)
				internal_panel=HTML(f"<div><pre><code>{body}</code></pre></div>",sizing_mode="stretch_width",height=400)
			elif type=="json-object":
				obj=item["object"]
				file = io.StringIO(json.dumps(obj))
				file.seek(0)
				internal_panel=JSON(obj,name="Object",depth=3, sizing_mode="stretch_width",height=400) 
			else:
				continue

			cards.append(Card(
					internal_panel,
					pn.widgets.FileDownload(file, embed=True, filename=filename,align="end"),
					title=filename,
					collapsed=(I>0),
					sizing_mode="stretch_width"
				)
			)

		self.showDialog(*cards)

	# showDialog
	def showDialog(self, *args,**kwargs):
		d={"position":"center", "width":1024, "height":600, "contained":False}
		d.update(**kwargs)
		float_panel=FloatPanel(*args, **d)
		self.dialogs.append(float_panel)

	# getMaxResolution
	def getMaxResolution(self):
		return self.db.getMaxResolution()

	# setViewDependent
	def setViewDependent(self, value):
		logger.debug(f"id={self.id} value={value}")
		self.view_dependent.value = value
		self.refresh()

	# getLogicAxis (depending on the projection XY is the slice plane Z is the orthogoal direction)
	def getLogicAxis(self):
		dir  = self.direction.value
		directions = self.direction.options
		# this is the projected slice
		XY = list(directions.values())
		if len(XY) == 3:
			del XY[dir]
		else:
			assert (len(XY) == 2)
		X, Y = XY
		# this is the cross dimension
		Z = dir if len(directions) == 3 else 2
		titles = list(directions.keys())
		return (X, Y, Z), (titles[X], titles[Y], titles[Z] if len(titles) == 3 else 'Z')

	# guessOffset
	def guessOffset(self, dir):

		pdim = self.getPointDim()

		# offset does not make sense in 1D and 2D
		if pdim<=2:
			return 0, [0, 0, 1] # (offset,range) 
		else:
			# 3d
			vt = [self.logic_to_physic[I][0] for I in range(pdim)]
			vs = [self.logic_to_physic[I][1] for I in range(pdim)]

			if all([it == 0 for it in vt]) and all([it == 1.0 for it in vs]):
				dims = [int(it) for it in self.db.getLogicSize()]
				value = dims[dir] // 2
				return value,[0, int(dims[dir]) - 1, 1]
			else:
				A, B = self.getPhysicBox()[dir]
				value = (A + B) / 2.0
				return value,[A, B, 0]

	# toPhysic (i.e. logic box -> canvas viewport in physic coordinates)
	def toPhysic(self, value):
		dir = self.direction.value
		pdim = self.getPointDim()
		vt = [self.logic_to_physic[I][0] for I in range(pdim)]
		vs = [self.logic_to_physic[I][1] for I in range(pdim)]
		p1,p2=value
		p1 = [vs[I] * p1[I] + vt[I] for I in range(pdim)]
		p2 = [vs[I] * p2[I] + vt[I] for I in range(pdim)]

		if pdim==1:
			# todo: what is the y range? probably I shold do what I am doing with the colormap
			assert(len(p1)==1 and len(p2)==1)
			p1.append(0.0)
			p2.append(1.0)

		elif pdim==2:
			assert(len(p1)==2 and len(p2)==2)

		else:
			assert(pdim==3 and len(p1)==3 and len(p2)==3)
			del p1[dir]
			del p2[dir]

		x1,y1=p1
		x2,y2=p2
		return [x1,y1, x2-x1, y2-y1]

	# toLogic
	def toLogic(self, value):
		pdim = self.getPointDim()
		dir = self.direction.value
		vt = [self.logic_to_physic[I][0] for I in range(pdim)]
		vs = [self.logic_to_physic[I][1] for I in range(pdim)]
		x,y,w,h=value
		p1=[x  ,y  ]
		p2=[x+w,y+h]

		if pdim==1:
			del p1[1]
			del p2[1]
		elif pdim==2:
			pass # alredy in 2D
		else:
			assert(pdim==3) 
			p1.insert(dir, 0) # need to add the missing direction
			p2.insert(dir, 0)

		assert(len(p1)==pdim and len(p2)==pdim)
		p1 = [(p1[I] - vt[I]) / vs[I] for I in range(pdim)]
		p2 = [(p2[I] - vt[I]) / vs[I] for I in range(pdim)]

		# in 3d the offset is what I should return in logic coordinates (making the box full dim)
		if pdim == 3:
			p1[dir] = int((self.offset.value  - vt[dir]) / vs[dir])
			p2[dir] = p1[dir]+1 
		
		return [p1, p2]

	# togglePlay
	def togglePlay(self):
		if self.play.is_playing:
			self.stopPlay()
		else:
			self.startPlay()

	# startPlay
	def startPlay(self):
		logger.info(f"id={self.id}::startPlay")
		self.play.is_playing = True
		self.play.t1 = time.time()
		self.play.wait_render_id = None
		self.play.num_refinements = self.num_refinements.value
		self.num_refinements.value = 1
		self.setWidgetsDisabled(True)
		self.play_button.disabled = False
		self.play_button.label = "Stop"

	# stopPlay
	def stopPlay(self):
		logger.info(f"id={self.id}::stopPlay")
		self.play.is_playing = False
		self.play.wait_render_id = None
		self.num_refinements.value = self.play.num_refinements
		self.setWidgetsDisabled(False)
		self.play_button.disabled = False
		self.play_button.label = "Play"

	# playNextIfNeeded
	def playNextIfNeeded(self):

		if not self.play.is_playing:
			return

		# avoid playing too fast by waiting a minimum amount of time
		t2 = time.time()
		if (t2 - self.play.t1) < float(self.play_sec.value):
			return

		# wait
		if self.play.wait_render_id is not None and self.render_id.value<self.play.wait_render_id:
			return

		# advance
		T = int(self.timestep.value) + self.timestep_delta.value

		# reached the end -> go to the beginning?
		if T >= self.timestep.end:
			T = self.timesteps.timestep.start

		logger.info(f"id={self.id}::playing timestep={T}")

		# I will wait for the resolution to be displayed
		self.play.wait_render_id = self.render_id.value+1
		self.play.t1 = time.time()
		self.timestep.value= T

	# onShowMetadataClick
	def onShowMetadataClick(self):
		self.metadata.visible = not self.metadata.visible

	# setWidgetsDisabled
	def setWidgetsDisabled(self, value):
		self.scene.disabled = value
		self.palette.disabled = value
		self.timestep.disabled = value
		self.timestep_delta.disabled = value
		self.field.disabled = value
		self.direction.disabled = value
		self.offset.disabled = value
		self.num_refinements.disabled = value
		self.resolution.disabled = value
		self.view_dependent.disabled = value
		self.request.disabled = value
		self.response.disabled = value
		self.play_button.disabled = value
		self.play_sec.disabled = value

	# getPointDim
	def getPointDim(self):
		return self.db.getPointDim() if self.db else 2

	# refresh
	def refresh(self):
		self.aborted.setTrue()
		self.new_job=True

	# getQueryLogicBox
	def getQueryLogicBox(self):
		viewport=self.canvas.getViewport()
		return self.toLogic(viewport)

	# setQueryLogicBox
	def setQueryLogicBox(self,value):
		viewport=self.toPhysic(value)
		self.canvas.setViewport(viewport)
		self.refresh()
  
	# getLogicCenter
	def getLogicCenter(self):
		pdim=self.getPointDim()  
		p1,p2=self.getQueryLogicBox()
		assert(len(p1)==pdim and len(p2)==pdim)
		return [(p1[I]+p2[I])*0.5 for I in range(pdim)]

	# getLogicSize
	def getLogicSize(self):
		pdim=self.getPointDim()
		p1,p2=self.getQueryLogicBox()
		assert(len(p1)==pdim and len(p2)==pdim)
		return [(p2[I]-p1[I]) for I in range(pdim)]

  # gotoPoint
	def gotoPoint(self,point):
		return  # COMMENTED OUT
		"""
		self.offset.value=point[self.direction.value]
		
		(p1,p2),dims=self.getQueryLogicBox(),self.getLogicSize()
		p1,p2=list(p1),list(p2)
		for I in range(self.getPointDim()):
			p1[I],p2[I]=point[I]-dims[I]/2,point[I]+dims[I]/2
		self.setQueryLogicBox([p1,p2])
		self.canvas.renderPoints([self.toPhysic(point)]) 
		"""
  
	# gotNewData
	def gotNewData(self, result):

		data=result['data']
		try:
			data_range=np.min(data),np.max(data)
		except:
			data_range=0.0,0.0

		logic_box=result['logic_box'] 

		# depending on the palette range mode, I need to use different color mapper low/high
		mode=self.range_mode.value

		# show the user what is the current offset
		maxh=self.db.getMaxResolution()
		dir=self.direction.value

		pdim=self.getPointDim()
		vt,vs=self.logic_to_physic[dir] if pdim==3 else (0.0,1.0)
		endh=result['H']

		user_physic_offset=self.offset.value

		real_logic_offset=logic_box[0][dir] if pdim==3 else 0.0
		real_physic_offset=vs*real_logic_offset + vt 
		user_logic_offset=int((user_physic_offset-vt)/vs)

		# update slider info
		self.offset.name=" ".join([
			f"Offset: {user_physic_offset:.3f}±{abs(user_physic_offset-real_physic_offset):.3f}",
			f"Pixel: {user_logic_offset}±{abs(user_logic_offset-real_logic_offset)}",
			f"Max Res: {endh}/{maxh}"
		])

		# refresh the range
		if True:

			# in dynamic mode, I need to use the data range
			if mode=="dynamic":
				self.range_min.value = data_range[0]
				self.range_max.value = data_range[1]
				
			# in data accumulation mode I am accumulating the range
			if mode=="dynamic-acc":
				if self.range_min.value==self.range_max.value:
					self.range_min.value=data_range[0]
					self.range_max.value=data_range[1]
				else:
					self.range_min.value = min(self.range_min.value, data_range[0])
					self.range_max.value = max(self.range_max.value, data_range[1])
			# update the color bar
			low =cdouble(self.range_min.value)
			high=cdouble(self.range_max.value)
			print(f'Min Value: {low} ;  Max Value: {high}')


		# regenerate colormap
		if self.color_bar is None:
			print('NONE COLORMAP')
			color_mapper_type=self.color_mapper_type.value
			assert(color_mapper_type in ["linear","log"])
			is_log=color_mapper_type=="log"
			palette=self.palette.value
			mapper_low =max(EPSILON, low ) if is_log else low
			mapper_high=max(EPSILON, high) if is_log else high
			self.color_bar = bokeh.models.ColorBar(color_mapper = 
				bokeh.models.LogColorMapper   (palette=palette, low=mapper_low, high=mapper_high) if is_log else 
				bokeh.models.LinearColorMapper(palette=palette, low=mapper_low, high=mapper_high)
			)

		logger.debug(f"id={self.id}::rendering result data.shape={data.shape} data.dtype={data.dtype} logic_box={logic_box} data-range={data_range} range={[low,high]}")

		# update the image
		self.canvas.showData(data, self.toPhysic(logic_box), color_bar=self.color_bar)

		(X,Y,Z),(tX,tY,tZ)=self.getLogicAxis()
		self.canvas.setAxisLabels(tX,tY)

		# update the status bar
		if True:
			tot_pixels=np.prod(data.shape)
			canvas_pixels=self.canvas.getWidth()*self.canvas.getHeight()
			self.H=result['H']
			query_status="running" if result['running'] else "FINISHED"
			self.response.value=" ".join([
				f"#{result['I']+1}",
				f"{str(logic_box).replace(' ','')}",
				str(data.shape),
				f"Res={result['H']}/{maxh}",
				f"{result['msec']}msec",
				str(query_status)
			])

		# this way someone from the outside can watch for new results
		self.render_id.value=self.render_id.value+1 
  
	# pushJobIfNeeded
	def pushJobIfNeeded(self):

		if not self.new_job:
			return

		canvas_w,canvas_h=(self.canvas.getWidth(),self.canvas.getHeight())
		query_logic_box=self.getQueryLogicBox()
		pdim=self.getPointDim()

		# abort the last one
		self.aborted.setTrue()
		self.query_node.waitIdle()
		num_refinements = self.num_refinements.value
		if num_refinements==0:
			num_refinements={
				1: 1, 
				2: 3, 
				3: 4  
			}[pdim]
		self.aborted=Aborted()

		# do not push too many jobs
		if (time.time()-self.last_job_pushed)<0.2:
			return
		
		# I will use max_pixels to decide what resolution, I am using resolution just to add/remove a little the 'quality'
		if not self.view_dependent.value:
			# I am not using the information about the pixel on screen
			endh=self.resolution.value
			max_pixels=None
		else:

			endh=None 
			canvas_w,canvas_h=(self.canvas.getWidth(),self.canvas.getHeight())

			# probably the UI is not ready yet
			if not canvas_w or not canvas_h:
				return

			if pdim==1:
				max_pixels=canvas_w
			else:
				delta=self.resolution.value-self.getMaxResolution()
				a,b=self.resolution.value,self.getMaxResolution()
				if a==b:
					coeff=1.0
				if a<b:
					coeff=1.0/pow(1.3,abs(delta)) # decrease 
				else:
					coeff=1.0*pow(1.3,abs(delta)) # increase 
				max_pixels=int(canvas_w*canvas_h*coeff)
			
		# new scene body
		self.scene_body.value=json.dumps(self.getSceneBody(),indent=2)
		
		logger.debug("# ///////////////////////////////")
		logger.debug(f"id={self.id} pushing new job query_logic_box={query_logic_box} max_pixels={max_pixels} endh={endh}..")

		timestep=int(self.timestep.value)
		field=self.field.value
		box_i=[[int(it) for it in jt] for jt in query_logic_box]
		self.request.value=f"t={timestep} b={str(box_i).replace(' ','')} {canvas_w}x{canvas_h}"
		self.response.value="Running..."

		self.query_node.pushJob(
			self.db, 
			access=self.access,
			timestep=timestep, 
			field=field, 
			logic_box=query_logic_box, 
			max_pixels=max_pixels, 
			num_refinements=num_refinements, 
			endh=endh, 
			aborted=self.aborted
		)
		
		self.last_job_pushed=time.time()
		self.new_job=False
		# logger.debug(f"id={self.id} pushed new job query_logic_box={query_logic_box}")

	# onIdle
	def onIdle(self):

		if not self.db:
			return

		self.canvas.onIdle()

		if self.canvas and  self.canvas.getWidth()>0 and self.canvas.getHeight()>0:
			self.playNextIfNeeded()

		if self.query_node:
			result=self.query_node.popResult(last_only=True) 
			if result is not None: 
				self.gotNewData(result)
			self.pushJobIfNeeded()






