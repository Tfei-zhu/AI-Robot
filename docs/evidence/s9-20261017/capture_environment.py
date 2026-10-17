import importlib.metadata,json,platform,subprocess,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent
version=subprocess.run(['docker','version'],text=True,capture_output=True,check=True).stdout
image=subprocess.run(['docker','image','inspect','airobot-go-validator:1.26.2','--format','{{.Id}}'],text=True,capture_output=True,check=True).stdout.strip()
containers=subprocess.run(['docker','ps','-a','--filter','name=airobot-go-','--format','{{.Names}} {{.Status}}'],text=True,capture_output=True,check=True).stdout
(OUT/'containers-after.txt').write_text(containers);(OUT/'docker-version.txt').write_text(version)
result=dict(python=sys.version,executable=sys.executable,platform=platform.platform(),docker_image_id=image,
 packages={p:importlib.metadata.version(p) for p in ('pytest','pydantic','fastapi','langgraph','langchain-openai','httpx')},leftover_containers=containers.splitlines(),
 remote_ci='not_run',python311_runtime='not_run; grammar checked locally only',model_requests='fixed clients only; no paid provider requests')
(OUT/'environment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps(result,ensure_ascii=False))
assert not containers
