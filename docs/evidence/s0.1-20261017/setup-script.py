import datetime, hashlib, importlib.util, json, os, pathlib, shutil, subprocess, sys, time
ROOT=pathlib.Path('/Users/xumanchun/Documents/agent项目/AI-Robot-latest')
OUT=ROOT/'docs/evidence/s0.1-20261017'
OUT.mkdir(exist_ok=False)
(OUT/'setup-script.py').write_bytes(pathlib.Path(__file__).read_bytes())
spec=importlib.util.spec_from_file_location('s0',ROOT/'docs/evidence/s0-20261017/run_baseline.py'); s0=importlib.util.module_from_spec(spec); spec.loader.exec_module(s0)
sha=lambda b: hashlib.sha256(b).hexdigest()
def save(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
before={'latest':s0.snapshot(ROOT),'old':s0.snapshot(s0.OLD)}
save('source-before.json',before)
historical=json.loads((ROOT/'docs/evidence/s0-20261017/source-after.json').read_text())
save('fingerprint-check.json',{'latest_matches_s0': before['latest']['files_sha256']==historical['latest']['files_sha256'], 'old_matches_s0':before['old']['files_sha256']==historical['old']['files_sha256'],'current':before['latest']['source_manifest_sha256'],'s0':historical['latest']['source_manifest_sha256']})
assert before['latest']['files_sha256']==historical['latest']['files_sha256'],'Source changed; inspect before continuing'
files={str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in (ROOT/'docs/evidence/s0-20261017').rglob('*') if p.is_file() and '__pycache__' not in str(p)}
save('s0-evidence-before.json',files)
(OUT/'execution-log-before.md').write_bytes((ROOT/'docs/multi-agent-execution-log.md').read_bytes())
for name,args in [('git-diff.txt',['git','diff','--binary','HEAD']),('git-staged-diff.txt',['git','diff','--cached','--binary'])]: (OUT/name).write_bytes(subprocess.check_output(args,cwd=ROOT))
raw=(ROOT/'docs/evidence/s0-20261017/borrowed-packages.txt').read_text(); packages=json.JSONDecoder().raw_decode(raw)[0]
(OUT/'s0-constraints.txt').write_text(''.join(p['name']+'=='+p['version']+'\n' for p in packages))
(OUT/'network-sandbox.txt').write_text('Sandbox probe: DNS pypi.org and openaipublic.blob.core.windows.net -> gaierror [Errno 8]; TLS urllib probes -> same DNS failure before TLS handshake. Python pip-vendored certifi CA configured. Tool command exit 0 (errors individually caught); no certificate failure reached.\n')
commands=[]
def run(label,args,timeout=600):
 start=datetime.datetime.now(datetime.timezone.utc).isoformat(); clock=time.monotonic()
 with (OUT/(label+'.txt')).open('w') as f:
  try: p=subprocess.run(args,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,timeout=timeout); code=p.returncode
  except subprocess.TimeoutExpired: f.write('\nS0.1 command timeout\n'); code=124
  except FileNotFoundError as exc: f.write(str(exc)); code=127
 row=dict(id=label,argv=args,cwd=str(ROOT),started_utc=start,exit_code=code,elapsed_seconds=round(time.monotonic()-clock,3),output=label+'.txt',output_sha256=sha((OUT/(label+'.txt')).read_bytes()))
 commands.append(row); save('setup-commands.json',commands); print(json.dumps(row,ensure_ascii=False),flush=True)
 return code
probe='''import socket,ssl,urllib.request,pip._vendor.certifi
print("CA",pip._vendor.certifi.where())
for host in ["pypi.org","openaipublic.blob.core.windows.net"]:
 try: print("DNS",host,sorted({x[4][0] for x in socket.getaddrinfo(host,443)}))
 except Exception as e: print(type(e).__name__,str(e))
for url in ["https://pypi.org/simple/pytest/","https://openaipublic.blob.core.windows.net/encodings/cl100k_base.tiktoken"]:
 try:
  with urllib.request.urlopen(url,context=ssl.create_default_context(cafile=pip._vendor.certifi.where()),timeout=30) as r: print("TLS",url,r.status)
 except Exception as e: print(type(e).__name__,str(e))
'''
run('network-outside-sandbox',[sys.executable,'-c',probe],90)
venv=ROOT/'.venv'
assert not venv.exists(),'Do not overwrite existing environment'
assert run('create-venv',[sys.executable,'-m','venv',str(venv)])==0
import pip._vendor.certifi
ca=pip._vendor.certifi.where()
args=[str(venv/'bin/python'),'-m','pip','--isolated','install','--disable-pip-version-check','--cert',ca,'--index-url','https://pypi.org/simple','-r','requirements-dev.txt','-c',str(OUT/'s0-constraints.txt'),'--report',str(OUT/'pip-install-report.json')]
code=run('install-dev',args,900)
if code: sys.exit(code)
run('pip-check',[str(venv/'bin/python'),'-m','pip','check'])
run('packages',[str(venv/'bin/python'),'-m','pip','list','--format=json'])
run('freeze',[str(venv/'bin/python'),'-m','pip','freeze','--all'])
run('docker-version',['docker','version'],30)
run('docker-desktop-status',['docker','desktop','status'],30)
run('python-version',[str(venv/'bin/python'),'--version'])
