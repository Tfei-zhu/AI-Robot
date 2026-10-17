import os,sys,socket
def reject(event,args):
 if event=="socket.getaddrinfo" or (event=="socket.connect" and args[0].family in (socket.AF_INET,socket.AF_INET6)):
  with open(os.environ["S01_NETWORK_AUDIT"],"a") as f: f.write(event+" blocked\n")
  raise RuntimeError("S01_OFFLINE_NETWORK_BLOCKED")
sys.addaudithook(reject)
