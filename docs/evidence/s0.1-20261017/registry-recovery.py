import hashlib,json,pathlib,ssl,urllib.request,urllib.error
import certifi
OUT=pathlib.Path('/Users/xumanchun/Documents/agent项目/AI-Robot-latest/docs/evidence/s0.1-20261017')
ctx=ssl.create_default_context(cafile=certifi.where())
digest='sha256:47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19'
accept='application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json,application/vnd.oci.image.manifest.v1+json,application/vnd.docker.distribution.manifest.v2+json'
def get(url,headers={}):
 with urllib.request.urlopen(urllib.request.Request(url,headers=headers),context=ctx,timeout=30) as r: return r.read(),dict(r.headers)
raw,_=get('https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/golang:pull')
token=json.loads(raw)['token']
try:
 raw,h=get('https://registry-1.docker.io/v2/library/golang/manifests/'+digest,{'Authorization':'Bearer '+token,'Accept':accept})
 actual='sha256:'+hashlib.sha256(raw).hexdigest(); assert actual==digest,(actual,digest)
 (OUT/'golang-base-index.json').write_bytes(raw)
 print('official manifest verified',actual)
 index=json.loads(raw)
 for manifest in index.get('manifests',[]):
  if manifest.get('platform',{}).get('os')=='linux' and manifest.get('platform',{}).get('architecture')=='arm64': print('linux arm64:',json.dumps(manifest))
except Exception as e: print('official manifest',type(e).__name__,str(e))
for host in ['docker.m.daocloud.io','docker.1ms.run']:
 try:
  raw,h=get('https://'+host+'/v2/library/golang/manifests/'+digest,{'Accept':accept})
  print(host,'manifest',len(raw),'sha256:'+hashlib.sha256(raw).hexdigest())
 except urllib.error.HTTPError as e: print(host,'HTTP',e.code)
 except Exception as e: print(host,type(e).__name__,str(e))
