import datetime,hashlib,importlib.util,json,os,pathlib,subprocess,sys,time
ROOT=pathlib.Path('/Users/xumanchun/Documents/agent项目/AI-Robot-latest'); OUT=ROOT/'docs/evidence/s0.1-20261017'; P=str(ROOT/'.venv/bin/python')
sha=lambda b:hashlib.sha256(b).hexdigest()
def save(name,value): (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
commands=[]
phase=sys.argv[1]
env={k:v for k,v in os.environ.items() if not k.startswith(('AIROBOT_','OPENAI_','LANGCHAIN_','LANGSMITH_','PYTEST_','PYTHONPATH'))}
env.update(PYTHONDONTWRITEBYTECODE='1',PYTHON_DOTENV_DISABLED='1',PYTHONPATH=os.pathsep.join([str(OUT/'offline_guard'),str(ROOT)]),AIROBOT_LLM_API_KEY='',AIROBOT_EMBEDDING_API_KEY='',AIROBOT_AMQP_URL='',AIROBOT_GO_API_BASE_URL='',AIROBOT_RERANK_ENABLED='false',AIROBOT_CONTEXT_MODE='off',LANGSMITH_TRACING='false',LANGCHAIN_TRACING_V2='false',TIKTOKEN_CACHE_DIR=str(ROOT/'.venv/tiktoken-cache'),S01_NETWORK_AUDIT=str(OUT/(phase+'-network-audit.txt')))
(OUT/(phase+'-network-audit.txt')).touch()
def run(label,args,*,guarded=True,timeout=600):
 started=datetime.datetime.now(datetime.timezone.utc).isoformat(); clock=time.monotonic()
 with (OUT/(label+'.txt')).open('x') as f:
  try: proc=subprocess.run(args,cwd=ROOT,env=env if guarded else None,stdout=f,stderr=subprocess.STDOUT,timeout=timeout); code=proc.returncode
  except subprocess.TimeoutExpired: f.write('\nS0.1 command timeout\n'); code=124
  except FileNotFoundError as exc: f.write(str(exc)); code=127
 row=dict(id=label,argv=args,cwd=str(ROOT),started_utc=started,exit_code=code,elapsed_seconds=round(time.monotonic()-clock,3),network_guard=guarded,output=label+'.txt',output_sha256=sha((OUT/(label+'.txt')).read_bytes()))
 commands.append(row); save(phase+'-commands.json',commands); print(json.dumps(row,ensure_ascii=False),flush=True)
 return code
if phase=='offline':
 (OUT/'run-baseline.py').write_bytes(pathlib.Path(__file__).read_bytes())
 guard=OUT/'offline_guard';guard.mkdir(exist_ok=True)
 (guard/'sitecustomize.py').write_text('''import os,sys,socket\ndef reject(event,args):\n if event=="socket.getaddrinfo" or (event=="socket.connect" and args[0].family in (socket.AF_INET,socket.AF_INET6)):\n  with open(os.environ["S01_NETWORK_AUDIT"],"a") as f: f.write(event+" blocked\\n")\n  raise RuntimeError("S01_OFFLINE_NETWORK_BLOCKED")\nsys.addaudithook(reject)\n''')
 token='''import ast,hashlib,inspect,json,os,pathlib,ssl,urllib.request
import certifi,tiktoken,tiktoken_ext.openai_public as defs
src=inspect.getsource(defs.cl100k_base); tree=ast.parse(src)
call=next(x for x in ast.walk(tree) if isinstance(x,ast.Call) and getattr(x.func,"id",None)=="load_tiktoken_bpe")
url=ast.literal_eval(call.args[0]); expected=ast.literal_eval(next(k.value for k in call.keywords if k.arg=="expected_hash"))
cache=pathlib.Path(os.environ["TIKTOKEN_CACHE_DIR"]); cache.mkdir(parents=True,exist_ok=True)
with urllib.request.urlopen(url,context=ssl.create_default_context(cafile=certifi.where()),timeout=60) as r:
 status=r.status; raw=r.read()
actual=hashlib.sha256(raw).hexdigest(); assert actual==expected,(actual,expected)
key=hashlib.sha1(url.encode()).hexdigest(); target=cache/key; target.write_bytes(raw)
report={"tiktoken_version":tiktoken.__version__,"source_url":url,"http_status":status,"expected_sha256":expected,"actual_sha256":actual,"cache_key":key,"cache_file":str(target),"bytes":len(raw),"ca_file":certifi.where(),"ca_sha256":hashlib.sha256(pathlib.Path(certifi.where()).read_bytes()).hexdigest(),"definition_file":inspect.getfile(defs),"definition_sha256":hashlib.sha256(pathlib.Path(inspect.getfile(defs)).read_bytes()).hexdigest()}
print(json.dumps(report,ensure_ascii=False,indent=2))
pathlib.Path("docs/evidence/s0.1-20261017/token-cache.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\\n")
'''
 publicenv=env.copy();publicenv['PYTHONPATH']=str(ROOT)
 original=env;env=publicenv
 assert run('token-cache-download',[P,'-c',token])==0
 env=original
 offline='''import json,os,sys,tiktoken,urllib.request
assert "sitecustomize" in sys.modules
enc=tiktoken.get_encoding("cl100k_base")
examples=["hello world","context cancellation","中文 Token 计量"]
rows=[{"text":s,"tokens":enc.encode(s)} for s in examples]
assert all(enc.decode(r["tokens"])==r["text"] for r in rows)
assert enc.n_vocab==100277
print(json.dumps({"encoding":enc.name,"n_vocab":enc.n_vocab,"examples":rows,"network_blocked":True},ensure_ascii=False,indent=2))
'''
 assert run('token-cache-offline',[P,'-c',offline])==0
 (ROOT/'.venv/activate-s01.sh').write_text('source "'+str(ROOT/'.venv/bin/activate')+'"\nexport TIKTOKEN_CACHE_DIR="'+str(ROOT/'.venv/tiktoken-cache')+'"\nexport SSL_CERT_FILE="'+str(ROOT/'.venv/lib/python3.13/site-packages/certifi/cacert.pem')+'"\nexport REQUESTS_CA_BUNDLE="$SSL_CERT_FILE"\n')
 run('guard-selftest',[P,'-c','import socket;\ntry: socket.getaddrinfo("pypi.org",443)\nexcept RuntimeError as e:\n assert str(e)=="S01_OFFLINE_NETWORK_BLOCKED"; print("PASS expected network rejection")\nelse: raise AssertionError("guard absent")'])
 # Selftest audit is separate from business tests.
 (OUT/'guard-selftest-audit.txt').write_bytes((OUT/'offline-network-audit.txt').read_bytes()); (OUT/'offline-network-audit.txt').write_text('')
 run('syntax',[P,'-m','compileall','-q','app','eval','scripts','tests'])
 run('import-smoke',[P,'-c','import sys,app.main,app.agents.graph; print(sys.executable); print(app.main.__file__); print(app.agents.graph.__file__); print("routes:", len(app.main.app.routes))'])
 for name in ['stability','integration','agent','tracing']: run('script-'+name,[P,'tests/test_'+name+'.py'])
 run('hardening',[P,'-m','unittest','discover','-s','tests','-p','test_hardening.py','-v'])
 run('agent-fixtures',[P,'eval/run_agent_eval.py'])
 go=[str(p.relative_to(ROOT)) for p in sorted((ROOT/'tests').glob('test_go_*.py'))]
 ctx=[str(p.relative_to(ROOT)) for p in sorted((ROOT/'tests').glob('test_context_*.py'))]
 run('go-pytest',[P,'-m','pytest',*go,'-q','-ra','--junitxml='+str(OUT/'go-pytest.xml')])
 run('context-pytest',[P,'-m','pytest',*ctx,'-q','-ra','--junitxml='+str(OUT/'context-pytest.xml')])
 run('full-pytest',[P,'-m','pytest','tests','-q','-ra','--junitxml='+str(OUT/'full-pytest.xml')])
 run('hardening-exception-witness',[P,str(OUT/'exception-witness.py')])
elif phase=='docker-prepare':
 run('docker-context',['docker','context','show'],guarded=False,timeout=30)
 run('docker-desktop-start',['docker','desktop','start'],guarded=False,timeout=180)
 if run('docker-info',['docker','info','--format','{{json .}}'],guarded=False,timeout=60)==0:
  run('docker-build',['docker','build','--progress=plain','-t','airobot-go-validator:1.26.2','sandbox/go'],guarded=False,timeout=900)
  run('docker-image',['docker','image','inspect','airobot-go-validator:1.26.2'],guarded=False,timeout=30)
elif phase=='docker-test':
 env['AIROBOT_TEST_DOCKER']='1'
 go=[str(p.relative_to(ROOT)) for p in sorted((ROOT/'tests').glob('test_go_*.py'))]
 run('docker-pytest',[P,'-m','pytest',*go,'-q','-ra','--junitxml='+str(OUT/'docker-pytest.xml')],timeout=900)
 run('go-fixtures',[P,'eval/run_go_eval.py','--fixtures','--output',str(OUT/'go-fixtures-report.json')],timeout=1800)
 run('docker-containers-after',['docker','ps','-a','--filter','name=airobot-go-','--format','{{.Names}} {{.Status}}'],guarded=False,timeout=30)
