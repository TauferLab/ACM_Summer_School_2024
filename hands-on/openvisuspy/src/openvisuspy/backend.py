import os,sys,copy,math,time,logging,types,requests,zlib,xmltodict,urllib,queue,types,threading
import numpy as np

from . utils import *

logger = logging.getLogger(__name__)

# //////////////////////////////////////////////////////////////////////////
class BaseDataset:

	# getAlignedBox
	def getAlignedBox(self, logic_box, endh, slice_dir:int=None):
		p1,p2=copy.deepcopy(logic_box)
		pdim=self.getPointDim()
		maxh=self.getMaxResolution()
		bitmask=self.getBitmask()
		delta=[1,1,1]
		
		for K in range(maxh,endh,-1):
			bit=ord(bitmask[K])-ord('0')
			delta[bit]*=2

		for I in range(pdim):
			p1[I]=delta[I]*(p1[I]//delta[I])
			p2[I]=delta[I]*(p2[I]//delta[I])
			p2[I]=max(p1[I]+delta[I], p2[I])
		
		num_pixels=[(p2[I]-p1[I])//delta[I] for I in range(pdim)]


		#  force to be a slice?
		# REMOVE THIS!!!
		if pdim==3 and slice_dir is not None:
			offset=p1[slice_dir]
			p2[slice_dir]=offset+0
			p2[slice_dir]=offset+1
		
		# print(f"getAlignedBox logic_box={logic_box} endh={endh} slice_dir={slice_dir} (p1,p2)={(p1,p2)} delta={delta} num_pixels={num_pixels}")

		return (p1,p2), delta, num_pixels

	# createBoxQuery
	def createBoxQuery(self,
		timestep=None, 
		field=None, 
		logic_box=None,
		max_pixels=None, 
		endh=None, 
		num_refinements=1, 
		aborted=None,
		full_dim=False,
	):

		pdim=self.getPointDim()
		assert pdim in [1,2,3]

		maxh=self.getMaxResolution()
		bitmask=self.getBitmask()
		dims=self.getLogicSize()

		if timestep is None:
			timestep=self.getTimestep()

		if field is None:
			field=self.getField()

		if logic_box is None:
			logic_box=self.getLogicBox()

		if endh is None and not max_pixels:
			endh=maxh

		if aborted is None:
			aborted=Aborted()

		logger.info(f"begin timestep={timestep} field={field} logic_box={logic_box} num_refinements={num_refinements} max_pixels={max_pixels} endh={endh}")

		# if box is not specified get the all box
		if logic_box is None:
			W,H,D=[int(it) for it in self.getLogicSize()]
			logic_box=[[0,0,0],[W,H,D]]
		
		# crop logic box
		if True:
			p1,p2=list(logic_box[0]),list(logic_box[1])
			slice_dir=None
			for I in range(pdim):
				
				# *************** is a slice? *******************
				if not full_dim and  pdim==3 and (p2[I]-p1[I])==1:
					assert slice_dir is None 
					slice_dir=I
					p1[I]=Clamp(p1[I],0,dims[I])
					p2[I]=p1[I]+1
				else:
					p1[I]=Clamp(int(math.floor(p1[I])),     0,dims[I])
					p2[I]=Clamp(int(math.ceil (p2[I])) ,p1[I],dims[I])
				if not p1[I]<p2[I]:
					return None
			logic_box=(p1,p2)
		
		# is view dependent? if so guess max resolution and endh is IGNORED and overwritten 
		if max_pixels:

			if IsIterable(max_pixels):
				max_pixels=int(np.prod(max_pixels,dtype=np.int64))

			original_box=logic_box
			for __endh in range(maxh,0,-1):
				aligned_box, delta, num_pixels=self.getAlignedBox(original_box,__endh, slice_dir=slice_dir)
				tot_pixels=np.prod(num_pixels, dtype=np.int64)
				if tot_pixels<=max_pixels:
					endh=__endh
					logger.info(f"Guess resolution endh={endh} original_box={original_box} aligned_box={aligned_box} delta={delta} num_pixels={repr(num_pixels)} tot_pixels={tot_pixels:,} max_pixels={max_pixels:,} end={endh}")
					logic_box=aligned_box
					break
		else:
			original_box=logic_box
			aligned_box, delta, num_pixels=self.getAlignedBox(original_box,endh, slice_dir=slice_dir)

		# this is the query I need
		end_resolutions=list(reversed([endh-pdim*I for I in range(num_refinements) if endh-pdim*I>=0]))

		# scrgiorgio: end_resolutions[0] is wrong, I need to align to the finest resolution
		logic_box, delta, num_pixels=self.getAlignedBox(logic_box, end_resolutions[-1], slice_dir=slice_dir)

		logic_box=[
			[int(it) for it in logic_box[0]],
			[int(it) for it in logic_box[1]]
		]

		query=types.SimpleNamespace()
		query.logic_box=logic_box
		query.timestep=timestep
		query.field=field
		query.end_resolutions=end_resolutions
		query.slice_dir=slice_dir
		query.aborted=aborted
		query.t1=time.time()
		query.cursor=0
		return query

	# beginBoxQuery
	def beginBoxQuery(self,query):
		logger.info(f"beginBoxQuery timestep={query.timestep} field={query.field} logic_box={query.logic_box} end_resolutions={query.end_resolutions}")	
		query.cursor=0	

	# isQueryRunning (if cursor==0 , means I have to begin, if cursor==1 means I have the first level ready etc)
	def isQueryRunning(self,query):
		return query is not None and query.cursor>=0 and query.cursor<len(query.end_resolutions)
		
	 # getQueryCurrentResolution
	def getQueryCurrentResolution(self,query):
		if query is None: return -1
		last=query.cursor-1
		return query.end_resolutions[last]  if last>=0 and last<len(query.end_resolutions) else -1

	# returnBoxQueryData
	def returnBoxQueryData(self,access, query, data):
		
		if query is None or data is None:
			logger.info(f"read done {query} {data}")
			return None

		# is a slice? I need to reduce the size (i.e. from 3d data to 2d data)
		if query.slice_dir is not None:
			dims=list(reversed(data.shape))
			assert dims[query.slice_dir]==1
			del dims[query.slice_dir]
			while len(dims)>2 and dims[-1]==1: dims=dims[0:-1] # remove right `1`
			data=data.reshape(list(reversed(dims)))

		H=self.getQueryCurrentResolution(query)
		msec=int(1000*(time.time()-query.t1))
		logger.info(f"got data cursor={query.cursor} end_resolutions{query.end_resolutions} timestep={query.timestep} field={query.field} H={H} data.shape={data.shape} data.dtype={data.dtype} logic_box={query.logic_box} m={np.min(data)} M={np.max(data)} ms={msec}")
		
		return {
			"I": query.cursor,
			"timestep": query.timestep,
			"field": query.field, 
			"logic_box": query.logic_box, 
			"H": H, 
			"data": data,
			"msec": msec,
			}

	# nextBoxQuery
	def nextBoxQuery(self,query):
		if not self.isQueryRunning(query): return
		query.cursor+=1

# //////////////////////////////////////////////////
from .utils import GetBackend
backend=GetBackend()

logger.info(f"openvisuspy backend={backend}")

if backend=="py":
	from .backend_py import *
else:
	from .backend_cpp import *