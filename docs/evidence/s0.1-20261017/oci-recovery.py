import concurrent.futures,hashlib,json,pathlib,ssl,tarfile,time,urllib.request
import certifi
ROOT=pathlib.Path('/Users/xumanchun/Documents/agent项目/AI-Robot-latest'); OUT=ROOT/'docs/evidence/s0.1-20261017'; LAYOUT=pathlib.Path('/private/tmp/airobot-s01-golang-oci'); LAYOUT.mkdir(exist_ok=False); BLOBS=LAYOUT/'blobs/sha256';BLOBS.mkdir(parents=True)
ctx=ssl.create_default_context(cafile=certifi.where()); base='https://registry-1.docker.io/v2/library/golang/'
with urllib.request.urlopen('https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/golang:pull',context=ctx,timeout=30) as r: token=json.load(r)['token']
headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.oci.image.index.v1+json,application/vnd.oci.image.manifest.v1+json'}
index_raw=(OUT/'golang-base-index.json').read_bytes(); index_digest='sha256:'+hashlib.sha256(index_raw).hexdigest(); assert index_digest=='sha256:47ce5636e9936b2c5cbf708925578ef386b4f8872aec74a67bd13a627d242b19'
(BLOBS/index_digest.split(':')[1]).write_bytes(index_raw)
desc=next(x for x in json.loads(index_raw)['manifests'] if x.get('platform',{}).get('architecture')=='arm64' and x.get('platform',{}).get('os')=='linux')
def fetch(kind,digest,size=None):
 path=BLOBS/digest.split(':')[1]
 for attempt in range(3):
  try:
   request=urllib.request.Request(base+kind+'/'+digest,headers=headers)
   hasher=hashlib.sha256(); total=0
   with urllib.request.urlopen(request,context=ctx,timeout=120) as r,path.open('wb') as f:
    while chunk:=r.read(1024*1024): hasher.update(chunk);f.write(chunk);total+=len(chunk)
   assert 'sha256:'+hasher.hexdigest()==digest,(digest,hasher.hexdigest())
   if size is not None: assert total==size,(total,size)
   print('verified',kind,digest,total,flush=True)
   return {'digest':digest,'size':total}
  except Exception as e:
   print('retry',kind,digest,attempt+1,type(e).__name__,str(e),flush=True)
   if attempt==2: raise
   time.sleep(1)
fetch('manifests',desc['digest'],desc['size']);manifest=json.loads((BLOBS/desc['digest'].split(':')[1]).read_bytes())
(OUT/'golang-base-arm64-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
items=[manifest['config'],*manifest['layers']]
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
 verified=list(pool.map(lambda x:fetch('blobs',x['digest'],x['size']),items))
(LAYOUT/'oci-layout').write_text('{"imageLayoutVersion":"1.0.0"}\n')
local_desc={**desc,'annotations':{'org.opencontainers.image.ref.name':'airobot-s01-golang-base:1.26.2-bookworm'}}
(LAYOUT/'index.json').write_text(json.dumps({'schemaVersion':2,'manifests':[local_desc]}))
report={'source':'https://registry-1.docker.io/v2/library/golang','tls_verification':True,'ca_file':certifi.where(),'original_index_digest':index_digest,'platform_manifest':desc,'verified_blobs':verified,'layout':str(LAYOUT),'note':'Same immutable official base, downloaded through host verified HTTPS; no project source changes.'}
(OUT/'golang-oci-provenance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
with tarfile.open('/private/tmp/airobot-s01-golang-oci.tar','w') as tar:
 for p in LAYOUT.rglob('*'):
  if p.is_file(): tar.add(p,arcname=str(p.relative_to(LAYOUT)),recursive=False)
print('OCI layout complete',flush=True)
