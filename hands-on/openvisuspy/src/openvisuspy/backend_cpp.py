import os,sys,time,threading,queue
import OpenVisus as ov

from .utils import *
from .backend import BaseDataset

logger = logging.getLogger(__name__)

# ///////////////////////////////////////////////////////////////////
class Aborted:
	
	# constructor
	def __init__(self,value=False):
		self.inner=ov.Aborted()
		if value: self.inner.setTrue()

	# setTrue
	def setTrue(self):
		self.inner.setTrue()

# ///////////////////////////////////////////////////////////////////
class Stats:
	
	# constructor
	def __init__(self):
		self.lock = threading.Lock()
		self.num_running=0
		
	# isRunning
	def isRunning(self):
		with self.lock:
			return self.num_running>0

	# readStats
	def readStats(self):

		io =ov.File.global_stats()
		net=ov.NetService.global_stats()

		ret= {
			"io": {
				"r":io.getReadBytes(),
				"w":io.getWriteBytes(),
				"n":io.getNumOpen(),
			},
			"net":{
				"r":net.getReadBytes(), 
				"w":net.getWriteBytes(),
				"n":net.getNumRequests(),
			}
		}

		ov.File      .global_stats().resetStats()
		ov.NetService.global_stats().resetStats()

		return ret
			

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
		sec=max(time.time()-self.t1,1e-8)
		stats=self.readStats()
		logger.info(f"Stats::printStatistics enlapsed={sec} seconds" )
		for k,v in stats.items():
			w,r,n=v['w'],v['r'],v['n']
			logger.info(" ".join([f"  {k:4}",
						f"r={HumanSize(r)} r_sec={HumanSize(r/sec)}/sec",
						f"w={HumanSize(w)} w_sec={HumanSize(w/sec)}/se ",
						f"n={n:,} n_sec={int(n/sec):,}/sec"]))


# /////////////////////////////////////////////////////////////////////////////////////////////////
class QueryNode:

	# shared by all instances (and must remain this way!)
	stats=Stats()

	# constructor
	def __init__(self):
		self.iqueue=queue.Queue()
		self.oqueue=queue.Queue()
		self.wait_for_oqueue=False
		self.thread=None

	# disableOutputQueue
	def disableOutputQueue(self):
		self.oqueue=None

	# start
	def start(self):
		# already running
		if not self.thread is None:
			return
		self.thread = threading.Thread(target=self._threadLoop,daemon=True)
		self.thread.start()

	# stop
	def stop(self):
		self.iqueue.join()
		self.iqueue.put((None,None))
		if self.thread is not None:
			self.thread.join()
			self.thread=None

	# waitIdle
	def waitIdle(self):
		self.iqueue.join()

	# pushJob
	def pushJob(self, db, **kwargs):
		self.iqueue.put([db,kwargs])

	# popResult
	def popResult(self, last_only=True):
		assert self.oqueue is not None
		ret=None
		while not self.oqueue.empty():
			ret=self.oqueue.get()
			self.oqueue.task_done()
			if not last_only: break
		return ret

	# _threadLoop
	def _threadLoop(self):

		logger.info("entering _threadLoop ...")

		is_aborted=ov.Aborted()
		is_aborted.setTrue()

		t1=None
		while True:

			if t1 is None or (time.time()-t1)>5.0:
				logger.info("_threadLoop is Alive")
				t1=time.time()

			db, kwargs=self.iqueue.get()
			if db is None: 
				logger.info("exiting _threadLoop...")
				return 
			
			self.stats.startCollecting() 

			access=kwargs['access'];del kwargs['access']
			query=db.createBoxQuery(**kwargs)
			db.beginBoxQuery(query)
			while db.isQueryRunning(query):
				try:
					result=db.executeBoxQuery(access, query)
				except Exception as ex:
					if not query.aborted == is_aborted:
						logger.info(f"db.executeBoxQuery failed {ex}")
					break

				if result is None: 
					break
				
				if query.aborted == is_aborted:
					break 

				
				db.nextBoxQuery(query)
				result["running"]=db.isQueryRunning(query)

				if self.oqueue:
					self.oqueue.put(result)
					if self.wait_for_oqueue:
						self.oqueue.join()
				
				time.sleep(0.01)

				# remove me
				# break

			logger.info("Query finished")
			self.iqueue.task_done()
			self.stats.stopCollecting()



# ///////////////////////////////////////////////////////////////////
class Dataset (BaseDataset):
	
	# coinstructor
	def __init__(self,url):
		self.url=url

		# handle security
		if all([
				url.startswith("http"),
				"mod_visus" in url,
			  "MODVISUS_USERNAME" in os.environ,
				"MODVISUS_PASSWORD" in os.environ,
				"~auth_username" not in url,
				"~auth_password" not in url,
		 	]) :

			url=url + f"&~auth_username={os.environ['MODVISUS_USERNAME']}&~auth_password={os.environ['MODVISUS_PASSWORD']}"

		self.inner=ov.LoadDataset(url)
		
	# getUrl
	def getUrl(self):
		return self.url       

	# getPointDim
	def getPointDim(self):
		return self.inner.getPointDim()

	# getLogicBox
	def getLogicBox(self):
		return self.inner.getLogicBox()

	# getMaxResolution
	def getMaxResolution(self):
		return self.inner.getMaxResolution()

	# getBitmask
	def getBitmask(self):
		return self.inner.getBitmask().toString()

	# getLogicSize
	def getLogicSize(self):
		return self.inner.getLogicSize()
	
	# getTimesteps
	def getTimesteps(self):
		return self.inner.getTimesteps() 

	# getTimestep
	def getTimestep(self):
		return self.inner.getTime()

	# getFields
	def getFields(self):
		return self.inner.getFields()

	# createAccess
	def createAccess(self):
		return self.inner.createAccess()

	# getField
	def getField(self,field=None):
		return self.inner.getField(field) if field is not None else self.inner.getField()

	# getDatasetBody
	def getDatasetBody(self):
		return self.inner.getDatasetBody()

	# ///////////////////////////////////////////////////////////////////////////

	def createBoxQuery(self, *args,**kwargs):

		query=super().createBoxQuery(*args,**kwargs)
		
		if query is None:
			return None

		query.inner  = self.inner.createBoxQuery(
			ov.BoxNi(ov.PointNi(query.logic_box[0]), ov.PointNi(query.logic_box[1])), 
			self.inner.getField(query.field), 
			query.timestep, 
			ord('r'), 
			query.aborted.inner)

		if not query.inner:
			return None

		for H in query.end_resolutions:
			query.inner.end_resolutions.push_back(H)

		return query

	# begin
	def beginBoxQuery(self,query):
		if query is None: return
		super().beginBoxQuery(query)
		self.inner.beginBoxQuery(query.inner)

	# isRunning
	def isQueryRunning(self,query):
		if query is None: return False
		return query.inner.isRunning() 

	# getQueryCurrentResolution
	def getQueryCurrentResolution(self, query):
		return query.inner.getCurrentResolution() if self.isQueryRunning(query) else -1

	# executeBoxQuery
	def executeBoxQuery(self,access, query):
		assert self.isQueryRunning(query)
		if not self.inner.executeBoxQuery(access, query.inner):
			return None
		data=ov.Array.toNumPy(query.inner.buffer, bShareMem=False) 
		return super().returnBoxQueryData(access,query,data)

	# nextBoxQuery
	def nextBoxQuery(self,query):
		if not self.isQueryRunning(query): return
		self.inner.nextBoxQuery(query.inner)
		super().nextBoxQuery(query)

# ///////////////////////////////////////////////////////////////////
def LoadDataset(url):
	return Dataset(url)

# ////////////////////////////////////////////////////////////////////////////////////////////////////////////
def ExecuteBoxQuery(db,*args,**kwargs):
	access=kwargs['access'];del kwargs['access']
	query=db.createBoxQuery(*args,**kwargs)
	t1=time.time()
	I,N=0,len(query.end_resolutions)
	db.beginBoxQuery(query)
	while db.isQueryRunning(query):
		result=db.executeBoxQuery(access, query)
		if result is None: break
		db.nextBoxQuery(query)
		result["running"]=db.isQueryRunning(query)
		yield result