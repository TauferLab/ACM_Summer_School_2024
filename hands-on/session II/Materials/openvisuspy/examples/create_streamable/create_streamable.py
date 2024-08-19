import os,sys,time, h5py
import numpy as np

import OpenVisus as ov

# //////////////////////////////////////////////////////////////////////////////////
class Streamable:

	compression="zip"
	arco="4mb"

	def __init__(self, src_file:h5py.File, dst_file:h5py.File, idx_urls:dict=None, compression=None, arco=None):
		self.src_file=src_file
		self.dst_file=dst_file
		assert(idx_urls and "local" in idx_urls) # I need to create local files

		# if not specified the first one will be the default
		if not "default" in idx_urls:
			idx_urls["default"]=idx_urls.keys()[0]

		# default it's just an alias/key
		assert(idx_urls["default"] in idx_urls)

		self.idx_urls=idx_urls 
		self.idx_datasets={}
		self.compression=compression or self.compression
		self.arco=arco or self.arco
	
	def copyAttribues(self, src, dst):
		for k,v in src.attrs.items():
			dst.attrs[k]=v

	def createIdx(self, idx_url, src):

		if True:
			data_dir=os.path.splitext(idx_url)[0]	
			print(f"DANGEROUS but needed: removing any old data file from {data_dir}")
			import shutil
			shutil.rmtree(data_dir, ignore_errors=True)
		
		t1=time.time()
		data = src[...]
		vmin,vmax=np.min(data),np.max(data)
		print(f"Read data in {time.time()-t1} seconds shape={data.shape} dtype={data.dtype} vmin={vmin} vmax={vmax}")

		# e.g. 1x1441x676x2048 -> 1441x676x2048
		if len(data.shape)==4:
			assert(data.shape[0]==1)
			data=data[0,...]

		basename=src.name.split("/")[-1]
		ov_field=ov.Field.fromString(f"""{basename} {str(data.dtype)} format(row_major) min({vmin}) max({vmax})""")

		
		idx_axis=["X", "Y", "Z"]
		D,H,W=data.shape
		idx_physic_box=[0,W,0,H,0,D] 

		# this is the NEXUS conventions where I have axes information 
		axes=[str(it) for it in src.parent.attrs.get("axes",[])]
		if axes:
			idx_axis,idx_physic_box=[], []
			for ax in reversed(axes):
				sub=src.parent.get(ax)
				idx_physic_box.extend([sub[0],sub[-1]])
				idx_axis.append(ax)

		idx_axis=" ".join([str(it) for it in idx_axis])
		idx_physic_box=" ".join([str(it) for it in idx_physic_box])

		db=ov.CreateIdx(
			url=idx_url, 
			dims=list(reversed(data.shape)), 
			fields=[ov_field], 
			compression="raw", # first I need to write uncompressed
			physic_box=ov.BoxNd.fromString(idx_physic_box),
			axis=idx_axis,
			arco=self.arco
		)
		print(f"Created IDX idx_url=[{idx_url}] idx_axis=[{idx_axis}] idx_physic_box=[{idx_physic_box}]")

		t1=time.time()
		db.write(data)
		print(f"Wrote IDX data in {time.time()-t1} seconds")

		if self.compression and self.compression!="raw":
			t1 = time.time()
			print(f"Compressing dataset compression={self.compression}...")
			db.compressDataset([self.compression])
			print(f"Compressed dataset to {self.compression} in {time.time()-t1} seconds")

	def doCopy(self, src):

		if isinstance(src,h5py.Group):
			dst=self.dst_file if src.name=="/" else self.dst_file.create_group(src.name)
			self.copyAttribues(src,dst)
			for it in src.keys():
				self.doCopy(src[it])
			return

		if isinstance(src,h5py.Dataset):

			shape, dtype=src.shape, src.dtype
			if len(shape)==3 or (len(shape)==4 and shape[0]==1):

				if src in self.idx_datasets:
					dst, urls=self.idx_datasets[src]
					self.dst_file[src.name]=dst
					print(f"Found already converted dataset, using the link {src.name}->{dst.name}")
				else:
					dst=self.dst_file.create_dataset(src.name, shape=shape, dtype=dtype, data=None)
					urls={k:v.replace("\\","/").replace("{name}",dst.name.lstrip("/")) for k,v in self.idx_urls.items()}
					self.idx_datasets[src]=(dst,urls)
					# need "local" to generate local datasets
					self.createIdx(urls["local"],src) 

				self.copyAttribues(src, dst)
				# I am setting the idx_url at the parent level
				dst.parent.attrs["idx_urls"] =str(urls)

				idx_url=urls[urls["default"]]
				dst.parent.attrs["idx_url" ] =str(idx_url)
				
			else:
				# just copy the dataset
				dst=self.dst_file.create_dataset(src.name, shape=shape, dtype=dtype, data=src[...])
				self.copyAttribues(src,dst)

			return
		
		raise NotImplementedError(f"doCopy of {src} not supported")


	@staticmethod 
	def SaveRemoteToLocal(remote_url, profile=None, endpoint_url=None):
		import s3fs, tempfile
		fs = s3fs.S3FileSystem(profile=profile,client_kwargs={'endpoint_url': endpoint_url})
		key=remote_url[len(endpoint_url):]
		key=key.lstrip("/")
		key=key.split("?")[0]
		with fs.open(key, mode='rb') as fin:
			with tempfile.NamedTemporaryFile(suffix=os.path.splitext(key)[1]) as tmpfile: temporary_filename=tmpfile.name
			with open(temporary_filename,"wb") as fout: fout.write(fin.read())
		return temporary_filename

	@staticmethod 
	def Create(src_filename:str,dst_filename:str, **kwargs):
		
		if os.path.isfile(dst_filename): 
				os.remove(dst_filename)
		
		os.makedirs(os.path.dirname(dst_filename),exist_ok=True)

		with h5py.File(src_filename, 'r') as src_file:
			with h5py.File(dst_filename,'w') as dst_file:
				streamable=Streamable(src_file, dst_file, **kwargs)
				streamable.doCopy(src_file)

		print(f"new-size/old-size={os.path.getsize(dst_filename):,}/{os.path.getsize(src_filename):,}")

	@staticmethod
	def Print(src, links={}, nrec=0):

		if isinstance(src,str):
			with h5py.File(src, 'r') as f:
				return Streamable.Print(f)

		print("  "*nrec, f"{src.name}",end="")
		is_link=src in links
		if is_link:
			print(f" link={links[src].name}")
		else:
			links[src]=src

		if isinstance(src,h5py.Dataset):
			print(f" shape='{src.shape}'",end="")
			print(f" dtype='{src.dtype}'",end="")
		print()

		for k,v in src.attrs.items():
			print("  "*(nrec+1), f"@{k}={v}")

		if not is_link and not isinstance(src,h5py.Dataset):
			for I,it in enumerate(src.keys()):
				Streamable.Print(src[it], links, nrec+1)


