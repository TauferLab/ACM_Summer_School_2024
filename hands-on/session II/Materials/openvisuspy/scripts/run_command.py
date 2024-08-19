import os,sys,glob
cmd,pattern=sys.argv[1:]
for notebook in glob.glob(pattern,recursive=True): 
  s=cmd.format(notebook=notebook)
  print(s)
  os.system(s)
exit()