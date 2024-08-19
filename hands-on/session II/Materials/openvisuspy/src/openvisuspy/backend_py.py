import os,sys,xmltodict,urllib,zlib,requests
from threading import Lock

from .utils import *
from .backend import BaseDataset

logger = logging.getLogger(__name__)

# ///////////////////////////////////////////////////////////////////
class Aborted:
	
	# constructor
	def __init__(self):
		self.value=False
		self.on_aborted=None

	# setTrue
	def setTrue(self):

		if self.value==True: 
			return
		
		self.value=True

		if self.on_aborted is not None:
			try:
				self.on_aborted()
			except:
				pass

# ///////////////////////////////////////////////////////////////////
class Stats:
	
	# constructor
	def __init__(self):
		self.lock = Lock()
		self.num_running=0
		
	# readStats
	def readStats(self):

		# TODO
		return {
			"io": {
				"r": 0,
				"w": 0,
				"n": 0,
			},
			"net":{
				"r": 0, 
				"w": 0,
				"n": 0,
			}
		}

		# todo reset

	# isRunning
	def isRunning(self):
		with self.lock:
			return self.num_running>0

	# startCollecting
	def startCollecting(self):
		with self.lock:
			self.num_running+=1
			if self.num_running>1: return
		self.t1=time.time()
		self.readStats()
			
	# stopCollecting
	def stopCollecting(self):
		with self.lock:
			self.num_running-=1
			if self.num_running>0: return
		self.printStatistics()

	# printStatistics
	def printStatistics(self):
		sec=time.time()-self.t1
		stats=self.readStats()
		logger.info(f"Stats::printStatistics enlapsed={sec} seconds" )
		try: # division by zero
			for k,v in stats.items():
				logger.info(f"   {k}  r={HumanSize(v['r'])} r_sec={HumanSize(v['r']/sec)}/sec w={HumanSize(v['w'])} w_sec={HumanSize(v['w']/sec)}/sec n={v.n:,} n_sec={int(v/sec):,}/sec")
		except:
			pass

# /////////////////////////////////////////////////////////////////////////////////////////////////
class QueryNode:

	# shared by all instances (and must remain this way!)
	stats=Stats()

	# constructor
	def __init__(self):
		self.job=[None,None]
		self.result=None
		self.task=None
		
	# disableOutputQueue
	def disableOutputQueue(self):
		pass

	# asyncExecuteQuery
	async def asyncExecuteQuery(self):
		(db,kwargs)=self.popJob()
		if db is None: return
		self.stats.startCollecting() 
		access=kwargs['access']
		del kwargs['access']
		query=db.createBoxQuery(**kwargs)
		db.beginBoxQuery(query)
		while db.isQueryRunning(query):
			result=None 
			try:
				result=await db.executeBoxQuery(access, query)
			except Exception as ex: # was without Exception
				logger.info(f"db.executeBoxQuery FAILED {ex}")
			except: # this is needed for pyoidide
				logger.info(f"db.executeBoxQuery FAILED unknown-error")
				
			if result is None: break
			db.nextBoxQuery(query)
			result["running"]=db.isQueryRunning(query)
			self.pushResult(result)
			await SleepMsec(0)
		self.stats.stopCollecting()

	# start
	def start(self):
		self.task=AddAsyncLoop(f"{self}.QueryNodeLoop",self.asyncExecuteQuery, msec=50) 

	# stop
	def stop(self):
		if self.task:
			self.task.cancel()
			self.task=None

	# waitIdle
	def waitIdle(self):
		pass # I don't think I need this

	# pushJob
	def pushJob(self, db, **kwargs):
		logger.info(f"pushed new job {db}")
		self.job=[db,kwargs]

	# popJob
	def popJob(self):
		ret,self.job=self.job,[None,None]
		return ret

	def pushResult(self, result):
		self.result=result

	# popResult
	def popResult(self, last_only=True):
		ret, self.result = self.result, None
		return ret

# ///////////////////////////////////////////////////////////////////
class Dataset(BaseDataset):
	
	# constructor
	def __init__(self):
		pass
	
	# getUrl
	def getUrl(self):
		return self.url
	
	# getPointDim
	def getPointDim(self):
		return self.pdim

	# getLogicBox
	def getLogicBox(self):
		return self.logic_box

	# getMaxResolution
	def getMaxResolution(self):
		return self.max_resolution

	# getBitmask
	def getBitmask(self):
		return self.bitmask

	# getLogicSize
	def getLogicSize(self):
		return self.logic_size
	
	# getTimesteps
	def getTimesteps(self):
		return self.timesteps

	# getTimestep
	def getTimestep(self):
		return self.timesteps[0]

	# getFields
	def getFields(self):
		return [it['name'] for it in self.fields]

	# createAccess
	def createAccess(self):
		return None # I don't have the access

	# getField
	def getField(self,field=None):
		if field is None:
			return self.fields[0]['name']
		else:
			raise Exception("internal error")

	# getDatasetBody
	def getDatasetBody(self):
		return self.body
		
	# /////////////////////////////////////////////////////////////////////////////////

	async def executeBoxQuery(self,access, query, verbose=False):

		"""
		Links:

		- https://blog.jonlu.ca/posts/async-python-http
		- https://requests.readthedocs.io/en/latest/user/advanced/
		- https://lwebapp.com/en/post/pyodide-fetch
		- https://stackoverflow.com/questions/31998421/abort-a-get-request-in-python-when-the-server-is-not-responding
		- https://developer.mozilla.org/en-US/docs/Web/API/fetch#options
		- https://pyodide.org/en/stable/usage/packages-in-pyodide.html
		"""

		if not self.isQueryRunning(query):
			return

		H=query.end_resolutions[query.cursor]

		url=self.getUrl()
		timestep=query.timestep
		field=query.field
		logic_box=query.logic_box
		toh=H
		compression="zip"

		parsed=urllib.parse.urlparse(url)
		
		scheme=parsed.scheme
		path=parsed.path;assert(path=="/mod_visus")
		params=urllib.parse.parse_qs(parsed.query)
		
		for k,v in params.items():
			if isinstance(v,list):
				params[k]=v[0]
		
		# remove array in values
		params={k:(v[0] if isinstance(v,list)  else v) for k,v in params.items()}

		def SetParam(key,value):
			nonlocal params
			if not key in params:
				params[key]=value
		
		SetParam('action',"boxquery")
		SetParam('box'," ".join([f"{a} {b-1}" for a,b in zip(*logic_box)]).strip())
		SetParam('compression',compression)
		SetParam('field',field)
		SetParam('time',timestep)
		SetParam('toh',toh)
	
		if verbose:
			logger.info("Sending params={params.items()}")
			
		url=f"{scheme}://{parsed.netloc}{path}?" + urllib.parse.urlencode(params)

		aborted=query.aborted
		if aborted.value: return None

		if IsPyodide():
				# see pyfetch (https://github.com/pyodide/pyodide/blob/main/src/py/pyodide/http.py)
				import js
				import pyodide
				import pyodide.http
				import pyodide.ffi 
				import pyodide.webloop
				
				options=pyodide.ffi.to_js({"method":"GET", "mode":"cors","cache":"no-cache","redirect":"follow",},dict_converter=js.Object.fromEntries)
				# https://github.com/pyodide/pyodide/issues/2923
				def OnError(err): print(f'there were error: {err.message}')
				js_future = js.fetch(url, options).catch(OnError)
				assert(isinstance(js_future,pyodide.webloop.PyodideFuture))
				def OnAborted(): js_future.cancel()
				aborted.on_aborted=OnAborted
				response=pyodide.http.FetchResponse(url,await js_future)
				response.status_code=response.status
				response.headers=response.js_response.headers

		else:
			import httpx
			client = httpx.AsyncClient(verify=False)
			def OnAborted(): client.close()
			aborted.on_aborted=OnAborted
			response = await client.get(url)
				
		if aborted.value:
			return None

		logger.info(f"[{response.status_code}] {response.url}")
		if response.status_code!=200:
			if not aborted.value: logger.info(f"Got unvalid response {response.status_code}")
			return None

		# get the body
		try:
			if IsPyodide():
				body=await response.bytes()
			else:
				body=response.content
		except Exception as ex:
			if not aborted.value: logger.info(f"Got unvalid response {ex}")
			return None			
		except:	# this is needed for pyoidide
			if not aborted.value: logger.info(f"Got unvalid response unknown-error")
			return None

		if verbose:
			logger.info(f"Got body len={len(body)}")
			logger.info(f"response headers {response.headers.items()}")

		dtype     = response.headers["visus-dtype"].strip()
		compression=response.headers["visus-compression"].strip()

		if compression=="raw" or compression=="":
			pass

		elif compression=="zip":
			body=zlib.decompress(body)
			if verbose:
				logger.info(f"data after decompression {type(body)} {len(body)}")
		else:
			raise Exception("internal error")
		
		nsamples=[int(it) for it in response.headers["visus-nsamples"].strip().split()]

		# example uint8[3]
		shape=list(reversed(nsamples))
		if "[" in dtype:
			assert dtype[-1]==']'
			dtype,N=dtype[0:-1].split("[")
			shape.append(int(N))

		if verbose:
			logger.info(f"numpy array dtype={dtype} shape={shape}")

		data=np.frombuffer(body,dtype=np.dtype(dtype)).reshape(shape)   

		# full-dimension
		return super().returnBoxQueryData(access, query, data)

# /////////////////////////////////////////////////////////////////////////////////
def LoadDataset(url):
	
	# i don't support block access
	if not "mod_visus" in url:
		raise Exception(f"{repr(url)} is not a mod_visus dataset")

	response=requests.get(url,params={'action':'readdataset','format':'xml'},verify=False) 
	if response.status_code!=200:
		raise Exception(f"requests.get({url}) returned {response.status_code}")

	assert(response.status_code==200)
	body=response.text
	logger.info(f"Got response {body}")
	
	def RemoveAt(cursor):
		if isinstance(cursor,dict):
			return {(k[1:] if k.startswith("@") else k):RemoveAt(v) for k,v in cursor.items()}
		elif isinstance(cursor,list):
			return [RemoveAt(it) for it in cursor]
		else:
			return cursor

	d=RemoveAt(xmltodict.parse(body)["dataset"]["idxfile"])
	# pprint(d)

	ret=Dataset()
	ret.url=url
	ret.body=body
	ret.bitmask=d["bitmask"]["value"]
	ret.pdim=3 if '2' in ret.bitmask else 2
	ret.max_resolution=len(ret.bitmask)-1

	# logic_box (X1 X2 Y1 Y2 Z1 Z2)
	v=[int(it) for it in d["box"]["value"].strip().split()]
	p1=[v[I] for I in range(0,len(v),2)]
	p2=[v[I] for I in range(1,len(v),2)]
	ret.logic_box=[p1,p2]
	
	# logic_size
	ret.logic_size=[(b-a) for a,b in zip(p1,p2)]

	# timesteps
	ret.timesteps=[]
	v=d["timestep"]
	if not isinstance(v,list): v=[v]
	for T,timestep in enumerate(v):
		if "when" in timestep:
			ret.timesteps.append(int(timestep["when"]))
		else:
			assert("from" in timestep)
			for T in range(int(timestep["from"]),int(timestep["to"]),int(timestep["step"])):
				ret.timesteps.append(T)

	# fields
	v=d["field"]
	if not isinstance(v,list):
		v=[v]
	ret.fields=[{"name":field["name"],"dtype": field["dtype"]} for field in v]
	
	logger.info(f"LoadDataset returned:\n" + str({
			"url":ret.url,
			"bitmask":ret.bitmask,
			"pdim":ret.pdim,
			"max_resolution":ret.max_resolution,
			"timesteps": ret.timesteps,
			"fields":ret.fields,
			"logic_box":ret.logic_box,
			"logic_size":ret.logic_size,
		}))
	

	#box,delta,num_pixels=ret.getAlignedBox(logic_box=[[0,0,539],[2048,2048,540]],endh=22,slice_dir=2)
	
	return ret

# ////////////////////////////////////////////////////////////////////////////////////////////////////////////
def ExecuteBoxQuery(db,*args,**kwargs):
	access=kwargs['access']
	del kwargs['access']
	
	query=db.createBoxQuery(*args,**kwargs)
	t1=time.time()
	I,N=0,len(query.end_resolutions)
	db.beginBoxQuery(query)
	while db.isQueryRunning(query):
		result=RunAsync(db.executeBoxQuery(access, query))
		if result is None: break
		db.nextBoxQuery(query)
		result["running"]=db.isQueryRunning(query)
		yield result


